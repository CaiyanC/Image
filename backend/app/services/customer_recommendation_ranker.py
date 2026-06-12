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
        return -100
    if any(word in lower for word in VALUE_PRICE_TERMS):
        return 45
    return -15


def recommendation_score(query: str, row: dict[str, Any]) -> float:
    text = _row_text(row)
    name = str(row.get("product_name_cn") or "")
    capacity_ml = _capacity_ml(row.get("capacity"))
    score = 0.0
    if is_obvious_product_type_mismatch(query, row):
        score -= 140
    if "露营" in query and "露营" in text:
        score += 30
    if any(word in query for word in ("年轻人", "三人", "三个人", "三个", "四人", "四个人", "四个")):
        if capacity_ml:
            if 1800 <= capacity_ml <= 4200:
                score += 35
            elif capacity_ml < 1500:
                score -= 25
            elif capacity_ml > 5000:
                score -= 15
        if any(word in text for word in ("家庭", "多人", "聚餐", "营地大餐", "精致露营")):
            score += 12
        if any(word in text for word in ("单人", "极限轻量", "速穿")):
            score -= 16
    if any(word in query for word in ("咖啡", "泡咖啡", "小锅")):
        if any(word in text for word in ("咖啡", "煮水", "速沸", "烧水", "单锅")):
            score += 35
        if capacity_ml:
            if 400 <= capacity_ml <= 1500:
                score += 35
            elif capacity_ml > 2000:
                score -= 35
        if any(word in name for word in ("炒锅", "煎锅", "煎盘")):
            score -= 50
        if "炉" in name and "锅" not in name:
            score -= 20
    if any(word in query for word in ("送礼", "礼物")):
        if any(word in text for word in ("颜值", "精致", "情绪价值", "优雅", "礼")):
            score += 25
        if any(word in text for word in ("套锅", "套装", "家庭", "精致露营")):
            score += 15
    if row.get("features"):
        score += 4
    score += budget_score(query, row)
    return score


def is_obvious_product_type_mismatch(query: str, row: dict[str, Any]) -> bool:
    query_text = str(query or "")
    name_category = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "category", "sub_category")
    )
    if any(term in query_text for term in ("小锅", "单锅", "套锅", "煎锅", "炒锅", "锅具", "锅")):
        if "锅" in name_category:
            return False
        return any(
            term in name_category
            for term in ("炉", "炉具", "酒精炉", "气炉", "卡式炉", "杯", "杯套", "水壶", "壶", "包", "收纳", "餐具", "勺", "铲")
        )
    if any(term in query_text for term in ("炉具", "酒精炉", "气炉", "卡式炉")) or ("炉" in query_text and "炉头" not in query_text):
        if "炉" in name_category:
            return False
        return any(term in name_category for term in ("锅", "烤盘", "水壶", "杯", "包", "餐具", "勺", "铲"))
    return False


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
        score = recommendation_score(query, row)
        reasons = []
        for keyword in keywords:
            token = keyword.lower()
            if token and token in haystack:
                score += 2
                reasons.append(f'命中"{keyword}"相关信息')
        if row.get("features"):
            reasons.append("有可用的卖点/场景信息")
        if row.get("capacity"):
            reasons.append("有容量信息可供判断")
        price_score = budget_score(query, row)
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
        score = llm_score + recommendation_score(query, row)
        ranked.append({"row": row, "score": score, "reasons": [reason] if reason else []})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked if ranked else fallback_rank(rows, query)


def _row_text(row: dict[str, Any]) -> str:
    values = []
    for key in (
        "product_name_cn",
        "product_name_en",
        "category",
        "sub_category",
        "capacity",
        "body_material",
        "features",
        "target_audience",
        "positioning",
        "price_positioning",
        "usage_scenarios",
        "emotional_value",
        "semantic_match",
    ):
        value = row.get(key)
        if value:
            values.append(str(value))
    field_values = row.get("field_values")
    if isinstance(field_values, dict):
        values.extend(str(value) for value in field_values.values())
    return " ".join(values)


def _capacity_ml(value: Any) -> float | None:
    text = str(value or "")
    numbers = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ML|ml|毫升)", text)]
    if numbers:
        return max(numbers)
    liters = [float(item) * 1000 for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:L|l|升)", text)]
    if liters:
        return max(liters)
    return None
