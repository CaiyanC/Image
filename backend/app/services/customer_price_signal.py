from __future__ import annotations

import re
from typing import Any


LOW_PRICE_TERMS = (
    "预算不高",
    "预算低",
    "低预算",
    "便宜",
    "便宜点",
    "便宜一些",
    "实惠",
    "性价比",
    "入门",
    "省钱",
    "不要太贵",
    "不太贵",
    "不是很贵",
    "别太贵",
    "价格别太高",
    "低一点",
    "亲民一点",
    "划算一点",
)
HIGH_PRICE_TERMS = (
    "高端",
    "高价",
    "高预算",
    "旗舰",
    "专业级",
    "高配",
    "高级一点",
    "贵一点",
    "更高端",
    "更高配",
    "premium",
    "Premium",
)
VALUE_PRICE_TERMS = ("入门", "亲民", "经济", "实惠", "低价", "基础", "性价比", "常规", "中端")


def is_low_price_query(query: str) -> bool:
    return price_preference(query) == "low"


def is_high_price_query(query: str) -> bool:
    return price_preference(query) == "high"


def price_preference(query: str) -> str:
    text = _normalize(query)
    if not text:
        return ""
    if _contains_any(text, LOW_PRICE_TERMS) or _looks_like_negated_expensive_request(text):
        return "low"
    if _contains_any(text, HIGH_PRICE_TERMS):
        return "high"
    if _contains_any(text, VALUE_PRICE_TERMS):
        return "value"
    return ""


def price_bucket_for_row(row: dict[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    )
    lower = text.lower()
    if _contains_any(lower, HIGH_PRICE_TERMS):
        return "high"
    if _contains_any(lower, VALUE_PRICE_TERMS):
        return "value"
    if _contains_any(lower, LOW_PRICE_TERMS):
        return "low"
    return ""


def price_score(query: str, row: dict[str, Any]) -> int:
    preference = price_preference(query)
    if not preference:
        return 0
    bucket = price_bucket_for_row(row)
    if preference == "low":
        if bucket == "high":
            return -100
        if bucket in {"low", "value"}:
            return 45
        return -15
    if preference == "high":
        if bucket == "high":
            return 90
        if bucket == "value":
            return -45
        if bucket == "low":
            return -55
        return -25
    if bucket == "value":
        return 35
    if bucket == "high":
        return -20
    if bucket == "low":
        return 15
    return 0


def _looks_like_negated_expensive_request(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    patterns = (
        "不要太贵",
        "不太贵",
        "不是很贵",
        "别太贵",
        "价格别太高",
        "别太高",
        "不要太高",
        "不贵",
        "别贵",
        "便宜点",
        "便宜一些",
        "再便宜点",
        "便宜一点",
    )
    return any(pattern in compact for pattern in patterns)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term and term.lower() in text.lower() for term in terms)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())
