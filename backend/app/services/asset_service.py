import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.product import Product
from ..models.product_asset import ProductAsset
from .asset_taxonomy import (
    CONTROLLED_TAG_DICTIONARY,
    DUPLICATE_STATUS_VALUES,
    EXPRESSION_REQUIREMENTS,
    LEGACY_TAG_KEYS,
    QUALITY_STATUS_VALUES,
)


DEFAULT_BRAND = "alocs"
DEFAULT_CHANNEL = "General"
DEFAULT_LANGUAGE = "CN"
DEFAULT_VERSION = "V1"
DEFAULT_STATUS = "待审核"
AI_GENERATED_CATEGORY_CODE = "07"
ARCHIVE_CATEGORY_CODE = "08"
ARCHIVE_CATEGORY_NAME = "参考归档禁用图"

PUBLICATION_FLAG_FIELDS = (
    "is_public",
    "ai_customer_usable",
    "ai_marketing_usable",
    "ai_reference_usable",
)
BLOCKED_AUTHORIZATION_STATUSES = {
    "",
    "unknown",
    "internal_test",
    "pending",
    "rejected",
    "unapproved",
}

logger = logging.getLogger(__name__)


def today_tag() -> str:
    return datetime.now().strftime("%Y%m%d")


def ensure_product_exists(db: Session, sku: str) -> Product:
    product = db.query(Product).filter(Product.sku == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def normalize_tags(tags: Any) -> str:
    if tags is None or tags == "":
        return "{}"
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
        except json.JSONDecodeError:
            return "{}"
    elif isinstance(tags, dict):
        parsed = tags
    else:
        return "{}"

    normalized: dict[str, list[str]] = {}
    for key, value in parsed.items():
        if isinstance(value, list):
            clean = [str(item).strip() for item in value if str(item).strip()]
            if clean:
                normalized[str(key)] = clean
    return json.dumps(normalized, ensure_ascii=False)


def parse_tags(tags: Any) -> dict[str, list[str]]:
    if isinstance(tags, dict):
        return json.loads(normalize_tags(tags))
    if not tags:
        return {}
    try:
        parsed = json.loads(tags)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return json.loads(normalize_tags(parsed))


def validate_asset_tags(
    tags: Any,
    *,
    legacy_controlled_values: dict[str, set[str]] | None = None,
    enforce_expression_requirements: bool = True,
) -> dict[str, list[str]]:
    normalized = parse_tags(tags)
    legacy_controlled_values = legacy_controlled_values or {}
    for key, allowed_values in CONTROLLED_TAG_DICTIONARY.items():
        values = set(normalized.get(key, []))
        allowed_legacy = legacy_controlled_values.get(key, set())
        unsupported = sorted(values - set(allowed_values) - allowed_legacy)
        if unsupported:
            allowed = "、".join(allowed_values)
            raise HTTPException(
                status_code=422,
                detail=f"{key} 存在不支持的标签：{'、'.join(unsupported)}；可选值：{allowed}",
            )
    if enforce_expression_requirements:
        for expression, required_key in EXPRESSION_REQUIREMENTS.items():
            if expression in normalized.get("expression_tags", []) and not normalized.get(required_key):
                raise HTTPException(status_code=422, detail=f"{expression} 必须选择对应标签")
    return normalized


def validate_asset_lifecycle_values(data: dict[str, Any]) -> None:
    quality_status = data.get("quality_status")
    if quality_status is not None and quality_status not in QUALITY_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"quality_status 必须是：{'、'.join(QUALITY_STATUS_VALUES)}",
        )
    duplicate_status = data.get("duplicate_status")
    if duplicate_status is not None and duplicate_status not in DUPLICATE_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"duplicate_status 必须是：{'、'.join(DUPLICATE_STATUS_VALUES)}",
        )


def model_to_dict(asset: ProductAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "sku": asset.sku,
        "category_code": asset.category_code,
        "category_name": asset.category_name,
        "sub_category": asset.sub_category,
        "asset_type": asset.asset_type,
        "url": asset.url,
        "thumbnail_url": asset.thumbnail_url,
        "brand": asset.brand,
        "material_type": asset.material_type,
        "source_key": asset.source_key,
        "angle_scene": asset.angle_scene,
        "channel": asset.channel,
        "language_tag": asset.language_tag,
        "version_tag": asset.version_tag,
        "product_version": asset.product_version,
        "market_version": asset.market_version,
        "date_tag": asset.date_tag,
        "status_tag": asset.status_tag,
        "file_name": asset.file_name,
        "original_file_name": asset.original_file_name,
        "file_format": asset.file_format,
        "mime_type": asset.mime_type,
        "file_size_bytes": asset.file_size_bytes,
        "checksum_sha256": asset.checksum_sha256,
        "width": asset.width,
        "height": asset.height,
        "quality_status": asset.quality_status,
        "quality_reason": asset.quality_reason,
        "duplicate_status": asset.duplicate_status,
        "duplicate_of_asset_id": asset.duplicate_of_asset_id,
        "resolution": asset.resolution,
        "aspect_ratio": asset.aspect_ratio,
        "asset_level": asset.asset_level,
        "is_real_product": asset.is_real_product,
        "is_ai_generated": asset.is_ai_generated,
        "is_competitor": asset.is_competitor,
        "is_latest_version": asset.is_latest_version,
        "is_public": asset.is_public,
        "ai_customer_usable": asset.ai_customer_usable,
        "ai_marketing_usable": asset.ai_marketing_usable,
        "ai_reference_usable": asset.ai_reference_usable,
        "editable_flag": asset.editable_flag,
        "review_status": asset.review_status,
        "authorization_status": asset.authorization_status,
        "forbidden_usage": asset.forbidden_usage,
        "maintainer": asset.maintainer,
        "seq": asset.seq,
        "sort_order": asset.sort_order,
        "tags": parse_tags(asset.tags),
        "notes": asset.notes,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def get_asset(db: Session, sku: str, asset_id: str) -> ProductAsset:
    asset = db.query(ProductAsset).filter(
        ProductAsset.sku == sku,
        ProductAsset.id == asset_id,
    ).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def list_assets(
    db: Session,
    sku: str,
    category: str | None = None,
    sub_category: str | None = None,
    asset_type: str | None = None,
) -> list[ProductAsset]:
    ensure_product_exists(db, sku)
    query = db.query(ProductAsset).filter(ProductAsset.sku == sku)
    if category:
        query = query.filter(ProductAsset.category_code == category)
    if sub_category:
        query = query.filter(ProductAsset.sub_category == sub_category)
    if asset_type:
        query = query.filter(ProductAsset.asset_type == asset_type)
    return query.order_by(
        ProductAsset.category_code.asc(),
        ProductAsset.sub_category.asc(),
        ProductAsset.material_type.asc(),
        ProductAsset.seq.asc(),
        ProductAsset.created_at.asc(),
    ).all()


def search_assets(
    db: Session,
    *,
    sku: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    review_status: str | None = None,
    authorization_status: str | None = None,
    quality_status: str | None = None,
    duplicate_status: str | None = None,
    expression_tags: list[str] | None = None,
    selling_point_tags: list[str] | None = None,
    scene_tags: list[str] | None = None,
    mood_tags: list[str] | None = None,
    product_tags: list[str] | None = None,
    material_type_tags: list[str] | None = None,
    usage_tags: list[str] | None = None,
    version_tags: list[str] | None = None,
    risk_tags: list[str] | None = None,
    channel_tags: list[str] | None = None,
    language_tags: list[str] | None = None,
    limit: int = 100,
) -> list[ProductAsset]:
    tag_inputs = {
        "expression_tags": expression_tags or [],
        "selling_point_tags": selling_point_tags or [],
        "scene_tags": scene_tags or [],
        "mood_tags": mood_tags or [],
        "product_tags": product_tags or [],
        "material_type_tags": material_type_tags or [],
        "usage_tags": usage_tags or [],
        "version_tags": version_tags or [],
        "risk_tags": risk_tags or [],
        "channel_tags": channel_tags or [],
        "language_tags": language_tags or [],
    }
    validate_asset_lifecycle_values({
        "quality_status": quality_status,
        "duplicate_status": duplicate_status,
    })
    validate_asset_tags(tag_inputs, enforce_expression_requirements=False)
    query = db.query(ProductAsset)
    for column, value in (
        (ProductAsset.sku, sku),
        (ProductAsset.category_code, category),
        (ProductAsset.channel, channel),
        (ProductAsset.review_status, review_status),
        (ProductAsset.authorization_status, authorization_status),
        (ProductAsset.quality_status, quality_status),
        (ProductAsset.duplicate_status, duplicate_status),
    ):
        if value:
            query = query.filter(column == value)

    requested_tags = {
        key: {str(value).strip() for value in values if str(value).strip()}
        for key, values in tag_inputs.items()
        if key in CONTROLLED_TAG_DICTIONARY or key in LEGACY_TAG_KEYS
    }
    candidates = query.order_by(
        ProductAsset.sku.asc(),
        ProductAsset.category_code.asc(),
        ProductAsset.seq.asc(),
    ).all()
    return [
        asset for asset in candidates
        if all(
            not values or values.intersection(parse_tags(asset.tags).get(key, []))
            for key, values in requested_tags.items()
        )
    ][:limit]


def group_assets(assets: list[ProductAsset]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[ProductAsset]] = {}
    for asset in assets:
        grouped.setdefault((asset.category_code, asset.category_name), []).append(asset)
    return [
        {
            "category_code": category_code,
            "category_name": category_name,
            "count": len(items),
            "items": [model_to_dict(item) for item in items],
        }
        for (category_code, category_name), items in grouped.items()
    ]


def next_seq(
    db: Session,
    sku: str,
    category_code: str,
    sub_category: str | None,
    material_type: str | None,
) -> int:
    max_seq = db.query(func.max(ProductAsset.seq)).filter(
        ProductAsset.sku == sku,
        ProductAsset.category_code == category_code,
        ProductAsset.sub_category == sub_category,
        ProductAsset.material_type == material_type,
    ).scalar()
    return int(max_seq or 0) + 1


def apply_status_movement(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status_tag")
    if status == "禁用":
        data["review_status"] = "disabled"
        data["is_public"] = False
        data["ai_customer_usable"] = False
        data["ai_marketing_usable"] = False
        data["category_code"] = ARCHIVE_CATEGORY_CODE
        data["category_name"] = ARCHIVE_CATEGORY_NAME
        data["sub_category"] = "禁用素材"
        data["material_type"] = "banned"
    elif status in ("归档历史版本", "归档"):
        data["review_status"] = "archived"
        data["is_latest_version"] = False
        data["is_public"] = False
        data["ai_customer_usable"] = False
        data["category_code"] = ARCHIVE_CATEGORY_CODE
        data["category_name"] = ARCHIVE_CATEGORY_NAME
        data["sub_category"] = "历史版本"
        data["material_type"] = "historical"
    elif status in ("已审核", "通过", "Approved"):
        data["review_status"] = "approved"
    return data


def apply_category_invariants(
    data: dict[str, Any],
    *,
    current_category_code: str | None = None,
) -> dict[str, Any]:
    """Keep ontology-backed asset flags consistent with their category."""
    effective_code = str(data.get("category_code") or current_category_code or "").strip()
    if effective_code == AI_GENERATED_CATEGORY_CODE:
        data["is_ai_generated"] = True
        data["is_real_product"] = False
    return data


def apply_publication_invariants(
    data: dict[str, Any],
    *,
    current: ProductAsset | None = None,
) -> dict[str, Any]:
    """Prevent lifecycle-incomplete assets from entering usable collections.

    This is a data-integrity boundary for the asset library, not a customer
    service routing rule.  A pending, internally tested, invalid, archived or
    duplicate asset can remain stored for review, but it must not be exposed
    as public or selected for an AI-facing use until its lifecycle is complete.
    Partial updates are evaluated against the existing row so changing an
    unrelated field cannot accidentally loosen an earlier restriction.
    """
    defaults = {
        "review_status": "pending",
        "authorization_status": "unknown",
        "quality_status": "usable",
        "duplicate_status": "unique",
    }
    effective = {
        field: getattr(current, field, defaults[field]) if current is not None else defaults[field]
        for field in defaults
    }
    effective.update({key: value for key, value in data.items() if key in effective})
    review_status = str(effective.get("review_status") or "").strip().lower()
    authorization_status = str(effective.get("authorization_status") or "").strip().lower()
    quality_status = str(effective.get("quality_status") or "").strip().lower()
    duplicate_status = str(effective.get("duplicate_status") or "").strip().lower()
    lifecycle_complete = (
        review_status == "approved"
        and authorization_status not in BLOCKED_AUTHORIZATION_STATUSES
        and quality_status == "usable"
        and duplicate_status == "unique"
    )
    if not lifecycle_complete:
        for field in PUBLICATION_FLAG_FIELDS:
            data[field] = False
    return data


def create_asset(
    db: Session,
    sku: str,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> ProductAsset:
    ensure_product_exists(db, sku)
    payload = apply_publication_invariants(
        apply_category_invariants(apply_status_movement(dict(data)))
    )
    validate_asset_lifecycle_values(payload)
    category_code = str(payload.get("category_code") or "").strip()
    category_name = str(payload.get("category_name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not category_code or not category_name or not url:
        raise HTTPException(status_code=400, detail="category_code, category_name and url are required")

    asset_type = str(payload.get("asset_type") or "image").strip()
    if asset_type not in {"image", "video"}:
        raise HTTPException(status_code=400, detail="asset_type must be image or video")

    material_type = payload.get("material_type")
    sub_category = payload.get("sub_category")
    seq = payload.get("seq")
    if seq is None:
        seq = next_seq(db, sku, category_code, sub_category, material_type)

    asset = ProductAsset(
        id=str(uuid.uuid4()),
        sku=sku,
        category_code=category_code,
        category_name=category_name,
        sub_category=sub_category,
        asset_type=asset_type,
        url=url,
        thumbnail_url=payload.get("thumbnail_url"),
        brand=payload.get("brand") or DEFAULT_BRAND,
        material_type=material_type,
        source_key=payload.get("source_key"),
        angle_scene=payload.get("angle_scene"),
        channel=payload.get("channel") or DEFAULT_CHANNEL,
        language_tag=payload.get("language_tag") or DEFAULT_LANGUAGE,
        version_tag=payload.get("version_tag") or DEFAULT_VERSION,
        product_version=payload.get("product_version") or payload.get("version_tag") or DEFAULT_VERSION,
        market_version=payload.get("market_version"),
        date_tag=payload.get("date_tag") or today_tag(),
        status_tag=payload.get("status_tag") or DEFAULT_STATUS,
        file_name=payload.get("file_name") or os.path.basename(url),
        original_file_name=payload.get("original_file_name"),
        file_format=payload.get("file_format") or os.path.splitext(url.split("?", 1)[0])[1].lstrip(".").lower() or None,
        mime_type=payload.get("mime_type"),
        file_size_bytes=payload.get("file_size_bytes"),
        checksum_sha256=payload.get("checksum_sha256"),
        width=payload.get("width"),
        height=payload.get("height"),
        quality_status=payload.get("quality_status") or "usable",
        quality_reason=payload.get("quality_reason"),
        duplicate_status=payload.get("duplicate_status") or "unique",
        duplicate_of_asset_id=payload.get("duplicate_of_asset_id"),
        resolution=payload.get("resolution"),
        aspect_ratio=payload.get("aspect_ratio"),
        asset_level=payload.get("asset_level") or "C",
        is_real_product=bool(payload.get("is_real_product", True)),
        is_ai_generated=bool(payload.get("is_ai_generated", False)),
        is_competitor=bool(payload.get("is_competitor", False)),
        is_latest_version=bool(payload.get("is_latest_version", True)),
        is_public=bool(payload.get("is_public", False)),
        ai_customer_usable=bool(payload.get("ai_customer_usable", False)),
        ai_marketing_usable=bool(payload.get("ai_marketing_usable", False)),
        ai_reference_usable=bool(payload.get("ai_reference_usable", False)),
        editable_flag=bool(payload.get("editable_flag", False)),
        review_status=payload.get("review_status") or "pending",
        authorization_status=payload.get("authorization_status") or "unknown",
        forbidden_usage=payload.get("forbidden_usage"),
        maintainer=payload.get("maintainer"),
        seq=int(seq),
        sort_order=int(payload.get("sort_order") or 0),
        tags=normalize_tags(validate_asset_tags(payload.get("tags"))),
        notes=payload.get("notes"),
    )
    db.add(asset)
    db.flush()
    if commit:
        db.commit()
        db.refresh(asset)
    return asset


def create_assets_batch(db: Session, sku: str, items: list[dict[str, Any]]) -> list[ProductAsset]:
    ensure_product_exists(db, sku)
    try:
        # Uploaded files carry a canonical checksum after image sanitization.
        # Resolve exact matches before each flush so an upload cannot silently
        # present an already stored file as unique.  Reuse remains allowed: it
        # is flagged for review rather than rejected, which also supports
        # legitimate cross-SKU campaign assets.
        checksums = {
            str(item.get("checksum_sha256") or "").strip().lower()
            for item in items
            if str(item.get("checksum_sha256") or "").strip()
        }
        existing_by_checksum: dict[str, list[ProductAsset]] = {}
        if checksums:
            existing_assets = db.query(ProductAsset).filter(
                ProductAsset.checksum_sha256.in_(checksums)
            ).order_by(
                ProductAsset.created_at.asc(),
                ProductAsset.id.asc(),
            ).all()
            for existing in existing_assets:
                key = str(existing.checksum_sha256 or "").strip().lower()
                if key:
                    existing_by_checksum.setdefault(key, []).append(existing)

        created: list[ProductAsset] = []
        for raw_item in items:
            item = dict(raw_item)
            checksum = str(item.get("checksum_sha256") or "").strip().lower()
            references = existing_by_checksum.get(checksum, []) if checksum else []
            reference = next(
                (candidate for candidate in references if candidate.sku == sku),
                references[0] if references else None,
            )
            if reference and item.get("duplicate_status") in (None, "", "unique"):
                # Preserve explicitly invalid/archived lifecycle decisions, but
                # never let the normal upload default hide an exact duplicate.
                if item.get("quality_status") not in {"invalid", "archived"}:
                    item["quality_status"] = "suspected_duplicate"
                item["duplicate_status"] = (
                    "suspected_duplicate" if reference.sku == sku else "cross_sku_reuse"
                )
                item["duplicate_of_asset_id"] = reference.id
                if not str(item.get("quality_reason") or "").strip():
                    item["quality_reason"] = (
                        f"与已有素材 {reference.sku}/{reference.id} 的文件校验和相同，"
                        "需人工确认是否复用"
                    )

            asset = create_asset(db, sku, item, commit=False)
            created.append(asset)
            if checksum:
                existing_by_checksum.setdefault(checksum, []).append(asset)

        db.commit()
        for item in created:
            db.refresh(item)
        return created
    except Exception:
        db.rollback()
        raise


def update_asset(db: Session, sku: str, asset_id: str, data: dict[str, Any]) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    payload = apply_category_invariants(
        apply_status_movement(dict(data)),
        current_category_code=asset.category_code,
    )
    payload = apply_publication_invariants(payload, current=asset)
    validate_asset_lifecycle_values(payload)
    validated_tags = None
    if "tags" in payload:
        current_tags = parse_tags(asset.tags)
        legacy_controlled_values = {
            key: set(value)
            for key, value in current_tags.items()
            if key in CONTROLLED_TAG_DICTIONARY and isinstance(value, list)
        }
        validated_tags = normalize_tags(
            validate_asset_tags(
                payload["tags"],
                legacy_controlled_values=legacy_controlled_values,
            )
        )
    allowed = {
        "category_code",
        "category_name",
        "sub_category",
        "asset_type",
        "url",
        "thumbnail_url",
        "brand",
        "material_type",
        "source_key",
        "angle_scene",
        "channel",
        "language_tag",
        "version_tag",
        "product_version",
        "market_version",
        "date_tag",
        "status_tag",
        "file_name",
        "original_file_name",
        "file_format",
        "mime_type",
        "file_size_bytes",
        "checksum_sha256",
        "width",
        "height",
        "quality_status",
        "quality_reason",
        "duplicate_status",
        "duplicate_of_asset_id",
        "resolution",
        "aspect_ratio",
        "asset_level",
        "is_real_product",
        "is_ai_generated",
        "is_competitor",
        "is_latest_version",
        "is_public",
        "ai_customer_usable",
        "ai_marketing_usable",
        "ai_reference_usable",
        "editable_flag",
        "review_status",
        "authorization_status",
        "forbidden_usage",
        "maintainer",
        "seq",
        "sort_order",
        "tags",
        "notes",
    }
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key == "tags":
            setattr(asset, key, validated_tags or "{}")
        else:
            setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset_tags(db: Session, sku: str, asset_id: str, tags: dict[str, list[str]]) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    current_tags = parse_tags(asset.tags)
    legacy_controlled_values = {
        key: set(value)
        for key, value in current_tags.items()
        if key in CONTROLLED_TAG_DICTIONARY and isinstance(value, list)
    }
    asset.tags = normalize_tags(
        validate_asset_tags(tags, legacy_controlled_values=legacy_controlled_values)
    )
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, sku: str, asset_id: str) -> None:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    paths = [asset.url, asset.thumbnail_url]
    db.delete(asset)
    db.commit()
    for path in paths:
        try:
            _delete_local_asset_file(path)
        except OSError as exc:
            logger.warning("failed to remove deleted asset file %s: %s", path, exc)


def _delete_local_asset_file(url: str | None) -> None:
    normalized = str(url or "").split("?", 1)[0].replace("\\", "/")
    if not normalized.startswith("/uploads/assets/"):
        return
    relative = normalized.removeprefix("/uploads/").lstrip("/")
    upload_root = os.path.abspath(settings.UPLOAD_DIR)
    target = os.path.abspath(os.path.join(upload_root, relative))
    if os.path.commonpath([target, upload_root]) != upload_root:
        return
    try:
        os.remove(target)
    except FileNotFoundError:
        pass


def filename_without_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    return os.path.splitext(os.path.basename(filename))[0]
