import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from ..core.database import SessionLocal
from . import knowledge_service, operation_log_service, product_service, product_vector_index_service


MAX_JOBS = 100
_LOCK = threading.RLock()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-job")
_JOBS: dict[str, dict[str, Any]] = {}


def create_reindex_job(*, created_by: str, mode: str = "pending", limit: int | None = None, embed: bool = True) -> dict:
    payload = {
        "mode": mode if mode in {"pending", "full"} else "pending",
        "limit": limit,
        "embed": embed,
    }
    return _create_job("product_reindex", created_by=created_by, payload=payload)


def create_embedding_retry_job(*, created_by: str, limit: int | None = 20) -> dict:
    payload = {"limit": limit}
    return _create_job("embedding_retry", created_by=created_by, payload=payload)


def list_jobs(limit: int = 20) -> dict:
    with _LOCK:
        items = sorted(_JOBS.values(), key=lambda item: item["created_at"], reverse=True)[:max(1, min(limit, MAX_JOBS))]
        return {"items": [_public_job(item) for item in items], "total": len(_JOBS)}


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _public_job(job) if job else None


def _create_job(kind: str, *, created_by: str, payload: dict[str, Any]) -> dict:
    job_id = str(uuid.uuid4())
    now = _now()
    job = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "stage": "queued",
        "created_by": created_by,
        "payload": payload,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    with _LOCK:
        _JOBS[job_id] = job
        _trim_jobs_locked()
    _EXECUTOR.submit(_run_job, job_id)
    return _public_job(job)


def _run_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = _get_job_for_update(job_id)
        if not job:
            return
        _update_job(job_id, status="running", stage="starting", started_at=_now())
        _log_job(db, job, "started")
        if job["kind"] == "product_reindex":
            result = _run_product_reindex(db, job_id, job["payload"])
        elif job["kind"] == "embedding_retry":
            result = _run_embedding_retry(db, job_id, job["payload"])
        else:
            raise RuntimeError(f"Unknown knowledge job kind: {job['kind']}")
        _update_job(job_id, status="succeeded", stage="completed", result=result, finished_at=_now())
        _log_job(db, _get_job_for_update(job_id), "succeeded")
    except Exception as exc:
        _update_job(job_id, status="failed", stage="failed", error=str(exc), finished_at=_now())
        failed_job = _get_job_for_update(job_id)
        if failed_job:
            _log_job(db, failed_job, "failed", error=str(exc))
    finally:
        db.close()


def _run_product_reindex(db, job_id: str, payload: dict[str, Any]) -> dict:
    mode = payload.get("mode") if payload.get("mode") in {"pending", "full"} else "pending"
    embed = bool(payload.get("embed", True))
    if mode == "full":
        _update_job(job_id, stage="indexing_all_products")
        indexed = product_vector_index_service.index_all_products(db)
        embed_limit = payload.get("limit")
    else:
        limit = min(max(int(payload.get("limit") or 100), 1), 1000)
        _update_job(job_id, stage="syncing_pending_products")
        indexed = product_service.sync_pending_products_to_vector_db(db, limit=limit)
        embed_limit = limit
    embedded = None
    if embed:
        _update_job(job_id, stage="embedding_unsynced_chunks")
        embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=embed_limit)
    _update_job(job_id, stage="building_health_report")
    return {
        "mode": mode,
        "indexed": indexed,
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


def _run_embedding_retry(db, job_id: str, payload: dict[str, Any]) -> dict:
    limit = min(max(int(payload.get("limit") or 20), 1), 500)
    _update_job(job_id, stage="embedding_retry")
    embedded = product_vector_index_service.run_embed_pending_chunks(db, limit=limit)
    _update_job(job_id, stage="building_health_report")
    return {
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


def _log_job(db, job: dict[str, Any] | None, status: str, error: str | None = None) -> None:
    if not job:
        return
    try:
        operation_log_service.log_operation(
            db,
            operator_id=job["created_by"],
            action_type="knowledge_job",
            action_name=f"Knowledge job {job['kind']} {status}",
            target_type="knowledge_job",
            target_id=job["id"],
            target_name=job["kind"],
            request_data=job.get("payload"),
            response_data=job.get("result"),
            status="failed" if status == "failed" else "success",
            error_message=error,
        )
    except Exception:
        db.rollback()


def _get_job_for_update(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **changes: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(changes)
        job["updated_at"] = _now()


def _public_job(job: dict[str, Any] | None) -> dict:
    if not job:
        return {}
    return {
        "id": job["id"],
        "kind": job["kind"],
        "status": job["status"],
        "stage": job["stage"],
        "payload": job["payload"],
        "result": job["result"],
        "error": job["error"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


def _trim_jobs_locked() -> None:
    if len(_JOBS) <= MAX_JOBS:
        return
    ordered = sorted(_JOBS.values(), key=lambda item: item["created_at"])
    for job in ordered[:len(_JOBS) - MAX_JOBS]:
        _JOBS.pop(job["id"], None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
