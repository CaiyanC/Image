import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.config import resolve_project_path, settings
from ..core.database import get_db
from ..core.security import has_permission, require_permission, require_product_permission
from ..models.user import User
from ..schemas.asset import AssetTagsUpdate, ProductAssetCreate, ProductAssetUpdate
from ..services import asset_service
from ..services.upload_validation_service import validate_image_content, validate_video_content

router = APIRouter(prefix="/api/products/{sku}/assets", tags=["assets"])

MAX_ASSET_IMAGE_BYTES = 20 * 1024 * 1024
MAX_ASSET_VIDEO_BYTES = 200 * 1024 * 1024
MAX_ASSET_IMAGES_PER_REQUEST = 20
MAX_ASSET_VIDEOS_PER_REQUEST = 5
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
ALLOWED_VIDEO_MIME_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
REVIEW_FIELDS = {
    "status_tag", "review_status", "authorization_status", "asset_level",
    "is_public", "ai_customer_usable", "ai_marketing_usable",
    "ai_reference_usable", "forbidden_usage", "is_latest_version",
}


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
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    del upload_user
    payload = body.model_dump()
    _require_review_permission_for_changed_fields(db, current_user, payload)
    return asset_service.model_to_dict(asset_service.create_asset(db, sku, payload))


@router.post("/batch")
def create_assets_batch(
    sku: str,
    body: list[ProductAssetCreate],
    current_user: User = Depends(require_product_permission("update")),
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    items = [item.model_dump() for item in body]
    del upload_user
    for item in items:
        _require_review_permission_for_changed_fields(db, current_user, item)
    created = asset_service.create_assets_batch(db, sku, items)
    return [asset_service.model_to_dict(item) for item in created]


@router.put("/{asset_id}")
def update_asset(
    sku: str,
    asset_id: str,
    body: ProductAssetUpdate,
    current_user: User = Depends(require_product_permission("update")),
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    payload = body.model_dump(exclude_unset=True)
    del upload_user
    current_asset = asset_service.get_asset(db, sku, asset_id)
    changed_review_fields = {
        field for field in REVIEW_FIELDS.intersection(payload)
        if payload[field] != getattr(current_asset, field)
    }
    if changed_review_fields and not has_permission(db, current_user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")
    return asset_service.model_to_dict(asset_service.update_asset(db, sku, asset_id, payload))


def _require_review_permission_for_changed_fields(db: Session, user: User, payload: dict) -> None:
    defaults = {
        "status_tag": asset_service.DEFAULT_STATUS,
        "review_status": "pending",
        "authorization_status": "unknown",
        "asset_level": "C",
        "is_public": False,
        "ai_customer_usable": False,
        "ai_marketing_usable": False,
        "ai_reference_usable": False,
        "forbidden_usage": None,
        "is_latest_version": True,
    }
    changed = {
        field for field in REVIEW_FIELDS.intersection(payload)
        if payload[field] != defaults[field]
    }
    if changed and not has_permission(db, user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")


@router.patch("/{asset_id}/tags")
def update_asset_tags(
    sku: str,
    asset_id: str,
    body: AssetTagsUpdate,
    current_user: User = Depends(require_product_permission("update")),
    tag_user: User = Depends(require_permission("tag.edit")),
    db: Session = Depends(get_db),
):
    del tag_user
    if body.risk_tags is not None and not has_permission(db, current_user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")
    return asset_service.model_to_dict(
        asset_service.update_asset_tags(db, sku, asset_id, body.normalized())
    )


@router.delete("/{asset_id}")
def delete_asset(
    sku: str,
    asset_id: str,
    current_user: User = Depends(require_product_permission("update")),
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    del current_user, upload_user
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
    maximum = MAX_ASSET_VIDEOS_PER_REQUEST if category_code == "06" else MAX_ASSET_IMAGES_PER_REQUEST
    if not files or len(files) > maximum:
        raise HTTPException(status_code=413, detail=f"每次最多上传 {maximum} 个文件")
    for upload in files:
        _prevalidate_asset_upload(upload, is_video=category_code == "06")
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
        _validate_media_content(content, ext, "video")
        asset_type = "video"
    else:
        _validate_file_type(ext, content_type, ALLOWED_IMAGE_SUFFIXES, ALLOWED_IMAGE_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "图片不能超过 20MB")
        _validate_media_content(content, ext, "image")
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
        raise HTTPException(status_code=413, detail=message)
    return content


def _prevalidate_asset_upload(upload: UploadFile, *, is_video: bool) -> None:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if is_video:
        _validate_file_type(ext, content_type, ALLOWED_VIDEO_SUFFIXES, ALLOWED_VIDEO_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_VIDEO_BYTES, "视频不能超过 200MB")
        _validate_media_content(content, ext, "video")
    else:
        _validate_file_type(ext, content_type, ALLOWED_IMAGE_SUFFIXES, ALLOWED_IMAGE_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "图片不能超过 20MB")
        _validate_media_content(content, ext, "image")
    upload.file.seek(0)


def _validate_media_content(content: bytes, ext: str, media_type: str) -> None:
    try:
        if media_type == "image":
            validate_image_content(content, ext)
        else:
            validate_video_content(content, ext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
