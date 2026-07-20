import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.knowledge_base import KnowledgeJob
from . import knowledge_service, operation_log_service, product_service, product_vector_index_service


def create_reindex_job(db: Session, *, created_by: str, mode: str = "pending", limit: int | None = None, embed: bool = True) -> dict:
    return _create_job(db, "product_reindex", created_by, {"mode": mode if mode in {"pending", "full"} else "pending", "limit": limit, "embed": embed})


def create_embedding_retry_job(db: Session, *, created_by: str, limit: int | None = 20) -> dict:
    return _create_job(db, "embedding_retry", created_by, {"limit": limit})


def _create_job(db: Session, kind: str, created_by: str, payload: dict[str, Any]) -> dict:
    active = db.query(KnowledgeJob).filter(KnowledgeJob.status.in_(["queued", "running"])).order_by(KnowledgeJob.created_at.desc()).first()
    if active:
        return _public_job(active)
    job = KnowledgeJob(kind=kind, status="queued", stage="queued", created_by=str(created_by), payload_json=json.dumps(payload, ensure_ascii=False))
    db.add(job)
    db.commit()
    db.refresh(job)
    from ..tasks.knowledge_tasks import run_knowledge_job
    run_knowledge_job.delay(job.id)
    return _public_job(job)


def list_jobs(db: Session, limit: int = 20) -> dict:
    rows = db.query(KnowledgeJob).order_by(KnowledgeJob.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return {"items": [_public_job(row) for row in rows], "total": db.query(KnowledgeJob).count()}


def get_job(db: Session, job_id: str) -> dict | None:
    job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
    return _public_job(job) if job else None


def run_job(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
        if not job:
            return {"ok": False, "error": "Knowledge job not found"}
        if job.status not in {"queued", "running"}:
            return {"ok": True, "status": job.status, "job_id": job.id}
        job.status, job.stage, job.started_at = "running", "starting", _now()
        db.commit()
        payload = _load_json(job.payload_json)
        if job.kind == "product_reindex":
            result = _run_product_reindex(db, job, payload)
        elif job.kind == "embedding_retry":
            result = _run_embedding_retry(db, job, payload)
        else:
            raise RuntimeError(f"Unknown knowledge job kind: {job.kind}")
        job.status, job.stage, job.result_json, job.finished_at = "succeeded", "completed", json.dumps(result, ensure_ascii=False), _now()
        db.commit()
        _log_job(db, job, "succeeded")
        return {"ok": True, "job_id": job.id, "status": job.status}
    except Exception as exc:
        db.rollback()
        job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
        if job:
            job.status, job.stage, job.error_message, job.finished_at = "failed", "failed", str(exc)[:2000], _now()
            db.commit()
            _log_job(db, job, "failed", str(exc))
        return {"ok": False, "job_id": job_id, "error": str(exc)[:2000]}
    finally:
        db.close()


def _run_product_reindex(db: Session, job: KnowledgeJob, payload: dict) -> dict:
    mode = payload.get("mode") if payload.get("mode") in {"pending", "full"} else "pending"
    job.stage = "indexing_all_products" if mode == "full" else "syncing_pending_products"
    db.commit()
    indexed = product_vector_index_service.index_all_products(db) if mode == "full" else product_service.sync_pending_products_to_vector_db(db, limit=min(max(int(payload.get("limit") or 100), 1), 1000))
    embedded = None
    if bool(payload.get("embed", True)):
        job.stage = "embedding_unsynced_chunks"
        db.commit()
        embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=payload.get("limit"))
    return {"mode": mode, "indexed": indexed, "embedding": embedded, "health": knowledge_service.health_report(db)}


def _run_embedding_retry(db: Session, job: KnowledgeJob, payload: dict) -> dict:
    job.stage = "embedding_retry"
    db.commit()
    embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=min(max(int(payload.get("limit") or 20), 1), 500))
    return {"embedding": embedded, "health": knowledge_service.health_report(db)}


def _public_job(job: KnowledgeJob) -> dict:
    return {"id": job.id, "kind": job.kind, "status": job.status, "stage": job.stage, "payload": _load_json(job.payload_json), "result": _load_json(job.result_json), "error": job.error_message, "created_at": job.created_at, "updated_at": job.updated_at, "started_at": job.started_at, "finished_at": job.finished_at}


def _load_json(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_job(db: Session, job: KnowledgeJob, status: str, error: str | None = None) -> None:
    try:
        operation_log_service.log_operation(db, operator_id=job.created_by, action_type="knowledge_job", action_name=f"Knowledge job {job.kind} {status}", target_type="knowledge_job", target_id=job.id, target_name=job.kind, request_data=_load_json(job.payload_json), response_data=_load_json(job.result_json), status="failed" if status == "failed" else "success", error_message=error)
    except Exception:
        db.rollback()
