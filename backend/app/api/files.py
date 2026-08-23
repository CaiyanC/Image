import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
import jwt
from jwt import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from ..core.config import BACKEND_ROOT, PROJECT_ROOT, settings
from ..core.database import get_db
from ..core.rate_limit import enforce_rate_limit
from ..core.security import get_current_user, has_permission
from ..core.permission_constants import FULL_ACCESS_GROUP_NAMES
from ..models.generation import Generation
from ..models.user import User
from ..models.group import Group
from ..models.user_group import UserGroup


router = APIRouter(prefix="/api/files", tags=["files"])

SIGNED_FILE_EXPIRE_SECONDS = int(os.getenv("SIGNED_FILE_EXPIRE_SECONDS", "600"))
FILE_SIGN_LIMIT_PER_MINUTE = 45
FILE_SIGN_BATCH_LIMIT_PER_MINUTE = 30
MAX_FILE_SIGN_BATCH_SIZE = 100
_SIGNED_FILE_ALGORITHM = settings.ALGORITHM
_SIGNED_FILE_AUDIENCE = "file-access"
logger = logging.getLogger(__name__)


class FileSignRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)


class FileSignResponse(BaseModel):
    url: str
    expires_in: int


class FileSignBatchRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1, max_length=MAX_FILE_SIGN_BATCH_SIZE)


class FileSignBatchItem(FileSignResponse):
    path: str


class FileSignBatchResponse(BaseModel):
    items: list[FileSignBatchItem]


@router.post("/sign", response_model=FileSignResponse)
def sign_file(
    body: FileSignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(
        user_id=str(current_user.id),
        scope="files.sign",
        limit=FILE_SIGN_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    normalized_path = _normalize_upload_url(body.path)
    _authorize_sign_request(db, current_user, normalized_path)
    token = _create_file_token(normalized_path)
    return FileSignResponse(url=f"/api/files/signed/{token}", expires_in=SIGNED_FILE_EXPIRE_SECONDS)


@router.post("/sign-batch", response_model=FileSignBatchResponse)
def sign_files_batch(
    body: FileSignBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(
        user_id=str(current_user.id),
        scope="files.sign-batch",
        limit=FILE_SIGN_BATCH_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    normalized_paths = list(dict.fromkeys(_normalize_upload_url(path) for path in body.paths))
    _authorize_sign_batch(db, current_user, normalized_paths)
    return FileSignBatchResponse(items=[
        FileSignBatchItem(
            path=path,
            url=f"/api/files/signed/{_create_file_token(path)}",
            expires_in=SIGNED_FILE_EXPIRE_SECONDS,
        )
        for path in normalized_paths
    ])


@router.get("/signed/{token}")
def get_signed_file(token: str):
    normalized_path = _decode_file_token(token)
    file_path = _resolve_upload_path(normalized_path)
    if not file_path.is_file():
        _copy_legacy_upload_if_available(normalized_path, file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(file_path)


def _authorize_sign_request(db: Session, user: User, normalized_path: str) -> None:
    if normalized_path.startswith("/uploads/knowledge-files/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Knowledge files must be downloaded through the knowledge base API",
        )
    if normalized_path.startswith("/uploads/reference-images/"):
        owner_id = normalized_path.removeprefix("/uploads/reference-images/").split("/", 1)[0]
        if owner_id == str(user.id) or _is_in_management_group(db, user.id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reference image access denied")
    if normalized_path.startswith(("/uploads/images/", "/uploads/videos/", "/uploads/assets/")):
        if has_permission(db, user.id, "product.read"):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: product.read")
    if normalized_path.startswith("/uploads/generated/"):
        if _is_generation_owner_or_manager(db, user, normalized_path):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Generated file access denied")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported file scope")


def _authorize_sign_batch(db: Session, user: User, normalized_paths: list[str]) -> None:
    product_read_allowed: bool | None = None
    management_allowed: bool | None = None
    for normalized_path in normalized_paths:
        if normalized_path.startswith("/uploads/knowledge-files/"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Knowledge files must be downloaded through the knowledge base API",
            )
        if normalized_path.startswith(("/uploads/images/", "/uploads/videos/", "/uploads/assets/")):
            if product_read_allowed is None:
                product_read_allowed = has_permission(db, user.id, "product.read")
            if product_read_allowed:
                continue
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: product.read")
        if normalized_path.startswith("/uploads/reference-images/"):
            owner_id = normalized_path.removeprefix("/uploads/reference-images/").split("/", 1)[0]
            if owner_id == str(user.id):
                continue
            if management_allowed is None:
                management_allowed = _is_in_management_group(db, user.id)
            if management_allowed:
                continue
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reference image access denied")
        if normalized_path.startswith("/uploads/generated/"):
            if management_allowed is None:
                management_allowed = _is_in_management_group(db, user.id)
            if management_allowed or _is_generation_owner(db, user, normalized_path):
                continue
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Generated file access denied")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported file scope")


def _is_generation_owner_or_manager(db: Session, user: User, normalized_path: str) -> bool:
    if _is_in_management_group(db, user.id):
        return True
    return _is_generation_owner(db, user, normalized_path)


def _is_generation_owner(db: Session, user: User, normalized_path: str) -> bool:
    row = (
        db.query(Generation)
        .filter(
            (Generation.result_image_path == normalized_path)
            | (Generation.result_video_path == normalized_path)
            | (cast(Generation.result_images, String).contains(normalized_path))
        )
        .first()
    )
    return bool(row and str(row.user_id) == str(user.id))


def _is_in_management_group(db: Session, user_id: str) -> bool:
    return (
        db.query(UserGroup)
        .join(Group, UserGroup.group_id == Group.id)
        .filter(UserGroup.user_id == user_id, Group.group_name.in_(FULL_ACCESS_GROUP_NAMES))
        .first()
        is not None
    )


def _create_file_token(normalized_path: str) -> str:
    from datetime import datetime, timedelta, timezone

    expire = datetime.now(timezone.utc) + timedelta(seconds=SIGNED_FILE_EXPIRE_SECONDS)
    payload = {"sub": normalized_path, "aud": _SIGNED_FILE_AUDIENCE, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_SIGNED_FILE_ALGORITHM)


def _decode_file_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[_SIGNED_FILE_ALGORITHM],
            audience=_SIGNED_FILE_AUDIENCE,
        )
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired file token")
    return _normalize_upload_url(str(payload.get("sub") or ""))


def _normalize_upload_url(raw_path: str) -> str:
    path = str(raw_path or "").strip().replace("\\", "/")
    if path.startswith("http://") or path.startswith("https://"):
        from urllib.parse import urlparse

        path = urlparse(path).path
    if not path.startswith("/uploads/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only /uploads paths can be signed")
    if ".." in Path(path).parts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    return path


def _resolve_upload_path(normalized_path: str) -> Path:
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    relative = normalized_path.removeprefix("/uploads/").lstrip("/")
    candidate = (upload_root / relative).resolve()
    if candidate != upload_root and upload_root not in candidate.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    return candidate


def _copy_legacy_upload_if_available(normalized_path: str, destination: Path) -> bool:
    """Copy a referenced file from the historical project-root upload folder.

    Old upload code interpreted relative UPLOAD_DIR values from PROJECT_ROOT,
    while readers used the backend cwd.  This compatibility copy is bounded to
    the known legacy root, verifies content, and intentionally leaves the source
    in place for rollback and later explicit reconciliation.
    """
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    if upload_root.parent != Path(BACKEND_ROOT).resolve():
        return False
    legacy_root = (Path(PROJECT_ROOT) / upload_root.name).resolve()
    if legacy_root == upload_root:
        return False
    relative = normalized_path.removeprefix("/uploads/").lstrip("/")
    source = (legacy_root / relative).resolve()
    if source != legacy_root and legacy_root not in source.parents:
        return False
    if not source.is_file():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.legacy-copy")
    try:
        shutil.copy2(source, temporary)
        if source.stat().st_size != temporary.stat().st_size or _sha256(source) != _sha256(temporary):
            raise OSError("legacy upload checksum verification failed")
        os.replace(temporary, destination)
        logger.info("copied legacy upload into canonical storage: %s", normalized_path)
        return True
    except OSError as exc:
        logger.warning("failed to copy legacy upload %s: %s", normalized_path, exc)
        return False
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
