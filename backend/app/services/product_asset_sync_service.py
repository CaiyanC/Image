import json
import os
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models.product import Product
from ..models.product_asset import ProductAsset


MEDIA_FIELD_MAP: dict[str, tuple[str, str, str, str]] = {
    "source_white_bg": ("01", "产品标准图", "白底图", "whiteBackground"),
    "source_multi_angle": ("01", "产品标准图", "多角度图", "multiAngle"),
    "source_accessories": ("01", "产品标准图", "配件图", "accessory"),
    "source_bundle": ("01", "产品标准图", "套装图", "set"),
    "source_storage": ("01", "产品标准图", "收纳前后图", "packed"),
    "source_size": ("02", "产品信息图", "尺寸图", "size"),
    "source_structure": ("02", "产品信息图", "结构图", "structure"),
    "source_exploded": ("02", "产品信息图", "爆炸图", "exploded"),
    "source_function": ("02", "产品信息图", "功能示意图", "functional"),
    "source_3d": ("02", "产品信息图", "其他说明", "render3d"),
    "source_usage_steps": ("03", "使用说明图", "其他说明", "usage"),
    "source_outdoor": ("04", "场景内容图", "户外场景", "outdoor"),
    "social_media": ("05", "渠道销售图", "社媒宣发", "socialMedia"),
    "social_ads": ("05", "渠道销售图", "活动广告", "campaignAd"),
    "social_video_urls": ("06", "视频素材", "视频", "video"),
    "ai_generated": ("07", "AI 生成图", "AI 生成图", "aiGenerated"),
    "ref_packaging": ("08", "参考归档禁用图", "包装图", "packaging"),
    "ref_manual": ("08", "参考归档禁用图", "说明书插图", "manual"),
    "ref_certification": ("08", "参考归档禁用图", "认证/测试图", "certification"),
    "ref_dealer": ("08", "参考归档禁用图", "经销商素材", "dealer"),
    "ref_brand_style": ("08", "参考归档禁用图", "品牌风格参考图", "brandReference"),
    "ref_competitor": ("08", "参考归档禁用图", "竞品参考图", "competitor"),
    "ref_archive": ("08", "参考归档禁用图", "历史版本", "historical"),
    "ref_banned": ("08", "参考归档禁用图", "禁用素材", "banned"),
}


def sync_product_assets_from_media_data(
    db: Session,
    product: Product,
    media_data: Any,
) -> None:
    if not isinstance(media_data, dict):
        return

    db.query(ProductAsset).filter(
        ProductAsset.sku == product.sku,
        ProductAsset.source_key.isnot(None),
    ).delete(synchronize_session=False)

    seq_by_group: dict[tuple[str, str, str], int] = defaultdict(int)
    for field_key, config in MEDIA_FIELD_MAP.items():
        values = media_data.get(field_key) or []
        if not isinstance(values, list):
            continue
        for index, url in enumerate(values, start=1):
            _add_asset(db, product, str(url or "").strip(), field_key, index, config, seq_by_group)

    channel_versions = media_data.get("channel_versions") or {}
    if isinstance(channel_versions, dict):
        for channel, versions in channel_versions.items():
            if not isinstance(versions, list):
                continue
            for version_index, version in enumerate(versions, start=1):
                if not isinstance(version, dict):
                    continue
                version_tag = str(version.get("version") or "V1")
                for field_key, sub_category, material_type in (
                    ("ecommerce_main", "电商主图", "ecommerceMain"),
                    ("detail_module", "详情页模块图", "detailModule"),
                ):
                    values = version.get(field_key) or []
                    if not isinstance(values, list):
                        continue
                    for index, url in enumerate(values, start=1):
                        source_key = f"channel:{channel}:{version_index}:{field_key}"
                        _add_asset(
                            db,
                            product,
                            str(url or "").strip(),
                            source_key,
                            index,
                            ("05", "渠道销售图", sub_category, material_type),
                            seq_by_group,
                            channel=str(channel),
                            version_tag=version_tag,
                            notes=str(version.get("label") or "") or None,
                        )


def media_data_from_assets(assets: list[ProductAsset]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    channel_versions: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        source_key = str(asset.source_key or "")
        if not source_key:
            continue
        if source_key in MEDIA_FIELD_MAP:
            result.setdefault(source_key, []).append(asset.url)
            continue
        if not source_key.startswith("channel:"):
            continue
        _, channel, version_index, field_key = source_key.split(":", 3)
        index = max(int(version_index or 1) - 1, 0)
        versions = channel_versions.setdefault(channel, [])
        while len(versions) <= index:
            versions.append({"version": "V1", "label": "", "ecommerce_main": [], "detail_module": []})
        versions[index]["version"] = asset.version_tag or "V1"
        versions[index]["label"] = asset.notes or ""
        versions[index].setdefault(field_key, []).append(asset.url)
    if channel_versions:
        result["channel_versions"] = channel_versions
    return result


def _add_asset(
    db: Session,
    product: Product,
    url: str,
    source_key: str,
    index: int,
    config: tuple[str, str, str, str],
    seq_by_group: dict[tuple[str, str, str], int],
    *,
    channel: str = "General",
    version_tag: str = "V1",
    notes: str | None = None,
) -> None:
    if not url:
        return
    category_code, category_name, sub_category, material_type = config
    group_key = (category_code, sub_category, material_type)
    seq_by_group[group_key] += 1
    is_ai = source_key == "ai_generated"
    is_competitor = source_key == "ref_competitor"
    is_archived = source_key == "ref_archive"
    is_banned = source_key == "ref_banned"
    file_name = os.path.basename(url.split("?", 1)[0]) or f"{source_key}-{index}"
    extension = os.path.splitext(file_name)[1].lstrip(".").lower() or None
    asset_type = "video" if category_code == "06" else "image"
    status_tag = "禁用" if is_banned else "归档历史版本" if is_archived else "待审核"
    review_status = "disabled" if is_banned else "archived" if is_archived else "pending"
    db.add(ProductAsset(
        id=str(uuid.uuid4()),
        sku=product.sku,
        category_code=category_code,
        category_name=category_name,
        sub_category=sub_category,
        asset_type=asset_type,
        url=url,
        brand=product.brand or "alocs",
        material_type=material_type,
        source_key=source_key,
        channel=channel,
        language_tag="CN",
        version_tag=version_tag,
        product_version=version_tag,
        date_tag=datetime.now().strftime("%Y%m%d"),
        status_tag=status_tag,
        file_name=file_name,
        file_format=extension,
        asset_level="C",
        is_real_product=not (is_ai or is_competitor),
        is_ai_generated=is_ai,
        is_competitor=is_competitor,
        is_latest_version=not is_archived,
        is_public=False,
        ai_customer_usable=False,
        ai_marketing_usable=False,
        ai_reference_usable=False,
        editable_flag=False,
        review_status=review_status,
        authorization_status="unknown",
        seq=seq_by_group[group_key],
        sort_order=0,
        tags=json.dumps({"source_keys": [source_key]}, ensure_ascii=False),
        notes=notes,
    ))
