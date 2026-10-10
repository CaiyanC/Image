import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.product import Product
from ..models.product_asset import ProductAsset, ProductAssetLink
from .video_metadata_service import validate_video_slot
from .asset_taxonomy import (
    APPROVED_AUTHORIZATION_STATUSES,
    CATEGORY_DEFINITION_BY_CODE,
    CATEGORY_TAG_VALUES,
    AUTHORIZATION_STATUS_VALUES,
    CONTROLLED_TAG_DICTIONARY,
    DUPLICATE_STATUS_VALUES,
    EXPRESSION_REQUIREMENTS,
    LEGACY_TAG_KEYS,
    QUALITY_STATUS_VALUES,
    REVIEW_STATUS_VALUES,
)


DEFAULT_BRAND = "alocs"
DEFAULT_CHANNEL = "General"
DEFAULT_LANGUAGE = "CN"
DEFAULT_VERSION = "V1"
DEFAULT_STATUS = "待审核"
AI_GENERATED_CATEGORY_CODE = "07"
ARCHIVE_CATEGORY_CODE = "08"
ARCHIVE_CATEGORY_NAME = "历史与禁用归档"

PUBLICATION_FLAG_FIELDS = (
    "is_public",
    "ai_customer_usable",
    "ai_marketing_usable",
    "ai_reference_usable",
)
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


def effective_asset_tags(asset: ProductAsset) -> dict[str, list[str]]:
    """Return stored tags plus non-destructive tags derived from legacy fields.

    The first version of the asset library stored classification in
    ``sub_category``, ``material_type``, ``channel`` and ``language_tag``.
    New uploads also store structured tags.  Search needs one compatible view
    so historical rows do not disappear merely because they were uploaded
    before the tag dimensions existed.  This helper never writes the derived
    values back to the database.
    """
    result = parse_tags(asset.tags)

    def add(key: str, value: str | None) -> None:
        clean = str(value or "").strip()
        if not clean:
            return
        values = result.setdefault(key, [])
        if clean not in values:
            values.append(clean)

    category = str(asset.category_code or "").strip()
    sub_category = str(asset.sub_category or "").strip()
    material_type = str(asset.material_type or "").strip()
    definition = CATEGORY_DEFINITION_BY_CODE.get(category, {})
    if category and sub_category and f"{category}/{sub_category}" in CATEGORY_TAG_VALUES:
        add("category_tags", f"{category}/{sub_category}")
    sub_definition = next(
        (item for item in definition.get("sub_categories", ()) if item.get("name") == sub_category),
        None,
    )
    material_definition = next(
        (item for item in definition.get("sub_categories", ()) if item.get("material_type") == material_type),
        None,
    )
    if category in {"01", "02", "03", "06"}:
        add("material_type_tags", (sub_definition or material_definition or {}).get("name"))

    if category == "01":
        subject_by_sub_category = {
            "主体图": "主体", "配件图": "配件", "收纳袋图": "收纳袋", "套装图": "套装",
        }
        add("subject_tags", subject_by_sub_category.get(sub_category))
        if sub_category == "多角度图" and not result.get("view_tags"):
            add("view_tags", {"front": "正视", "side": "侧视", "back": "背视", "detail": "特写"}.get(material_type))
    if category == "03":
        add("language_tags", {"中文说明": "中文", "英文说明": "英文"}.get(sub_category))
    if category == "04":
        add("scene_tags", "车露" if sub_category == "车露营" else sub_category)
    add("channel_tags", getattr(asset, "channel", None))
    add("language_tags", {"CN": "中文", "EN": "英文", "JA": "日文"}.get(str(getattr(asset, "language_tag", "") or "").upper()))
    return result


def default_upload_tags(category_code: str, sub_category: str | None) -> dict[str, list[str]]:
    """Derive only taxonomy-safe tags that are explicit in the upload slot."""
    sub_category = str(sub_category or "").strip()
    scene_name = "车露" if sub_category == "车露营" else sub_category
    tags: dict[str, list[str]] = {}
    primary_category_tag = f"{category_code}/{sub_category}" if sub_category else ""
    if primary_category_tag in CATEGORY_TAG_VALUES:
        tags["category_tags"] = [primary_category_tag]
    subject = {"主体图": "主体", "配件图": "配件", "收纳袋图": "收纳袋", "套装图": "套装"}.get(sub_category)
    if category_code == "01" and subject:
        tags["subject_tags"] = [subject]
    # Keep the dimensions separate: a scene sub-category such as ``森林`` is
    # an environment, not a material form.  Otherwise every scene upload is
    # silently labelled as both a material type and a scene, which makes the
    # two filters indistinguishable.  Product/info/instruction/video slots
    # still receive their explicit sub-category as a helpful default, while
    # scene and archive rows remain opt-in for material-form labels.
    if sub_category and category_code in {"01", "02", "03", "06"}:
        tags["material_type_tags"] = [sub_category]
    if category_code == "04" and scene_name in CONTROLLED_TAG_DICTIONARY["scene_tags"]:
        tags["expression_tags"] = ["场景图"]
        tags["scene_tags"] = [scene_name]
    if category_code == "03" and sub_category in {"中文说明", "英文说明"}:
        tags["language_tags"] = ["中文" if sub_category == "中文说明" else "英文"]
    return tags


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
        expressions = set(normalized.get("expression_tags", []))
        composition = set(normalized.get("composition_tags", []))
        if {"人物场景图", "纯产品场景图"}.issubset(expressions):
            raise HTTPException(status_code=422, detail="人物场景图和纯产品场景图不能同时选择")
        if ("人物场景图" in expressions and "纯产品" in composition) or ("纯产品场景图" in expressions and "带人物" in composition):
            raise HTTPException(status_code=422, detail="人物构成与场景表达标签冲突，请统一标注")
        checks = normalized.get("quality_check_tags", [])
        for criterion in ("完整性", "瑕疵检查", "质感", "复用性"):
            if f"{criterion}通过" in checks and f"{criterion}需修改" in checks:
                raise HTTPException(status_code=422, detail=f"{criterion}不能同时通过和需修改")
        if len(set(normalized.get("view_tags", []))) > 1:
            raise HTTPException(status_code=422, detail="拍摄视角只能选择一个；组合画面请在备注说明")
        if len(set(normalized.get("composition_tags", []))) > 1:
            raise HTTPException(status_code=422, detail="人物构成只能选择带人物或纯产品之一")
        for expression, required_key in EXPRESSION_REQUIREMENTS.items():
            if expression in normalized.get("expression_tags", []) and not normalized.get(required_key):
                raise HTTPException(status_code=422, detail=f"{expression} 必须选择对应标签")
    return normalized


def validate_asset_lifecycle_values(data: dict[str, Any]) -> None:
    review_status = data.get("review_status")
    if review_status is not None:
        normalized_review = str(review_status).strip().lower()
        if normalized_review not in REVIEW_STATUS_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"review_status 必须是：{'、'.join(REVIEW_STATUS_VALUES)}",
            )
        data["review_status"] = normalized_review
    authorization_status = data.get("authorization_status")
    if authorization_status is not None:
        normalized_authorization = str(authorization_status).strip().lower()
        if normalized_authorization not in AUTHORIZATION_STATUS_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"authorization_status 必须是：{'、'.join(AUTHORIZATION_STATUS_VALUES)}",
            )
        data["authorization_status"] = normalized_authorization
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


def validate_asset_classification(
    data: dict[str, Any],
    *,
    current: ProductAsset | None = None,
) -> None:
    """Validate new classification edits without rewriting untouched legacy rows."""
    classification_fields = {
        "category_code", "category_name", "sub_category", "material_type", "asset_type",
    }
    if current is not None and not classification_fields.intersection(data):
        return

    category_code = str(
        data.get("category_code", current.category_code if current is not None else "") or ""
    ).strip()
    definition = CATEGORY_DEFINITION_BY_CODE.get(category_code)
    if definition is None:
        raise HTTPException(status_code=422, detail="category_code 必须是素材库定义的 01–08 分类")
    data["category_code"] = category_code

    expected_name = str(definition["name"])
    category_name = str(
        data.get("category_name", current.category_name if current is not None else "") or ""
    ).strip()
    if current is None or "category_name" in data:
        if category_name != expected_name:
            raise HTTPException(
                status_code=422,
                detail=f"分类 {category_code} 的名称必须是：{expected_name}",
            )
    elif category_name != expected_name:
        # A deliberate classification edit upgrades only the category label;
        # untouched legacy rows remain unchanged via the early return above.
        data["category_name"] = expected_name

    raw_sub_category = data.get(
        "sub_category", current.sub_category if current is not None else None,
    )
    sub_category = str(raw_sub_category).strip() if raw_sub_category is not None else ""
    asset_type = str(
        data.get("asset_type", current.asset_type if current is not None else "image") or ""
    ).strip()
    if category_code == "06" and asset_type != "video":
        raise HTTPException(status_code=422, detail="视频素材分类只能保存视频文件")
    if category_code not in {"06", "08"} and asset_type != "image" and not (category_code == "03" and asset_type == "document"):
        raise HTTPException(status_code=422, detail=f"{expected_name} 分类只能保存图片文件")
    raw_material_type = data.get(
        "material_type", current.material_type if current is not None else None,
    )
    material_type = str(raw_material_type).strip() if raw_material_type is not None else ""
    if not sub_category:
        if not material_type:
            if "sub_category" in data:
                data["sub_category"] = None
            return
        matching_sub_categories = [
            item for item in definition["sub_categories"]
            if material_type in set(item.get("allowed_material_types", (item["material_type"],)))
        ]
        if len(matching_sub_categories) != 1:
            raise HTTPException(
                status_code=422,
                detail="指定素材形式/版位时必须选择对应且唯一的二级分类",
            )
        sub_category = str(matching_sub_categories[0]["name"])
        data["sub_category"] = sub_category

    sub_definitions = {
        str(item["name"]): item for item in definition["sub_categories"]
    }
    sub_definition = sub_definitions.get(sub_category)
    if sub_definition is None:
        raise HTTPException(
            status_code=422,
            detail=f"{expected_name} 不包含二级分类：{sub_category}",
        )
    data["sub_category"] = sub_category

    default_material_type = str(sub_definition["material_type"])
    sub_category_changed = current is not None and sub_category != (current.sub_category or "")
    if not material_type:
        material_type = default_material_type
        data["material_type"] = material_type
    elif sub_category_changed and "material_type" not in data:
        old_default = None
        old_category = CATEGORY_DEFINITION_BY_CODE.get(current.category_code)
        if old_category is not None:
            old_sub = next(
                (item for item in old_category["sub_categories"] if item["name"] == current.sub_category),
                None,
            )
            old_default = old_sub["material_type"] if old_sub is not None else None
        if current.material_type in (None, "", old_default):
            material_type = default_material_type
            data["material_type"] = material_type

    allowed_material_types = set(
        sub_definition.get("allowed_material_types", (default_material_type,))
    )
    if material_type not in allowed_material_types:
        raise HTTPException(
            status_code=422,
            detail=f"二级分类“{sub_category}”不允许素材形式/版位：{material_type}",
        )

def model_to_dict(asset: ProductAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "sku": asset.sku,
        "related_skus": asset.related_skus,
        "reference_only": asset.reference_only,
        "availability_status": asset.availability_status,
        "material_layer": asset.material_layer,
        "video_duration_seconds": asset.video_duration_seconds,
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


def _sku_filter(sku: str):
    return or_(ProductAsset.sku == sku, ProductAsset.id.in_(
        select(ProductAssetLink.asset_id).where(ProductAssetLink.sku == sku)
    ))


def _set_related_skus(db: Session, asset: ProductAsset, skus: list[str]) -> None:
    cleaned = list(dict.fromkeys(str(item).strip() for item in skus if str(item).strip()))
    for linked_sku in cleaned:
        ensure_product_exists(db, linked_sku)
    existing = {link.sku: link for link in asset.product_links}
    asset.product_links = [existing.get(item) or ProductAssetLink(sku=item) for item in cleaned if item != asset.sku]


def get_asset(db: Session, sku: str, asset_id: str, *, allow_related: bool = False) -> ProductAsset:
    asset = db.query(ProductAsset).filter(
        _sku_filter(sku) if allow_related else ProductAsset.sku == sku,
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
    query = db.query(ProductAsset).filter(_sku_filter(sku))
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


def select_product_cover(assets: list[ProductAsset]) -> ProductAsset | None:
    """Choose a current real-product image; prefer the standard front view.

    This is a management preview, not a publication/authorization decision.
    Stable input order is retained when candidates have the same priority.
    """
    candidates = [asset for asset in assets if (
        asset.asset_type == "image"
        and asset.category_code != ARCHIVE_CATEGORY_CODE
        and asset.status_tag not in {"禁用", "归档历史版本"}
        and asset.quality_status not in {"invalid", "archived"}
        and asset.review_status not in {"rejected", "banned"}
        and asset.is_latest_version
        and asset.is_real_product
        and not asset.is_ai_generated
        and not asset.is_competitor
    )]
    def priority(asset: ProductAsset) -> int:
        standard = asset.category_code == "01"
        views = parse_tags(asset.tags).get("view_tags", [])
        front = "正视" in views if views else asset.material_type == "front" or asset.angle_scene in {"front", "正面", "正视", "正视图"}
        if standard and front:
            return 0
        if standard:
            return 1
        return 2
    return min(candidates, key=priority) if candidates else None


def list_product_asset_overview(
    db: Session,
    *,
    q: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return one lightweight asset summary per product for the library home.

    The detail page already loads a single SKU's complete asset list.  The
    overview must not repeat that request once per SKU, so this intentionally
    uses one product query plus one ordered asset query and groups the result
    in memory.  The cover follows the same stable ordering as ``list_assets``
    and is always the first image, even when a product also has videos.
    """
    limit = min(max(int(limit or 500), 1), 500)
    query = db.query(Product).order_by(Product.sku.asc())
    keyword = str(q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            Product.sku.ilike(like),
            Product.product_name_cn.ilike(like),
            Product.product_name_en.ilike(like),
            Product.brand.ilike(like),
        ))

    total = query.count()
    products = query.limit(limit).all()
    if not products:
        return {"items": [], "total": total}

    skus = [product.sku for product in products]
    assets = db.query(ProductAsset).filter(
        or_(ProductAsset.sku.in_(skus), ProductAsset.id.in_(select(ProductAssetLink.asset_id).where(ProductAssetLink.sku.in_(skus)))),
    ).order_by(
        ProductAsset.sku.asc(),
        ProductAsset.category_code.asc(),
        ProductAsset.sub_category.asc(),
        ProductAsset.material_type.asc(),
        ProductAsset.seq.asc(),
        ProductAsset.created_at.asc(),
        ProductAsset.id.asc(),
    ).all()
    assets_by_sku: dict[str, list[ProductAsset]] = {}
    for asset in assets:
        for linked_sku in asset.related_skus:
            if linked_sku in skus:
                assets_by_sku.setdefault(linked_sku, []).append(asset)

    items: list[dict[str, Any]] = []
    for product in products:
        product_assets = assets_by_sku.get(product.sku, [])
        images = [asset for asset in product_assets if asset.asset_type == "image"]
        videos = [asset for asset in product_assets if asset.asset_type == "video"]
        cover = select_product_cover(product_assets)
        items.append({
            "id": product.id,
            "sku": product.sku,
            "product_name_cn": product.product_name_cn,
            "product_name_en": product.product_name_en,
            "brand": product.brand,
            "asset_count": len(product_assets),
            "image_count": len(images),
            "video_count": len(videos),
            "total_size_bytes": sum(int(asset.file_size_bytes or 0) for asset in product_assets),
            "cover_asset_id": cover.id if cover else None,
            "cover_url": cover.url if cover else None,
            "cover_thumbnail_url": cover.thumbnail_url if cover else None,
            "cover_category_name": cover.category_name if cover else None,
            "cover_sub_category": cover.sub_category if cover else None,
        })
    return {"items": items, "total": total}


def is_ai_reference_ready(asset: ProductAsset) -> bool:
    """Product AI references require independent lifecycle and use grants."""
    authorization = str(asset.authorization_status or "").strip().lower()
    return (
        asset.review_status == "approved"
        and asset.quality_status == "usable"
        and asset.duplicate_status == "unique"
        and authorization in APPROVED_AUTHORIZATION_STATUSES
        and bool(asset.is_public)
        and bool(asset.ai_reference_usable)
        and bool(asset.is_latest_version)
        and not bool(asset.is_competitor)
        and not bool(asset.reference_only)
        and asset.availability_status not in {"disabled", "unavailable", "archived"}
        and asset.category_code != ARCHIVE_CATEGORY_CODE
    )


def search_assets(
    db: Session,
    *,
    sku: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    maintainer: str | None = None,
    review_status: str | None = None,
    authorization_status: str | None = None,
    is_public: bool | None = None,
    ai_customer_usable: bool | None = None,
    ai_marketing_usable: bool | None = None,
    ai_reference_usable: bool | None = None,
    quality_status: str | None = None,
    duplicate_status: str | None = None,
    category_tags: list[str] | None = None,
    quality_check_tags: list[str] | None = None,
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
    subject_tags: list[str] | None = None,
    composition_tags: list[str] | None = None,
    view_tags: list[str] | None = None,
    limit: int = 100,
    ai_reference_ready_only: bool = False,
) -> list[ProductAsset]:
    tag_inputs = {
        "category_tags": category_tags or [],
        "quality_check_tags": quality_check_tags or [],
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
        "subject_tags": subject_tags or [],
        "composition_tags": composition_tags or [],
        "view_tags": view_tags or [],
    }
    lifecycle_filters = {
        "review_status": review_status,
        "authorization_status": authorization_status,
        "quality_status": quality_status,
        "duplicate_status": duplicate_status,
    }
    validate_asset_lifecycle_values(lifecycle_filters)
    review_status = lifecycle_filters["review_status"]
    authorization_status = lifecycle_filters["authorization_status"]
    quality_status = lifecycle_filters["quality_status"]
    duplicate_status = lifecycle_filters["duplicate_status"]
    validate_asset_tags(tag_inputs, enforce_expression_requirements=False)
    query = db.query(ProductAsset)
    if sku:
        query = query.filter(_sku_filter(sku))
    for column, value in (
        (ProductAsset.category_code, category),
        (ProductAsset.channel, channel),
        (ProductAsset.review_status, review_status),
        (ProductAsset.authorization_status, authorization_status),
        (ProductAsset.quality_status, quality_status),
        (ProductAsset.duplicate_status, duplicate_status),
    ):
        if value:
            query = query.filter(column == value)
    for column, value in (
        (ProductAsset.is_public, is_public),
        (ProductAsset.ai_customer_usable, ai_customer_usable),
        (ProductAsset.ai_marketing_usable, ai_marketing_usable),
        (ProductAsset.ai_reference_usable, ai_reference_usable),
    ):
        if value is not None:
            query = query.filter(column.is_(value))
    if maintainer and maintainer.strip():
        query = query.filter(ProductAsset.maintainer.ilike(f"%{maintainer.strip()}%"))

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
        if (not ai_reference_ready_only or is_ai_reference_ready(asset)) and all(
            not values or values.intersection(effective_asset_tags(asset).get(key, []))
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


def apply_manual_language(data: dict[str, Any], current: ProductAsset | None = None) -> dict[str, Any]:
    code = data.get("category_code", current.category_code if current else None)
    sub = data.get("sub_category", current.sub_category if current else None)
    expected = {"中文说明": ("CN", "中文"), "英文说明": ("EN", "英文")}.get(sub)
    if code != "03" or not expected:
        return data
    explicit_language = data.get("language_tag")
    if explicit_language and str(explicit_language).upper() != expected[0]:
        raise HTTPException(status_code=422, detail=f"{sub}的主语言必须为 {expected[0]}")
    tags = parse_tags(data.get("tags", current.tags if current else {}))
    if "tags" in data and tags.get("language_tags") and tags["language_tags"] != [expected[1]]:
        raise HTTPException(status_code=422, detail=f"{sub}的语言标签必须为{expected[1]}")
    tags["language_tags"] = [expected[1]]
    data["tags"] = tags
    data["language_tag"] = expected[0]
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
        and authorization_status in APPROVED_AUTHORIZATION_STATUSES
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
    payload = apply_manual_language(payload)
    validate_asset_lifecycle_values(payload)
    validate_asset_classification(payload)
    category_code = str(payload.get("category_code") or "").strip()
    category_name = str(payload.get("category_name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not category_code or not category_name or not url:
        raise HTTPException(status_code=400, detail="category_code, category_name and url are required")

    asset_type = str(payload.get("asset_type") or "image").strip()
    if asset_type not in {"image", "video", "document"}:
        raise HTTPException(status_code=400, detail="asset_type must be image, video or document")
    if asset_type == "document" and category_code != "03":
        raise HTTPException(status_code=422, detail="说明书附件只能归入使用说明分类")

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
        video_duration_seconds=payload.get("video_duration_seconds"),
        reference_only=bool(payload.get("reference_only", False)),
        availability_status=payload.get("availability_status"),
        material_layer=payload.get("material_layer"),
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
    _set_related_skus(db, asset, payload.get("related_skus") or [])
    db.add(asset)
    db.flush()
    if commit:
        db.commit()
        db.refresh(asset)
    return asset


def create_assets_batch(db: Session, sku: str, items: list[dict[str, Any]], *, commit: bool = True) -> list[ProductAsset]:
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

        if commit:
            db.commit()
            for item in created:
                db.refresh(item)
        else:
            db.flush()
        return created
    except Exception:
        db.rollback()
        raise


def update_asset(db: Session, sku: str, asset_id: str, data: dict[str, Any], *, commit: bool = True) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    payload = apply_category_invariants(
        apply_status_movement(dict(data)),
        current_category_code=asset.category_code,
    )
    payload = apply_manual_language(payload, current=asset)
    validate_asset_classification(payload, current=asset)
    if any(payload.get(key, getattr(asset, key)) != getattr(asset, key)
           for key in ("sub_category", "material_type", "asset_type")):
        sub_category = payload.get("sub_category", asset.sub_category)
        material_type = payload.get("material_type", asset.material_type)
        video_names = {"sceneShortVideo": "场景短视频（≤30秒）", "sceneLongVideo": "场景长视频（>30秒）"}
        if material_type in video_names and sub_category != video_names[material_type]:
            raise HTTPException(status_code=422, detail="视频形式与短/长视频分类不一致")
        placements = {
            "国内电商": {"domesticEcommerce", "mainImage", "detailPage"},
            "跨境电商": {"crossBorderEcommerce", "mainImage", "aPlus"},
        }
        if sub_category in placements and material_type not in placements[sub_category]:
            raise HTTPException(status_code=422, detail="电商版位与国内/跨境分类不一致，请重新选择版位")
        if sub_category in {"场景短视频（≤30秒）", "场景长视频（>30秒）"}:
            if payload.get("asset_type", asset.asset_type) != "video":
                raise HTTPException(status_code=422, detail="场景视频分类只能用于视频文件")
            technical_tags = parse_tags(asset.tags)
            duration = None
            if technical_tags.get("video_duration_status") == ["measured"]:
                try:
                    duration = float(technical_tags["video_duration_seconds"][0])
                except (KeyError, IndexError, TypeError, ValueError):
                    pass
            try:
                validate_video_slot(duration, sub_category)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = apply_publication_invariants(payload, current=asset)
    if payload.get("asset_type", asset.asset_type) == "document" and payload.get("category_code", asset.category_code) not in {"03", "08"}:
        raise HTTPException(status_code=422, detail="说明书附件只能保存在使用说明或历史归档分类")
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
        "reference_only", "availability_status", "material_layer",
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
    if "related_skus" in payload:
        _set_related_skus(db, asset, payload["related_skus"] or [])
    for key, value in payload.items():
        if key not in allowed:
            continue
        if key == "tags":
            setattr(asset, key, validated_tags or "{}")
        else:
            setattr(asset, key, value)
    if commit:
        db.commit()
        db.refresh(asset)
    else:
        db.flush()
    return asset


def update_asset_tags(db: Session, sku: str, asset_id: str, tags: dict[str, list[str]], *, commit: bool = True) -> ProductAsset:
    ensure_product_exists(db, sku)
    asset = get_asset(db, sku, asset_id)
    current_tags = parse_tags(asset.tags)
    manual_payload = apply_manual_language({"tags": {**current_tags, **tags}}, current=asset)
    tags = manual_payload["tags"]
    legacy_controlled_values = {
        key: set(value)
        for key, value in current_tags.items()
        if key in CONTROLLED_TAG_DICTIONARY and isinstance(value, list)
    }
    normalized_tags = normalize_tags(
        validate_asset_tags({**current_tags, **tags}, legacy_controlled_values=legacy_controlled_values)
    )
    if "language_tag" in manual_payload:
        asset.language_tag = manual_payload["language_tag"]
    asset.tags = normalized_tags
    if commit:
        db.commit()
        db.refresh(asset)
    else:
        db.flush()
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
