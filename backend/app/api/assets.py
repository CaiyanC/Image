import hashlib
import logging
import os
import uuid
from io import BytesIO
from math import gcd
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.security import has_permission, require_any_permission, require_permission, require_product_permission
from ..models.user import User
from ..schemas.asset import AssetTagsUpdate, ProductAssetCreate, ProductAssetUpdate
from ..services import asset_service, operation_log_service
from ..services.upload_validation_service import validate_image_content, validate_video_content, validate_docx_content
from ..services.video_metadata_service import read_video_duration, validate_video_slot

router = APIRouter(prefix="/api/products/{sku}/assets", tags=["assets"])
logger = logging.getLogger(__name__)

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
    "quality_status", "quality_reason", "duplicate_status", "duplicate_of_asset_id",
}


@router.get("")
def list_assets(
    sku: str,
    category: str | None = None,
    sub_category: str | None = None,
    asset_type: str | None = None,
    grouped: bool = False,
    current_user: User = Depends(require_any_permission("media.read", "media.search", "product.full.view", "product.edit")),
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
    current_user: User = Depends(require_any_permission("media.read", "media.search", "product.full.view", "product.edit")),
    db: Session = Depends(get_db),
):
    return asset_service.model_to_dict(asset_service.get_asset(db, sku, asset_id, allow_related=True))


@router.post("")
def create_asset(
    request: Request,
    sku: str,
    body: ProductAssetCreate,
    current_user: User = Depends(require_product_permission("update")),
    upload_user: User = Depends(require_permission("media.upload")),
    db: Session = Depends(get_db),
):
    del upload_user
    payload = body.model_dump()
    _require_review_permission_for_changed_fields(db, current_user, payload)
    created = asset_service.create_asset(db, sku, payload, commit=False)
    _commit_quality_changes(db, current_user, request, sku, [(created, [])])
    return asset_service.model_to_dict(created)


@router.post("/batch")
def create_assets_batch(
    request: Request,
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
    created = asset_service.create_assets_batch(db, sku, items, commit=False)
    _commit_quality_changes(db, current_user, request, sku, [(item, []) for item in created])
    return [asset_service.model_to_dict(item) for item in created]


@router.put("/{asset_id}")
def update_asset(
    request: Request,
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
    if payload.get("url", current_asset.url) != current_asset.url and asset_service.parse_tags(current_asset.tags).get("video_duration_status"):
        raise HTTPException(status_code=422, detail="已测量的视频不能直接替换文件地址，请重新上传以校验时长")
    changed_review_fields = {
        field for field in REVIEW_FIELDS.intersection(payload)
        if payload[field] != getattr(current_asset, field)
    }
    _require_review_tag_permission(db, current_user, payload, asset_service.parse_tags(current_asset.tags))
    if changed_review_fields and not has_permission(db, current_user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")
    lifecycle_before = {
        field: getattr(current_asset, field)
        for field in sorted(REVIEW_FIELDS)
    }
    before_checks = asset_service.parse_tags(current_asset.tags).get("quality_check_tags", [])
    updated = asset_service.update_asset(db, sku, asset_id, payload, commit=False)
    _commit_quality_changes(
        db,
        current_user,
        request,
        sku,
        [(updated, before_checks)],
        lifecycle_before={updated.id: lifecycle_before},
    )
    return asset_service.model_to_dict(updated)


def _require_review_permission_for_changed_fields(db: Session, user: User, payload: dict) -> None:
    _require_review_tag_permission(db, user, payload, {})
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
        "quality_status": "usable",
        "quality_reason": None,
        "duplicate_status": "unique",
        "duplicate_of_asset_id": None,
    }
    changed = {
        field for field in REVIEW_FIELDS.intersection(payload)
        if payload[field] != defaults[field]
    }
    if changed and not has_permission(db, user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")


def _require_review_tag_permission(db: Session, user: User, payload: dict, current_tags: dict) -> None:
    if "tags" not in payload:
        return
    proposed = asset_service.parse_tags(payload["tags"])
    if any(proposed.get(key, []) != current_tags.get(key, []) for key in ("video_duration_seconds", "video_duration_status")):
        raise HTTPException(status_code=422, detail="视频时长元数据由上传解析生成，不能手工修改或清除")
    if any(proposed.get(key, []) != current_tags.get(key, []) for key in ("risk_tags", "quality_check_tags")):
        if not has_permission(db, user.id, "media.review"):
            raise HTTPException(status_code=403, detail="Permission required: media.review")


@router.patch("/{asset_id}/tags")
def update_asset_tags(
    request: Request,
    sku: str,
    asset_id: str,
    body: AssetTagsUpdate,
    current_user: User = Depends(require_product_permission("update")),
    tag_user: User = Depends(require_permission("tag.edit")),
    db: Session = Depends(get_db),
):
    del tag_user
    if (body.risk_tags is not None or body.quality_check_tags is not None) and not has_permission(db, current_user.id, "media.review"):
        raise HTTPException(status_code=403, detail="Permission required: media.review")
    before_checks = asset_service.parse_tags(asset_service.get_asset(db, sku, asset_id).tags).get("quality_check_tags", [])
    updated = asset_service.update_asset_tags(db, sku, asset_id, body.normalized(), commit=False)
    _commit_quality_changes(db, current_user, request, sku, [(updated, before_checks)])
    return asset_service.model_to_dict(updated)


def _log_quality_checks(db: Session, user: User, request: Request, sku: str, asset_id: str, before: list, after: list) -> None:
    if before == after:
        return
    operation_log_service.log_operation(
        db, operator_id=user.id, action_type="asset_quality_check",
        action_name="更新素材标准检查", target_type="product_asset",
        target_id=asset_id, target_name=sku,
        request_data={"before": before}, response_data={"after": after}, request=request, commit=False,
    )


def _log_lifecycle_review(db: Session, user: User, request: Request, sku: str, asset, before: dict) -> None:
    after = {field: getattr(asset, field) for field in sorted(REVIEW_FIELDS)}
    changed = {field for field in after if before.get(field) != after[field]}
    if not changed:
        return
    operation_log_service.log_operation(
        db,
        operator_id=user.id,
        action_type="asset_lifecycle_review",
        action_name="更新素材审核与使用范围",
        target_type="product_asset",
        target_id=asset.id,
        target_name=sku,
        request_data={"before": {field: before.get(field) for field in sorted(changed)}},
        response_data={"after": {field: after[field] for field in sorted(changed)}},
        request=request,
        commit=False,
    )


def _commit_quality_changes(
    db: Session,
    user: User,
    request: Request,
    sku: str,
    changes: list,
    *,
    lifecycle_before: dict[str, dict] | None = None,
) -> None:
    try:
        for asset, before in changes:
            _log_quality_checks(db, user, request, sku, asset.id, before, asset_service.parse_tags(asset.tags).get("quality_check_tags", []))
            if lifecycle_before and asset.id in lifecycle_before:
                _log_lifecycle_review(db, user, request, sku, asset, lifecycle_before[asset.id])
        db.commit()
    except Exception:
        db.rollback()
        raise
    for asset, _ in changes:
        db.refresh(asset)


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
    request: Request,
    sku: str,
    files: List[UploadFile] = File(...),
    maintainer: str | None = Form(None, max_length=100),
    related_skus: List[str] = Form(default=[]),
    category_tags: List[str] = Form(default=[]),
    material_type_tags: List[str] = Form(default=[]),
    subject_tags: List[str] = Form(default=[]),
    expression_tags: List[str] = Form(default=[]),
    selling_point_tags: List[str] = Form(default=[]),
    composition_tags: List[str] = Form(default=[]),
    view_tags: List[str] = Form(default=[]),
    scene_tags: List[str] = Form(default=[]),
    mood_tags: List[str] = Form(default=[]),
    channel_tags: List[str] = Form(default=[]),
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
    # ``status_tag`` is a review/lifecycle decision, even though it arrives in
    # the multipart upload form rather than the JSON asset update endpoint.
    # Keep ordinary uploaders able to create pending assets, but do not let
    # ``media.upload`` implicitly grant ``media.review`` and publish a file to
    # the approved/MCP-visible set.
    if status_tag is not None:
        _require_review_permission_for_changed_fields(
            db,
            current_user,
            {"status_tag": status_tag},
        )
    del upload_user
    asset_service.ensure_product_exists(db, sku)
    for linked_sku in related_skus:
        asset_service.ensure_product_exists(db, linked_sku.strip())
    upload_tags = asset_service.default_upload_tags(category_code, sub_category)
    if category_tags:
        upload_tags["category_tags"] = list(dict.fromkeys([
            *upload_tags.get("category_tags", []),
            *category_tags,
        ]))
    for key, values in (
        ("material_type_tags", material_type_tags),
        ("subject_tags", subject_tags),
        ("expression_tags", expression_tags),
        ("selling_point_tags", selling_point_tags),
        ("scene_tags", scene_tags),
        ("mood_tags", mood_tags),
        ("channel_tags", channel_tags),
    ):
        if values:
            upload_tags[key] = list(dict.fromkeys([
                *upload_tags.get(key, []),
                *values,
            ]))
    if composition_tags:
        upload_tags["composition_tags"] = list(dict.fromkeys(composition_tags))
    if view_tags:
        upload_tags["view_tags"] = list(dict.fromkeys(view_tags))
    elif category_code == "01" and sub_category == "多角度图":
        slot_view = {"front": "正视", "side": "侧视", "back": "背视", "detail": "特写"}.get(material_type)
        if slot_view:
            upload_tags["view_tags"] = [slot_view]
    upload_tags = asset_service.validate_asset_tags(upload_tags)
    maximum = MAX_ASSET_VIDEOS_PER_REQUEST if category_code == "06" else MAX_ASSET_IMAGES_PER_REQUEST
    if not files or len(files) > maximum:
        raise HTTPException(status_code=413, detail=f"每次最多上传 {maximum} 个文件")
    for upload in files:
        _prevalidate_asset_upload(upload, is_video=category_code == "06", allow_document=category_code == "03")
    saved_paths: list[str] = []
    items: list[dict] = []
    try:
        for upload in files:
            payload = _save_upload_file(
                sku=sku,
                upload=upload,
                category_code=category_code,
                sub_category=sub_category,
                material_type=material_type,
            )
            saved_paths.extend(payload.pop("_local_paths", []))
            item_tags = dict(upload_tags)
            if category_code == "06":
                duration = payload.get("_video_duration_seconds")
                item_tags["video_duration_status"] = ["measured" if duration is not None else "unavailable"]
                if duration is not None:
                    item_tags["video_duration_seconds"] = [str(duration)]
            upload_sub_category = sub_category
            upload_material_type = material_type
            upload_asset_type = payload["asset_type"]
            if category_code == "06":
                upload_sub_category = sub_category or "视频"
                canonical_video_type = {
                    "白底视频": "whiteBackgroundVideo",
                    "场景短视频（≤30秒）": "sceneShortVideo",
                    "场景长视频（>30秒）": "sceneLongVideo",
                }.get(upload_sub_category)
                upload_material_type = (
                    canonical_video_type
                    if material_type in (None, "", "video") and canonical_video_type
                    else material_type or "video"
                )
                upload_asset_type = "video"
            items.append({
                "category_code": category_code,
                "related_skus": related_skus,
                "video_duration_seconds": payload.get("_video_duration_seconds"),
                "category_name": category_name,
                "sub_category": upload_sub_category,
                "asset_type": upload_asset_type,
                "url": payload["url"],
                "thumbnail_url": payload.get("thumbnail_url"),
                "material_type": upload_material_type,
                "angle_scene": angle_scene or None,
                "maintainer": maintainer.strip() or None if maintainer else None,
                "channel": channel or (upload_tags.get("channel_tags") or [None])[0],
                "language_tag": language_tag or (
                    {"中文说明": "CN", "英文说明": "EN"}.get(upload_sub_category)
                    if category_code == "03" else None
                ),
                "version_tag": version_tag or None,
                "status_tag": status_tag or None,
                "tags": item_tags,
                "notes": notes or asset_service.filename_without_extension(upload.filename),
                "original_file_name": payload.get("original_file_name"),
                "file_format": payload.get("file_format"),
                "mime_type": payload.get("mime_type"),
                "file_size_bytes": payload.get("file_size_bytes"),
                "checksum_sha256": payload.get("checksum_sha256"),
                "width": payload.get("width"),
                "height": payload.get("height"),
                "resolution": payload.get("resolution"),
                "aspect_ratio": payload.get("aspect_ratio"),
            })
        created = asset_service.create_assets_batch(db, sku, items, commit=False)
    except Exception:
        db.rollback()
        _cleanup_saved_paths(saved_paths)
        raise
    try:
        operation_log_service.log_operation(
            db, operator_id=current_user.id, action_type="asset_upload",
            action_name=f"上传 {len(created)} 个产品素材", target_type="product_asset_batch",
            target_id=sku, target_name=sku,
            request_data={
                "category_code": category_code, "category_name": category_name,
                "sub_category": sub_category, "material_type": material_type,
                "maintainer": maintainer.strip() if maintainer else None,
                "channel_tags": upload_tags.get("channel_tags", []),
                "files": [{"name": item.get("original_file_name"), "size": item.get("file_size_bytes"),
                           "mime_type": item.get("mime_type")} for item in items],
            },
            response_data={"count": len(created), "asset_ids": [item.id for item in created]},
            request=request, commit=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        _cleanup_saved_paths(saved_paths)
        raise
    for item in created:
        db.refresh(item)
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
    storage_scope: str = "assets",
) -> dict:
    if storage_scope not in {"assets", "competitors"}:
        raise ValueError("Unknown upload storage scope")
    ext = os.path.splitext(upload.filename or "")[1].lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    is_video_category = category_code == "06"
    duration = None
    if category_code == "03" and ext == ".docx":
        _validate_file_type(ext, content_type, {'.docx'}, {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "Word资料不能超过 20MB")
        _validate_manual_docx(content)
        asset_type = 'document'
    elif category_code == "03" and ext == ".pdf":
        _validate_file_type(ext, content_type, {".pdf"}, {"application/pdf"})
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "说明书不能超过 20MB")
        _validate_manual_pdf(content)
        asset_type = "document"
    elif is_video_category:
        _validate_file_type(ext, content_type, ALLOWED_VIDEO_SUFFIXES, ALLOWED_VIDEO_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_VIDEO_BYTES, "视频不能超过 200MB")
        _validate_media_content(content, ext, "video")
        duration = read_video_duration(content)
        try:
            validate_video_slot(duration, sub_category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        asset_type = "video"
    else:
        _validate_file_type(ext, content_type, ALLOWED_IMAGE_SUFFIXES, ALLOWED_IMAGE_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "图片不能超过 20MB")
        _validate_media_content(content, ext, "image")
        asset_type = "image"

    safe_sku = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in sku)
    asset_dir = os.path.abspath(os.path.join(settings.UPLOAD_DIR, storage_scope, safe_sku))
    os.makedirs(asset_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(asset_dir, filename)
    width = height = None
    if asset_type == "image":
        content, width, height = _sanitize_image_content(content, ext)

    saved_paths: list[str] = []
    try:
        _atomic_write(path, content)
        saved_paths.append(path)
        relative_url = f"/uploads/{storage_scope}/{safe_sku}/{filename}"
        thumbnail_url = None
        if asset_type == "image":
            thumbnail_url, thumbnail_path = _try_make_thumbnail(path, safe_sku, filename, storage_scope=storage_scope)
            if thumbnail_path:
                saved_paths.append(thumbnail_path)
        divisor = gcd(width, height) if width and height else 0
        return {
            "url": relative_url,
            "thumbnail_url": thumbnail_url,
            "asset_type": asset_type,
            "original_file_name": os.path.basename(upload.filename or "") or None,
            "file_format": ext.lstrip(".") or None,
            "mime_type": content_type or None,
            "file_size_bytes": len(content),
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}" if width and height else None,
            "aspect_ratio": f"{width // divisor}:{height // divisor}" if divisor else None,
            "_local_paths": saved_paths,
            "_video_duration_seconds": duration,
        }
    except Exception:
        _cleanup_saved_paths(saved_paths)
        raise


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


def _validate_manual_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="说明书必须为有效 PDF 文件")
    try:
        import fitz
        with fitz.open(stream=content, filetype="pdf") as reader:
            if reader.is_encrypted or not reader.page_count:
                raise ValueError("encrypted or empty manual")
            catalog = reader.pdf_catalog()
            if any(reader.xref_get_key(catalog, key)[0] != "null" for key in ("OpenAction", "AA")) or reader.embfile_count():
                raise ValueError("active PDF content")
            for xref in range(1, reader.xref_length()):
                if reader.xref_get_key(xref, "S")[1] in {"/JavaScript", "/Launch", "/SubmitForm"}:
                    raise ValueError("active PDF action")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="PDF 无法预览，或包含加密／自动执行内容，请上传普通说明书 PDF") from exc


def _prevalidate_asset_upload(upload: UploadFile, *, is_video: bool, allow_document: bool = False) -> None:
    ext = os.path.splitext(upload.filename or "")[1].lower()
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if allow_document and ext == '.docx':
        _validate_file_type(ext, content_type, {'.docx'}, {'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
        _validate_manual_docx(_read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "Word资料不能超过 20MB"))
    elif allow_document and ext == ".pdf":
        _validate_file_type(ext, content_type, {".pdf"}, {"application/pdf"})
        _validate_manual_pdf(_read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "说明书不能超过 20MB"))
    elif is_video:
        _validate_file_type(ext, content_type, ALLOWED_VIDEO_SUFFIXES, ALLOWED_VIDEO_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_VIDEO_BYTES, "视频不能超过 200MB")
        _validate_media_content(content, ext, "video")
    else:
        _validate_file_type(ext, content_type, ALLOWED_IMAGE_SUFFIXES, ALLOWED_IMAGE_MIME_TYPES)
        content = _read_limited_upload(upload, MAX_ASSET_IMAGE_BYTES, "图片不能超过 20MB")
        _validate_media_content(content, ext, "image")
    upload.file.seek(0)


def _validate_manual_docx(content: bytes) -> None:
    try:
        validate_docx_content(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_media_content(content: bytes, ext: str, media_type: str) -> None:
    try:
        if media_type == "image":
            validate_image_content(content, ext)
        else:
            validate_video_content(content, ext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _atomic_write(path: str, content: bytes) -> None:
    temporary_path = f"{path}.{uuid.uuid4().hex}.part"
    try:
        with open(temporary_path, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass


def _sanitize_image_content(content: bytes, ext: str) -> tuple[bytes, int, int]:
    """Normalize orientation and remove embedded camera metadata.

    Animated GIFs are preserved byte-for-byte so sanitization cannot destroy
    animation.  Static product images are re-encoded in their original format.
    """
    try:
        from PIL import Image, ImageOps
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Image processing is unavailable") from exc

    with Image.open(BytesIO(content)) as source:
        width, height = source.size
        if ext == ".gif" and bool(getattr(source, "is_animated", False)):
            return content, width, height
        image = ImageOps.exif_transpose(source)
        width, height = image.size
        output = BytesIO()
        if ext in {".jpg", ".jpeg"}:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(output, "JPEG", quality=95, optimize=True)
        elif ext == ".png":
            image.save(output, "PNG", optimize=True)
        elif ext == ".webp":
            image.save(output, "WEBP", quality=95, method=4)
        else:
            image.save(output, source.format or "PNG")
        return output.getvalue(), width, height


def _cleanup_saved_paths(paths: list[str]) -> None:
    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    for path in reversed(paths):
        target = os.path.abspath(path)
        try:
            if os.path.commonpath([target, upload_root]) == upload_root:
                os.remove(target)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("failed to compensate uploaded file %s: %s", target, exc)


def _try_make_thumbnail(path: str, safe_sku: str, filename: str, *, storage_scope: str = "assets") -> tuple[str | None, str | None]:
    try:
        from PIL import Image, ImageOps
    except Exception as exc:
        logger.warning("thumbnail support is unavailable: %s", exc)
        return None, None
    try:
        thumb_name = f"{os.path.splitext(filename)[0]}_thumb.jpg"
        thumb_path = os.path.join(os.path.dirname(path), thumb_name)
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((400, 400))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            buffer = BytesIO()
            image.save(buffer, "JPEG", quality=86, optimize=True)
            _atomic_write(thumb_path, buffer.getvalue())
        return f"/uploads/{storage_scope}/{safe_sku}/{thumb_name}", thumb_path
    except Exception as exc:
        logger.warning("failed to create thumbnail for %s: %s", path, exc)
        return None, None
