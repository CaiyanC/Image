import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.config import resolve_project_path, settings
from ..core.database import get_db
from ..core.security import require_permission, require_product_permission
from ..models.user import User
from ..schemas.asset import AssetTagsUpdate, ProductAssetCreate, ProductAssetUpdate
from ..services import asset_service

router = APIRouter(prefix="/api/products/{sku}/assets", tags=["assets"])

MAX_ASSET_IMAGE_BYTES = 20 * 1024 * 1024
MAX_ASSET_VIDEO_BYTES = 200 * 1024 * 1024
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
ALLOWED_VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/webm"}


@router.get("")
def list_assets(
    sku: str,
    category: str | None = None,
    sub_category: str | None = None,
    asset_type: str | None = None,
    grouped: bool = False,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    items = asset_service.list_assets(db, sku, category, sub_category, asset_type)
    if grouped:
        return asset_service.group_assets(items)
    return [asset_service.model_to_dict(item) for item in items]


@router.get("/{asset_id}")
def get_asset(
    sku: str,
    asset_id: str,
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    return asset_service.model_to_dict(asset_service.get_asset(db, sku, asset_id))


@router.post("")
def create_asset(
    sku: str,
    body: ProductAssetCreate,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    return asset_service.model_to_dict(asset_service.create_asset(db, sku, body.model_dump()))


@router.post("/batch")
def create_assets_batch(
    sku: str,
    body: list[ProductAssetCreate],
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    items = [item.model_dump() for item in body]
    created = asset_service.create_assets_batch(db, sku, items)
    return [asset_service.model_to_dict(item) for item in created]


@router.put("/{asset_id}")
def update_asset(
    sku: str,
    asset_id: str,
    body: ProductAssetUpdate,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    payload = body.model_dump(exclude_unset=True)
    return asset_service.model_to_dict(asset_service.update_asset(db, sku, asset_id, payload))


@router.patch("/{asset_id}/tags")
def update_asset_tags(
    sku: str,
    asset_id: str,
    body: AssetTagsUpdate,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    return asset_service.model_to_dict(
        asset_service.update_asset_tags(db, sku, asset_id, body.normalized())
    )


@router.delete("/{asset_id}")
def delete_asset(
    sku: str,
    asset_id: str,
    current_user: User = Depends(require_product_permission("update")),
    db: Session = Depends(get_db),
):
    asset_service.delete_asset(db, sku, asset_id)
    return {"ok": True}


@router.post("/upload")
def upload_assets(
    sku: str,
    files: List[UploadFile] = File(...),
    category_code: str = Form(...),
    category_name: str = Form(...),
    sub_category: str | None = Form(None),
    material_type: str | None = Form(None),
    angle_scene: str | None = Form(None),
    channel: str | None = Form(None),
    language_tag: str | None = Form(None),
    version_tag: str | None = Form(None),
    status_tag: str | None = Form(None),
    notes: str | None = Form(None),
    current_user: User = Depends(require_product_permission("update")),
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    del current_user, upload_user
    asset_service.ensure_product_exists(db, sku)
    created = []
    for upload in files:
        payload = _save_upload_file(
            sku=sku,
            upload=upload,
            category_code=category_code,
            sub_category=sub_category,
            material_type=material_type,
        )
        upload_sub_category = sub_category
        upload_material_type = material_type
        upload_asset_type = payload["asset_type"]
        if category_code == "06":
            upload_sub_category = "视频"
            upload_material_type = "video"
            upload_asset_type = "video"
        item = {
            "category_code": category_code,
            "category_name": category_name,
            "sub_category": upload_sub_category,
            "asset_type": upload_asset_type,
            "url": payload["url"],
            "thumbnail_url": payload.get("thumbnail_url"),
            "material_type": upload_material_type,
            "angle_scene": angle_scene or None,
            "channel": channel or None,
            "language_tag": language_tag or None,
            "version_tag": version_tag or None,
            "status_tag": status_tag or None,
            "notes": notes or asset_service.filename_without_extension(upload.filename),
        }
        created.append(asset_service.create_asset(db, sku, item))
    return {
        "count": len(created),
        "items": [asset_service.model_to_dict(item) for item in created],
    }


def _save_upload_file(
    *,
    sku: str,
    upload: UploadFile,
    category_code: str,
    sub_category: str | None,
    material_type: str | None,
) -> dict[str, str | None]:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    is_video_category = category_code == "06"
    if is_video_category:
        _validate_file_type(ext, content_type, ALLOWED_VIDEO_SUFFIXES, ALLOWED_VIDEO_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_VIDEO_BYTES, "视频不能超过 200MB")
        asset_type = "video"
    else:
        _validate_file_type(ext, content_type, ALLOWED_IMAGE_SUFFIXES, ALLOWED_IMAGE_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "图片不能超过 20MB")
        asset_type = "image"

    safe_sku = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in sku)
    asset_dir = resolve_project_path(os.path.join(settings.UPLOAD_DIR, "assets", safe_sku))
    os.makedirs(asset_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(asset_dir, filename)
    with open(path, "wb") as handle:
        handle.write(content)

    relative_url = f"/uploads/assets/{safe_sku}/{filename}"
    thumbnail_url = None
    if asset_type == "image":
        thumbnail_url = _try_make_thumbnail(path, safe_sku, filename)
    return {"url": relative_url, "thumbnail_url": thumbnail_url, "asset_type": asset_type}


def _validate_file_type(
    ext: str,
    content_type: str,
    allowed_suffixes: set[str],
    allowed_mime_types: set[str],
) -> None:
    if ext not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    if content_type and content_type not in allowed_mime_types:
        raise HTTPException(status_code=400, detail="不支持的文件类型")


def _read_limited_upload(upload: UploadFile, max_bytes: int, message: str) -> bytes:
    content = upload.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=message)
    return content


def _try_make_thumbnail(path: str, safe_sku: str, filename: str) -> str | None:
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        thumb_name = f"{os.path.splitext(filename)[0]}_thumb.jpg"
        thumb_path = os.path.join(os.path.dirname(path), thumb_name)
        with Image.open(path) as image:
            image.thumbnail((400, 4000))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(thumb_path, "JPEG", quality=86)
        return f"/uploads/assets/{safe_sku}/{thumb_name}"
    except Exception:
        return None
