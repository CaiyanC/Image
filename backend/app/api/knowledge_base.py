import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import SessionLocal, get_db
from ..core.rate_limit import enforce_rate_limit
from ..core.security import get_current_super_admin
from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument, KnowledgeParseTask
from ..models.product import Product
from ..models.user import User
from ..services import knowledge_job_service, knowledge_service, product_service, product_vector_index_service
from ..services.file_ingestion_service import (
    ingest_file,
    list_stuck_processing_documents,
    reconcile_parse_task_states,
    recover_stuck_processing_documents,
)
from ..services.upload_validation_service import validate_knowledge_file_content
from ..tasks.parse_tasks import parse_document

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])

ALLOWED_KNOWLEDGE_FILE_SUFFIXES = {".pdf", ".docx", ".pptx", ".txt", ".xlsx"}
ALLOWED_KNOWLEDGE_FILE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "application/octet-stream",
}
MAX_KNOWLEDGE_FILE_BYTES = 20 * 1024 * 1024
MAX_KNOWLEDGE_FILES_PER_REQUEST = 20
KNOWLEDGE_FILE_DIR = settings.KNOWLEDGE_FILE_DIR


def _knowledge_file_roots() -> tuple[Path, ...]:
    """Return the current bounded roots used for knowledge-file access.

    Keep this dynamic because tests and isolated deployments may replace the
    primary directory after module import.  The allowlist remains limited to
    the configured primary root plus explicit compatibility roots.
    """
    roots = (KNOWLEDGE_FILE_DIR, *getattr(settings, "KNOWLEDGE_FILE_LEGACY_DIRS", []))
    return tuple(dict.fromkeys(Path(root).resolve(strict=False) for root in roots if root))


class KnowledgeDocumentCreate(BaseModel):
    source_type: str = "manual"
    title: str
    content: str
    sku: str | None = None
    source_id: str | None = None
    metadata: dict | None = None


class KnowledgeSearchPreviewRequest(BaseModel):
    query: str
    sku: str | None = None
    limit: int = 8


class ProductReindexRequest(BaseModel):
    mode: str = "pending"
    limit: int | None = None
    embed: bool = True


class EmbeddingRetryRequest(BaseModel):
    limit: int | None = 20


class RecoverStuckFilesRequest(BaseModel):
    timeout_minutes: int = 30
    dry_run: bool = True


@router.get("/status")
def status(
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return knowledge_service.vector_status(db)


@router.get("/health")
def health(
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return knowledge_service.health_report(db)


@router.post("/search-preview")
async def search_preview(
    body: KnowledgeSearchPreviewRequest,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    limit = min(max(body.limit, 1), 20)
    return await knowledge_service.search_preview(db, body.query, sku=body.sku, limit=limit)


@router.post("/reindex-products")
async def reindex_products(
    body: ProductReindexRequest,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    mode = (body.mode or "pending").strip().lower()
    if mode == "full":
        indexed = product_vector_index_service.index_all_products(db)
        embed_limit = body.limit
    else:
        limit = min(max(body.limit or 100, 1), 1000)
        indexed = product_service.sync_pending_products_to_vector_db(db, limit=limit)
        embed_limit = limit
    embedded = None
    if body.embed:
        embedded = await product_vector_index_service.embed_pending_chunks(db, limit=embed_limit)
    return {
        "mode": mode,
        "indexed": indexed,
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


@router.post("/jobs/reindex-products")
def create_reindex_job(
    body: ProductReindexRequest,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="knowledge.reindex_job", limit=10, window_seconds=600)
    try:
        return knowledge_job_service.create_reindex_job(
            db,
            created_by=current_user.id,
            mode=body.mode,
            limit=body.limit,
            embed=body.embed,
        )
    except knowledge_job_service.KnowledgeJobEnqueueError as exc:
        raise HTTPException(status_code=503, detail=f"任务队列暂不可用；任务 {exc.job_id} 已标记失败") from exc


@router.post("/jobs/retry-embeddings")
def create_embedding_retry_job(
    body: EmbeddingRetryRequest,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="knowledge.embedding_retry", limit=20, window_seconds=600)
    limit = min(max(body.limit or 20, 1), 500)
    try:
        return knowledge_job_service.create_embedding_retry_job(
            db, created_by=current_user.id, limit=limit
        )
    except knowledge_job_service.KnowledgeJobEnqueueError as exc:
        raise HTTPException(status_code=503, detail=f"任务队列暂不可用；任务 {exc.job_id} 已标记失败") from exc


@router.get("/jobs")
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return knowledge_job_service.list_jobs(db, limit=limit)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    job = knowledge_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/documents")
def create_document(
    body: KnowledgeDocumentCreate,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    doc = knowledge_service.create_document(
        db,
        source_type=body.source_type,
        title=body.title,
        content=body.content,
        sku=body.sku,
        source_id=body.source_id,
        metadata=body.metadata,
        created_by=current_user.id,
    )
    return {
        "id": doc.id,
        "source_type": doc.source_type,
        "sku": doc.sku,
        "title": doc.title,
        "created_at": str(doc.created_at),
    }


@router.get("/tasks/{task_id}")
def get_parse_task(
    task_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    reconcile_parse_task_states(db, task_id=task_id)
    task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _build_task_payload(task)


@router.get("/files")
def list_knowledge_files(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    # A parser can commit the document and be interrupted before it commits
    # the task row.  Reconcile the display state before returning the list so
    # the UI does not report a completed file as still processing.
    reconcile_parse_task_states(db)
    documents = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.source_type == "file")
        .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.created_at.desc())
        .limit(limit)
        .all()
    )
    total = db.query(KnowledgeDocument).filter(KnowledgeDocument.source_type == "file").count()
    return {
        "items": [_build_file_document_payload(db, document) for document in documents],
        "total": total,
    }


@router.get("/files/{document_id}/download")
def download_knowledge_file(
    document_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    get_current_super_admin(current_user, db)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if not document or document.source_type != "file":
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.file_path:
        raise HTTPException(status_code=404, detail="File not found")
    file_path = _resolve_knowledge_file_path(document.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=document.file_name or file_path.name)


@router.delete("/files/{document_id}")
def delete_knowledge_file(
    document_id: str,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if not document or document.source_type != "file":
        raise HTTPException(status_code=404, detail="Document not found")
    file_path = document.file_path
    resolved_file_path = _resolve_knowledge_file_path(file_path) if file_path else None
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete(synchronize_session=False)
    db.query(KnowledgeParseTask).filter(KnowledgeParseTask.document_id == document.id).delete(synchronize_session=False)
    db.delete(document)
    db.commit()
    if resolved_file_path:
        _remove_file_safely(str(resolved_file_path))
    return {"ok": True, "document_id": document_id}


@router.post("/files/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    related_skus: str | None = Form(default=None),
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(user_id=current_user.id, scope="knowledge.files.upload", limit=45, window_seconds=60)
    if not files or len(files) > MAX_KNOWLEDGE_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"每次最多上传 {MAX_KNOWLEDGE_FILES_PER_REQUEST} 个文件",
        )
    os.makedirs(KNOWLEDGE_FILE_DIR, exist_ok=True)
    results: list[dict] = []
    normalized_related_skus = _normalize_related_skus(related_skus)
    for file in files:
        document: KnowledgeDocument | None = None
        original_name = os.path.basename(file.filename or "").strip()
        suffix = _validate_knowledge_file(file)
        saved_path, stored_name, file_hash = await _save_knowledge_file(file, suffix)
        try:
            validate_knowledge_file_content(saved_path, suffix)
        except ValueError as exc:
            _remove_file_safely(saved_path)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            existing = _find_existing_file_document(db, file_hash)
            if existing:
                results.append(
                    _build_existing_document_payload(
                        db,
                        existing=existing,
                        original_name=original_name,
                        stored_name=stored_name,
                        duplicate=True,
                        message=_duplicate_message(existing.parse_status),
                        incoming_related_skus=normalized_related_skus,
                    )
                )
                _remove_file_safely(saved_path)
                continue

            document = KnowledgeDocument(
                source_type="file",
                source_id=file_hash,
                sku=normalized_related_skus[0] if normalized_related_skus else None,
                title=original_name or stored_name,
                content="",
                file_name=original_name or stored_name,
                file_path=saved_path,
                file_type=suffix.lstrip("."),
                file_hash=file_hash,
                page_count=0,
                parse_status="processing",
                parse_error=None,
                related_skus_json=json.dumps(normalized_related_skus, ensure_ascii=False),
                metadata_json=json.dumps(
                    {
                        "file_name": original_name or stored_name,
                        "file_type": suffix.lstrip("."),
                        "file_hash": file_hash,
                        "file_path": saved_path,
                        "related_skus": normalized_related_skus,
                    },
                    ensure_ascii=False,
                ),
            )
            db.add(document)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = _find_existing_file_document(db, file_hash)
                if existing:
                    results.append(
                        _build_existing_document_payload(
                            db,
                            existing=existing,
                            original_name=original_name,
                            stored_name=stored_name,
                            duplicate=True,
                            message=_duplicate_message(existing.parse_status),
                            incoming_related_skus=normalized_related_skus,
                        )
                    )
                    _remove_file_safely(saved_path)
                    continue
                _remove_file_safely(saved_path)
                raise HTTPException(status_code=409, detail="文件已存在或正在处理中，请刷新后重试")

            db.refresh(document)
            task = _create_parse_task(db, document.id)
            # BackgroundTasks fallback is retained in _run_file_parse_task for quick rollback.
            # P1.5 schedules parsing in the external Celery worker instead of the API process.
            try:
                parse_document.apply_async(args=[document.id, task.id], task_id=task.id)
            except Exception as exc:
                task.status = "error"
                task.error_message = "Task queue unavailable"
                task.finished_at = datetime.now(timezone.utc)
                document.parse_status = "error"
                document.parse_error = "Task queue unavailable"
                db.commit()
                raise HTTPException(
                    status_code=503,
                    detail="文件已保存，但解析队列暂不可用；任务已标记失败",
                ) from exc
            results.append(
                {
                    "document_id": document.id,
                    "task_id": task.id,
                    "task_status": task.status,
                    "duplicate": False,
                    "reused_document_id": None,
                    "message": "文件已上传，解析任务已创建",
                    "file_name": document.file_name or original_name or stored_name,
                    "file_type": document.file_type,
                    "parse_status": document.parse_status,
                    "parse_error": document.parse_error,
                    "chunk_count": 0,
                    "related_skus": _load_related_skus(document.related_skus_json),
                }
            )
        except HTTPException:
            db.rollback()
            persisted = db.get(KnowledgeDocument, document.id) if document and document.id else None
            if not persisted:
                _remove_file_safely(saved_path)
            raise
        except IntegrityError:
            db.rollback()
            existing = _find_existing_file_document(db, file_hash)
            if existing:
                results.append(
                    _build_existing_document_payload(
                        db,
                        existing=existing,
                        original_name=original_name,
                        stored_name=stored_name,
                        duplicate=True,
                        message=_duplicate_message(existing.parse_status),
                        incoming_related_skus=normalized_related_skus,
                    )
                )
                _remove_file_safely(saved_path)
                continue
            _remove_file_safely(saved_path)
            raise HTTPException(status_code=409, detail="文件入库失败，请重试")
        except Exception:
            db.rollback()
            _remove_file_safely(saved_path)
            raise
    return {"items": results}


@router.post("/files/recover-stuck")
def recover_stuck_files(
    body: RecoverStuckFilesRequest,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    timeout_minutes = min(max(body.timeout_minutes or 30, 1), 24 * 60)
    candidates = list_stuck_processing_documents(db, timeout_minutes=timeout_minutes)
    if body.dry_run:
        return {
            "recovered_count": 0,
            "candidates_count": len(candidates),
            "documents": candidates,
        }

    result = recover_stuck_processing_documents(db, timeout_minutes=timeout_minutes)
    return {
        "recovered_count": result["recovered_count"],
        "candidates_count": len(candidates),
        "documents": result["documents"],
    }


def _create_parse_task(db: Session, document_id: str) -> KnowledgeParseTask:
    task = KnowledgeParseTask(
        document_id=document_id,
        status="pending",
        error_message=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _find_latest_parse_task(db: Session, document_id: str) -> KnowledgeParseTask | None:
    return (
        db.query(KnowledgeParseTask)
        .filter(KnowledgeParseTask.document_id == document_id)
        .order_by(KnowledgeParseTask.created_at.desc())
        .first()
    )


def _run_file_parse_task(
    *,
    document_id: str,
    task_id: str,
    file_path: str,
    file_name: str,
    related_skus: list[str],
) -> None:
    db = SessionLocal()
    try:
        task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not task or not document:
            return

        now = datetime.now(timezone.utc)
        task.status = "processing"
        task.started_at = now
        task.error_message = None
        document.parse_status = "processing"
        document.parse_error = None
        db.commit()

        document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not document:
            task.status = "error"
            task.finished_at = datetime.now(timezone.utc)
            task.error_message = "Document not found"
            db.commit()
            return

        parsed_document = None
        try:
            parsed_document = _run_async_ingest_file(
                db,
                file_path=file_path,
                file_name=file_name,
                related_skus=related_skus,
                document=document,
            )
            db.refresh(task)
            if parsed_document.parse_status == "done":
                task.status = "done"
                task.error_message = None
            else:
                task.status = "error"
                task.error_message = parsed_document.parse_error or "File parsing failed"
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.query(KnowledgeParseTask).filter(KnowledgeParseTask.id == task_id).first()
            document = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
            error_message = str(exc)[:2000]
            if document:
                document.parse_status = "error"
                document.parse_error = error_message
            if task:
                task.status = "error"
                task.error_message = error_message
                task.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _run_async_ingest_file(
    db: Session,
    *,
    file_path: str,
    file_name: str,
    related_skus: list[str],
    document: KnowledgeDocument,
) -> KnowledgeDocument:
    import asyncio

    return asyncio.run(
        ingest_file(
            db,
            file_path=file_path,
            file_name=file_name,
            related_skus=related_skus,
            document=document,
        )
    )


def _build_task_payload(task: KnowledgeParseTask) -> dict:
    return {
        "task_id": task.id,
        "document_id": task.document_id,
        "status": task.status,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _build_file_document_payload(db: Session, document: KnowledgeDocument) -> dict:
    related_skus = _load_related_skus(document.related_skus_json)
    products = _related_product_payloads(db, related_skus)
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).all()
    embedding_synced_count = sum(1 for chunk in chunks if chunk.embedding_status == "synced")
    embedding_pending_count = sum(1 for chunk in chunks if chunk.embedding_status == "pending")
    embedding_failed_count = sum(1 for chunk in chunks if chunk.embedding_status == "failed")
    task = _find_latest_parse_task(db, document.id)
    return {
        "document_id": document.id,
        "file_name": document.file_name or document.title,
        "file_type": document.file_type,
        "parse_status": document.parse_status,
        "parse_error": document.parse_error,
        "chunk_count": len(chunks),
        "embedding_synced_count": embedding_synced_count,
        "embedding_pending_count": embedding_pending_count,
        "embedding_failed_count": embedding_failed_count,
        "related_skus": related_skus,
        "related_products": products,
        "task_id": task.id if task else None,
        "task_status": task.status if task else None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if document.updated_at else None,
    }


def _related_product_payloads(db: Session, skus: list[str]) -> list[dict]:
    if not skus:
        return []
    rows = db.query(Product).filter(Product.sku.in_(skus)).all()
    by_sku = {str(row.sku or "").upper(): row for row in rows}
    result = []
    for sku in skus:
        product = by_sku.get(sku)
        result.append(
            {
                "sku": sku,
                "product_name_cn": product.product_name_cn if product else None,
                "product_name_en": product.product_name_en if product else None,
                "exists": bool(product),
            }
        )
    return result


def _validate_knowledge_file(file: UploadFile) -> str:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_KNOWLEDGE_FILE_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in ALLOWED_KNOWLEDGE_FILE_MIME_TYPES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    return suffix


async def _save_knowledge_file(file: UploadFile, suffix: str) -> tuple[str, str, str]:
    original_name = os.path.basename(file.filename or "").strip().replace("\x00", "")
    if not original_name:
        original_name = f"knowledge-file{suffix}"
    if Path(original_name).suffix.lower() != suffix:
        original_name = f"{Path(original_name).stem}{suffix}"
    stored_name = _available_knowledge_file_name(original_name)
    saved_path = os.path.join(KNOWLEDGE_FILE_DIR, stored_name)
    digest = hashlib.sha256()
    total_bytes = 0
    async with aiofiles.open(saved_path, "wb") as handle:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > MAX_KNOWLEDGE_FILE_BYTES:
                await handle.close()
                _remove_file_safely(saved_path)
                raise HTTPException(status_code=413, detail="文件不能超过 20MB")
            digest.update(chunk)
            await handle.write(chunk)
    return saved_path, stored_name, digest.hexdigest()


def _available_knowledge_file_name(file_name: str) -> str:
    """Keep readable source names while preventing same-name uploads from overwriting files."""
    candidate = Path(file_name)
    stem = candidate.stem or "knowledge-file"
    suffix = candidate.suffix
    index = 1
    while (Path(KNOWLEDGE_FILE_DIR) / candidate.name).exists():
        candidate = Path(f"{stem} ({index}){suffix}")
        index += 1
    return candidate.name


def _normalize_related_skus(values: str | list[str] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, list):
        raw_values = values
    else:
        text = str(values).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    raw_values = parsed
                else:
                    raw_values = [parsed]
            except Exception:
                raw_values = [text]
        else:
            raw_values = [item.strip() for item in text.replace(";", ",").replace("\n", ",").split(",")]
    seen = set()
    normalized: list[str] = []
    for value in raw_values:
        sku = str(value or "").strip().upper()
        if sku and sku not in seen:
            seen.add(sku)
            normalized.append(sku)
    return normalized


def _find_existing_file_document(db: Session, file_hash: str):
    rows = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.source_type == "file",
            KnowledgeDocument.file_hash == file_hash,
        )
        .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.created_at.desc())
        .all()
    )
    for row in rows:
        if row.parse_status == "done":
            return row
    for row in rows:
        if row.parse_status == "processing":
            return row
    for row in rows:
        if row.parse_status == "error":
            return row
    return None


def _build_existing_document_payload(
    db: Session,
    *,
    existing: KnowledgeDocument,
    original_name: str,
    stored_name: str,
    duplicate: bool,
    message: str,
    incoming_related_skus: list[str],
) -> dict:
    if existing.parse_status == "done":
        _merge_related_skus(db, existing, incoming_related_skus)
        db.refresh(existing)
    task = _find_latest_parse_task(db, existing.id)
    return {
        "document_id": existing.id,
        "task_id": task.id if task else None,
        "task_status": task.status if task else None,
        "reused_document_id": existing.id,
        "duplicate": duplicate,
        "message": message,
        "file_name": existing.file_name or original_name or stored_name,
        "file_type": existing.file_type,
        "parse_status": existing.parse_status,
        "parse_error": existing.parse_error,
        "chunk_count": db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == existing.id).count(),
        "related_skus": _load_related_skus(existing.related_skus_json),
    }


def _duplicate_message(parse_status: str | None) -> str:
    if parse_status == "processing":
        return "文件正在处理中，请稍后刷新后查看"
    if parse_status == "error":
        return "文件已上传过，但上次解析失败，请先处理错误记录"
    return "文件已上传过，已复用已有知识库文档"


def _merge_related_skus(db: Session, document, incoming_skus: list[str]) -> list[str]:
    existing = _load_related_skus(document.related_skus_json)
    merged = []
    seen = set()
    for sku in [*existing, *incoming_skus]:
        value = str(sku or "").strip().upper()
        if value and value not in seen:
            seen.add(value)
            merged.append(value)
    document.related_skus_json = json.dumps(merged, ensure_ascii=False)
    if not document.sku and merged:
        document.sku = merged[0]
    db.commit()
    db.refresh(document)
    return merged


def _load_related_skus(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            seen = set()
            items = []
            for sku in parsed:
                normalized = str(sku or "").strip().upper()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    items.append(normalized)
            return items
    except Exception:
        pass
    return []


def _remove_file_safely(path: str) -> None:
    try:
        candidate = _resolve_knowledge_file_path(path)
        if candidate.exists():
            candidate.unlink()
    except Exception:
        pass


def _resolve_knowledge_file_path(path: str) -> Path:
    raw_path = str(path or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Invalid file path")
    try:
        candidate_path = Path(raw_path)
        if not candidate_path.is_absolute():
            candidate_path = Path(KNOWLEDGE_FILE_DIR) / candidate_path
        candidate = candidate_path.resolve(strict=False)
        roots = _knowledge_file_roots()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return candidate
