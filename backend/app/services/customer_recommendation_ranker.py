from __future__ import annotations

import re
from typing import Any

from . import customer_price_signal


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

ONE_OR_TWO_PERSON_TERMS = ("1-2", "1－2", "一到两", "一至两", "一两", "两个人", "两人", "双人", "单人", "1人", "2人", "１-２", "１－２")
TWO_PERSON_TERMS = ("两个人", "两人", "双人", "2人", "２人", "1-2", "1－2", "一到两", "一至两", "一两")
LIGHTWEIGHT_TERMS = ("轻量", "轻便", "便携", "徒步", "背包", "极简", "速穿")
FAMILY_OR_LARGE_TERMS = ("家庭", "多人", "房车", "自驾", "营地大餐", "大容量", "聚餐")
THREE_FOUR_PERSON_TERMS = ("三人", "三个人", "3人", "2-4", "3-4", "四人", "四个人", "4人", "多人", "家庭")
COOKING_METHOD_TERMS = ("煎炒煮", "煎", "炒", "煮", "煎炒", "炒菜", "做饭")
PICNIC_TERMS = ("野餐", "周末野餐", "公园野餐", "家庭野餐", "周末")
SET_TERMS = ("套装", "套锅", "件套", "炊具套装", "炊具组合", "锅具套装", "野餐锅", "野营锅", "收纳便携")
MID_BUDGET_TERMS = ("预算中等", "中等预算", "预算适中", "别太贵", "不要太贵", "不要太入门", "别太入门", "预算")
ENTRY_LEVEL_TERMS = ("入门", "新手", "基础款")


def budget_score(query: str, row: dict[str, Any]) -> int:
    return customer_price_signal.price_score(query, row)


def recommendation_score(query: str, row: dict[str, Any]) -> float:
    query_text = str(query or "")
    text = _row_text(row)
    scene_text = _scene_text(row)
    name = str(row.get("product_name_cn") or "")
    capacity_ml = _capacity_ml(row.get("capacity"))
    desired_type = desired_product_type(query_text)

    score = 0.0
    score += _raw_product_hint_score(query_text, text)
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

    if _contains_any(query_text, TWO_PERSON_TERMS):
        if _contains_any(text, ("1-2", "两人", "双人", "2人", "满足双人")):
            score += 45
        if _contains_any(text, ("单人", "极限轻量", "速穿", "单人野宿")):
            score -= 45
        if _contains_any(text, ("2-4", "3-4", "多人", "家庭", "营地大餐")):
            score -= 35
        if capacity_ml:
            if 1200 <= capacity_ml <= 1800:
                score += 25
            elif capacity_ml < 1100:
                score -= 25

    if _contains_any(query_text, COOKING_METHOD_TERMS):
        if _contains_any(text, ("煎", "炒", "煮", "不粘", "不沾", "烹饪", "做饭", "一锅")):
            score += 35
        if _contains_any(text, ("速沸", "烧水", "单人野宿", "极限轻量")):
            score -= 20

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

    if _is_picnic_lightweight_set_mid_budget_query(query_text):
        if _row_is_set(row):
            score += 45
        else:
            score -= 35
        if _contains_any(text, PICNIC_TERMS):
            score += 40
        if _contains_any(scene_text, PICNIC_TERMS + ("家庭", "公园野炊")):
            score += 18
        if _contains_any(text, ("2-3人", "2-3 人", "两个人", "两人", "双人", "家庭周末野餐", "小家庭")):
            score += 45
        if _contains_any(scene_text, ("2-3人", "2-3 人", "小家庭", "家庭周末野餐用户")):
            score += 18
        elif _contains_any(text, ("1-2人", "1-2 人", "1-2")):
            score -= 12
        if _contains_any(text, ("全套收纳便携", "套娃式收纳", "收纳便携", "轻便", "便携", "轻量化")):
            score += 25
        if _contains_any(text, ("常规价格带", "中端", "高性价比")):
            score += 28
        if _contains_any(text, ENTRY_LEVEL_TERMS):
            score -= 18
        if _contains_any(scene_text, ("单人背包客", "单人露营", "轻量徒步", "背包旅行", "极简野炊", "荒野求生", "机车旅行")) and not _contains_any(scene_text, PICNIC_TERMS + ("家庭", "公园野炊")):
            score -= 55
        if _contains_any(text, ("徒步", "背包", "极简", "野宿")) and not _contains_any(text, PICNIC_TERMS):
            score -= 18
        if _contains_any(text, ("3-4人", "3-4 人", "2-4人", "2-4 人", "多人", "营地大餐")):
            score -= 24
        if capacity_ml:
            if 1600 <= capacity_ml <= 2600:
                score += 22
            elif capacity_ml < 1200:
                score -= 48
                if _contains_any(scene_text, ("单人背包客", "轻量徒步", "极简野炊", "荒野求生")):
                    score -= 24
            elif capacity_ml >= 3000:
                score -= 20

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
    raw_text = str(query or "")
    text = _positive_query_text(raw_text)
    for product_type, terms in PRODUCT_TYPE_QUERY_TERMS.items():
        if _contains_any(text, terms):
            return product_type
    for product_type, terms in PRODUCT_TYPE_QUERY_TERMS.items():
        if _contains_any(raw_text, terms) and not _has_explicit_type_exclusion(raw_text, terms):
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
        explanation = explain_match(query, row, score, reasons)
        ranked.append({
            "row": row,
            "score": score,
            "reasons": explanation["matched"],
            "matched": explanation["matched"],
            "missing_or_uncertain": explanation["missing_or_uncertain"],
            "score_reason": explanation["score_reason"],
        })
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
        seed_reasons = [reason] if reason else []
        explanation = explain_match(query, row, score, seed_reasons)
        ranked.append({
            "row": row,
            "score": score,
            "reasons": explanation["matched"],
            "matched": explanation["matched"],
            "missing_or_uncertain": explanation["missing_or_uncertain"],
            "score_reason": explanation["score_reason"],
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked if ranked else fallback_rank(rows, query)


def _row_matches_type(row: dict[str, Any], product_type: str) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "category", "sub_category")
    )
    return _contains_any(text, PRODUCT_TYPE_ROW_TERMS.get(product_type, ()))


def explain_match(query: str, row: dict[str, Any], score: float | None = None, seed_reasons: list[str] | None = None) -> dict[str, Any]:
    query_text = str(query or "")
    text = _row_text(row)
    scene_text = _scene_text(row)
    matched: list[str] = list(seed_reasons or [])
    missing: list[str] = []
    capacity_ml = _capacity_ml(row.get("capacity"))
    desired_type = desired_product_type(query_text)

    if desired_type and _row_matches_type(row, desired_type):
        matched.append(f"类目匹配{_product_type_label(desired_type)}")

    if _contains_any(query_text, THREE_FOUR_PERSON_TERMS):
        if capacity_ml and 1600 <= capacity_ml <= 4500:
            matched.append("容量适合3-4人或多人露营")
        elif capacity_ml:
            missing.append("容量与3-4人需求不完全匹配")
        else:
            missing.append("未标注可判断人数的容量信息")
        if _contains_any(text, FAMILY_OR_LARGE_TERMS + ("2-4", "3-4")):
            matched.append("资料包含多人/家庭/2-4人场景")
        else:
            missing.append("未明确标注多人或家庭出行场景")

    if _contains_any(query_text, COOKING_METHOD_TERMS):
        if _contains_any(text, ("煎", "炒", "煮", "不粘", "不沾", "烹饪", "做饭", "一锅")):
            matched.append("资料支持煎炒煮/做饭相关需求")
        else:
            missing.append("未明确标注煎炒煮能力")

    if _contains_any(query_text, ("咖啡", "泡咖啡", "煮咖啡", "煮茶")):
        if _contains_any(text, ("咖啡", "煮茶", "烧水", "速沸", "水壶", "单锅")):
            matched.append("资料包含咖啡/煮茶/烧水相关场景")
        else:
            missing.append("未明确标注咖啡或煮茶场景")

    if _contains_any(query_text, LIGHTWEIGHT_TERMS):
        if _contains_any(text, LIGHTWEIGHT_TERMS + ("轻",)):
            matched.append("资料包含轻量/便携信息")
        else:
            missing.append("未明确标注轻量便携优势")

    if _is_picnic_lightweight_set_mid_budget_query(query_text):
        if _row_is_set(row):
            matched.append("属于套装/套锅组合，更适合野餐整套携带")
        else:
            missing.append("不属于明确套装组合")
        if _contains_any(text, PICNIC_TERMS):
            matched.append("资料包含周末野餐/家庭野餐场景")
        else:
            missing.append("未明确标注野餐场景")
        if _contains_any(text, ("2-3人", "2-3 人", "两个人", "两人", "双人", "家庭周末野餐", "小家庭")):
            matched.append("人数更贴近两个人周末野餐")
        elif _contains_any(text, ("1-2人", "1-2 人", "1-2")):
            missing.append("容量偏小，更像入门轻量小套装")
        if _contains_any(text, ("全套收纳便携", "套娃式收纳", "收纳便携", "轻便", "便携", "轻量化")):
            matched.append("有全套收纳便携证据")
        if _contains_any(scene_text, ("单人背包客", "单人露营", "轻量徒步", "背包旅行", "极简野炊", "荒野求生", "机车旅行")) and not _contains_any(scene_text, PICNIC_TERMS + ("家庭", "公园野炊")):
            missing.append("更偏徒步背包小套装，不是更从容的双人野餐套装")
        if _contains_any(text, ("常规价格带", "中端", "高性价比")):
            matched.append("价格定位更接近中等预算")
        elif _contains_any(text, ENTRY_LEVEL_TERMS):
            missing.append("更偏入门款")

    if "硬质氧化铝合金" in query_text:
        if "硬质氧化铝合金" in text:
            matched.append("材质为硬质氧化铝合金")
        else:
            missing.append("材质未标注为硬质氧化铝合金")

    price_score = budget_score(query_text, row)
    if price_score > 0:
        matched.append("价格定位更符合预算诉求")
    elif price_score < -10:
        missing.append("价格定位偏高，需提醒不一定符合预算")

    if row.get("features"):
        matched.append("有卖点/场景资料可引用")
    else:
        missing.append("卖点/场景资料不足")
    if not row.get("capacity"):
        missing.append("容量资料未标注")

    return {
        "matched": list(dict.fromkeys(item for item in matched if item and item != "与本轮需求匹配")),
        "missing_or_uncertain": list(dict.fromkeys(missing)),
        "score_reason": f"排序分数 {score:.1f}" if isinstance(score, (int, float)) else "",
    }


def _product_type_label(product_type: str) -> str:
    return {
        "water": "水具",
        "stove": "炉具",
        "pot": "锅具",
        "cutlery": "餐具",
        "bag": "收纳包",
    }.get(product_type, product_type)


def _raw_product_hint_score(query_text: str, row_text: str) -> int:
    hints = (
        ("锅", ("锅", "套锅", "单锅", "炒锅", "煎锅", "烤盘")),
        ("炉", ("炉", "酒精炉", "气炉", "卡式炉")),
        ("勺", ("勺", "铲", "刀", "叉", "餐具")),
        ("杯", ("杯", "壶", "水壶", "水杯", "水瓶")),
        ("包", ("包", "收纳", "背包")),
    )
    query_text = str(query_text or "")
    row_text = str(row_text or "")
    score = 0
    for _, terms in hints:
        if any(term in query_text for term in terms):
            if any(term in row_text for term in terms):
                score += 40
            else:
                score -= 40
    return score


def _positive_query_text(query: str) -> str:
    text = str(query or "")
    for term in NEGATION_TERMS:
        text = re.sub(rf"{re.escape(term)}\s*[\u4e00-\u9fffA-Za-z0-9_\-]+", " ", text)
    return text


def _has_explicit_type_exclusion(text: str, terms: tuple[str, ...]) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    exclusion_terms = ("不要", "别要", "不想要", "排除", "去掉", "剔除", "不要买", "别买")
    return any(
        re.search(rf"{re.escape(prefix)}[^，。？！]{{0,8}}{re.escape(term)}", compact)
        for prefix in exclusion_terms
        for term in terms
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term and term.lower() in text.lower() for term in terms)


def _is_picnic_lightweight_set_mid_budget_query(query: str) -> bool:
    text = str(query or "")
    return (
        _contains_any(text, PICNIC_TERMS)
        and _contains_any(text, SET_TERMS)
        and _contains_any(text, LIGHTWEIGHT_TERMS + ("收纳",))
        and _contains_any(text, TWO_PERSON_TERMS)
        and _contains_any(text, MID_BUDGET_TERMS)
    )


def _row_is_set(row: dict[str, Any]) -> bool:
    text = _row_text(row)
    return _contains_any(text, SET_TERMS)


def _scene_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("features", "target_audience", "positioning", "price_positioning", "usage_scenarios")
    )


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
