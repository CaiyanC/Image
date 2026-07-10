from __future__ import annotations

import json
import re

from typing import Any
from ..core.config import settings
from . import customer_agent_service, customer_field_contract, customer_llm_service


EXPLICIT_SKU_RE = re.compile(
    r"\b[A-Za-z]{1,6}[A-Za-z0-9]{0,12}(?:[-_](?:[A-Za-z0-9]{1,24}(?:[\(（][A-Za-z0-9]{1,24}[\)）])?|[\u4e00-\u9fff]{1,8}))+(?=$|[\s，。,；;：:）)\]】>\"'？?])"
)


PLAIN_EXPLICIT_SKU_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}\d{2,12}[A-Za-z0-9\u4e00-\u9fff]{0,12})(?=$|[\s锛屻€?锛?锛?锛?\]銆?\"'锛?])"
)


SKU_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}[A-Za-z0-9]{0,12}(?:[-_](?:[A-Za-z0-9]{1,24}(?:[\(\uFF08][A-Za-z0-9]{1,24}[\)\uFF09])?|[\u4e00-\u9fff]{1,2}))+ )".replace("+ )", "+)")
)
PLAIN_SKU_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}\d{2,12}[A-Za-z0-9]{0,12}(?:[\(\uFF08][A-Za-z0-9]{1,24}[\)\uFF09])?)"
)


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


SEMANTIC_PREPLAN_ROUTE_HINTS = {
    "usage_care",
    "recommendation",
    "product_detail",
    "query_products",
    "knowledge_base_answer",
    "comparison",
    "unknown_field",
    "clarification",
}
SEMANTIC_PREPLAN_QUESTION_TYPES = {
    "safety",
    "count",
    "filter",
    "field",
    "contents_accessories",
    "comparison",
    "recommendation",
    "usage",
    "unknown_field",
    "followup",
}
SEMANTIC_PREPLAN_SUBTYPES = {
    "",
    "unknown_realtime",
    "commercial_realtime",
    "contents_accessories",
    "composition",
    "known_detail",
    "usage_care",
    "relation_comparison",
    "recommendation",
    "structured_query",
    "generic_query",
    "no_match",
}
SEMANTIC_PREPLAN_ENTITY_SCOPES = {
    "",
    "resolved_single",
    "unique_product_name",
    "ambiguous_product_name",
    "unresolved_product_like",
    "generic_scope",
    "category_scope",
    "product_like",
    "resolved_product",
    "ambiguous_product",
    "unresolved_product",
    "negative_product",
}
SEMANTIC_PREPLAN_ROUTE_FAMILIES = {
    "",
    "structured_query",
    "recommendation",
    "product_bound_qa",
    "unresolved_product_like",
    "negative_product_like",
    "unknown_realtime",
    "contents_accessories",
    "generic_query",
    "clarification",
}
SEMANTIC_PREPLAN_FIELD_TYPES = {
    "",
    "material",
    "category",
    "usage",
    "heat_source",
    "capacity",
    "price",
    "stock",
    "shipping",
    "gift",
    "contents",
    "recommendation",
    "unknown",
}
SEMANTIC_PREPLAN_FORBIDDEN_KEYS = {
    "answer",
    "final_answer",
    "candidate_skus",
    "recommended_skus",
    "result_skus",
    "sku",
    "skus",
    "price",
    "stock",
    "sales",
    "certification",
    "warranty",
}
SEMANTIC_PREPLAN_ALLOWED_KEYS = {
    "route_family",
    "route_hint",
    "question_type",
    "entities",
    "field_type",
    "field_hint",
    "subtype",
    "entity_scope",
    "qa_or_usage_care",
    "unknown_field",
    "confidence",
    "reason",
    "r",
    "q",
    "e",
    "f",
    "s",
    "scope",
    "u",
    "n",
    "c",
    "why",
}
SEMANTIC_PREPLAN_SHORT_KEY_MAP = {
    "r": "route_hint",
    "q": "question_type",
    "e": "entities",
    "f": "field_hint",
    "s": "subtype",
    "scope": "entity_scope",
    "u": "qa_or_usage_care",
    "n": "unknown_field",
    "c": "confidence",
    "why": "reason",
}


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


def _empty_semantic_preplan(*, called: bool = False, fallback_reason: str = "") -> dict[str, Any]:
    return {
        "called": called,
        "purpose": "semantic_preplan",
        "route_family": "",
        "route_hint": "",
        "question_type": "",
        "entities": [],
        "field_type": "",
        "field_hint": None,
        "subtype": "",
        "entity_scope": "",
        "qa_or_usage_care": False,
        "unknown_field": False,
        "confidence": 0.0,
        "confidence_label": "",
        "reason": "",
        "accepted_or_overridden": "",
        "override_reason": "",
        "fallback_reason": fallback_reason,
        "llm_call_count": 1 if called else 0,
        "llm_call_count_delta": 1 if called else 0,
        "raw_preview": "",
        "preplan_model": "",
        "preplan_temperature": None,
        "preplan_max_tokens": None,
        "preplan_json_mode": False,
        "preplan_thinking_disabled": False,
        "preplan_latency_ms": None,
        "provider_usage_available": False,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "prompt_cache_hit_tokens": None,
        "prompt_cache_miss_tokens": None,
    }


def _semantic_preplan_runtime_settings() -> dict[str, Any]:
    return {
        "model": str(settings.SEMANTIC_PREPLAN_MODEL or "").strip() or None,
        "temperature": float(settings.SEMANTIC_PREPLAN_TEMPERATURE),
        "max_tokens": max(1, int(settings.SEMANTIC_PREPLAN_MAX_TOKENS)),
        "response_format": {"type": "json_object"} if settings.SEMANTIC_PREPLAN_JSON_MODE else None,
        "thinking": {"type": "disabled"} if settings.SEMANTIC_PREPLAN_THINKING_DISABLED else None,
    }


def _apply_semantic_preplan_observability(
    result: dict[str, Any],
    metadata: dict[str, Any] | None,
    runtime_settings: dict[str, Any],
) -> dict[str, Any]:
    result["preplan_model"] = str((metadata or {}).get("request_model") or runtime_settings.get("model") or "")
    result["preplan_temperature"] = (metadata or {}).get("temperature", runtime_settings.get("temperature"))
    result["preplan_max_tokens"] = (metadata or {}).get("max_tokens", runtime_settings.get("max_tokens"))
    result["preplan_json_mode"] = bool(runtime_settings.get("response_format"))
    thinking = (metadata or {}).get("thinking", runtime_settings.get("thinking"))
    result["preplan_thinking_disabled"] = isinstance(thinking, dict) and thinking.get("type") == "disabled"
    result["preplan_latency_ms"] = (metadata or {}).get("elapsed_ms")
    usage = (metadata or {}).get("usage") if isinstance((metadata or {}).get("usage"), dict) else {}
    result["provider_usage_available"] = bool(usage)
    result["prompt_tokens"] = usage.get("prompt_tokens")
    result["completion_tokens"] = usage.get("completion_tokens")
    result["total_tokens"] = usage.get("total_tokens")
    completion_details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    result["reasoning_tokens"] = completion_details.get("reasoning_tokens")
    result["prompt_cache_hit_tokens"] = usage.get("prompt_cache_hit_tokens")
    result["prompt_cache_miss_tokens"] = usage.get("prompt_cache_miss_tokens")
    return result


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index, char in enumerate(raw[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(raw[start : index + 1])
                        return data if isinstance(data, dict) else None
                    except json.JSONDecodeError:
                        return None
    return None


def _safe_preview(value: str, limit: int = 200) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _semantic_route_family_defaults(route_family: str) -> dict[str, Any]:
    family = str(route_family or "").strip()
    if family == "structured_query":
        return {"route_hint": "query_products", "question_type": "filter", "subtype": "structured_query"}
    if family == "recommendation":
        return {"route_hint": "recommendation", "question_type": "recommendation", "subtype": "recommendation"}
    if family == "product_bound_qa":
        return {"route_hint": "product_detail", "question_type": "field", "subtype": "known_detail"}
    if family in {"unresolved_product_like", "negative_product_like"}:
        return {"route_hint": "clarification", "question_type": "field", "subtype": "no_match"}
    if family == "unknown_realtime":
        return {"route_hint": "unknown_field", "question_type": "unknown_field", "subtype": "unknown_realtime", "unknown_field": True}
    if family == "contents_accessories":
        return {"route_hint": "product_detail", "question_type": "contents_accessories", "subtype": "contents_accessories"}
    if family == "generic_query":
        return {"route_hint": "query_products", "question_type": "filter", "subtype": "generic_query"}
    if family == "clarification":
        return {"route_hint": "clarification", "question_type": "field", "subtype": "no_match"}
    return {}


def _semantic_route_family_from_legacy(route_hint: str, question_type: str, subtype: str) -> str:
    if subtype == "structured_query" or (route_hint == "query_products" and question_type in {"filter", "count"}):
        return "structured_query" if subtype == "structured_query" else "generic_query"
    if route_hint == "recommendation" or subtype == "recommendation":
        return "recommendation"
    if route_hint == "unknown_field" or subtype in {"unknown_realtime", "commercial_realtime"}:
        return "unknown_realtime"
    if question_type == "contents_accessories" or subtype in {"contents_accessories", "composition"}:
        return "contents_accessories"
    if route_hint in {"product_detail", "usage_care", "knowledge_base_answer"}:
        return "product_bound_qa"
    if route_hint == "clarification" or subtype == "no_match":
        return "clarification"
    return ""


def _semantic_confidence_parts(value: Any) -> tuple[float, str]:
    label = str(value or "").strip().lower()
    if label in {"low", "medium", "high"}:
        return {"low": 0.35, "medium": 0.65, "high": 0.9}[label], label
    try:
        numeric = max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0, ""
    if numeric >= 0.8:
        label = "high"
    elif numeric >= 0.5:
        label = "medium"
    elif numeric > 0:
        label = "low"
    else:
        label = ""
    return numeric, label


def _validate_semantic_preplan(data: dict[str, Any] | None, *, raw_content: str = "") -> dict[str, Any]:
    if not isinstance(data, dict):
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_json")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    data = dict(data)
    for short_key, long_key in SEMANTIC_PREPLAN_SHORT_KEY_MAP.items():
        if long_key not in data and short_key in data:
            data[long_key] = data[short_key]
    forbidden = sorted(key for key in data if key in SEMANTIC_PREPLAN_FORBIDDEN_KEYS)
    route_family = str(data.get("route_family") or "").strip()
    route_hint = str(data.get("route_hint") or "").strip()
    question_type = str(data.get("question_type") or "").strip()
    defaults = _semantic_route_family_defaults(route_family)
    if defaults:
        route_hint = route_hint or str(defaults.get("route_hint") or "")
        question_type = question_type or str(defaults.get("question_type") or "")
        data["subtype"] = data.get("subtype") or defaults.get("subtype") or ""
        if defaults.get("unknown_field"):
            data["unknown_field"] = True
    confidence, confidence_label = _semantic_confidence_parts(data.get("confidence"))
    if route_hint not in SEMANTIC_PREPLAN_ROUTE_HINTS:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_route_hint")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if question_type not in SEMANTIC_PREPLAN_QUESTION_TYPES:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_question_type")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    entities = [str(item).strip() for item in entities[:8] if str(item or "").strip()]
    field_hint = data.get("field_hint")
    field_hint = str(field_hint).strip() if field_hint is not None and str(field_hint).strip() else None
    subtype = str(data.get("subtype") or "").strip()
    entity_scope = str(data.get("entity_scope") or "").strip()
    field_type = str(data.get("field_type") or "").strip()
    if not route_family:
        route_family = _semantic_route_family_from_legacy(route_hint, question_type, subtype)
    if route_family not in SEMANTIC_PREPLAN_ROUTE_FAMILIES:
        route_family = ""
    if subtype not in SEMANTIC_PREPLAN_SUBTYPES:
        subtype = ""
    if entity_scope not in SEMANTIC_PREPLAN_ENTITY_SCOPES:
        entity_scope = ""
    field_type = customer_field_contract.semantic_preplan_field_type(field_type)
    if field_type not in SEMANTIC_PREPLAN_FIELD_TYPES:
        field_type = ""
    result = _empty_semantic_preplan(called=True)
    result.update(
        {
            "route_family": route_family,
            "route_hint": route_hint,
            "question_type": question_type,
            "entities": entities,
            "field_type": field_type,
            "field_hint": field_hint,
            "subtype": subtype,
            "entity_scope": entity_scope,
            "qa_or_usage_care": bool(data.get("qa_or_usage_care")),
            "unknown_field": bool(data.get("unknown_field")),
            "confidence": max(0.0, min(1.0, confidence)),
            "confidence_label": confidence_label,
            "reason": str(data.get("reason") or "")[:300],
            "raw_preview": _safe_preview(raw_content),
        }
    )
    if forbidden:
        result["fallback_reason"] = "forbidden_keys:" + ",".join(forbidden)
        result["route_hint"] = ""
        result["confidence"] = 0.0
    extra_keys = sorted(key for key in data if key not in SEMANTIC_PREPLAN_ALLOWED_KEYS and key not in SEMANTIC_PREPLAN_FORBIDDEN_KEYS)
    if extra_keys:
        result["fallback_reason"] = "unexpected_keys:" + ",".join(extra_keys[:8])
        result["route_hint"] = ""
        result["confidence"] = 0.0
    return result


def _semantic_preplan_messages(
    *,
    question: str,
    deterministic_plan: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Return only JSON, no markdown. You are a pre-route arbiter only; do not answer and do not judge product facts. "
                "Preferred keys: route_family, entity_scope, field_type, confidence, reason. "
                "route_family enum: structured_query,recommendation,product_bound_qa,unresolved_product_like,negative_product_like,unknown_realtime,contents_accessories,generic_query,clarification. "
                "entity_scope enum: generic_scope,category_scope,product_like,resolved_product,ambiguous_product,unresolved_product,negative_product. "
                "field_type enum: material,category,usage,heat_source,capacity,price,stock,shipping,gift,contents,recommendation,unknown. "
                "confidence enum: low,medium,high. reason must be short debug only. "
                "Never output answer, SKU facts, candidate_skus, recommended_skus, result_skus, price, stock, sales, certification, warranty."
            ),
        },
        {
            "role": "user",
            "content": (
                f"question: {question}\n"
                f"deterministic_primary_intent: {deterministic_plan.get('primary_intent') or ''}\n"
                f"deterministic_answer_type: {deterministic_plan.get('answer_type') or ''}\n"
                f"deterministic_requested_field: {deterministic_plan.get('requested_field') or ''}\n"
                f"deterministic_product_ref: {deterministic_plan.get('product_ref') or ''}\n"
                f"has_conversation_id: {bool(context.get('conversation_id'))}\n"
                f"has_recommendation_context: {bool(context.get('has_recommendation_context'))}\n"
                'JSON shape: {"route_family":"recommendation","entity_scope":"category_scope","field_type":"recommendation","confidence":"high","reason":"short"}'
            ),
        },
    ]


def _semantic_preplan_feature_summary(question: str, deterministic_plan: dict[str, Any], context: dict[str, Any]) -> str:
    text = str(question or "")
    features = {
        "has_conversation": bool(context.get("conversation_id")),
        "has_recommendation_context": bool(context.get("has_recommendation_context")),
        "deterministic_intent": str(deterministic_plan.get("primary_intent") or ""),
        "deterministic_answer_type": str(deterministic_plan.get("answer_type") or ""),
        "mentions_griddle": any(term in text for term in ("烤盘", "煎烤", "煎蛋", "煎培根")),
        "mentions_cookware": any(term in text for term in ("锅", "锅具", "炊具", "煮面", "正餐")),
        "mentions_filter": any(term in text for term in ("有哪些", "哪几", "更偏", "适合", "推荐")),
        "mentions_contents_accessories": customer_agent_service.looks_like_contents_accessories_question(text),
        "mentions_waterware": any(term in text for term in ("水具", "水杯", "水壶", "冷水", "补水", "随身")),
        "mentions_coffee": any(term in text for term in ("咖啡", "咖啡器具", "手冲")),
        "mentions_usage_restriction": any(term in text for term in ("使用限制", "注意事项", "禁忌")),
        "mentions_alternative": any(term in text for term in ("不要刚才那个", "换个", "换一个", "更轻", "更便宜", "还有别的")),
    }
    return "; ".join(f"{key}={str(value).lower()}" for key, value in features.items())


def _question_type_for_route(route_hint: str, feature_summary: str) -> str:
    if "mentions_alternative=true" in feature_summary:
        return "followup"
    if "mentions_contents_accessories=true" in feature_summary:
        return "contents_accessories"
    if route_hint == "comparison":
        return "comparison"
    if route_hint == "query_products":
        if "deterministic_intent=catalog_count" in feature_summary:
            return "count"
        return "filter"
    if route_hint == "usage_care":
        return "usage"
    if route_hint == "product_detail":
        return "field"
    if route_hint == "unknown_field":
        return "unknown_field"
    if route_hint == "recommendation":
        return "recommendation"
    return "recommendation"


def _validate_semantic_preplan_label(content: str, *, feature_summary: str) -> dict[str, Any]:
    label = str(content or "").strip().lower()
    label = re.sub(r"[^a-z_]+", "", label.splitlines()[0] if label else "")
    if label not in SEMANTIC_PREPLAN_ROUTE_HINTS:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_label")
        result["raw_preview"] = _safe_preview(content)
        return result
    question_type = _question_type_for_route(label, feature_summary)
    result = _empty_semantic_preplan(called=True)
    result.update(
        {
            "route_hint": label,
            "question_type": question_type,
            "confidence": 0.72,
            "reason": "semantic label fallback",
            "raw_preview": _safe_preview(content),
        }
    )
    return result


async def _repair_semantic_preplan_output(db, *, question: str, raw_content: str) -> str:
    runtime_settings = _semantic_preplan_runtime_settings()
    return await customer_llm_service.chat_completion(
        db,
        [
            {
                "role": "system",
                "content": (
                    "Return only one compact JSON object with keys route_family, entity_scope, field_type, confidence, reason. "
                    "Classify route only; never answer or output SKU facts/candidates. "
                    "route_family enum: structured_query,recommendation,product_bound_qa,unresolved_product_like,negative_product_like,unknown_realtime,contents_accessories,generic_query,clarification. "
                    "entity_scope enum: generic_scope,category_scope,product_like,resolved_product,ambiguous_product,unresolved_product,negative_product. "
                    "field_type enum: material,category,usage,heat_source,capacity,price,stock,shipping,gift,contents,recommendation,unknown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"question: {question}\n"
                    f"previous_output_preview: {_safe_preview(raw_content, 120)}\n"
                    'JSON shape: {"route_family":"structured_query","entity_scope":"category_scope","field_type":"material","confidence":"high","reason":"short"}'
                ),
            },
        ],
        temperature=runtime_settings["temperature"],
        max_tokens=runtime_settings["max_tokens"],
        purpose="semantic_preplan_repair",
        api_model_override=runtime_settings["model"],
        response_format=runtime_settings["response_format"],
        thinking=runtime_settings["thinking"],
    )


async def _semantic_preplan_label_output(
    db,
    *,
    feature_summary: str,
) -> str:
    runtime_settings = _semantic_preplan_runtime_settings()
    return await customer_llm_service.chat_completion(
        db,
        [
            {
                "role": "system",
                "content": (
                    "Choose exactly one route label. Output only the label token. "
                    "Allowed labels: usage_care, recommendation, product_detail, query_products, "
                    "knowledge_base_answer, comparison, unknown_field, clarification. "
                    "Do not answer the user. Do not output products, SKUs, fields, prices, stock, sales, certification, warranty, or facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"features: {feature_summary}\n"
                    "Rules: griddle+cookware choice => comparison; filter+waterware or filter+coffee => query_products; "
                    "usage_restriction => product_detail; alternative followup => recommendation."
                ),
            },
        ],
        temperature=runtime_settings["temperature"],
        max_tokens=min(runtime_settings["max_tokens"], 256),
        purpose="semantic_preplan_label",
        api_model_override=runtime_settings["model"],
        thinking=runtime_settings["thinking"],
    )


async def plan_customer_question_semantic(
    db,
    question: str,
    deterministic_plan: dict | None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Ask the LLM only for an ambiguous-route hint; never for facts or SKUs."""
    text = str(question or "").strip()
    if not text:
        return _empty_semantic_preplan(fallback_reason="empty_question")
    deterministic_plan = deterministic_plan if isinstance(deterministic_plan, dict) else {}
    context = context if isinstance(context, dict) else {}
    messages = _semantic_preplan_messages(question=text, deterministic_plan=deterministic_plan, context=context)
    feature_summary = _semantic_preplan_feature_summary(text, deterministic_plan, context)
    runtime_settings = _semantic_preplan_runtime_settings()
    llm_call_count = 0
    llm_metadata: dict[str, Any] = {}
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages,
            temperature=runtime_settings["temperature"],
            max_tokens=runtime_settings["max_tokens"],
            purpose="semantic_preplan",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
            metadata=llm_metadata,
        )
        llm_call_count += 1
    except Exception as exc:
        result = _empty_semantic_preplan(called=True, fallback_reason=f"llm_error:{type(exc).__name__}")
        result["error"] = str(exc)[:240]
        _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
        return result
    result = _validate_semantic_preplan(_extract_json_object(content), raw_content=content)
    _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
    if result.get("fallback_reason") == "invalid_json":
        try:
            repaired = await _repair_semantic_preplan_output(db, question=text, raw_content=content)
            llm_call_count += 1
        except Exception as exc:
            result["fallback_reason"] = f"repair_error:{type(exc).__name__}"
            result["error"] = str(exc)[:240]
            result["llm_call_count"] = llm_call_count
            result["llm_call_count_delta"] = llm_call_count
            _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
            return result
        result = _validate_semantic_preplan(_extract_json_object(repaired), raw_content=repaired)
        _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
    if result.get("fallback_reason") == "invalid_json":
        try:
            label_content = await _semantic_preplan_label_output(db, feature_summary=feature_summary)
            llm_call_count += 1
        except Exception as exc:
            result["fallback_reason"] = f"label_error:{type(exc).__name__}"
            result["error"] = str(exc)[:240]
            result["llm_call_count"] = llm_call_count
            result["llm_call_count_delta"] = llm_call_count
            _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
            return result
        result = _validate_semantic_preplan_label(label_content, feature_summary=feature_summary)
        _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
    result["llm_call_count"] = llm_call_count
    result["llm_call_count_delta"] = llm_call_count
    if not result.get("route_hint"):
        result["fallback_reason"] = result.get("fallback_reason") or "empty_route_hint"
    return result


def plan_customer_question(
    question: str,
    *,
    deterministic_intent: str | None = None,
    deterministic_answer_type: str | None = None,
) -> dict[str, Any]:
    text = str(question or "").strip()
    plan = _base_plan()
    plan["raw_question"] = text

    compatibility = _explicit_pan_alcohol_stove_compatibility(text)
    if compatibility:
        plan.update(compatibility)
        return plan

    explicit_heat_source_compatibility = _explicit_product_alcohol_stove_compatibility(text)
    if explicit_heat_source_compatibility:
        plan.update(explicit_heat_source_compatibility)
        return plan

    compare_refs = _extract_compare_product_refs(text)
    if _is_compare_question(text) and not _is_generic_category_compare_recommendation(text, compare_refs):
        products = compare_refs
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
    if requested_field and product_ref and _supports_field_only_plan(text, requested_field):
        explicit_sku = _extract_explicit_sku(text)
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
                "sku": explicit_sku if explicit_sku == product_ref else "",
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


def _explicit_product_alcohol_stove_compatibility(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    lowered = value.lower()
    has_alcohol_stove = "酒精炉" in value or "alcohol stove" in lowered
    has_compatibility = any(term in value for term in ("能不能用", "能否使用", "是否支持", "支不支持", "可不可以放", "可以用", "适用", "兼容"))
    if not (has_alcohol_stove and has_compatibility):
        return None
    product_ref = _explicit_heat_source_product_ref(value)
    if not product_ref:
        return None
    explicit_sku = _extract_explicit_sku(value)
    return {
        "primary_intent": "product_field",
        "answer_type": "product_detail",
        "product_ref": product_ref,
        "sku": explicit_sku or "",
        "requested_field": "heat_source",
        "field_only": True,
        "explicit_product_or_category": True,
        "must_not_recommend_other_categories": True,
        "confidence": "high",
        "tasks": [{"type": "product_field", "product_ref": product_ref, "requested_field": "heat_source"}],
    }


def _explicit_heat_source_product_ref(text: str) -> str:
    value = str(text or "").strip()
    explicit_sku = _extract_explicit_sku(value)
    if explicit_sku:
        return explicit_sku
    generic_refs = {"锅", "锅具", "套锅", "单锅", "炊具", "产品", "它", "这个", "这款", "刚才那个"}
    for marker in ("能不能用", "能否使用", "是否支持", "支不支持", "可不可以放", "可以用", "适用", "兼容"):
        idx = value.find(marker)
        if idx <= 0:
            continue
        candidate = _clean_product_ref_fragment(value[:idx])
        if candidate and candidate not in generic_refs:
            return candidate
    return ""


def _extract_explicit_sku(text: str) -> str:
    value = str(text or "").strip()
    clean_patterns = (
        re.compile(r"^[A-Z]{1,6}[A-Z0-9]{0,12}(?:-[A-Z0-9]{1,24})+(?:[(（][A-Z0-9]{1,24}[)）])?$"),
        re.compile(r"^[A-Z]{1,6}[A-Z0-9]{0,12}(?:-[A-Z0-9]{1,24})*-[\u4e00-\u9fff]$"),
        re.compile(r"^[A-Z]{1,6}\d{2,12}[A-Z0-9]{0,12}$"),
    )
    for candidate in customer_agent_service._extract_skus(value):
        normalized = str(candidate or "").strip().upper().replace("_", "-")
        if normalized and any(pattern.fullmatch(normalized) for pattern in clean_patterns):
            return normalized
    for pattern in (EXPLICIT_SKU_RE, PLAIN_EXPLICIT_SKU_RE):
        sku_match = pattern.search(value)
        if sku_match:
            return sku_match.group(0).upper().replace("_", "-")
    for pattern in (SKU_PREFIX_RE, PLAIN_SKU_PREFIX_RE):
        sku_match = pattern.search(value)
        if sku_match:
            return sku_match.group(0).upper().replace("_", "-")
    return ""


def _is_compare_question(text: str) -> bool:
    if _looks_like_context_ordinal_reference(text):
        return False
    if len(_extract_compare_product_refs(text)) < 2:
        return False
    if "vs" in text.lower() or "VS" in text:
        return True
    if "和" not in text:
        return False
    return any(term in text for term in ("区别", "不同", "对比", "比较", "哪个", "哪款", "更适合", "该买", "应该买", "买哪个"))


def _is_compare_choice_question(text: str) -> bool:
    return (
        _is_compare_question(text)
        and any(term in text for term in ("选哪个", "应该选", "应该买", "买哪个", "更适合", "选哪", "该买"))
    )


def _is_generic_category_compare_recommendation(text: str, refs: list[str] | None = None) -> bool:
    products = [str(item or "").strip() for item in (refs or _extract_compare_product_refs(text))]
    generic_categories = {"锅具", "套锅", "单锅", "炊具", "炉具", "炉子", "烤盘", "煎盘", "水具", "水壶"}
    if len(products) < 2 or not all(item in generic_categories for item in products[:2]):
        return False
    return _looks_like_scenario_selection_question(text) or _looks_like_scenario_statement_recommendation(text)


def _extract_compare_product_refs(text: str) -> list[str]:
    products: list[str] = []
    sku_refs = re.findall(r"\b[A-Za-z]{1,6}[-_][A-Za-z0-9][A-Za-z0-9_-]{1,40}\b", text)
    if len(sku_refs) >= 2:
        return [item.upper().replace("_", "-") for item in sku_refs[:2]]
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
        or any(term in text for term in ("有哪些", "都有哪些", "列一下", "产品有哪些", "产品列表", "有多少个", "多少个", "分别是什么"))
    )


def _catalog_product_ref(text: str) -> str:
    if "配件" in text:
        return "配件"
    if "炉具" in text or "炉子" in text:
        return "炉具"
    if "餐具" in text:
        return "餐具"
    if "水具" in text:
        return "水具"
    if "桌椅" in text:
        return "桌椅"
    if "咖啡器具" in text or "咖啡" in text:
        return "咖啡器具"
    if "茶具" in text:
        return "茶具"
    if any(term in text for term in ("天幕", "地垫", "帐篷")):
        return "天幕/地垫/帐篷"
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
    if any(term in text for term in ("适合几个人", "适合几人", "几个人", "几人使用", "多少人", "人数", "适用人数")):
        return "适用人数"
    if any(term in text for term in ("适合什么场景", "适合哪些场景", "适合露营用", "适用人群", "干嘛用")):
        return "适用场景"
    if any(term in text for term in ("酒精炉", "明火", "热源", "燃料", "能不能用", "能否用", "可以用", "支持")):
        return "热源"
    return ""


def _field_product_ref(text: str, requested_field: str) -> str:
    if not requested_field:
        return ""
    explicit_sku = _extract_explicit_sku(text)
    if explicit_sku:
        return explicit_sku
    for suffix in ("尺寸是什么", "多大", "规格是什么", "直径是多少", "容量是多少", "重量是多少", "材质是什么", "尺寸", "规格", "直径", "容量", "重量", "材质"):
        idx = text.find(suffix)
        if idx > 0:
            return _clean_product_ref_fragment(text[:idx])
    return ""


def _supports_field_only_plan(text: str, requested_field: str) -> bool:
    value = str(text or "").strip()
    field = str(requested_field or "").strip()
    if not value or not field:
        return False
    if _is_recommendation_question(value) or _looks_like_scenario_statement_recommendation(value):
        return False
    extra_detail_signals = {
        "\u6750\u8d28": (
            "\u7c98\u9505",
            "\u4e0d\u7c98",
            "\u4e0d\u6cbe",
            "\u6d82\u5c42",
            "\u51b7\u6c34",
            "\u70ed\u6c34",
            "\u6c34\u6e29",
        ),
        "\u5bb9\u91cf": (
            "\u51b7\u6c34",
            "\u70ed\u6c34",
            "\u6c34\u6e29",
            "\u6750\u8d28",
            "\u7c98\u9505",
            "\u4e0d\u7c98",
            "\u4e0d\u6cbe",
            "\u6d82\u5c42",
        ),
        "\u91cd\u91cf": (
            "\u51b7\u6c34",
            "\u70ed\u6c34",
            "\u6c34\u6e29",
            "\u6750\u8d28",
            "\u5bb9\u91cf",
            "\u7c98\u9505",
            "\u4e0d\u7c98",
        ),
        "\u5c3a\u5bf8": (
            "\u51b7\u6c34",
            "\u70ed\u6c34",
            "\u6c34\u6e29",
            "\u6750\u8d28",
            "\u5bb9\u91cf",
            "\u7c98\u9505",
            "\u4e0d\u7c98",
        ),
    }
    if any(signal in value for signal in extra_detail_signals.get(field, ())):
        return False
    if value.count("\uFF1F") + value.count("?") >= 2:
        return False
    return True


def _clean_product_ref_fragment(value: str) -> str:
    text = str(value or "").strip("「」 ？?。,.，")
    for prefix in ("你们那个", "你们的", "那个", "这款", "这个"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for suffix in ("到底", "具体", "大概", "请问"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    text = _strip_trailing_question_phrase(text)
    return text.strip("「」 ？?。,.，")


def _strip_trailing_question_phrase(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    trailing_patterns = (
        r"(?:是|为)?(?:什么|啥|哪种|哪些)$",
        r"(?:可不可以|可以|能不能|能否|是否)(?:装|用|支持).{0,12}$",
        r"(?:会不会|是不是).{0,12}$",
    )
    for pattern in trailing_patterns:
        value = re.sub(pattern, "", value).strip()
    return value


def _is_recommendation_question(text: str) -> bool:
    if _looks_like_context_ordinal_reference(text):
        return False
    if _looks_like_scenario_selection_question(text) or _looks_like_scenario_statement_recommendation(text):
        return True
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


def _looks_like_scenario_selection_question(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.search(r"\b[A-Za-z]{1,6}[-_][A-Za-z0-9][A-Za-z0-9_-]{1,40}\b", value):
        return False
    choice_terms = ("推荐", "推荐哪个", "选哪个", "怎么选", "该选哪个", "先买哪类", "先买哪个", "更适合哪个")
    product_terms = ("锅", "锅具", "套锅", "单锅", "炉", "炉具", "烤盘", "水壶", "餐具", "套装")
    scene_terms = ("家庭", "团建", "露营", "轻露营", "野餐", "徒步", "火锅", "烧烤", "带孩子", "公园")
    constraint_terms = ("轻一点", "轻量", "轻便", "好收纳", "收纳", "稳一点", "稳定", "容量大", "容量优先", "预算", "别太难清理", "别太单薄")
    explicit_choice = (
        any(term in value for term in choice_terms)
        and any(term in value for term in product_terms)
        and (
            any(term in value for term in scene_terms)
            or any(term in value for term in constraint_terms)
        )
    )
    if explicit_choice:
        return True
    desire_terms = ("希望", "想", "想要", "适合")
    people_terms = ("两个人", "两人", "双人", "一个人", "单人", "家庭")
    return (
        any(term in value for term in desire_terms)
        and any(term in value for term in product_terms)
        and any(term in value for term in scene_terms)
        and any(term in value for term in constraint_terms)
        and any(term in value for term in people_terms)
    )


def _looks_like_scenario_statement_recommendation(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if EXPLICIT_SKU_RE.search(value):
        return False
    product_terms = ("锅", "锅具", "套锅", "单锅", "炊具", "炉具", "炉子", "烤盘")
    cooking_terms = ("正餐", "做正餐", "烧水", "做简单餐食", "煎东西", "火锅")
    scene_terms = ("家庭", "周末", "近郊", "露营", "徒步", "自驾", "公园", "营地", "野餐", "烧烤", "早餐", "正餐")
    people_terms = ("一个人", "单人", "两个人", "两人", "双人", "三口之家", "三个人", "四五个", "多人", "家庭", "带孩子", "新手", "女生")
    constraint_terms = (
        "容量", "稳", "稳定", "收纳", "轻", "轻量", "轻便", "别太重", "别太小", "别太差", "别太难清理",
        "烧水", "做简单餐食", "做正餐", "煎东西", "更看重", "好上手", "最值", "怎么搭", "更合适",
    )
    if not any(term in value for term in product_terms) and not any(term in value for term in cooking_terms):
        return False
    if not any(term in value for term in scene_terms):
        return False
    constraint_hits = sum(1 for term in constraint_terms if term in value)
    if any(term in value for term in people_terms) and constraint_hits >= 1:
        return True
    if constraint_hits >= 2:
        return True
    if any(term in value for term in ("怎么搭", "更合适", "先买哪类", "先买哪个", "最值")) and any(term in value for term in ("炉具", "炉子", "烤盘")):
        return True
    return False


def _looks_like_context_ordinal_reference(text: str) -> bool:
    return (
        any(term in text for term in ("刚才", "前面", "上面"))
        and any(term in text for term in ("第一个", "第一款"))
        and any(term in text for term in ("第二个", "第二款"))
    )


def _has_two_person_signal(text: str) -> bool:
    return any(term in text for term in ("两个人", "2人", "两人", "二人"))
