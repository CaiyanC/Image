import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.tool_run import ToolRun


MAX_UPLOAD_FILES = 20
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIX = ".xlsx"
_UNSAFE_INPUT_NAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
MAX_INPUT_BASENAME_LENGTH = 100


def _safe_input_basename(filename: str | None) -> str:
    # Browser filenames can contain either Windows or POSIX separators,
    # regardless of the server OS. Never retain a caller-supplied directory.
    basename = (filename or "upload.xlsx").replace("\\", "/").rsplit("/", 1)[-1]
    basename = _UNSAFE_INPUT_NAME.sub("_", basename).strip().rstrip(". ")
    if Path(basename).suffix.lower() != ALLOWED_SUFFIX:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .xlsx files are allowed")
    # Bound the complete storage component including the UUID prefix. Retain
    # business tokens such as '30天' needed by the workbook role detector.
    stem = Path(basename).stem[:MAX_INPUT_BASENAME_LENGTH - len(ALLOWED_SUFFIX)].rstrip(". ") or "upload"
    return stem + ALLOWED_SUFFIX


def run_directory(run_id: str) -> Path:
    try:
        normalized_id = str(uuid.UUID(str(run_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool run not found") from exc
    root = Path(settings.UPLOAD_DIR).resolve() / "tool-runs" / normalized_id
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    if upload_root not in root.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tool run path")
    return root


def create_run(db: Session, *, tool_key: str, created_by: str, parameters: dict, status: str = "queued") -> ToolRun:
    run = ToolRun(tool_key=tool_key, created_by=created_by, parameters=parameters, status=status)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def input_directory(run: ToolRun) -> Path:
    return run_directory(run.id) / "input"


def get_run(db: Session, run_id: str) -> ToolRun:
    run = db.get(ToolRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool run not found")
    return run


def ensure_run_access(run: ToolRun, *, user_id: str, is_management: bool) -> ToolRun:
    if not is_management and str(run.created_by) != str(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this tool run")
    return run


def save_input_file(run: ToolRun, *, filename: str | None, source: BinaryIO) -> dict:
    original_name = _safe_input_basename(filename)
    payload = source.read(MAX_UPLOAD_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Excel file is too large")

    input_dir = run_directory(run.id) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid.uuid4().hex}_{original_name}"
    path = input_dir / storage_name
    path.write_bytes(payload)
    return {
        "display_name": original_name,
        "storage_name": storage_name,
        "relative_path": f"input/{storage_name}",
        "size": len(payload),
    }


def resolve_run_file(run: ToolRun, relative_path: str) -> Path:
    candidate = (run_directory(run.id) / relative_path).resolve()
    root = run_directory(run.id).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid run file")
    if candidate.suffix.lower() not in {".xlsx", ".txt"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid run file")
    return candidate


def mark_running(db: Session, run: ToolRun) -> ToolRun:
    if run.status != "queued":
        raise ValueError(f"Cannot start tool run in {run.status} state")
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def mark_succeeded(db: Session, run: ToolRun, output_files: list[dict]) -> ToolRun:
    if run.status != "running":
        raise ValueError(f"Cannot complete tool run in {run.status} state")
    run.status = "succeeded"
    run.output_files = output_files
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run


def mark_failed(db: Session, run: ToolRun, message: str) -> ToolRun:
    if run.status not in {"queued", "running"}:
        raise ValueError(f"Cannot fail tool run in {run.status} state")
    run.status = "failed"
    run.error_message = message[:1000]
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return run
