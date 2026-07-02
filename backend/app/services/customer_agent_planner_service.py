from __future__ import annotations

import re

from typing import Any


TIMING_KEYS = (
    "total_duration_ms",
    "planner_duration_ms",
    "retrieval_duration_ms",
    "executor_duration_ms",
    "llm_duration_ms",
    "llm_call_count",
    "composer_duration_ms",
    "guard_duration_ms",
)


def empty_timing() -> dict[str, float | int | None]:
    timing: dict[str, float | int | None] = {key: 0 for key in TIMING_KEYS}
    timing["llm_call_count"] = 0
    return timing


def merge_timing(existing: dict | None, updates: dict | None = None) -> dict:
    timing = empty_timing()
    if isinstance(existing, dict):
        for key in TIMING_KEYS:
            if key in existing:
                timing[key] = existing[key]
    if isinstance(updates, dict):
        for key in TIMING_KEYS:
            if key in updates:
                timing[key] = updates[key]
    return timing


def plan_customer_question(
    question: str,
    *,
    deterministic_intent: str | None = None,
    deterministic_answer_type: str | None = None,
) -> dict[str, Any]:
    text = str(question or "").strip()
    plan = _base_plan()

    compatibility = _explicit_pan_alcohol_stove_compatibility(text)
    if compatibility:
        plan.update(compatibility)
        return plan

    if _is_compare_question(text):
        products = _extract_compare_product_refs(text)
        must_make_choice = _is_compare_choice_question(text)
        plan.update(
            {
                "primary_intent": "product_compare_recommendation" if must_make_choice else "comparison",
                "answer_type": "comparison",
                "product_refs": products,
                "scenario": "两个人吃饱" if _has_two_person_signal(text) else "",
                "constraints": ["两人", "容量够", "户外吃饭"],
                "must_compare_both_products": True,
                "must_make_choice": must_make_choice,
                "confidence": "high",
                "tasks": [
                    {
                        "type": "product_compare",
                        "products": products,
                        "compare_dimensions": ["容量", "适用人数", "重量", "材质", "场景", "优缺点"],
                    },
                    {
                        "type": "knowledge_evidence_lookup",
                        "products": products,
                        "source": "file_knowledge_base",
                    },
                    *(
                        [{
                            "type": "recommendation_decision",
                            "scenario": "两个人吃饱",
                            "constraints": ["两人", "容量够", "户外吃饭"],
                        }]
                        if must_make_choice
                        else []
                    ),
                ],
            }
        )
        return plan

    if _is_catalog_count_question(text):
        product_ref = _catalog_product_ref(text)
        plan.update(
            {
                "primary_intent": "catalog_count",
                "answer_type": "query_products",
                "product_ref": product_ref,
                "source": "product_catalog_structured_query",
                "confidence": "high",
                "tasks": [{"type": "catalog_count", "product_ref": product_ref}],
            }
        )
        return plan

    requested_field = _requested_field(text)
    product_ref = _field_product_ref(text, requested_field)
    if requested_field and product_ref:
        conflict = deterministic_intent in {"recommendation", "knowledge_base_answer", "query_products"} or deterministic_answer_type in {
            "recommendation",
            "knowledge_base_answer",
            "query_products",
        }
        plan.update(
            {
                "primary_intent": "product_field",
                "answer_type": "product_detail",
                "product_ref": product_ref,
                "requested_field": requested_field,
                "field_only": True,
                "routing_conflict": bool(conflict),
                "confidence": "high",
                "tasks": [{"type": "product_field", "product_ref": product_ref, "requested_field": requested_field}],
            }
        )
        return plan

    if _is_recommendation_question(text):
        plan.update(
            {
                "primary_intent": "recommendation",
                "answer_type": "recommendation",
                "scenario": text,
                "must_return_products": True,
                "confidence": "medium",
                "tasks": [{"type": "recommendation", "scenario": text}],
            }
        )
        return plan

    plan.update(
        {
            "primary_intent": deterministic_intent or "",
            "answer_type": deterministic_answer_type or "",
            "confidence": "low",
        }
    )
    return plan


def _base_plan() -> dict[str, Any]:
    return {
        "primary_intent": "",
        "answer_type": "",
        "tasks": [],
        "product_ref": "",
        "category_ref": "",
        "product_refs": [],
        "sku": "",
        "requested_field": "",
        "scenario": "",
        "constraints": [],
        "needs_clarification": False,
        "routing_conflict": False,
        "confidence": "low",
        "field_only": False,
        "must_return_products": False,
        "must_compare_both_products": False,
        "must_make_choice": False,
        "explicit_product_or_category": False,
        "must_stay_within_category": False,
        "must_not_recommend_other_categories": False,
        "source": "",
    }


def _explicit_pan_alcohol_stove_compatibility(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    lowered = value.lower()
    has_alcohol_stove = "酒精炉" in value or "alcohol stove" in lowered
    has_compatibility = any(term in value for term in ("能不能用", "能否使用", "是否支持", "支不支持", "可不可以放", "可以用", "适用"))
    has_pan_scope = any(
        term in lowered
        for term in ("烤盘", "煎盘", "煎烤盘", "griddle", "grill pan", "fry pan", "pan plate", "cf-pg19")
    )
    if not (has_alcohol_stove and has_compatibility and has_pan_scope):
        return None

    sku_match = re.search(r"\bCF-PG19(?:PRO)?\b", value, flags=re.I)
    if sku_match or "瓦片烤盘" in value:
        product_ref = sku_match.group(0).upper() if sku_match else ("瓦片烤盘Pro" if "瓦片烤盘Pro" in value else "瓦片烤盘")
        return {
            "primary_intent": "product_field",
            "answer_type": "product_detail",
            "product_ref": product_ref,
            "requested_field": "heat_source",
            "field_only": True,
            "explicit_product_or_category": True,
            "must_not_recommend_other_categories": True,
            "confidence": "high",
            "tasks": [{"type": "product_field", "product_ref": product_ref, "requested_field": "heat_source"}],
        }

    category_ref = "煎烤盘" if "煎烤盘" in value else "煎盘" if "煎盘" in value else "烤盘" if "烤盘" in value else "griddle"
    return {
        "primary_intent": "category_compatibility",
        "answer_type": "product_detail",
        "category_ref": category_ref,
        "requested_field": "heat_source",
        "explicit_product_or_category": True,
        "must_stay_within_category": True,
        "must_not_recommend_other_categories": True,
        "confidence": "high",
        "tasks": [{"type": "category_compatibility", "category_ref": category_ref, "requested_field": "heat_source"}],
    }


def _is_compare_question(text: str) -> bool:
    return (
        "和" in text
        and any(term in text for term in ("区别", "不同", "对比", "比较"))
        and len(_extract_compare_product_refs(text)) >= 2
    )


def _is_compare_choice_question(text: str) -> bool:
    return (
        _is_compare_question(text)
        and any(term in text for term in ("选哪个", "应该选", "应该买", "买哪个", "更适合", "选哪", "该买"))
    )


def _extract_compare_product_refs(text: str) -> list[str]:
    products: list[str] = []
    for name in ("行山单锅", "激川单锅", "轻途套锅", "享野套锅"):
        if name in text:
            products.append(name)
    if products:
        return products
    if "和" in text:
        left, right = text.split("和", 1)
        right = right.split("的", 1)[0].split("，", 1)[0].split(",", 1)[0]
        return [left.strip("「」 ？?"), right.strip("「」 ？?")]
    return []


def _is_catalog_count_question(text: str) -> bool:
    has_catalog = "产品库" in text or "库里" in text
    has_count_or_list = any(term in text for term in ("多少", "有多少", "多少个", "几个", "数量", "有哪些", "都有哪些", "列一下", "产品有哪些", "产品列表", "几款", "几种"))
    has_product_scope = any(term in text for term in ("套锅", "锅具", "水壶", "烤盘", "单锅", "产品"))
    return has_count_or_list and has_product_scope and (
        has_catalog
        or any(term in text for term in ("有哪些", "都有哪些", "列一下", "产品有哪些", "产品列表"))
    )


def _catalog_product_ref(text: str) -> str:
    if "套锅" in text:
        return "套锅"
    if "锅具" in text:
        return "锅具"
    if "水壶" in text:
        return "水壶"
    if "烤盘" in text:
        return "烤盘"
    if "单锅" in text:
        return "单锅"
    return "产品"


def _requested_field(text: str) -> str:
    if any(term in text for term in ("尺寸", "多大", "规格", "直径", "长宽高", "长宽", "高度", "宽度")):
        return "尺寸"
    if any(term in text for term in ("容量", "装多少")):
        return "容量"
    if any(term in text for term in ("重量", "多重", "多沉")):
        return "重量"
    if any(term in text for term in ("材质", "什么材料", "材料")):
        return "材质"
    return ""


def _field_product_ref(text: str, requested_field: str) -> str:
    if not requested_field:
        return ""
    for suffix in ("尺寸是什么", "多大", "规格是什么", "直径是多少", "容量是多少", "重量是多少", "材质是什么", "尺寸", "规格", "直径", "容量", "重量", "材质"):
        idx = text.find(suffix)
        if idx > 0:
            return _clean_product_ref_fragment(text[:idx])
    return ""


def _clean_product_ref_fragment(value: str) -> str:
    text = str(value or "").strip("「」 ？?。,.，")
    for prefix in ("你们那个", "你们的", "那个", "这款", "这个"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for suffix in ("到底", "具体", "大概", "请问"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text.strip("「」 ？?。,.，")


def _is_recommendation_question(text: str) -> bool:
    if _looks_like_context_ordinal_reference(text):
        return False
    if any(term in text for term in ("推荐", "买什么", "买哪款", "选哪款", "该买哪", "买什么产品")):
        return True
    product_terms = ("锅", "套锅", "单锅", "炉", "炉具", "水壶", "餐具", "套装")
    scenario_terms = ("野餐", "露营", "徒步", "爬山", "公园", "周末", "两个人", "三个人", "一个人", "轻便", "轻量")
    purchase_decision_terms = ("想买", "买个", "买口", "买套", "买一套", "应该买", "该买", "买")
    return (
        any(term in text for term in purchase_decision_terms)
        and any(term in text for term in product_terms)
        and any(term in text for term in scenario_terms)
    )


def _looks_like_context_ordinal_reference(text: str) -> bool:
    return (
        any(term in text for term in ("刚才", "前面", "上面"))
        and any(term in text for term in ("第一个", "第一款"))
        and any(term in text for term in ("第二个", "第二款"))
    )


def _has_two_person_signal(text: str) -> bool:
    return any(term in text for term in ("两个人", "2人", "两人", "二人"))
