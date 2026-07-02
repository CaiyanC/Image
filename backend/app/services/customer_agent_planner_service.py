from __future__ import annotations

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

    if _is_compare_choice_question(text):
        products = _extract_compare_product_refs(text)
        plan.update(
            {
                "primary_intent": "product_compare_recommendation",
                "answer_type": "comparison",
                "product_refs": products,
                "scenario": "两个人吃饱" if _has_two_person_signal(text) else "",
                "constraints": ["两人", "容量够", "户外吃饭"],
                "must_compare_both_products": True,
                "must_make_choice": True,
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
                    {
                        "type": "recommendation_decision",
                        "scenario": "两个人吃饱",
                        "constraints": ["两人", "容量够", "户外吃饭"],
                    },
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
        "source": "",
    }


def _is_compare_choice_question(text: str) -> bool:
    return (
        "和" in text
        and any(term in text for term in ("区别", "不同", "对比", "比较"))
        and any(term in text for term in ("选哪个", "应该选", "更适合", "选哪"))
    )


def _extract_compare_product_refs(text: str) -> list[str]:
    products: list[str] = []
    for name in ("行山单锅", "激川单锅"):
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
    if any(term in text for term in ("尺寸", "多大", "规格", "直径")):
        return "尺寸"
    return ""


def _field_product_ref(text: str, requested_field: str) -> str:
    if not requested_field:
        return ""
    for suffix in ("尺寸是什么", "多大", "规格是什么", "直径是多少", "尺寸", "规格", "直径"):
        if text.endswith(suffix):
            return text[: -len(suffix)].strip("「」 ？?")
    return ""


def _is_recommendation_question(text: str) -> bool:
    return any(term in text for term in ("推荐", "买什么", "买哪款", "选哪款", "该买哪", "买什么产品"))


def _has_two_person_signal(text: str) -> bool:
    return any(term in text for term in ("两个人", "2人", "两人", "二人"))
