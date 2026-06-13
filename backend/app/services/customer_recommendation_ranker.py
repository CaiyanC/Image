from __future__ import annotations

import re
from typing import Any


LOW_BUDGET_TERMS = ("预算不高", "预算低", "低预算", "便宜", "实惠", "性价比", "入门", "省钱", "不要太贵")
HIGH_PRICE_TERMS = ("高端", "高价", "高预算", "旗舰", "专业级", "premium")
VALUE_PRICE_TERMS = ("入门", "亲民", "经济", "实惠", "低价", "基础", "性价比", "常规", "中端")

NEGATION_TERMS = ("不要", "别要", "不想要", "排除", "去掉", "剔除", "不是")

PRODUCT_TYPE_QUERY_TERMS = {
    "water": ("水具", "水壶", "水杯", "杯子", "杯", "壶", "饮水", "补水", "煮茶"),
    "stove": ("炉具", "炉子", "酒精炉", "气炉", "卡式炉", "炉"),
    "pot": ("锅具", "套锅", "单锅", "煎锅", "炒锅", "烤盘", "锅子", "小锅", "锅", "做饭", "煮面"),
    "cutlery": ("餐具", "勺", "叉", "铲"),
    "bag": ("收纳包", "包具", "背包", "包"),
}

PRODUCT_TYPE_ROW_TERMS = {
    "water": ("水具", "水壶", "水杯", "杯", "壶", "饮水", "补水"),
    "stove": ("炉具", "酒精炉", "气炉", "卡式炉", "炉"),
    "pot": ("锅具", "套锅", "单锅", "煎锅", "炒锅", "烤盘", "煎盘", "锅"),
    "cutlery": ("餐具", "勺", "叉", "铲"),
    "bag": ("收纳包", "包具", "背包", "包"),
}

ONE_OR_TWO_PERSON_TERMS = ("1-2", "一到两", "一至两", "一两", "两个人", "双人", "单人", "1人", "2人")
LIGHTWEIGHT_TERMS = ("轻量", "轻便", "便携", "徒步", "背包", "极简", "速穿")
FAMILY_OR_LARGE_TERMS = ("家庭", "多人", "房车", "自驾", "营地大餐", "大容量", "聚餐")
THREE_FOUR_PERSON_TERMS = ("三人", "三个人", "3人", "3-4", "四人", "四个人", "4人", "多人", "家庭")


def budget_score(query: str, row: dict[str, Any]) -> int:
    if not _contains_any(str(query or ""), LOW_BUDGET_TERMS):
        return 0
    price_text = " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    )
    lower = price_text.lower()
    if _contains_any(lower, HIGH_PRICE_TERMS):
        return -100
    if _contains_any(lower, VALUE_PRICE_TERMS):
        return 45
    return -15


def recommendation_score(query: str, row: dict[str, Any]) -> float:
    query_text = str(query or "")
    text = _row_text(row)
    name = str(row.get("product_name_cn") or "")
    capacity_ml = _capacity_ml(row.get("capacity"))
    desired_type = desired_product_type(query_text)

    score = 0.0
    if desired_type:
        score += 85 if _row_matches_type(row, desired_type) else -160
    elif is_obvious_product_type_mismatch(query_text, row):
        score -= 140

    if "露营" in query_text and "露营" in text:
        score += 25

    if _contains_any(query_text, THREE_FOUR_PERSON_TERMS):
        if capacity_ml:
            if 1600 <= capacity_ml <= 4500:
                score += 35
            elif capacity_ml < 1400:
                score -= 30
            elif capacity_ml > 5000:
                score -= 15
        if _contains_any(text, FAMILY_OR_LARGE_TERMS):
            score += 15
        if _contains_any(text, ("单人", "极限轻量", "速穿")):
            score -= 18

    if _contains_any(query_text, ONE_OR_TWO_PERSON_TERMS + LIGHTWEIGHT_TERMS):
        if capacity_ml:
            if capacity_ml <= 1600:
                score += 45
            elif capacity_ml <= 2400:
                score += 12
            elif capacity_ml >= 3000:
                score -= 65
        if _contains_any(text, ONE_OR_TWO_PERSON_TERMS + LIGHTWEIGHT_TERMS):
            score += 35
        if _contains_any(text, FAMILY_OR_LARGE_TERMS):
            score -= 35

    if _contains_any(query_text, ("咖啡", "泡咖啡", "煮茶", "小锅")):
        if _contains_any(text, ("咖啡", "煮茶", "烧水", "速沸", "水壶", "单锅")):
            score += 28
        if capacity_ml:
            if 400 <= capacity_ml <= 1500:
                score += 28
            elif capacity_ml > 2000:
                score -= 35
        if any(word in name for word in ("炒锅", "煎锅", "煎盘")):
            score -= 50

    if _contains_any(query_text, ("送礼", "礼物", "朋友", "精致露营")):
        if _contains_any(text, ("颜值", "精致", "情绪价值", "礼", "高端", "套装")):
            score += 25

    if row.get("features"):
        score += 4
    score += budget_score(query_text, row)
    return score


def is_obvious_product_type_mismatch(query: str, row: dict[str, Any]) -> bool:
    desired_type = desired_product_type(query)
    if desired_type:
        return not _row_matches_type(row, desired_type)
    return False


def desired_product_type(query: str) -> str | None:
    text = _positive_query_text(str(query or ""))
    for product_type, terms in PRODUCT_TYPE_QUERY_TERMS.items():
        if _contains_any(text, terms):
            return product_type
    return None


def fallback_rank(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    keywords = [item for item in re.split(r"[\s,，。？?]+", str(query or "")) if item]
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


def _row_matches_type(row: dict[str, Any], product_type: str) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "category", "sub_category")
    )
    return _contains_any(text, PRODUCT_TYPE_ROW_TERMS.get(product_type, ()))


def _positive_query_text(query: str) -> str:
    text = str(query or "")
    for term in NEGATION_TERMS:
        text = re.sub(rf"{re.escape(term)}\s*[\u4e00-\u9fffA-Za-z0-9_\-]+", " ", text)
    return text


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term and term.lower() in text.lower() for term in terms)


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
