from __future__ import annotations

import re
from typing import Any


LOW_BUDGET_TERMS = ("预算不高", "预算低", "便宜", "实惠", "性价比", "入门", "低预算", "省钱", "不要太贵")
HIGH_PRICE_TERMS = ("高端", "高价", "高预算", "旗舰", "专业级", "premium")
VALUE_PRICE_TERMS = ("入门", "亲民", "经济", "实惠", "低价", "基础", "性价比", "常规")


def budget_score(query: str, row: dict[str, Any]) -> int:
    if not any(word in str(query or "") for word in LOW_BUDGET_TERMS):
        return 0
    price_text = " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    )
    lower = price_text.lower()
    if any(word in lower for word in HIGH_PRICE_TERMS):
        return -45
    if any(word in lower for word in VALUE_PRICE_TERMS):
        return 25
    return -5


def fallback_rank(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    keywords = [item for item in re.split(r"[\s,，。/]+", str(query or "")) if item]
    ranked = []
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in (
                "product_name_cn",
                "product_name_en",
                "category",
                "capacity",
                "body_material",
                "color",
                "features",
                "target_audience",
                "usage_scenarios",
                "positioning",
                "price_positioning",
            )
        ).lower()
        score = 0
        reasons = []
        for keyword in keywords:
            token = keyword.lower()
            if token and token in haystack:
                score += 2
                reasons.append(f'命中"{keyword}"相关信息')
        if row.get("features"):
            score += 1
            reasons.append("有可用的卖点/场景信息")
        if row.get("capacity"):
            score += 1
            reasons.append("有容量信息可供判断")
        price_score = budget_score(query, row)
        score += price_score
        if price_score > 0:
            reasons.append("价格定位更符合低预算/性价比需求")
        elif price_score < -10:
            reasons.append("价格定位偏高，不适合低预算首选")
        ranked.append({"row": row, "score": score, "reasons": list(dict.fromkeys(reasons))})
    ranked.sort(
        key=lambda item: (
            item["score"],
            bool(item["row"].get("features")),
            bool(item["row"].get("capacity")),
        ),
        reverse=True,
    )
    return ranked


def rank_from_llm_order(rows: list[dict[str, Any]], ranking: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not ranking:
        return fallback_rank(rows, query)
    ordered_indexes = [item.get("index") for item in ranking if isinstance(item.get("index"), int)]
    ranking_map = {
        item["index"]: str(item.get("reason") or "")
        for item in ranking
        if isinstance(item.get("index"), int)
    }
    ranked = []
    for index, row in enumerate(rows):
        reason = ranking_map.get(index, "")
        llm_score = 10 - ordered_indexes.index(index) if index in ordered_indexes else 0
        score = llm_score + budget_score(query, row)
        ranked.append({"row": row, "score": score, "reasons": [reason] if reason else []})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked if ranked else fallback_rank(rows, query)
