import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.rate_limit import enforce_rate_limit
from ..core.security import get_current_user, has_permission
from ..core.permission_constants import MANAGEMENT_GROUP_NAME
from ..models.generation import Generation
from ..models.user import User
from ..models.group import Group
from ..models.user_group import UserGroup


router = APIRouter(prefix="/api/files", tags=["files"])

SIGNED_FILE_EXPIRE_SECONDS = int(os.getenv("SIGNED_FILE_EXPIRE_SECONDS", "600"))
FILE_SIGN_LIMIT_PER_MINUTE = 45
_SIGNED_FILE_ALGORITHM = settings.ALGORITHM
_SIGNED_FILE_AUDIENCE = "file-access"


class FileSignRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)


class FileSignResponse(BaseModel):
    url: str
    expires_in: int


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


@router.get("/signed/{token}")
def get_signed_file(token: str):
    normalized_path = _decode_file_token(token)
    file_path = _resolve_upload_path(normalized_path)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(file_path)


def _authorize_sign_request(db: Session, user: User, normalized_path: str) -> None:
    if normalized_path.startswith("/uploads/knowledge-files/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Knowledge files must be downloaded through the knowledge base API",
        )
    if normalized_path.startswith("/uploads/images/") or normalized_path.startswith("/uploads/videos/"):
        if has_permission(db, user.id, "product.read"):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission required: product.read")
    if normalized_path.startswith("/uploads/generated/"):
        if _is_generation_owner_or_manager(db, user, normalized_path):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Generated file access denied")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unsupported file scope")


def _is_generation_owner_or_manager(db: Session, user: User, normalized_path: str) -> bool:
    if _is_in_management_group(db, user.id):
        return True
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
        .filter(UserGroup.user_id == user_id, Group.group_name == MANAGEMENT_GROUP_NAME)
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
    except JWTError:
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
