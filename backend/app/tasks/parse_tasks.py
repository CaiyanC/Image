import asyncio
import json
from datetime import datetime, timezone

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..models.knowledge_base import KnowledgeDocument, KnowledgeParseTask
from ..services import product_vector_index_service
from ..services.file_ingestion_service import ingest_file


@celery_app.task(name="parse_document")
def parse_document(document_id: str, task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not task or not document:
            return {"ok": False, "error": "Task or document not found"}

        task.status = "processing"
        task.started_at = datetime.now(timezone.utc)
        task.error_message = None
        document.parse_status = "processing"
        document.parse_error = None
        db.commit()

        file_path = document.file_path
        file_name = document.file_name or document.title
        related_skus = _load_related_skus(document.related_skus_json)
        parsed_document = asyncio.run(
            ingest_file(
                db,
                file_path=file_path,
                file_name=file_name,
                related_skus=related_skus,
                document=document,
            )
        )

        task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
        if not task:
            return {"ok": False, "error": "Task not found after parsing"}

        task.finished_at = datetime.now(timezone.utc)
        if parsed_document.parse_status == "done":
            embedding_result = _embed_parsed_document(db, document_id)
            task.status = "done"
            task.error_message = None
            db.commit()
            return {
                "ok": True,
                "status": "done",
                "document_id": document_id,
                "task_id": task_id,
                "embedding": embedding_result,
            }

        task.status = "error"
        task.error_message = parsed_document.parse_error or "File parsing failed"
        db.commit()
        return {"ok": False, "status": "error", "document_id": document_id, "task_id": task_id}
    except Exception as exc:
        db.rollback()
        error_message = str(exc)[:2000]
        try:
            task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
            document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
            if document:
                document.parse_status = "error"
                document.parse_error = error_message
            if task:
                task.status = "error"
                task.error_message = error_message
                task.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        return {"ok": False, "status": "error", "document_id": document_id, "task_id": task_id, "error": error_message}
    finally:
        db.close()


def _load_related_skus(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        sku = str(item or "").strip().upper()
        if sku and sku not in seen:
            seen.add(sku)
            result.append(sku)
    return result


def _embed_parsed_document(db, document_id: str) -> dict:
    if not _should_auto_embed_document(db):
        return {"skipped": True, "reason": "unsupported_database"}
    try:
        return product_vector_index_service.run_embed_pending_chunks(db, document_id=document_id)
    except Exception as exc:
        return {"skipped": False, "error": str(exc)[:2000]}


def _should_auto_embed_document(db) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False
