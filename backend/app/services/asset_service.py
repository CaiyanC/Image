import json
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.config import resolve_project_path, settings
from ..models.product import Product
from ..models.product_asset import ProductAsset


DEFAULT_BRAND = "alocs"
DEFAULT_CHANNEL = "General"
DEFAULT_LANGUAGE = "CN"
DEFAULT_VERSION = "V1"
DEFAULT_STATUS = "待审核"
ARCHIVE_CATEGORY_CODE = "08"
ARCHIVE_CATEGORY_NAME = "参考归档禁用图"


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
        "file_format": asset.file_format,
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


def create_asset(db: Session, sku: str, data: dict[str, Any]) -> ProductAsset:
    ensure_product_exists(db, sku)
    payload = apply_status_movement(dict(data))
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
        file_format=payload.get("file_format") or os.path.splitext(url.split("?", 1)[0])[1].lstrip(".").lower() or None,
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
        tags=normalize_tags(payload.get("tags")),
        notes=payload.get("notes"),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def create_assets_batch(db: Session, sku: str, items: list[dict[str, Any]]) -> list[ProductAsset]:
    created = []
    for item in items:
        created.append(create_asset(db, sku, item))
    return created


def update_asset(db: Session, sku: str, asset_id: str, data: dict[str, Any]) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    payload = apply_status_movement(dict(data))
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
        "file_format",
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
            setattr(asset, key, normalize_tags(value))
        else:
            setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset_tags(db: Session, sku: str, asset_id: str, tags: dict[str, list[str]]) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    asset.tags = normalize_tags(tags)
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
        _delete_local_asset_file(path)


def _delete_local_asset_file(url: str | None) -> None:
    normalized = str(url or "").split("?", 1)[0].replace("\\", "/")
    if not normalized.startswith("/uploads/assets/"):
        return
    relative = normalized.removeprefix("/uploads/").lstrip("/")
    target = os.path.abspath(resolve_project_path(os.path.join(settings.UPLOAD_DIR, relative)))
    upload_root = os.path.abspath(resolve_project_path(settings.UPLOAD_DIR))
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
