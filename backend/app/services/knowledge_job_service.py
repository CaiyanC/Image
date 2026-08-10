from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.knowledge_job import KnowledgeJob
from . import knowledge_service, operation_log_service, product_service, product_vector_index_service


MAX_JOBS = 100
ACTIVE_SLOT = "knowledge-maintenance"
TERMINAL_STATUSES = {"succeeded", "failed"}


class KnowledgeJobEnqueueError(RuntimeError):
    def __init__(self, job_id: str):
        super().__init__("Knowledge job could not be queued")
        self.job_id = job_id


def create_reindex_job(
    db: Session,
    *,
    created_by: str,
    mode: str = "pending",
    limit: int | None = None,
    embed: bool = True,
) -> dict:
    payload = {
        "mode": mode if mode in {"pending", "full"} else "pending",
        "limit": limit,
        "embed": embed,
    }
    return _create_job(db, "product_reindex", created_by=created_by, payload=payload)


def create_embedding_retry_job(
    db: Session,
    *,
    created_by: str,
    limit: int | None = 20,
) -> dict:
    return _create_job(db, "embedding_retry", created_by=created_by, payload={"limit": limit})


def list_jobs(db: Session, limit: int = 20) -> dict:
    capped_limit = max(1, min(limit, MAX_JOBS))
    items = (
        db.query(KnowledgeJob)
        .order_by(KnowledgeJob.created_at.desc())
        .limit(capped_limit)
        .all()
    )
    total = db.query(KnowledgeJob).count()
    return {"items": [_public_job(item) for item in items], "total": total}


def get_job(db: Session, job_id: str) -> dict | None:
    job = db.get(KnowledgeJob, job_id)
    return _public_job(job) if job else None


def _create_job(db: Session, kind: str, *, created_by: str, payload: dict[str, Any]) -> dict:
    active = _active_job(db)
    if active:
        return _public_job(active)

    job = KnowledgeJob(
        kind=kind,
        status="queued",
        stage="queued",
        created_by=created_by,
        payload=payload,
        active_slot=ACTIVE_SLOT,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Another API worker won the unique active-slot race.
        db.rollback()
        active = _active_job(db)
        if active:
            return _public_job(active)
        raise
    db.refresh(job)
    _trim_terminal_jobs(db)

    try:
        from ..tasks.knowledge_jobs import run_knowledge_job

        run_knowledge_job.apply_async(args=[job.id], task_id=job.id)
    except Exception as exc:
        db.rollback()
        failed = db.get(KnowledgeJob, job.id)
        if failed:
            _mark_terminal(
                failed,
                status="failed",
                stage="enqueue_failed",
                error=f"Celery enqueue failed: {type(exc).__name__}",
            )
            db.commit()
        raise KnowledgeJobEnqueueError(job.id) from exc
    return _public_job(job)


def run_job(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = (
            db.query(KnowledgeJob)
            .filter(KnowledgeJob.id == job_id)
            .with_for_update()
            .first()
        )
        if not job:
            return {"ok": False, "error": "Job not found", "job_id": job_id}
        if job.status in TERMINAL_STATUSES:
            return {"ok": job.status == "succeeded", "job": _public_job(job)}

        job.status = "running"
        job.stage = "starting"
        job.started_at = job.started_at or _now()
        job.error = None
        db.commit()
        _log_job(db, job, "started")

        if job.kind == "product_reindex":
            result = _run_product_reindex(db, job, dict(job.payload or {}))
        elif job.kind == "embedding_retry":
            result = _run_embedding_retry(db, job, dict(job.payload or {}))
        else:
            raise RuntimeError(f"Unknown knowledge job kind: {job.kind}")

        job = db.get(KnowledgeJob, job_id)
        _mark_terminal(job, status="succeeded", stage="completed", result=result)
        db.commit()
        _log_job(db, job, "succeeded")
        return {"ok": True, "job": _public_job(job)}
    except Exception as exc:
        db.rollback()
        job = db.get(KnowledgeJob, job_id)
        if job:
            _mark_terminal(
                job,
                status="failed",
                stage="failed",
                error=str(exc)[:2000],
            )
            db.commit()
            _log_job(db, job, "failed", error=str(exc)[:2000])
            return {"ok": False, "job": _public_job(job)}
        return {"ok": False, "error": str(exc)[:2000], "job_id": job_id}
    finally:
        db.close()


def recover_stale_jobs(db: Session, *, stale_minutes: int | None = None) -> int:
    minutes = max(1, stale_minutes or settings.KNOWLEDGE_JOB_STALE_MINUTES)
    cutoff = _now() - timedelta(minutes=minutes)
    stale = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.status.in_(("queued", "running")),
            KnowledgeJob.updated_at < cutoff,
        )
        .all()
    )
    for job in stale:
        _mark_terminal(
            job,
            status="failed",
            stage="interrupted",
            error="Job did not finish before the recovery timeout.",
        )
    if stale:
        db.commit()
    return len(stale)


def _run_product_reindex(db: Session, job: KnowledgeJob, payload: dict[str, Any]) -> dict:
    mode = payload.get("mode") if payload.get("mode") in {"pending", "full"} else "pending"
    embed = bool(payload.get("embed", True))
    if mode == "full":
        _set_stage(db, job, "indexing_all_products")
        indexed = product_vector_index_service.index_all_products(db)
        embed_limit = payload.get("limit")
    else:
        limit = min(max(int(payload.get("limit") or 100), 1), 1000)
        _set_stage(db, job, "syncing_pending_products")
        indexed = product_service.sync_pending_products_to_vector_db(db, limit=limit)
        embed_limit = limit
    embedded = None
    if embed:
        _set_stage(db, job, "embedding_unsynced_chunks")
        embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=embed_limit)
    _set_stage(db, job, "building_health_report")
    return {
        "mode": mode,
        "indexed": indexed,
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


def _run_embedding_retry(db: Session, job: KnowledgeJob, payload: dict[str, Any]) -> dict:
    limit = min(max(int(payload.get("limit") or 20), 1), 500)
    _set_stage(db, job, "embedding_retry")
    embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=limit)
    _set_stage(db, job, "building_health_report")
    return {
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


def _set_stage(db: Session, job: KnowledgeJob, stage: str) -> None:
    job.stage = stage
    job.updated_at = _now()
    db.commit()


def _mark_terminal(
    job: KnowledgeJob,
    *,
    status: str,
    stage: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    job.status = status
    job.stage = stage
    job.result = result
    job.error = error
    job.active_slot = None
    job.finished_at = _now()
    job.updated_at = job.finished_at


def _active_job(db: Session) -> KnowledgeJob | None:
    return (
        db.query(KnowledgeJob)
        .filter(KnowledgeJob.active_slot == ACTIVE_SLOT)
        .order_by(KnowledgeJob.created_at.asc())
        .first()
    )


def _trim_terminal_jobs(db: Session) -> None:
    stale_ids = [
        row[0]
        for row in (
            db.query(KnowledgeJob.id)
            .filter(KnowledgeJob.active_slot.is_(None))
            .order_by(KnowledgeJob.created_at.desc())
            .offset(MAX_JOBS)
            .all()
        )
    ]
    if stale_ids:
        db.query(KnowledgeJob).filter(KnowledgeJob.id.in_(stale_ids)).delete(synchronize_session=False)
        db.commit()


def _log_job(db: Session, job: KnowledgeJob, status: str, error: str | None = None) -> None:
    try:
        operation_log_service.log_operation(
            db,
            operator_id=job.created_by,
            action_type="knowledge_job",
            action_name=f"Knowledge job {job.kind} {status}",
            target_type="knowledge_job",
            target_id=job.id,
            target_name=job.kind,
            request_data=job.payload,
            response_data=job.result,
            status="failed" if status == "failed" else "success",
            error_message=error,
        )
    except Exception:
        db.rollback()


def _public_job(job: KnowledgeJob) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "stage": job.stage,
        "payload": dict(job.payload or {}),
        "result": dict(job.result) if isinstance(job.result, dict) else None,
        "error": job.error,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _now() -> datetime:
    return datetime.now(timezone.utc)
