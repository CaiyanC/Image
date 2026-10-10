"""Canonical visual-asset vocabulary and lifecycle rules.

The frontend may provide a convenience copy of these values for rendering,
but the backend is the source of truth for the current category hierarchy,
controlled dimensions, and lifecycle vocabularies. Legacy/free-form tag
dimensions and untouched historical classifications remain backward compatible.
"""

from __future__ import annotations

from typing import Any


ASSET_CATEGORY_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "code": "01", "name": "产品标准图",
        "sub_categories": (
            {"name": "白底图", "material_type": "whiteBackground"},
            {"name": "主体图", "material_type": "productBody"},
            {"name": "多角度图", "material_type": "multiAngle", "allowed_material_types": ("multiAngle", "front", "side", "back", "detail")},
            {"name": "配件图", "material_type": "accessory"},
            {"name": "收纳袋图", "material_type": "storageBag"},
            {"name": "套装图", "material_type": "set"},
            {"name": "收纳前后图", "material_type": "packed"},
        ),
    },
    {
        "code": "02", "name": "产品信息图",
        "sub_categories": (
            {"name": "3D图", "material_type": "threeD"},
            {"name": "功能特写", "material_type": "functionCloseup"},
            {"name": "尺寸图", "material_type": "size"},
            {"name": "结构图", "material_type": "structure"},
            {"name": "爆炸图", "material_type": "exploded"},
            {"name": "功能示意图", "material_type": "functional"},
            {"name": "参数图", "material_type": "parameter"},
            {"name": "其他说明", "material_type": "otherDesc"},
        ),
    },
    {
        "code": "03", "name": "使用说明图",
        "sub_categories": (
            {"name": "安装步骤", "material_type": "install"},
            {"name": "点火步骤", "material_type": "ignite"},
            {"name": "清洁步骤", "material_type": "clean"},
            {"name": "安全说明", "material_type": "safety"},
            {"name": "售后易错图", "material_type": "afterSales"},
            {"name": "中文说明", "material_type": "manualZh"},
            {"name": "英文说明", "material_type": "manualEn"},
            {"name": "其他说明", "material_type": "otherDesc"},
        ),
    },
    {
        "code": "04", "name": "场景内容图",
        "sub_categories": (
            {"name": "汽车露营", "material_type": "carCampingActivity"},
            {"name": "骑行", "material_type": "cycling"},
            {"name": "摩旅", "material_type": "motorcycling"},
            {"name": "狩猎", "material_type": "hunting"},
            {"name": "垂钓", "material_type": "fishing"},
            {"name": "硬核露营", "material_type": "hardcoreCamping"},
            {"name": "徒步", "material_type": "hiking"},
            {"name": "车露营", "material_type": "carCamping"},
            {"name": "家庭露营", "material_type": "familyCamping"},
            {"name": "雪地", "material_type": "snow"},
            {"name": "森林", "material_type": "forest"},
            {"name": "湖边", "material_type": "lakeside"},
            {"name": "室内", "material_type": "indoor"},
        ),
    },
    {
        "code": "05", "name": "电商与品牌图",
        "sub_categories": (
            {"name": "国内电商", "material_type": "domesticEcommerce", "allowed_material_types": ("domesticEcommerce", "mainImage", "detailPage")},
            {"name": "跨境电商", "material_type": "crossBorderEcommerce", "allowed_material_types": ("crossBorderEcommerce", "mainImage", "aPlus")},
            {"name": "国内品牌", "material_type": "domesticBrand"},
            {"name": "跨境品牌", "material_type": "crossBorderBrand"},
        ),
    },
    {
        "code": "06", "name": "视频素材",
        "sub_categories": (
            {"name": "开箱视频", "material_type": "unboxingVideo"},
            {"name": "操作视频", "material_type": "operationVideo"},
            {"name": "测试视频", "material_type": "testingVideo"},
            {"name": "使用场景视频", "material_type": "usageSceneVideo"},
            {"name": "国内达人视频", "material_type": "domesticCreatorVideo"},
            {"name": "跨境达人视频", "material_type": "crossBorderCreatorVideo"},
            {"name": "白底视频", "material_type": "whiteBackgroundVideo"},
            {"name": "场景短视频（≤30秒）", "material_type": "sceneShortVideo"},
            {"name": "场景长视频（>30秒）", "material_type": "sceneLongVideo"},
        ),
    },
    {
        # Retained only so historical rows can still be read and edited.  The
        # management UI no longer exposes this legacy category for new work.
        "code": "07", "name": "AI 生成图", "hidden": True,
        "sub_categories": (
            {"name": "AI 场景图", "material_type": "aiScene"},
            {"name": "AI 产品图", "material_type": "aiProduct"},
            {"name": "AI 提示词模板", "material_type": "aiPrompt"},
        ),
    },
    {
        "code": "08", "name": "历史与禁用归档",
        "sub_categories": (
            {"name": "历史版本", "material_type": "historical"},
            {"name": "旧包装", "material_type": "oldPack"},
            {"name": "禁用素材", "material_type": "banned"},
        ),
    },
)

CATEGORY_DEFINITION_BY_CODE: dict[str, dict[str, Any]] = {
    item["code"]: item for item in ASSET_CATEGORY_DEFINITIONS
}


# A category association is stored as ``category_code/sub_category`` so it is
# stable even when two categories happen to use the same human-readable name.
# Hidden AI-generated categories are intentionally excluded from new labels;
# their historical rows are still readable through the legacy classification
# fields.
CATEGORY_TAG_VALUES: tuple[str, ...] = tuple(
    f"{category['code']}/{sub_category['name']}"
    for category in ASSET_CATEGORY_DEFINITIONS
    if not category.get("hidden")
    for sub_category in category["sub_categories"]
)


CONTROLLED_TAG_DICTIONARY: dict[str, tuple[str, ...]] = {
    "category_tags": CATEGORY_TAG_VALUES,
    "subject_tags": ("主体", "配件", "收纳袋", "套装"),
    "composition_tags": ("带人物", "纯产品"),
    "view_tags": ("正视", "侧视", "背视", "特写"),
    "quality_check_tags": (
        "完整性通过", "完整性需修改", "瑕疵检查通过", "瑕疵检查需修改",
        "质感通过", "质感需修改", "复用性通过", "复用性需修改",
    ),
    "expression_tags": ("卖点图", "场景图", "人物场景图", "纯产品场景图", "氛围图"),
    "selling_point_tags": (
        "轻量便携",
        "易收纳",
        "耐用",
        "导热均匀",
        "保温",
        "易清洁",
        "安全",
        "容量大",
    ),
    "scene_tags": ("徒步", "汽车露营", "骑行", "摩旅", "狩猎", "垂钓", "硬核露营", "车露", "家庭露营", "雪地", "森林", "湖边", "室内"),
    "mood_tags": ("硬核", "温暖", "自由", "专业", "精致", "极简"),
}

EXPRESSION_REQUIREMENTS: dict[str, str] = {
    "卖点图": "selling_point_tags",
    "场景图": "scene_tags",
    "人物场景图": "scene_tags",
    "纯产品场景图": "scene_tags",
    "氛围图": "mood_tags",
}

QUALITY_STATUS_VALUES: tuple[str, ...] = (
    "usable",
    "pending_tagging",
    "suspected_duplicate",
    "invalid",
    "archived",
)

DUPLICATE_STATUS_VALUES: tuple[str, ...] = (
    "unique",
    "cross_sku_reuse",
    "suspected_duplicate",
)

REVIEW_STATUS_VALUES: tuple[str, ...] = (
    "pending",
    "approved",
    "rejected",
    "disabled",
    "archived",
)

AUTHORIZATION_STATUS_VALUES: tuple[str, ...] = (
    "unknown",
    "pending",
    "internal_test",
    "approved",
    "authorized",
    "rejected",
    "denied",
    "revoked",
    "unapproved",
)

APPROVED_AUTHORIZATION_STATUSES: frozenset[str] = frozenset({"approved", "authorized"})

LEGACY_TAG_KEYS: tuple[str, ...] = (
    "product_tags",
    "material_type_tags",
    "usage_tags",
    "version_tags",
    "risk_tags",
    "channel_tags",
    "language_tags",
)

PILOT_REQUIRED_FIELDS: dict[str, Any] = {
    "ingestion": [
        "sku",
        "category_code",
        "category_name",
        "asset_type",
        "url_or_upload",
        "checksum_sha256",
        "review_status",
        "authorization_status",
    ],
    "annotation": ["expression_tags"],
    "publication": [
        "review_status=approved",
        "authorization_status=approved|authorized",
        "is_public=true",
        "ai_reference_usable=true",
    ],
}


def dictionary_payload() -> dict[str, Any]:
    """Return JSON-safe taxonomy metadata for the management UI and audits."""

    return {
        "categories": [
            {
                "code": category["code"],
                "name": category["name"],
                "hidden": bool(category.get("hidden", False)),
                "sub_categories": [
                    {
                        "name": sub_category["name"],
                        "material_type": sub_category["material_type"],
                    }
                    for sub_category in category["sub_categories"]
                ],
            }
            for category in ASSET_CATEGORY_DEFINITIONS
        ],
        "dimensions": {
            key: {"values": list(values)}
            for key, values in CONTROLLED_TAG_DICTIONARY.items()
        },
        "expression_requirements": dict(EXPRESSION_REQUIREMENTS),
        "quality_statuses": list(QUALITY_STATUS_VALUES),
        "duplicate_statuses": list(DUPLICATE_STATUS_VALUES),
        "review_statuses": list(REVIEW_STATUS_VALUES),
        "authorization_statuses": list(AUTHORIZATION_STATUS_VALUES),
        "legacy_tag_keys": list(LEGACY_TAG_KEYS),
        "pilot_required_fields": PILOT_REQUIRED_FIELDS,
    }
