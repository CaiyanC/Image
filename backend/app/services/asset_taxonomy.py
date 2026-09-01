"""Canonical visual-asset vocabulary and lifecycle rules.

The frontend may provide a convenience copy of these values for rendering
chips, but the backend is the source of truth.  Only the four pilot search
dimensions are controlled here; legacy/free-form tag dimensions remain
backward compatible.
"""

from __future__ import annotations

from typing import Any


CONTROLLED_TAG_DICTIONARY: dict[str, tuple[str, ...]] = {
    "expression_tags": ("卖点图", "场景图", "氛围图"),
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
    "scene_tags": ("徒步", "硬核露营", "车露", "家庭露营", "雪地", "森林", "湖边", "室内"),
    "mood_tags": ("硬核", "温暖", "自由", "专业", "精致", "极简"),
}

EXPRESSION_REQUIREMENTS: dict[str, str] = {
    "卖点图": "selling_point_tags",
    "场景图": "scene_tags",
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
        "authorization_status!=unknown",
        "is_public=true",
        "ai_reference_usable=true",
    ],
}


def dictionary_payload() -> dict[str, Any]:
    """Return JSON-safe taxonomy metadata for the management UI and audits."""

    return {
        "dimensions": {
            key: {"values": list(values)}
            for key, values in CONTROLLED_TAG_DICTIONARY.items()
        },
        "expression_requirements": dict(EXPRESSION_REQUIREMENTS),
        "quality_statuses": list(QUALITY_STATUS_VALUES),
        "duplicate_statuses": list(DUPLICATE_STATUS_VALUES),
        "legacy_tag_keys": list(LEGACY_TAG_KEYS),
        "pilot_required_fields": PILOT_REQUIRED_FIELDS,
    }
