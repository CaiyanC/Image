from __future__ import annotations

import asyncio
import json
import re

import httpx
from typing import Any
from ..core.config import settings
from ..models.product import Product
from . import (
    customer_agent_service,
    customer_field_contract,
    customer_llm_service,
    customer_recommendation_verification_contract,
)


def _is_retryable_semantic_preplan_error(exc: Exception) -> bool:
    """Allow one retry for pure semantic-planning transport failures only.

    Semantic preplanning is side-effect free: retrying cannot duplicate an
    order, mutate a conversation, or manufacture product facts.  Configuration
    and validation errors deliberately remain fail-closed.
    """
    if isinstance(exc, (TimeoutError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
        return status_code == 429 or status_code >= 500
    return isinstance(exc, RuntimeError) and "当前请求较多" in str(exc)


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
    "navigation",
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
    "navigation",
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
    "comparison",
    "product_bound_qa",
    "unresolved_product_like",
    "negative_product_like",
    "unknown_realtime",
    "contents_accessories",
    "generic_query",
    "knowledge_base_meta",
    "clarification",
    "product_navigation",
}
SEMANTIC_PREPLAN_INFORMATION_SCOPES = {"", "knowledge_base_meta"}
SEMANTIC_PREPLAN_FIELD_TYPES = {
    "",
    "recommendation",
    "unknown",
} | set(customer_field_contract.FORMAL_DETAIL_FIELDS)
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
    "recommendation_constraints",
    "structured_query_constraints",
    "unrepresented_recommendation_requirements",
    "recommendation_soft_preferences",
    "recommendation_followup_action",
    "information_scope",
    "subject_text", "canonical_fields", "ambiguity", "evidence_required", "evidence_kind", "qa_evidence_query", "context_usage", "decision_requested", "reasoning_summary",
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
        "subject_text": "",
        "canonical_fields": [],
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "",
        "qa_evidence_query": "",
        "context_usage": "none",
        "decision_requested": False,
        "information_scope": "",
        "recommendation_constraints": {},
        "structured_query_constraints": [],
        "unrepresented_recommendation_requirements": [],
        "recommendation_soft_preferences": [],
        "reasoning_summary": "",
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
    if family == "comparison":
        return {"route_hint": "comparison", "question_type": "comparison", "subtype": "relation_comparison"}
    if family == "product_bound_qa":
        return {"route_hint": "product_detail", "question_type": "field", "subtype": "known_detail"}
    if family == "product_navigation":
        return {"route_hint": "product_detail", "question_type": "navigation", "subtype": "navigation"}
    if family in {"unresolved_product_like", "negative_product_like"}:
        return {"route_hint": "clarification", "question_type": "field", "subtype": "no_match"}
    if family == "unknown_realtime":
        return {"route_hint": "unknown_field", "question_type": "unknown_field", "subtype": "unknown_realtime", "unknown_field": True}
    if family == "contents_accessories":
        return {"route_hint": "product_detail", "question_type": "contents_accessories", "subtype": "contents_accessories"}
    if family == "generic_query":
        return {"route_hint": "query_products", "question_type": "filter", "subtype": "generic_query"}
    if family == "knowledge_base_meta":
        return {"route_hint": "clarification", "question_type": "field", "subtype": "no_match"}
    if family == "clarification":
        return {"route_hint": "clarification", "question_type": "field", "subtype": "no_match"}
    return {}


def _semantic_route_family_from_legacy(route_hint: str, question_type: str, subtype: str) -> str:
    if subtype == "structured_query" or (route_hint == "query_products" and question_type in {"filter", "count"}):
        return "structured_query" if subtype == "structured_query" else "generic_query"
    if route_hint == "recommendation" or subtype == "recommendation":
        return "recommendation"
    if route_hint == "comparison" or question_type == "comparison" or subtype == "relation_comparison":
        return "comparison"
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


def _validated_recommendation_constraints(value: Any) -> dict[str, Any] | None:
    """Accept only abstract, allowlisted recommendation preferences.

    The semantic model may describe *what* the customer needs, never a product,
    SKU, candidate list, database value, or answer.  Keeping this schema small
    makes the later database verification contract the sole source of facts.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    allowed = {"subject_kind", "people", "heat_sources", "scenarios", "weight_preference", "price_preference", "storage_preference"}
    if any(key not in allowed for key in value):
        return None
    result: dict[str, Any] = {}
    subject_kind = value.get("subject_kind")
    if subject_kind is not None:
        if subject_kind not in {"cookware", "waterware", "stove"}:
            return None
        result["subject_kind"] = subject_kind
    people = value.get("people")
    if people == {}:
        people = None
    if people is not None:
        if not isinstance(people, dict) or set(people) != {"min", "max"}:
            return None
        lower, upper = people.get("min"), people.get("max")
        if type(lower) is not int or type(upper) is not int or not (1 <= lower <= upper <= 99):
            return None
        result["people"] = {"min": lower, "max": upper}
    heat_sources = value.get("heat_sources")
    if heat_sources == []:
        heat_sources = None
    if heat_sources is not None:
        allowed_heat = {"card_stove", "gas_stove", "alcohol_stove", "open_flame", "induction"}
        if not isinstance(heat_sources, list) or not heat_sources or len(heat_sources) > 5:
            return None
        if any(item not in allowed_heat for item in heat_sources):
            return None
        result["heat_sources"] = list(dict.fromkeys(heat_sources))
    scenarios = value.get("scenarios")
    if scenarios is not None:
        allowed_scenarios = {"camping", "hiking", "self_drive", "seaside", "soup"}
        if not isinstance(scenarios, list) or not scenarios or len(scenarios) > 5:
            return None
        if any(item not in allowed_scenarios for item in scenarios):
            return None
        result["scenarios"] = list(dict.fromkeys(scenarios))
    weight_preference = value.get("weight_preference")
    if weight_preference is not None:
        if weight_preference not in {"lightweight"}:
            return None
        result["weight_preference"] = weight_preference
    price_preference = value.get("price_preference")
    if price_preference is not None:
        if price_preference not in {"affordable", "premium"}:
            return None
        result["price_preference"] = price_preference
    storage_preference = value.get("storage_preference")
    if storage_preference is not None:
        if storage_preference != "compact_storage":
            return None
        result["storage_preference"] = storage_preference
    return result


def _validated_recommendation_constraint_subset(value: Any) -> dict[str, Any] | None:
    """Keep only independently valid allowlisted semantic constraint entries.

    This is used solely after the semantic schema-repair call has also
    preserved a literal unrepresented requirement. It does not infer a value
    or substitute one enum for another; it prevents a malformed extra entry
    from erasing a separately valid semantic constraint before the caller
    fail-closes on the preserved requirement.
    """
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        validated = _validated_recommendation_constraints({key: item})
        if validated:
            result.update(validated)
    return result or None


def _validated_unrepresented_recommendation_requirements(value: Any) -> list[str] | None:
    """Keep material semantic needs that have no current verification dimension.

    These are not product facts or candidate constraints.  The semantic layer
    identifies them so later execution can fail closed rather than silently
    broadening a recommendation; deterministic code only validates shape.
    """
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 5:
        return None
    items = [str(item or "").strip() for item in value]
    if any(not item or len(item) > 80 for item in items):
        return None
    return list(dict.fromkeys(items))


def _validated_recommendation_soft_preferences(value: Any) -> list[str] | None:
    """Validate literal non-eligibility priorities supplied by semantic preplan.

    This is intentionally only a shape and literal-span boundary.  It does not
    decide whether words such as "new to camping" or "compact" are soft: the
    semantic preplan makes that sentence-level judgement.  Consumers may pass
    these phrases to the evidence-bound narrator, but must never use them to
    assert a product fact or to filter candidates.
    """
    return _validated_unrepresented_recommendation_requirements(value)


_SEMANTIC_STRUCTURED_QUERY_OPERATORS = {
    "material": {"contains"},
    "capacity": {">=", ">", "<=", "<", "=", "between"},
    "weight": {">=", ">", "<=", "<", "=", "between"},
    "dimensions": {"contains", "="},
    "people": {">=", ">", "<=", "<", "=", "between"},
    "color": {"contains", "="},
    "heat_source": {"supports", "not_supports"},
    "usage_scene": {"contains"},
    "waterproof": {"="},
}


def _validated_structured_query_constraints(
    value: Any,
    *,
    allow_empty_category_scope: bool = False,
) -> list[dict[str, Any]] | None:
    """Validate semantic predicate structure without accepting product facts.

    The values remain provisional customer-language spans.  The structured
    contract adapter later proves each span occurs in the original question,
    then evaluates it against a product's own database columns.
    """
    if value is None:
        return []
    if value == [] and allow_empty_category_scope:
        return []
    if not isinstance(value, list) or not (1 <= len(value) <= 4):
        return None
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"field", "operator", "value", "evidence_span", "unit"}:
            return None
        field = customer_field_contract.semantic_preplan_field_type(item.get("field"))
        operator = str(item.get("operator") or "").strip()
        evidence_span = str(item.get("evidence_span") or "").strip()
        raw_value = item.get("value")
        unit = item.get("unit")
        if (
            field not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS
            or operator not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS[field]
            or not evidence_span
            or len(evidence_span) > 80
            or EXPLICIT_SKU_RE.search(evidence_span)
            or PLAIN_EXPLICIT_SKU_RE.search(evidence_span)
        ):
            return None
        if isinstance(raw_value, str):
            normalized_value: Any = raw_value.strip()
            if not normalized_value or len(normalized_value) > 80:
                return None
        elif type(raw_value) in {int, float}:
            normalized_value = raw_value
        elif isinstance(raw_value, list) and operator == "between" and len(raw_value) == 2 and all(type(part) in {int, float} for part in raw_value):
            normalized_value = list(raw_value)
        elif field == "waterproof" and raw_value is True:
            normalized_value = True
        else:
            return None
        # Textual predicates are not a normalization channel.  The value may
        # be the literal object inside a longer verb phrase (for example,
        # ``明火`` in ``支持明火``), but it must remain a verbatim substring of
        # the quoted customer span.  Numeric predicates retain the existing
        # typed evaluator.
        if (
            field in {"material", "dimensions", "color", "heat_source", "usage_scene"}
            and normalized_value not in evidence_span
        ):
            return None
        if unit is not None and (not isinstance(unit, str) or len(unit.strip()) > 12):
            return None
        normalized_unit = unit.strip() if isinstance(unit, str) else None
        normalized = {
            "field": field,
            "operator": operator,
            "value": normalized_value,
            "evidence_span": evidence_span,
            "unit": normalized_unit,
        }
        if normalized not in result:
            result.append(normalized)
    return result


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
    information_scope = str(data.get("information_scope") or "").strip()
    field_type = str(data.get("field_type") or "").strip()
    if not route_family:
        route_family = _semantic_route_family_from_legacy(route_hint, question_type, subtype)
    if route_family not in SEMANTIC_PREPLAN_ROUTE_FAMILIES:
        route_family = ""
    if subtype not in SEMANTIC_PREPLAN_SUBTYPES:
        subtype = ""
    if entity_scope not in SEMANTIC_PREPLAN_ENTITY_SCOPES:
        entity_scope = ""
    if information_scope not in SEMANTIC_PREPLAN_INFORMATION_SCOPES:
        information_scope = ""
    field_type = customer_field_contract.semantic_preplan_field_type(field_type)
    field_hint = customer_field_contract.semantic_preplan_field_type(field_hint) if field_hint else None
    if field_type not in SEMANTIC_PREPLAN_FIELD_TYPES:
        field_type = ""
    canonical_fields = data.get("canonical_fields") if isinstance(data.get("canonical_fields"), list) else []
    canonical_fields = [customer_field_contract.semantic_preplan_field_type(item) for item in canonical_fields]
    canonical_fields = list(dict.fromkeys(item for item in canonical_fields if item in SEMANTIC_PREPLAN_FIELD_TYPES and item))
    raw_evidence_kind = str(data.get("evidence_kind") or "").strip()
    # Backward-compatible semantic shape: before ``evidence_kind`` became a
    # required key, a product-bound plan with no canonical field was already
    # the model's only way to say “use same-SKU QA”.  Preserve that semantic
    # decision rather than allowing aliases to reclassify it as a column.
    evidence_kind = raw_evidence_kind or (
        "product_qa"
        if route_family == "product_bound_qa" and not canonical_fields and not field_type and not field_hint
        else "structured_field"
    )
    if evidence_kind not in {"structured_field", "product_qa"}:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_evidence_kind")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # ``product_qa`` is a semantic decision that the customer asks for a
    # product-specific capability, judgement, or procedure for which the
    # authoritative source is same-SKU QA rather than a structured column.
    # It intentionally clears compatibility mirrors as well: otherwise a
    # keyword/alias from the question would silently recreate the very field
    # the model rejected.  Identity and QA evidence are sealed downstream.
    if evidence_kind == "product_qa":
        if route_family not in {"product_bound_qa", "comparison"}:
            result = _empty_semantic_preplan(called=True, fallback_reason="product_qa_outside_product_bound_route")
            result["raw_preview"] = _safe_preview(raw_content)
            return result
        canonical_fields = []
        field_type = ""
        field_hint = None
    qa_evidence_query = str(data.get("qa_evidence_query") or "").strip()[:160]
    if evidence_kind != "product_qa":
        qa_evidence_query = ""
    # A navigation turn changes only the active product subject.  It must not
    # manufacture a field merely because a model guesses an overview default.
    if route_family == "product_navigation":
        field_type = ""
        field_hint = None
        canonical_fields = []
    # canonical_fields is the public structured semantic result.  Some
    # constrained providers correctly emit that required field while omitting
    # the old compatibility mirrors.  A single allowlisted canonical field is
    # sufficient to reconstruct those mirrors; this does not accept any
    # identity or fact from the semantic response.
    if not field_type and len(canonical_fields) == 1:
        field_type = canonical_fields[0]
    if not field_hint and field_type:
        field_hint = field_type
    if not canonical_fields and field_type:
        canonical_fields = [field_type]
    # A pairwise decision must name the single formal criterion that makes one
    # participant more suitable. Empty fields leave the comparison executor no
    # evidence policy to apply, so repair the semantic plan instead of asking a
    # legacy clarification after both entities have already been resolved.
    if (
        route_family == "comparison"
        and len(entities) >= 2
        and not canonical_fields
        and evidence_kind != "product_qa"
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="missing_comparison_decision_criterion")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # Route labels (for example ``recommendation``) are not comparison
    # dimensions.  A named-product comparison must contain only formal fields
    # before later evidence can be sealed.  Returning this to the same
    # semantic repair pass keeps the model responsible for its whole-sentence
    # criterion; otherwise a legacy alias in a product name could substitute a
    # different field.
    if (
        route_family == "comparison"
        and evidence_kind != "product_qa"
        and any(field not in customer_field_contract.FORMAL_DETAIL_FIELDS for field in canonical_fields)
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_comparison_decision_criterion")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A preplan that itself extracts two participants and a requested choice
    # cannot coherently route to a single-product fact. Ask semantic repair to
    # resolve this internal contradiction before any legacy executor sees it.
    if (
        len(entities) >= 2
        and bool(data.get("decision_requested"))
        # Pairwise recommendation is a valid semantic family: the later
        # sealed comparison adapter turns it into multi-entity execution.
        # Only a single-product/detail family is internally contradictory.
        and route_family not in {"comparison", "recommendation"}
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="self_conflicting_pairwise_decision_route")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A factual request about two explicitly named products is comparison work
    # too.  A catalogue structured query has filters over a product set; it
    # cannot carry independent entity contracts for two named participants.
    # Reject the invalid semantic shape and let the same semantic repair pass
    # preserve the requested field with decision_requested=false.
    if len(entities) >= 2 and route_family == "structured_query":
        result = _empty_semantic_preplan(called=True, fallback_reason="pairwise_factual_requires_comparison_contract")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A request to choose between two named products is comparison work even
    # when the semantic model initially labels it recommendation.  The model
    # still owns the criterion; this merely rejects the internally inconsistent
    # route shape so the same semantic repair pass can express that criterion
    # through the comparison contract before any recommendation executor sees
    # the participants.
    if (
        route_family == "recommendation"
        and len(entities) >= 2
        and bool(data.get("decision_requested"))
    ):
        result = _empty_semantic_preplan(
            called=True,
            fallback_reason="pairwise_recommendation_requires_comparison_contract",
        )
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if route_family == "comparison" and len(entities) < 2 and not forbidden:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_comparison_participants")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # Some constrained-model responses place the public top-level
    # ``unrepresented_recommendation_requirements`` key inside the adjacent
    # constraints object.  This is a structural placement error, not a cue to
    # infer a requirement from wording: move only that exact model-supplied
    # key, only when no top-level value exists, then run the ordinary strict
    # schemas below.  Any other unknown constraint key remains invalid.
    raw_constraints = data.get("recommendation_constraints")
    if (
        isinstance(raw_constraints, dict)
        and "unrepresented_recommendation_requirements" in raw_constraints
        and "unrepresented_recommendation_requirements" not in data
    ):
        data = dict(data)
        raw_constraints = dict(raw_constraints)
        data["unrepresented_recommendation_requirements"] = raw_constraints.pop(
            "unrepresented_recommendation_requirements"
        )
        data["recommendation_constraints"] = raw_constraints
    recommendation_constraints = _validated_recommendation_constraints(data.get("recommendation_constraints"))
    structured_query_constraints = _validated_structured_query_constraints(
        data.get("structured_query_constraints"),
        allow_empty_category_scope=(
            route_family == "structured_query"
            and not entities
            and set(canonical_fields) == {"category"}
        ),
    )
    unrepresented_requirements = _validated_unrepresented_recommendation_requirements(
        data.get("unrepresented_recommendation_requirements")
    )
    soft_preferences = _validated_recommendation_soft_preferences(
        data.get("recommendation_soft_preferences")
    )
    if recommendation_constraints is None:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_recommendation_constraints")
        # The model has already classified this turn as a recommendation, but
        # its optional constraint schema is unusable.  Preserve that narrow
        # provenance so the caller can fail closed instead of handing the
        # request to a lexical recommendation fallback.  This is not a
        # customer constraint and must never select a catalogue candidate.
        if route_family == "recommendation":
            result["semantic_route_family_hint"] = "recommendation"
            result["semantic_confidence_hint"] = confidence
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if structured_query_constraints is None:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_structured_query_constraints")
        if route_family == "structured_query":
            # Preserve only route provenance.  The executor must fail closed
            # rather than let a legacy one-condition parser reinterpret this
            # malformed multi-condition semantic plan.
            result["semantic_route_family_hint"] = "structured_query"
            result["semantic_confidence_hint"] = confidence
            # A malformed filter predicate does not invalidate the model's
            # independent recognition of one formal field and its textual
            # subject.  Preserve that candidate for the service layer to
            # validate against an EntityResolutionContract; it cannot select
            # an SKU, evidence, or answer on its own.
            subject_text = str(data.get("subject_text") or "").strip()
            if (
                subject_text
                and len(canonical_fields) == 1
                and canonical_fields[0] in customer_field_contract.FORMAL_DETAIL_FIELDS
                and confidence >= 0.9
            ):
                result["invalid_structured_query_named_detail_candidate"] = {
                    "subject_text": subject_text[:200],
                    "canonical_fields": list(canonical_fields),
                    "confidence": confidence,
                }
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if unrepresented_requirements is None:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_unrepresented_recommendation_requirements")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if soft_preferences is None:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_recommendation_soft_preferences")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if recommendation_constraints and route_family != "recommendation":
        result = _empty_semantic_preplan(called=True, fallback_reason="recommendation_constraints_outside_recommendation")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if structured_query_constraints and route_family != "structured_query":
        result = _empty_semantic_preplan(called=True, fallback_reason="structured_query_constraints_outside_structured_query")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if structured_query_constraints and not set(item["field"] for item in structured_query_constraints).issubset(set(canonical_fields)):
        result = _empty_semantic_preplan(called=True, fallback_reason="structured_query_constraints_field_mismatch")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A semantic plan may preserve a named product and its formal record field
    # while accidentally selecting the broad catalogue-query route because the
    # wording asks "which" comparable items.  A non-filter field has no
    # executable structured predicate by design.  Treat that route/schema
    # contradiction as repairable semantic output; do not let a legacy product
    # query reinterpret the name as a missing category.
    if (
        route_family == "structured_query"
        # The semantic schema permits a named product to be carried in
        # subject_text without duplicating it in entities.  That is still a
        # named-product field request, so it must receive the same repair as
        # an explicit entity list rather than falling to the old catalogue
        # executor.
        and (entities or str(data.get("subject_text") or "").strip())
        and canonical_fields
        and any(field not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS for field in canonical_fields)
        # A value-grounded catalogue field (for example a stored series name)
        # is a filter subject, not a named product.  The semantic planner must
        # still choose this route; the executor later verifies the actual DB
        # value before returning any rows.
        and not (
            not entities
            and set(canonical_fields).issubset({"series", "brand", "category", "product_level"})
        )
    ):
        result = _empty_semantic_preplan(
            called=True,
            fallback_reason="named_nonfilter_field_in_structured_query",
        )
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A high-confidence semantic filter with multiple formal fields is not
    # executable until every requested dimension has a literal predicate.
    # Returning it to semantic repair keeps meaning ownership with the LLM;
    # allowing an older one-field parser to execute here would silently widen
    # the customer's request.
    if (
        route_family == "structured_query"
        and route_hint == "query_products"
        and question_type == "filter"
        and subtype == "structured_query"
        and confidence >= 0.9
        and len(canonical_fields) >= 2
        and len(structured_query_constraints) < 2
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="missing_structured_query_constraints")
        result["semantic_route_family_hint"] = "structured_query"
        result["semantic_confidence_hint"] = confidence
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    recommendation_followup_action = str(data.get("recommendation_followup_action") or "").strip()
    if recommendation_followup_action not in {"", "alternative"}:
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_recommendation_followup_action")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if recommendation_followup_action and route_family != "recommendation":
        result = _empty_semantic_preplan(called=True, fallback_reason="recommendation_followup_action_outside_recommendation")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    result = _empty_semantic_preplan(called=True)
    result.update(
        {
            "route_family": route_family,
            "route_hint": route_hint,
            "question_type": question_type,
            "entities": entities,
            "field_type": field_type,
            "canonical_fields": canonical_fields,
            "subject_text": str(data.get("subject_text") or "").strip()[:200],
            "ambiguity": bool(data.get("ambiguity")),
            "evidence_required": bool(data.get("evidence_required", True)),
            "evidence_kind": evidence_kind,
            "qa_evidence_query": qa_evidence_query,
            "context_usage": str(data.get("context_usage") or "none").strip()[:40],
            "decision_requested": bool(data.get("decision_requested")),
            "information_scope": information_scope,
            "recommendation_constraints": recommendation_constraints,
            "structured_query_constraints": structured_query_constraints,
            "unrepresented_recommendation_requirements": unrepresented_requirements,
            "recommendation_soft_preferences": soft_preferences,
            "recommendation_followup_action": recommendation_followup_action,
            "reasoning_summary": str(data.get("reasoning_summary") or data.get("reason") or "").strip()[:300],
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
                "Required keys: route_family, entities, subject_text, canonical_fields, confidence, ambiguity, evidence_required, evidence_kind, qa_evidence_query, context_usage, decision_requested, information_scope, reasoning_summary. "
            "For route_family=recommendation, optionally add recommendation_constraints with only these abstract keys: subject_kind (cookware|waterware|stove), people ({min,max} positive integers), heat_sources (card_stove|gas_stove|alcohol_stove|open_flame|induction), scenarios (camping|hiking|self_drive|seaside|soup), weight_preference (lightweight), price_preference (affordable|premium), storage_preference (compact_storage). Every explicit cardinality or group-size expression is an independent people condition, including written or numeric one-person, two-person, three-person, family, or group wording; retain it even when the same sentence also names a scenario, heat source, or product kind. Heat-source codes are exact ontology values: card_stove=卡式炉, gas_stove=燃气炉, alcohol_stove=酒精炉, open_flame=明火, induction=电磁炉. Do not substitute one code for another. storage_preference=compact_storage is only for an explicit desire for compact storage, nesting, folding, or taking little packing space; it is a soft preference, never a hard eligibility condition. Classify every non-ontology customer expression by its meaning in the whole question. Do not assume it is already satisfied because it sounds typical for the requested product category or because a later writer might find related content. Put an unmet must-have eligibility condition in unrepresented_recommendation_requirements, but put every non-binding desire, use-context, or decision framing in recommendation_soft_preferences. A descriptive preference introduced as a wish, preference, or choice framing is non-binding unless the customer explicitly makes it non-negotiable (for example, must, only, cannot accept, or equivalent force); do not upgrade it to an unmet hard requirement merely because the current ontology has no key. Both arrays contain at most five exact literal customer phrases; never silently omit or paraphrase them. A phrase represented by a formal constraint must not also be copied into recommendation_soft_preferences. Soft preferences never prove a product fact and do not filter candidates. Never include product names, SKUs, candidates, database values, reasons about a particular product, or an answer in recommendation_constraints. "
                "For route_family=structured_query with one or more explicit filters, add structured_query_constraints: an array of 1-4 objects {field,operator,value,evidence_span,unit}. field must be one of material,capacity,weight,dimensions,people,color,heat_source,usage_scene,waterproof and must also be in canonical_fields. operator must be: material/usage_scene contains; heat_source supports or not_supports; numeric fields >=,>,<=,<,=,between; color/dimensions contains or =; waterproof =. evidence_span must be an exact customer phrase in this turn, and each textual value must be a verbatim substring of that evidence_span (for example value=明火, evidence_span=支持明火). A generic catalogue kind such as cookware, stove, or waterware is the query subject scope in subject_text, not a category predicate and not an extra canonical_fields entry; canonical_fields contains only the actual requested filter dimensions. This is a query predicate only: never include a product name, SKU, candidate, database value, answer, or inferred condition. "
                "For a catalogue count or an unconstrained list whose only scope is a generic product kind (for example, how many stoves are recorded), use route_family=structured_query, route_hint=query_products, subject_text for that kind, canonical_fields=[category], and structured_query_constraints=[]; category describes the database membership scope here and MUST NOT appear as a predicate object. "
                "subject_kind means the thing the customer is actually seeking: waterware is for a vessel explicitly requested to carry or boil water, cookware is for a pot, pan, griddle, or cooking vessel, and stove is for a burner or heat source. Do not select cookware merely because water can also be heated in cookware. weight_preference is only an explicit physical-mass requirement (for example light, heavy, weight, or carrying load). Compactness, storage, or not taking space is not weight_preference; use storage_preference=compact_storage for an explicit non-binding storage preference, and preserve an explicitly non-negotiable storage requirement in unrepresented_recommendation_requirements. "
                "When decision_requested is true and the customer contrasts two or more product forms that all belong to one allowed broad subject_kind, emit that shared subject_kind so the evidence executor has a bounded catalogue scope. This does not decide which form wins and does not create a product-form constraint; the later semantic writer may choose only from sealed same-SKU evidence. "
                "Every recommendation constraint must be explicitly stated by the customer in this turn or supplied by an explicit prior-turn customer preference; omit it when it is merely plausible or typical. In particular, do not infer people, heat_sources, scenarios, or weight_preference from the product category, a generic outdoor word, or the fact that a customer asks for a recommendation. "
                "For a recommendation that explicitly asks to replace the prior recommendation, set recommendation_followup_action=alternative; otherwise omit it. This is only allowed when an explicit prior customer preference is supplied. "
                    "Before returning a recommendation plan, inspect every explicit customer requirement. When one customer expression contains multiple independently allowed requirements, emit every matching allowed constraint rather than letting one suppress another. If a must-have eligibility condition cannot be put in recommendation_constraints without inventing a meaning, it MUST appear verbatim in unrepresented_recommendation_requirements. Do not turn a non-binding preference into an eligibility gap merely because the ontology cannot encode it. "
                "route_family enum: structured_query,recommendation,comparison,product_bound_qa,product_navigation,unresolved_product_like,negative_product_like,unknown_realtime,contents_accessories,generic_query,knowledge_base_meta,clarification. Use knowledge_base_meta only when the user asks about a knowledge-base document itself, its contents, rules, or principles rather than requesting a product fact. A named-product question about operating steps, safety rules, prohibited actions, cleaning, maintenance, or any other product field is product_bound_qa even if its answer may later use a manual or knowledge-base document as evidence. "
                "entity_scope enum: generic_scope,category_scope,product_like,resolved_product,ambiguous_product,unresolved_product,negative_product. "
                "field_type enum: " + ",".join(sorted(SEMANTIC_PREPLAN_FIELD_TYPES)) + ". "
                "evidence_kind is required for every product_bound_qa request. Use structured_field only when the customer directly asks for a recorded field value. Use product_qa when the customer asks a product-specific capability, judgement, procedure, or compatibility fact that is not identical to one structured field; then canonical_fields MUST be [] and no field_type/field_hint may be emitted. For product_qa, qa_evidence_query is required: return a concise semantic retrieval phrase for the customer's intent, with no product name, SKU, database value, or answer. Preserve the customer's concrete operative condition rather than replacing it with an abstract category: for a question about whether low heat can be adjusted for simmering, the retrieval phrase must retain the low-heat adjustment and simmering condition, not merely say slow-cooking performance. For example, describe gifting suitability, authenticity verification, flame adjustability, household compatibility, durability, or load-bearing as the requested capability. For every other evidence_kind set qa_evidence_query="". Durability is not lifecycle_status; whether a product is suitable as a present is not whether a purchase includes a promotional gift; authenticity verification is not certification; adjustability is not a numeric power rating; household compatibility is not a list of usage scenes; and load-bearing is not net weight, headcount, or volume. These are ontology boundaries, not product facts: keep them product_qa so only a later same-SKU QA evidence contract may answer. "
                "canonical_fields is an ordered array of one or more field concepts; use every independently requested field. A number, unit, model marker, capacity, size, color, or version that occurs only inside the product mention belongs only to subject_text and MUST NOT create an additional canonical field, structured filter, recommendation condition, or ambiguity. Add a field only when the customer's predicate independently asks for that fact. subject_text is the product mention only, never a SKU decision. "
                "For a comparison between two or more named products, entities is mandatory: put each verbatim product mention in entities in mention order (at least two items). Any factual request that asks for those named participants' respective values is route_family=comparison even when it asks for no winner; structured_query is only for filters over a product set, never a pairwise product fact. canonical_fields must contain only the field explicitly asked for, or the single field that directly expresses the user's stated suitability criterion; never enumerate product dimensions that the user did not ask about. If the criterion is a product-specific capability, procedure, compatibility, judgement, or performance fact that is not identical to one structured field, set evidence_kind=product_qa, canonical_fields=[], and provide qa_evidence_query; never substitute a merely related structured field. Set decision_requested=true whenever the user asks which named participant wins a stated criterion, including which is lighter, heavier, larger, cheaper, more suitable, or should be chosen; otherwise false. Never infer a preference from a product name, version label, or SKU, and never invent, normalize, or choose a SKU. "
                "Do not choose recommendation merely because a question asks where, what, or which: recommendation requires asking for options or advice, not a fact about one product. "
                "information_scope enum: knowledge_base_meta when the user asks about a knowledge-base document, its contents, rules, or principles rather than requesting products; otherwise an empty string. A knowledge_base_meta turn has no product candidates unless a later provenance-bound retrieval supplies them. "
                "brand=manufacturer or brand owner; questions asking whose brand, maker, or which company a named product is from are brand. "
                "category=the product kind, class, merchandise type, or taxonomy bucket. A request for which kind, class, category, or type a product is belongs to category. "
                "series=a named product family, collection, or product line, never a generic product kind/class. Use series only when the requested relationship is to a named family, collection, line, or range; "
                "do not reinterpret a generic classification request as series merely because the product also has a series value. launch_date=market introduction time; "
                "surface_finish=outer surface treatment; positioning=target customer/problem, intended role, or brand strategy. A predicate about a product's need, use case, problem, role, or job-to-be-done is positioning even when it uses a broad word such as 'targeted at' or 'for'; it does not become target_audience unless it asks who the users are. "
                "people=a numeric or bounded group-size fact: how many persons the product serves, supports, or is intended for. "
                "target_audience=the user persona, customer type, or user group a product suits, not a numeric headcount and not the product need, use case, role, or problem it serves. "
                "A question such as ‘适合哪些人/什么人/适合谁’ asks target_audience; it does not ask a person count. Choose people only when the customer asks a numeric or bounded headcount such as 几个人、几人、多少人 or 1-2人. Numbers such as volume or size inside the product name do not change that distinction. "
                "cleaning=how to remove soot, stains, residue, or dirt after use; care=storage or ongoing preservation after cleaning. A question about 熏黑、污渍或清洗 therefore asks cleaning unless it explicitly asks storage or preservation. "
                "price_positioning=entry, mid, premium, affordable, or high-end price tier rather than current price; "
                "never use positioning or brand for a price-tier question. emotional_value=the intended feeling, emotional experience, or felt outcome the product is meant to create; "
                "use emotional_value when the user asks about the feeling, experience, mood, or emotional outcome emphasized for the user; "
                "do not use selling_point merely because an experience can also be described as a benefit. "
                "usage_scene=concrete usage setting or activity, not the target customer/problem or user group; "
                "sales_region=geographic markets, countries, areas, territories, or launch regions where sold or deployed; questions about where a named product is mainly placed, launched, distributed, or targeted geographically are sales_region, not purchase_channel. certification=compliance or certification; "
                "purchase_channel=official platforms, stores, or order channels where one named product can be bought. "
                "When wording asks about geographic places or markets, choose sales_region; when it asks about a platform/store/channel, choose purchase_channel. "
                "manual=an official manual, user guide, handbook, or downloadable instruction document; it is not the same as asking how to operate the product. "
                "after_sales_contact=a telephone number, hotline, customer-service contact, or method for contacting after-sales support; it is not purchase_channel. "
                "inventory=current stock or in-stock availability; lifecycle_status is only the catalogue lifecycle label and must not be used as realtime stock, product durability, expected usable years, service life, or replacement interval. "
                "A question about how long one named product can normally be used is a product-bound QA or warranty fact; when the formal taxonomy has no direct recorded field, retain route_family=product_bound_qa with canonical_fields=[] so sealed same-SKU QA evidence can be evaluated. "
                "gift=a promotional free gift or giveaway included with a purchase; it is not whether the named product itself is suitable to give someone as a present. A question about gifting suitability is a product-bound QA or selling-point fact, not gift. accessories=the standard package contents, included parts, or items supplied with the product. "
                "warranty=a guarantee, warranty coverage, or warranty duration; it is not lifecycle_status. "
                "shipping=dispatch time, delivery time, postage, or shipping commitment. price=current selling price; price_positioning=a price tier rather than a realtime amount. "
                "competitor_benchmark=the named product's recorded comparison set, comparable products, competitive references, or official benchmark products; it is a product fact, not a generic category search or recommendation. "
                "sku=the SKU, item number, product code, catalogue code, or stock code used to identify the product record. "
                "product_name_cn=the product's short Chinese display name or Chinese product name. product_name_en=the product's short English display name or English product name; neither is the brand nor a specification. "
                "content_title=a customer-facing listing, website, Amazon, or marketing title; it is distinct from the short catalogue product name. In particular, a request for a Chinese/English product title, listing title, website title, Amazon title, or marketing title is content_title, while a request for the Chinese/English product name is product_name_cn/product_name_en. content_description=a customer-facing long description, product detail introduction, or listing description. bullet_points=the product's recorded five-point bullets or listed key points. A request for five selling points, five key points, or a numbered product-point list is bullet_points even though it contains the word selling point; selling_point is only a non-numbered general highlights request. For these content fields, retain the language and channel expressed by the customer as the requested subtype; do not substitute a name, specification, or selling-point field. "
                "search_keywords=an internal search-keyword or backend retrieval-key request. It is a recognised but non-public field: never substitute a title, description, name, SKU, or selling point for it. "
                "model=a distinct manufacturer model number only when the product record explicitly provides one; never substitute SKU, item number, product code, catalogue code, or stock code for model. "
                "barcode=an EAN, UPC, GTIN, scannable barcode, or printed bar-code value; never map a SKU, model, item number, product code, or catalogue code to barcode. "
                "dimensions=physical measurements such as length, width, height, diameter, folded size, or unfolded size; capacity=volume or the amount a container can hold. "
                "If generic wording such as how big could genuinely mean either physical dimensions or capacity, mark ambiguity instead of using a number in the product name to guess. "
                "heat_source=compatible stove types, heating methods, fuel sources, or whether direct flame/charcoal/wood/induction is supported. "
                "power=rated output, wattage, electrical power consumption, burner output, heat output, or firepower. A request for rated output or power must use power, not specification merely because it is a technical parameter. Operating duration, fuel endurance, burn time, runtime, or how long a consumable load lasts are not power: when the formal taxonomy has no direct field for that product-specific fact, retain route_family=product_bound_qa with canonical_fields=[] so the sealed same-SKU QA evidence stage can evaluate it. "
                "usage_instruction=operating or usage steps for the product; a request about stove, fuel, or heating compatibility remains heat_source even if phrased as how compatibility should be stated. "
                "dishwasher=only whether the product is explicitly dishwasher-safe or compatible with a dishwashing machine. "
                "generic machine-wash or washing-machine compatibility belongs to cleaning, not dishwasher; never translate generic machine-wash wording into dishwasher. "
                "cleaning=manual cleaning methods, washing steps, wiping, rinsing, detergents, or laundry-machine compatibility, excluding explicit dishwasher compatibility. "
                "care=maintenance, upkeep, drying before storage, rust prevention, protection, or long-term storage practices. Care and maintenance remain care even when the evidence shares a usage-instruction document; do not relabel them as cleaning or usage_instruction. "
                "product_level=the catalogue's grade or tier label such as A-class or B-class; category=the merchandise type such as cookware, stove, or accessory. "
                "selling_point=the named product's benefits, highlights, advantages, differentiators, or reasons it is worth choosing. Asking why one already named product is worth choosing is a product_bound_qa selling_point fact, not recommendation. "
                "technical_advantages=concrete product technologies, engineering mechanisms, technical structures, or technical capabilities recorded for the product; do not use selling_point merely because a technical fact is also beneficial. "
                "Use selling_point for customer-facing value propositions and general highlights, and technical_advantages for how the product achieves a capability through a named technology, mechanism, structure, or technical implementation. "
                "recommendation requires asking the assistant to select, rank, or propose product options; it is not triggered by asking for the merits of one named product. "
                "For a pronoun follow-up with a conversation, classify only the requested field; do not infer or output an identity. "
                "If the user only selects, switches to, opens, or says they want to look at one named product without asking any fact, use route_family=product_navigation, extract that product mention in subject_text, set canonical_fields=[], evidence_required=false, and do not invent an overview field. "
                "For a product fact use route_family=product_bound_qa, question_type=field, subtype=known_detail, "
                "and repeat the selected canonical label in field_hint. "
                "When evidence_kind=product_qa, qa_evidence_query must be a short retrieval phrase in the customer's language that describes only the requested capability, judgement, procedure, or concern. "
                "For a Chinese question it must contain Chinese, not an English ontology label; it must not contain a product name, SKU, answer, or database fact. "
                "confidence enum: low,medium,high. ambiguity is true only when the request itself has incompatible field meanings. evidence_required is true for product facts. context_usage is none,entity_anchor,or field_and_entity. reasoning_summary must be a short auditable summary, not private chain-of-thought. "
                "Never output an answer or standalone factual values. Never output SKU facts, candidate_skus, recommended_skus, or result_skus."
            ),
        },
        {
            "role": "user",
            "content": (
                f"question: {question}\n"
                f"deterministic_primary_intent: {deterministic_plan.get('primary_intent') or ''}\n"
                f"deterministic_answer_type: {deterministic_plan.get('answer_type') or ''}\n"
                f"has_conversation_id: {bool(context.get('conversation_id'))}\n"
                f"has_recommendation_context: {bool(context.get('has_recommendation_context'))}\n"
                "database_field_value_hints: "
                + json.dumps(context.get("database_field_value_hints") or [], ensure_ascii=False)
                + "\n"
                "explicit_prior_customer_preference_texts: "
                + json.dumps(context.get("prior_customer_preference_texts") or [], ensure_ascii=False)
                + "\n"
                "database_field_value_hints are only schema-grounding candidates whose matched_text occurs in the current question; they are not product facts and must never be returned as an answer. If a matched hint is a named collection/line and the user asks which products it contains, use route_family=structured_query, canonical_fields=[series], and preserve the matched customer phrase in subject_text. Do not infer a field from an unmatched hint. Return every required key. Select canonical_fields only from the field_type enum above; do not copy a field from an output example."
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


def _deterministic_semantic_field_fallback(question: str) -> dict[str, Any] | None:
    """Classify compositional field meaning when the external semantic model is unavailable.

    This is deliberately a small intent algebra, not a catalogue/name/SKU
    lookup and not a list of acceptance questions.  It supplies only an
    allowlisted canonical field; Phase 2 must still form an independent
    EntityResolutionContract before any product evidence can be read.
    """
    text = re.sub(r"\s+", "", str(question or "").lower())
    if not text:
        return None

    composed = customer_field_contract.deterministic_compositional_field_candidate(text)
    if composed is None:
        return None
    field_type, reason = composed

    if field_type not in SEMANTIC_PREPLAN_FIELD_TYPES:
        return None
    return {
        "called": True,
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "entities": [],
        "field_type": field_type,
        "field_hint": field_type,
        "subtype": "known_detail",
        "entity_scope": "product_like",
        "qa_or_usage_care": False,
        "unknown_field": False,
        "confidence": 0.9,
        "confidence_label": "high",
        "reason": reason,
        "raw_preview": "",
        # This is a validated semantic adapter, not an error fallback.  The
        # FieldContract validator correctly rejects non-empty fallback_reason
        # values, so provenance is recorded separately.
        "semantic_adapter_source": "deterministic_compositional_field",
    }


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


async def _repair_semantic_preplan_output(
    db,
    *,
    question: str,
    raw_content: str,
    failure_reason: str = "",
) -> str:
    runtime_settings = _semantic_preplan_runtime_settings()
    # Keep repair on exactly the same public semantic schema as the initial
    # preplan. A duplicated, stale mini-prompt had dropped newer route
    # families and structured fields, turning valid customer meaning into an
    # avoidable legacy fallback.
    messages = _semantic_preplan_messages(
        question=question,
        deterministic_plan={},
        context={},
    )
    messages[0]["content"] += (
        " The prior semantic JSON violated this contract. Repair its schema; "
        "preserve only customer-stated intent and return every required key."
    )
    if failure_reason in {
        "pairwise_recommendation_requires_comparison_contract",
        "invalid_comparison_decision_criterion",
        "missing_comparison_decision_criterion",
        "pairwise_factual_requires_comparison_contract",
    }:
        messages[0]["content"] += (
            " This is a named two-or-more-product comparison. MUST return route_family=comparison, "
            "route_hint=comparison, question_type=comparison, and "
            "subtype=relation_comparison. Preserve decision_requested exactly: "
            "true only for a requested winner and false for a request to list "
            "the participants' respective facts. Translate the requested field or "
            "condition into only the existing formal canonical_fields taxonomy (for example scenario to "
            "usage_scene, people to people, heat compatibility to heat_source, "
            "or lightness to weight); never return recommendation as its field."
        )
    if failure_reason == "invalid_comparison_participants":
        prior_data = _extract_json_object(raw_content)
        prior_entities = prior_data.get("entities") if isinstance(prior_data, dict) else []
        prior_fields = prior_data.get("canonical_fields") if isinstance(prior_data, dict) else []
        if (
            isinstance(prior_entities, list)
            and len(prior_entities) < 2
            and isinstance(prior_fields, list)
            and any(
                customer_field_contract.semantic_preplan_field_type(item)
                in customer_field_contract.FORMAL_DETAIL_FIELDS
                for item in prior_fields
            )
        ):
            messages[0]["content"] += (
                " Comparison requires two or more explicitly named product "
                "participants. The previous output had one named product and "
                "a formal customer field, so repair it as route_family="
                "product_bound_qa, route_hint=product_detail, question_type="
                "field, subtype=known_detail, with the same formal canonical "
                "field. Do not manufacture a second participant or turn this "
                "into a catalogue query."
            )
        else:
            messages[0]["content"] += (
                " Comparison requires two or more explicitly named product "
                "participants. Do not invent a missing participant; return a "
                "safe clarification route when the customer did not name them."
            )
    if failure_reason in {
        "invalid_structured_query_constraints",
        "structured_query_constraints_outside_structured_query",
        "structured_query_constraints_field_mismatch",
        "named_nonfilter_field_in_structured_query",
        "missing_structured_query_constraints",
    }:
        prior_data = _extract_json_object(raw_content)
        prior_fields = (
            [
                customer_field_contract.semantic_preplan_field_type(item)
                for item in prior_data.get("canonical_fields", [])
            ]
            if isinstance(prior_data, dict) and isinstance(prior_data.get("canonical_fields"), list)
            else []
        )
        # A malformed predicate schema does not prove that the customer's
        # request is a catalogue filter.  In particular, the semantic model can
        # correctly name a product-bound field that is deliberately not an
        # executable filter column (for example competitor_benchmark), then
        # attach an invalid structured-query object because of broad wording
        # such as "which comparable products".  Let semantic repair correct
        # that route contradiction instead of deterministically reclassifying
        # the field or coercing the invalid filter route.
        if set(prior_fields).issubset({"category"}):
            messages[0]["content"] += (
                " This is a catalogue count or unconstrained category list, not a multi-condition filter. "
                "Keep route_family=structured_query and route_hint=query_products; put the requested product kind "
                "only in subject_text, keep canonical_fields=[category], and return "
                "structured_query_constraints=[] with no category predicate."
            )
        elif any(field and field not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS for field in prior_fields):
            messages[0]["content"] += (
                " The previous output used structured_query for a canonical "
                "field that is not an executable catalogue predicate. A named-product "
                "field is a product fact: when the customer's subject is one named "
                "product, return route_family=product_bound_qa, "
                "route_hint=product_detail, question_type=field, and "
                "subtype=known_detail while preserving only the semantic canonical "
                "field and customer subject. Do not invent structured predicates."
            )
        else:
            messages[0]["content"] += (
                " Before treating this as a catalogue filter, re-read the whole "
                "question and identify the entire product mention separately from "
                "the requested predicate. A number, capacity, size, count, color, "
                "model marker, or version that is part of the entire product "
                "mention is not an independent field or filter. If the customer "
                "asks one fact about one named product, return "
                "route_family=product_bound_qa, route_hint=product_detail, "
                "question_type=field, subtype=known_detail, preserve the entire "
                "product mention in subject_text, and keep only the independently "
                "requested canonical field. Use structured_query only when the "
                "customer independently asks to filter a catalogue set."
            )
    if failure_reason == "missing_recommendation_constraints":
        messages[0]["content"] += (
            " This is a high-confidence recommendation whose route was valid "
            "but whose formal recommendation_constraints were omitted. Re-read "
            "the complete customer wording and emit every allowed literal "
            "constraint that it explicitly supports; retain any material "
            "unrepresented requirement verbatim instead of guessing a product "
            "fact or changing the route."
        )
    if failure_reason == "unclassified_product_bound_field":
        messages[0]["content"] += (
            " The prior output classified this as a named product fact but "
            "left canonical_fields unknown. Re-read the complete customer "
            "meaning and select exactly one existing formal canonical field "
            "when the meaning maps to the published ontology. Keep "
            "route_family=product_bound_qa, route_hint=product_detail, "
            "question_type=field, and subtype=known_detail for that case. "
            "If the customer's requested fact genuinely has no formal field, "
            "return a safe clarification/unknown-field route; never replace "
            "the unknown field with a keyword-derived guess."
        )
    if failure_reason == "invalid_recommendation_constraints":
        messages[0]["content"] += (
            " The prior recommendation_constraints contained a non-ontology "
            "key or value. Return only the allowed recommendation constraint "
            "schema from this prompt; do not return an unsupported constraint "
            "key. Preserve any customer requirement that has no allowed formal "
            "representation as an exact literal item in "
            "unrepresented_recommendation_requirements rather than inventing "
            "a new recommendation constraint. That array is a top-level sibling "
            "of recommendation_constraints: never nest "
            "unrepresented_recommendation_requirements inside "
            "recommendation_constraints. An unsupported cooking purpose, product "
            "style, or other non-ontology need belongs only in that top-level "
            "literal array."
        )
    # Keep the complete bounded semantic object visible to repair.  A short
    # prefix drops optional fields emitted near the end (notably material
    # requirements that cannot yet be represented by the DB contract), so the
    # repair model cannot preserve customer intent it already understood.
    messages[1]["content"] += f"\nprevious_output_preview: {_safe_preview(raw_content, 1000)}"
    return await customer_llm_service.chat_completion(
        db,
        messages,
        temperature=runtime_settings["temperature"],
        max_tokens=runtime_settings["max_tokens"],
        purpose="semantic_preplan_repair",
        api_model_override=runtime_settings["model"],
        response_format=runtime_settings["response_format"],
        thinking=runtime_settings["thinking"],
    )


async def _repair_semantic_recommendation_constraint_partition(
    db,
    *,
    question: str,
    invalid_constraints: Any,
    invalid_unrepresented_requirements: Any,
) -> dict[str, Any] | None:
    """Let DeepSeek rebuild only an invalid recommendation requirement partition.

    The broad preplan repair can occasionally repeat an invalid enum because it
    must also reproduce the full route schema. This bounded second repair owns
    no route, identity, candidate, or product fact: it only returns the two
    semantic fields whose contract was malformed. Deterministic code validates
    the closed schema and literal-span boundary before reattaching them to the
    original semantic route.
    """
    runtime_settings = _semantic_preplan_runtime_settings()
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON. Repair only the recommendation requirement partition for the exact customer question; "
                "do not answer, choose a product, infer a SKU, or change the route. "
                "Output exactly {\"recommendation_constraints\":object,\"unrepresented_recommendation_requirements\":array}. "
                "recommendation_constraints may contain only subject_kind (cookware|waterware|stove), people ({min,max}), "
                "heat_sources (card_stove|gas_stove|alcohol_stove|open_flame|induction), scenarios (camping|hiking|self_drive|seaside|soup), "
                "weight_preference (lightweight), price_preference (affordable|premium), and storage_preference (compact_storage). "
                "Keep only constraints explicitly stated by the customer. Every material customer requirement that cannot use those exact keys or values "
                "must be copied as an exact literal substring into the top-level unrepresented_recommendation_requirements array; never nest that array "
                "inside recommendation_constraints and never invent a synonym. When an invalid fine-grained product-form comparison belongs to one allowed broad subject_kind, retain only that shared broad subject_kind; do not invent a product_form key or use a product title as a constraint."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "invalid_recommendation_constraints": invalid_constraints,
                    "invalid_unrepresented_recommendation_requirements": invalid_unrepresented_requirements,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages,
            temperature=runtime_settings["temperature"],
            max_tokens=min(int(runtime_settings["max_tokens"]), 320),
            purpose="semantic_recommendation_constraint_schema_repair",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return None
    data = _extract_json_object(content)
    if not isinstance(data, dict) or set(data) != {
        "recommendation_constraints", "unrepresented_recommendation_requirements",
    }:
        return None
    constraints = _validated_recommendation_constraints(data.get("recommendation_constraints"))
    unrepresented = _validated_unrepresented_recommendation_requirements(
        data.get("unrepresented_recommendation_requirements")
    )
    # If the semantic repair retained a valid allowlisted subset but also
    # repeated a non-ontology item, keep only that subset *when* it explicitly
    # preserved literal unmet customer wording. The next executor sees the
    # nonempty unrepresented list and therefore clarifies instead of widening
    # into a recommendation; this is validation/fail-closed behavior, never a
    # deterministic interpretation of the discarded item.
    if constraints is None and unrepresented:
        constraints = _validated_recommendation_constraint_subset(data.get("recommendation_constraints"))
    if constraints is None or unrepresented is None or any(item not in question for item in unrepresented):
        return None
    return {
        "recommendation_constraints": constraints,
        "unrepresented_recommendation_requirements": unrepresented,
    }


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


def _recommendation_constraints_are_subset(
    proposed: dict[str, Any],
    grounded: dict[str, Any],
) -> bool:
    """The grounding pass may only remove semantic constraints, never add one."""
    for key, value in grounded.items():
        original = proposed.get(key)
        if key in {"heat_sources", "scenarios"}:
            if not isinstance(original, list) or any(item not in original for item in value):
                return False
        elif original != value:
            return False
    return True


def _recommendation_constraints_preserve_existing(
    original: dict[str, Any],
    reconciled: dict[str, Any],
) -> bool:
    """A semantic completeness review may add literal constraints, never alter one."""
    for key, value in original.items():
        updated = reconciled.get(key)
        if key in {"heat_sources", "scenarios"}:
            if not isinstance(updated, list) or any(item not in updated for item in value):
                return False
        elif updated != value:
            return False
    return True


async def _semantic_recommendation_requirement_reconciliation(
    db,
    *,
    question: str,
    proposed_constraints: dict[str, Any],
    unrepresented_requirements: list[str],
    soft_preferences: list[str],
    runtime_settings: dict[str, Any],
) -> dict[str, Any] | None:
    """Let the semantic model correct only its own formal/unrepresented partition.

    This pass receives no catalogue data, candidates, identities, or answer text.
    It prevents a valid literal requirement from being omitted or placed in the
    safe-missing list when the existing recommendation ontology can represent it.
    Deterministic code validates schema, preservation, and literal spans only.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON. Audit a recommendation preplan against the exact customer question. "
                "The prior plan may have omitted a literal customer requirement, or placed it in "
                "unrepresented_recommendation_requirements, even though it belongs in the existing "
                "recommendation ontology. Reconcile the complete plan: preserve every existing "
                "constraint unchanged, and add an allowed constraint only when an exact literal "
                "customer phrase supports it. Do not assume an expression is satisfied merely because it sounds typical for a product category or might be mentioned in later content. Put an unmet must-have eligibility condition in unrepresented_recommendation_requirements; put a non-binding desire, use-context, or decision framing in recommendation_soft_preferences. Soft preferences do not filter candidates and never prove a product fact. Leave requirements unrepresented when the ontology "
                "cannot express them; do not infer a product, SKU, candidate, database fact, price, "
                "or answer. An explicit cardinality or group-size phrase is always an independent people constraint when the ontology can represent it; do not let an accompanying scenario, heat source, or subject kind suppress it. A wish, preference, or choice-framing phrase is soft unless the customer explicitly makes it non-negotiable; do not turn it into an unmet hard requirement merely because it has no ontology key. When the customer asks how to choose or does not force a single product, contextual storage or space pressure is a soft preference unless they explicitly state it is a must-have eligibility condition. A literal phrase already represented by a retained formal constraint must not be repeated as a soft preference. Allowed constraint schema is exactly: subject_kind "
                "(cookware|waterware|stove), people ({min,max}), heat_sources "
                "(card_stove|gas_stove|alcohol_stove|open_flame|induction), scenarios "
                "(camping|hiking|self_drive|seaside|soup), weight_preference (lightweight), "
                "price_preference (affordable|premium), storage_preference (compact_storage). For every retained or added constraint, "
                "evidence_spans must contain exact literal customer substrings. Output exactly "
                "{\"recommendation_constraints\":{...},\"unrepresented_recommendation_requirements\":[...],\"recommendation_soft_preferences\":[...],"
                "\"evidence_spans\":{\"constraint_key\":[\"exact customer words\"]}}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "proposed_constraints": proposed_constraints,
                    "unrepresented_recommendation_requirements": unrepresented_requirements,
                    "recommendation_soft_preferences": soft_preferences,
                },
                ensure_ascii=False,
            ),
        },
    ]
    # The reconciliation model sometimes keeps an unsupported added constraint
    # with an empty span. Give the semantic task one chance to remove that key;
    # accepting the malformed object would preserve a false "unrepresented"
    # blocker, while deterministic code still validates every retained span.
    for attempt in range(2):
        attempt_messages = [dict(message) for message in messages]
        if attempt:
            attempt_messages[0]["content"] += (
                " Your preceding JSON was invalid: every constraint key must "
                "have a non-empty exact evidence_spans entry. Remove an added "
                "constraint if it has no literal support; do not retain an "
                "unrepresented requirement when it is represented by a retained "
                "formal constraint."
            )
        try:
            content = await customer_llm_service.chat_completion(
                db,
                attempt_messages,
                temperature=0,
                max_tokens=min(int(runtime_settings["max_tokens"]), 320),
                purpose="semantic_preplan_requirement_reconciliation",
                api_model_override=runtime_settings["model"],
                response_format=runtime_settings["response_format"],
                thinking=runtime_settings["thinking"],
            )
        except Exception:
            continue
        data = _extract_json_object(content)
        if not isinstance(data, dict) or set(data) not in (
            {"recommendation_constraints", "unrepresented_recommendation_requirements", "evidence_spans"},
            {"recommendation_constraints", "unrepresented_recommendation_requirements", "recommendation_soft_preferences", "evidence_spans"},
        ):
            # A blank or structurally unrelated response contributes no
            # candidate constraint or literal provenance. Retrying that same
            # ungrounded semantic request cannot make the existing customer
            # requirement safer, so fail closed and leave it unrepresented.
            # Parsed-but-invalid evidence below still receives one repair try.
            return None
        constraints = _validated_recommendation_constraints(data.get("recommendation_constraints"))
        unrepresented = _validated_unrepresented_recommendation_requirements(
            data.get("unrepresented_recommendation_requirements")
        )
        reconciled_soft_preferences = _validated_recommendation_soft_preferences(
            data.get("recommendation_soft_preferences")
        )
        spans = data.get("evidence_spans")
        if (
            constraints is None
            or unrepresented is None
            or reconciled_soft_preferences is None
            or not isinstance(spans, dict)
            or set(spans) != set(constraints)
            or not _recommendation_constraints_preserve_existing(proposed_constraints, constraints)
            or any(item not in question for item in [*unrepresented, *reconciled_soft_preferences])
        ):
            continue
        normalized_spans: dict[str, list[str]] = {}
        for key in constraints:
            values = spans.get(key)
            if not isinstance(values, list) or not values:
                normalized_spans = {}
                break
            normalized = [str(item or "").strip() for item in values]
            if any(not item or item not in question for item in normalized):
                normalized_spans = {}
                break
            normalized_spans[key] = list(dict.fromkeys(normalized))
        if set(normalized_spans) != set(constraints):
            continue
        return {
            "recommendation_constraints": constraints,
            "unrepresented_recommendation_requirements": unrepresented,
            "recommendation_soft_preferences": reconciled_soft_preferences,
            "evidence_spans": normalized_spans,
        }
    return None


_RECOMMENDATION_LITERAL_CONSTRAINT_TERMS = {
    "subject_kind": {
        "cookware": ("锅", "煎盘", "烤盘", "炊具"),
        "waterware": ("水壶", "水具", "水杯", "杯", "烧水", "煮水"),
        "stove": ("炉", "灶", "燃烧器"),
    },
    "heat_sources": {
        "card_stove": ("卡式炉",),
        "gas_stove": ("燃气炉", "燃气灶"),
        "alcohol_stove": ("酒精炉",),
        "open_flame": ("明火",),
        "induction": ("电磁炉",),
    },
    "scenarios": {
        "camping": ("露营", "营地"),
        "hiking": ("徒步",),
        "self_drive": ("自驾",),
        "seaside": ("海边",),
        "soup": ("煮汤",),
    },
}


def _recommendation_literal_grounding_filter(
    constraints: dict[str, Any],
    evidence_spans: dict[str, list[str]],
    *,
    preserve_semantic_subject_kind: bool = False,
    preserve_semantic_weight_preference: bool = False,
    preserve_semantic_storage_preference: bool = False,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Keep only semantic constraints with literal ontology-compatible support.

    This is a contract validator, not a second intent classifier: the semantic
    layer still decides the route and proposes the allowed ontology values.
    It merely rejects a proposed enum value when the cited words cannot name
    that value (for example, generic ``户外`` cannot prove camping or hiking).
    """
    filtered_constraints: dict[str, Any] = {}
    filtered_spans: dict[str, list[str]] = {}
    for key, value in constraints.items():
        spans = list(evidence_spans.get(key) or [])
        if key in {"heat_sources", "scenarios"}:
            supported_values = [
                item
                for item in value
                if any(
                    any(term in span for term in _RECOMMENDATION_LITERAL_CONSTRAINT_TERMS[key][item])
                    for span in spans
                )
            ]
            if supported_values:
                filtered_constraints[key] = supported_values
                filtered_spans[key] = [
                    span
                    for span in spans
                    if any(
                        any(term in span for term in _RECOMMENDATION_LITERAL_CONSTRAINT_TERMS[key][item])
                        for item in supported_values
                    )
                ]
            continue
        if key == "subject_kind":
            if preserve_semantic_subject_kind and spans:
                filtered_constraints[key] = value
                filtered_spans[key] = spans
                continue
            if any(term in span for span in spans for term in _RECOMMENDATION_LITERAL_CONSTRAINT_TERMS[key][value]):
                filtered_constraints[key] = value
                filtered_spans[key] = spans
            continue
        if key == "weight_preference":
            # Weight preference can be expressed by a sentence-level physical
            # burden description (for example, "背起来不累") rather than one
            # of the compact ontology labels below.  When the semantic
            # grounding pass has already supplied an exact customer span, keep
            # that validated meaning; this helper is otherwise the conservative
            # no-model fallback.
            if preserve_semantic_weight_preference and spans:
                filtered_constraints[key] = value
                filtered_spans[key] = spans
                continue
            if any(any(term in span for term in ("轻", "重量", "背着", "负重")) for span in spans):
                filtered_constraints[key] = value
                filtered_spans[key] = spans
            continue
        if key == "storage_preference":
            # Storage preference is also a sentence-level semantic decision:
            # the grounding model has already confirmed that its exact span
            # expresses compact storage.  Do not turn this contract validator
            # into another storage-keyword router.
            if preserve_semantic_storage_preference and spans:
                filtered_constraints[key] = value
                filtered_spans[key] = spans
            continue
        if key == "price_preference":
            terms = ("预算", "便宜", "别太高", "低价") if value == "affordable" else ("高端", "高价", "贵")
            if any(any(term in span for term in terms) for span in spans):
                filtered_constraints[key] = value
                filtered_spans[key] = spans
            continue
        if key == "people":
            # The semantic layer owns intent, but a party-size value is a
            # structured numeric claim. Its cited span must parse to the same
            # range before it can narrow the catalogue. This rejects semantic
            # slips such as interpreting "beginner" as one person without
            # deciding the route or replacing the semantic subject.
            matching_spans = []
            if isinstance(value, dict):
                expected_range = (value.get("min"), value.get("max"))
                for span in spans:
                    lower, upper, _ = customer_recommendation_verification_contract._parse_people(span)
                    if (lower, upper) == expected_range:
                        matching_spans.append(span)
            if matching_spans:
                filtered_constraints[key] = value
                filtered_spans[key] = matching_spans
            continue
    return filtered_constraints, filtered_spans


async def _semantic_recommendation_constraint_grounding(
    db,
    *,
    question: str,
    proposed_constraints: dict[str, Any],
    runtime_settings: dict[str, Any],
    prior_customer_preference_texts: list[str] | None = None,
) -> dict[str, Any] | None:
    """Ask the semantic layer to remove recommendation constraints it cannot ground.

    This is intentionally a second semantic judgment, not a keyword matcher.
    The deterministic checks below merely prove that the model returned an
    allowlisted subset and literal source spans from the customer's sentence.
    """
    prior_texts = list(dict.fromkeys(
        str(item or "").strip()[:600]
        for item in (prior_customer_preference_texts or [])
        if str(item or "").strip()
    ))[:3]
    evidence_texts = [question, *prior_texts]
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON. Review proposed recommendation constraints against the customer's exact words. "
                "Keep a constraint only when the customer explicitly stated it in this question or in supplied explicit_prior_customer_preference_texts; do not treat generic outdoor wording as camping, hiking, self-drive, seaside, lightweight, a heat source, or a group size. "
                "For subject_kind, an explicit noun naming the requested broad product class is sufficient literal support: a pot, pan, griddle, or cookware supports cookware; a kettle, cup, water vessel, or wording that explicitly asks to carry or boil water supports waterware; a burner or stove supports stove. When a decision question contrasts two such forms within the same broad class, retain that shared subject_kind and cite the literal comparison phrase. This only bounds the catalogue; it does not decide which form is better or assert that any candidate meets the customer's purpose. "
                "For each kept key, evidence_spans must contain one or more exact literal substrings from the current question or supplied prior customer preference text that support it. "
                "You may only remove proposed constraints, never add or change them. "
                "Use the exact heat-source ontology: card_stove=卡式炉, gas_stove=燃气炉, alcohol_stove=酒精炉, open_flame=明火, induction=电磁炉; never substitute another code. price_preference=affordable only for an explicit lower-budget/non-high-end preference, premium only for an explicit high-end preference. storage_preference=compact_storage only for an explicit preference for compact storage, nesting, folding, or taking little packing space. Schema exactly: {\"recommendation_constraints\":{...},\"evidence_spans\":{\"constraint_key\":[\"exact customer words\"]}}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "explicit_prior_customer_preference_texts": prior_texts,
                    "proposed_constraints": proposed_constraints,
                },
                ensure_ascii=False,
            ),
        },
    ]
    # A retained constraint without an evidence span is a malformed semantic
    # response. Retry once with the same semantic task instead of discarding
    # other valid customer constraints or handing route ownership to rules.
    for attempt in range(2):
        attempt_messages = [dict(message) for message in messages]
        if attempt:
            attempt_messages[0]["content"] += (
                " Your preceding JSON was invalid: every retained constraint key "
                "must include its own non-empty exact-literal evidence_spans entry. "
                "Complete that schema or remove only the constraint that lacks "
                "a literal source."
            )
        try:
            content = await customer_llm_service.chat_completion(
                db,
                attempt_messages,
                temperature=0,
                max_tokens=min(int(runtime_settings["max_tokens"]), 320),
                purpose="semantic_recommendation_constraint_grounding",
                api_model_override=runtime_settings["model"],
                response_format=runtime_settings["response_format"],
                thinking=runtime_settings["thinking"],
            )
        except Exception:
            continue
        data = _extract_json_object(content)
        if not isinstance(data, dict) or set(data) != {"recommendation_constraints", "evidence_spans"}:
            continue
        constraints = _validated_recommendation_constraints(data.get("recommendation_constraints"))
        spans = data.get("evidence_spans")
        if constraints is None or not isinstance(spans, dict):
            continue
        if set(spans) != set(constraints) or not _recommendation_constraints_are_subset(proposed_constraints, constraints):
            continue
        normalized_spans: dict[str, list[str]] = {}
        for key in constraints:
            values = spans.get(key)
            if not isinstance(values, list) or not values:
                normalized_spans = {}
                break
            normalized = [str(item or "").strip() for item in values]
            if any(not item or not any(item in source for source in evidence_texts) for item in normalized):
                normalized_spans = {}
                break
            normalized_spans[key] = list(dict.fromkeys(normalized))
        if set(normalized_spans) != set(constraints):
            continue
        # The semantic pass owns sentence meaning, but closed recommendation
        # enums still need an ontology-compatible source span: generic
        # “户外” must not become the stronger camping or hiking constraint.
        # Preserve the semantic judgment for weight preference, which has
        # legitimate sentence-level expressions such as “背起来不累”.
        constraints, normalized_spans = _recommendation_literal_grounding_filter(
            constraints,
            normalized_spans,
            preserve_semantic_subject_kind=True,
            preserve_semantic_weight_preference=True,
            preserve_semantic_storage_preference=True,
        )
        evidence_sources = {
            key: {
                span: "current_turn" if span in question else "prior_customer_turn"
                for span in spans
            }
            for key, spans in normalized_spans.items()
        }
        return {
            "recommendation_constraints": constraints,
            "evidence_spans": normalized_spans,
            "evidence_sources": evidence_sources,
        }
    return None


def _database_field_value_hints(db, question: str) -> list[dict[str, str]]:
    """Offer the semantic planner compact, data-derived catalogue vocabulary.

    A collection name often has no lexical marker such as “series”.  The model
    still owns the route decision, but it needs to know that a phrase in the
    current utterance is an actual value of a public catalogue field.  Hints
    are emitted only when a meaningful component of a stored value occurs in
    this turn; no SKU, product name, result, or fact is supplied.
    """
    normalized_question = customer_agent_service.normalize_search_text(question).lower()
    if db is None or not normalized_question:
        return []
    hints: list[dict[str, str]] = []
    field_columns = (
        ("series", Product.series),
        ("brand", Product.brand),
        ("category", Product.category),
        ("product_level", Product.product_level),
    )
    for field, column in field_columns:
        values = db.query(column).filter(column.isnot(None), column != "").distinct().all()
        for (raw_value,) in values:
            value = str(raw_value or "").strip()
            if not value:
                continue
            fragments = [part.strip() for part in re.split(r"[\-/|、，,；;]+", value) if part.strip()]
            fragments.append(value)
            for fragment in fragments:
                normalized_fragment = customer_agent_service.normalize_search_text(fragment).lower()
                if len(normalized_fragment) >= 2 and normalized_fragment in normalized_question:
                    hint = {"field": field, "value": value, "matched_text": fragment}
                    if hint not in hints:
                        hints.append(hint)
                    break
    return hints[:12]


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
    context = dict(context)
    context["database_field_value_hints"] = _database_field_value_hints(db, text)
    messages = _semantic_preplan_messages(question=text, deterministic_plan=deterministic_plan, context=context)
    feature_summary = _semantic_preplan_feature_summary(text, deterministic_plan, context)
    runtime_settings = _semantic_preplan_runtime_settings()
    llm_call_count = 0
    llm_metadata: dict[str, Any] = {}
    semantic_retry_count = 0
    semantic_retry_error = ""
    content = ""
    last_error: Exception | None = None
    for attempt in range(2):
        attempt_metadata: dict[str, Any] = {}
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
                metadata=attempt_metadata,
            )
            llm_call_count += 1
            llm_metadata = attempt_metadata
            last_error = None
            break
        except Exception as exc:
            llm_call_count += 1
            last_error = exc
            llm_metadata = attempt_metadata
            if attempt == 0 and _is_retryable_semantic_preplan_error(exc):
                semantic_retry_count = 1
                semantic_retry_error = type(exc).__name__
                # Yield once so a just-released provider slot can be acquired;
                # the retry stays bounded to this side-effect-free preplan.
                await asyncio.sleep(0)
                continue
            break
    if last_error is not None and not content:
        exc = last_error
        result = _deterministic_semantic_field_fallback(text)
        if result is None:
            result = _empty_semantic_preplan(called=True, fallback_reason=f"llm_error:{type(exc).__name__}")
        else:
            result["called"] = True
            result["error"] = f"llm_error:{type(exc).__name__}"
        result["llm_call_count"] = llm_call_count
        result["llm_call_count_delta"] = llm_call_count
        result["semantic_retry_count"] = semantic_retry_count
        if semantic_retry_error:
            result["semantic_retry_error"] = semantic_retry_error
        _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
        return result
    initial_semantic_data = _extract_json_object(content)
    initial_unrepresented_requirements = (
        _validated_unrepresented_recommendation_requirements(
            initial_semantic_data.get("unrepresented_recommendation_requirements")
        )
        if isinstance(initial_semantic_data, dict)
        else []
    )
    if initial_unrepresented_requirements is None or any(
        str(item) not in text for item in initial_unrepresented_requirements
    ):
        initial_unrepresented_requirements = []
    initial_soft_preferences = (
        _validated_recommendation_soft_preferences(
            initial_semantic_data.get("recommendation_soft_preferences")
        )
        if isinstance(initial_semantic_data, dict)
        else []
    )
    if initial_soft_preferences is None or any(
        str(item) not in text for item in initial_soft_preferences
    ):
        initial_soft_preferences = []
    result = _validate_semantic_preplan(initial_semantic_data, raw_content=content)
    unrepresented_requirements = result.get("unrepresented_recommendation_requirements") or []
    if any(str(item) not in text for item in unrepresented_requirements):
        # The semantic model may identify material gaps, but deterministic code
        # accepts only verbatim customer spans; it never infers a requirement.
        result["unrepresented_recommendation_requirements"] = []
        result["fallback_reason"] = "invalid_unrepresented_recommendation_requirements"
    soft_preferences = result.get("recommendation_soft_preferences") or []
    if any(str(item) not in text for item in soft_preferences):
        # As with hard gaps, only an exact customer span may enter the semantic
        # contract. This is provenance validation, never a lexical classifier.
        result["recommendation_soft_preferences"] = []
        result["fallback_reason"] = "invalid_recommendation_soft_preferences"
    result["semantic_retry_count"] = semantic_retry_count
    if semantic_retry_error:
        result["semantic_retry_error"] = semantic_retry_error
    _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
    # A high-confidence recommendation with an identified subject or formal
    # customer fields but no executable subject contract is incomplete semantic
    # output, not permission for a legacy keyword planner to decide the need.
    # Send only that semantic object back through the same schema repair path.
    # The repair remains an allowlisted LLM decision; deterministic code never
    # derives a subject kind from the customer's wording.
    recommendation_constraints = result.get("recommendation_constraints")
    if (
        result.get("route_family") == "recommendation"
        and not result.get("fallback_reason")
        and float(result.get("confidence") or 0) >= 0.9
        and (
            result.get("subject_text")
            or result.get("canonical_fields")
            or result.get("decision_requested")
        )
        and (
            not recommendation_constraints
            or (
                isinstance(recommendation_constraints, dict)
                and "subject_kind" not in recommendation_constraints
                and bool(result.get("subject_text"))
            )
        )
    ):
        result["fallback_reason"] = (
            "missing_recommendation_subject_kind"
            if recommendation_constraints else "missing_recommendation_constraints"
        )
    # A named-product question already understood as a factual request cannot
    # safely fall through to a legacy catalogue/KB route merely because the
    # first semantic JSON left its canonical field as ``unknown``.  Give the
    # same semantic model one bounded schema repair; the deterministic layer
    # still accepts only an allowlisted field and never supplies one itself.
    if (
        result.get("route_family") == "product_bound_qa"
        and result.get("question_type") == "field"
        and bool(result.get("evidence_required"))
        and str(result.get("field_type") or "") in {"", "unknown"}
        and set(result.get("canonical_fields") or []) <= {"unknown"}
        and not result.get("fallback_reason")
    ):
        result["fallback_reason"] = "unclassified_product_bound_field"
    # A structurally valid preplan can still be unusable when its
    # recommendation schema violates the contract.  Repair that semantic
    # output with the same LLM before considering any legacy label fallback;
    # otherwise an invalid optional constraint silently hands route ownership
    # back to the old planner.
    repairable_preplan_failures = {
        "invalid_json",
        "invalid_recommendation_constraints",
        "invalid_unrepresented_recommendation_requirements",
        "invalid_recommendation_soft_preferences",
        "recommendation_constraints_outside_recommendation",
        "invalid_structured_query_constraints",
        "structured_query_constraints_outside_structured_query",
        "structured_query_constraints_field_mismatch",
        "named_nonfilter_field_in_structured_query",
        "missing_structured_query_constraints",
        "missing_recommendation_constraints",
        "missing_recommendation_subject_kind",
        "missing_comparison_decision_criterion",
        "unclassified_product_bound_field",
        "invalid_comparison_decision_criterion",
        "invalid_comparison_participants",
        "self_conflicting_pairwise_decision_route",
        "pairwise_recommendation_requires_comparison_contract",
        "pairwise_factual_requires_comparison_contract",
    }
    if result.get("fallback_reason") in repairable_preplan_failures:
        raw_pairwise_entities = (
            [str(item or "").strip()[:200] for item in initial_semantic_data.get("entities", [])]
            if isinstance(initial_semantic_data, dict) and isinstance(initial_semantic_data.get("entities"), list)
            else []
        )
        preserved_pairwise_repair_intent = (
            {
                **dict(result),
                # Validation deliberately removes an invalid route from its
                # normal output. For a repair failure, retain only the
                # model-supplied participant spans so downstream code can ask
                # for a criterion instead of reopening catalogue selection.
                "route_family": "recommendation",
                "route_hint": "recommendation",
                "entities": raw_pairwise_entities,
                "canonical_fields": list(initial_semantic_data.get("canonical_fields") or []),
            }
            if (
                result.get("fallback_reason") == "pairwise_recommendation_requires_comparison_contract"
                and len(raw_pairwise_entities) >= 2
            )
            else None
        )
        try:
            repaired = await _repair_semantic_preplan_output(
                db,
                question=text,
                raw_content=content,
                failure_reason=str(result.get("fallback_reason") or ""),
            )
            llm_call_count += 1
        except Exception as exc:
            result["fallback_reason"] = f"repair_error:{type(exc).__name__}"
            result["error"] = str(exc)[:240]
            result["llm_call_count"] = llm_call_count
            result["llm_call_count_delta"] = llm_call_count
            _apply_semantic_preplan_observability(result, llm_metadata, runtime_settings)
            return result
        repaired_data = _extract_json_object(repaired)
        result = _validate_semantic_preplan(repaired_data, raw_content=repaired)
        # Structured comparison criteria occasionally remain empty or illegal
        # after the first repair even though the two customer-named entities
        # were valid. Retry this bounded, side-effect-free semantic repair once;
        # deterministic code still accepts only a formal field enum and never
        # supplies a comparison dimension itself.
        if (
            len(raw_pairwise_entities) >= 2
            and result.get("fallback_reason") in {
                "invalid_comparison_decision_criterion",
                "missing_comparison_decision_criterion",
            }
        ):
            try:
                repaired = await _repair_semantic_preplan_output(
                    db,
                    question=text,
                    raw_content=repaired,
                    failure_reason=str(result.get("fallback_reason") or ""),
                )
                llm_call_count += 1
                repaired_data = _extract_json_object(repaired)
                result = _validate_semantic_preplan(repaired_data, raw_content=repaired)
            except Exception as exc:
                result["fallback_reason"] = f"repair_error:{type(exc).__name__}"
                result["error"] = str(exc)[:240]
        # The full semantic replan occasionally repeats an invalid
        # recommendation partition while preserving every other valid route
        # field. Re-ask DeepSeek only for that partition rather than handing
        # route ownership to a lexical fallback or asking deterministic code to
        # infer a replacement field. The narrow response is schema- and
        # literal-validated before it is reattached to the same semantic plan.
        if result.get("fallback_reason") == "invalid_recommendation_constraints":
            partition_source = repaired_data if isinstance(repaired_data, dict) else initial_semantic_data
            partition_source = partition_source if isinstance(partition_source, dict) else {}
            partition = await _repair_semantic_recommendation_constraint_partition(
                db,
                question=text,
                invalid_constraints=partition_source.get("recommendation_constraints"),
                invalid_unrepresented_requirements=partition_source.get(
                    "unrepresented_recommendation_requirements"
                ),
            )
            llm_call_count += 1
            if partition is not None:
                repaired_partition_data = dict(partition_source)
                repaired_partition_data.update(partition)
                result = _validate_semantic_preplan(
                    repaired_partition_data,
                    raw_content=json.dumps(repaired_partition_data, ensure_ascii=False),
                )
        if initial_unrepresented_requirements and not result.get("fallback_reason"):
            # Repair may remove only malformed constraints.  A prior semantic
            # response that already supplied an exact customer requirement is
            # still valid intent and must not disappear merely because repair
            # shortened the JSON object.
            result["unrepresented_recommendation_requirements"] = initial_unrepresented_requirements
        if initial_soft_preferences and not result.get("fallback_reason"):
            # A schema repair may only repair malformed routing structure. It
            # must not erase an already validated semantic soft preference,
            # because no deterministic layer is permitted to recreate it.
            result["recommendation_soft_preferences"] = initial_soft_preferences
        if result.get("fallback_reason") and preserved_pairwise_repair_intent is not None:
            # The initial semantic response had already identified the two
            # participant spans.  If repair cannot express a formal criterion,
            # preserve that limited intent so downstream EntityResolution can
            # clarify safely instead of reopening a catalogue recommendation.
            preserved_pairwise_repair_intent["repair_failure"] = result.get("fallback_reason")
            result = preserved_pairwise_repair_intent
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
    proposed_constraints = result.get("recommendation_constraints")
    unrepresented_requirements = result.get("unrepresented_recommendation_requirements") or []
    soft_preferences = result.get("recommendation_soft_preferences") or []
    if (
        result.get("route_family") == "recommendation"
        and isinstance(proposed_constraints, dict)
        and proposed_constraints
        and not result.get("fallback_reason")
    ):
        try:
            reconciliation = await _semantic_recommendation_requirement_reconciliation(
                db,
                question=text,
                proposed_constraints=proposed_constraints,
                unrepresented_requirements=unrepresented_requirements,
                soft_preferences=soft_preferences,
                runtime_settings=runtime_settings,
            )
            llm_call_count += 1
        except Exception:
            reconciliation = None
            llm_call_count += 1
        if reconciliation is not None:
            result["recommendation_constraints"] = reconciliation["recommendation_constraints"]
            result["unrepresented_recommendation_requirements"] = reconciliation[
                "unrepresented_recommendation_requirements"
            ]
            result["recommendation_soft_preferences"] = reconciliation[
                "recommendation_soft_preferences"
            ]
            result["recommendation_requirement_reconciliation"] = "validated_semantic_reconciliation"
            result["recommendation_constraint_evidence_spans"] = reconciliation["evidence_spans"]
        proposed_constraints = result.get("recommendation_constraints")
    # The initial semantic preplan is the sole authority for whether a literal
    # customer requirement has no formal representation.  A second, isolated
    # model pass receives neither candidate evidence nor the first model's
    # reasoning, and was therefore reinterpreting already accepted semantic
    # constraints as new blockers (for example, turning a requested cookware
    # use into a broad clarification).  Keep the first plan's explicit spans;
    # downstream verification decides whether concrete candidates substantiate
    # them.  Deterministic code still validates the fixed schema and grounding.
    if (
        result.get("route_family") == "recommendation"
        and isinstance(proposed_constraints, dict)
        and proposed_constraints
        and not result.get("fallback_reason")
    ):
        try:
            grounding = await _semantic_recommendation_constraint_grounding(
                db,
                question=text,
                proposed_constraints=proposed_constraints,
                runtime_settings=runtime_settings,
                prior_customer_preference_texts=context.get("prior_customer_preference_texts"),
            )
            llm_call_count += 1
        except Exception:
            grounding = None
            llm_call_count += 1
        if grounding is None:
            # The second semantic review is allowed to remove constraints, not
            # to erase already validated literal provenance from the preceding
            # semantic reconciliation.  Re-check that provenance through the
            # same ontology contract and retain only what it can prove.  This
            # remains fail-closed: a missing or generic span (for example
            # ``户外`` for camping) is removed rather than broadened.
            reconciled_spans = result.get("recommendation_constraint_evidence_spans")
            if isinstance(reconciled_spans, dict):
                constraints, spans = _recommendation_literal_grounding_filter(
                    proposed_constraints,
                    reconciled_spans,
                )
                result["recommendation_constraints"] = constraints
                result["recommendation_constraint_evidence_spans"] = spans
                result["recommendation_constraint_evidence_sources"] = {
                    key: {span: "current_turn" if span in text else "prior_customer_turn" for span in values}
                    for key, values in spans.items()
                }
                result["recommendation_constraint_grounding"] = "reconciled_literal_contract_fallback"
            else:
                # Without a previous literal source span, an ungrounded
                # constraint must never narrow the catalogue or become a
                # fabricated customer need.
                result["recommendation_constraints"] = {}
                result["recommendation_constraint_grounding"] = "unavailable_or_invalid"
        else:
            result["recommendation_constraints"] = grounding["recommendation_constraints"]
            result["recommendation_constraint_evidence_spans"] = grounding["evidence_spans"]
            result["recommendation_constraint_evidence_sources"] = grounding["evidence_sources"]
            result["recommendation_constraint_grounding"] = "validated_semantic_grounding"
    result["llm_call_count"] = llm_call_count
    result["llm_call_count_delta"] = llm_call_count
    # A successful semantic preplan owns field meaning.  The compositional
    # classifier above is intentionally used only when that call fails; it
    # must not turn into a second router that overwrites a valid, contextual
    # semantic decision because of a token in the question.
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

    compare_refs = _extract_compare_product_refs(text)
    multi_sku_intro = _is_multi_sku_intro_question(text, compare_refs)
    if (_is_compare_question(text) or multi_sku_intro) and not _is_generic_category_compare_recommendation(text, compare_refs):
        products = compare_refs
        # A comparison can carry a second decision task after the pairwise
        # analysis ("compare A/B, then recommend ...").  Preserve both tasks
        # in one plan rather than returning early with a lossy comparison-only
        # route.
        must_make_choice = _is_compare_choice_question(text) or _has_following_recommendation_request(text)
        plan.update(
            {
                "primary_intent": "product_compare_recommendation" if must_make_choice else "comparison",
                "answer_type": "comparison",
                "product_refs": products,
                "scenario": "两个人吃饱" if _has_two_person_signal(text) else "",
                "constraints": ["两人", "容量够", "户外吃饭"],
                "must_compare_both_products": True,
                "must_make_choice": must_make_choice,
                "comparison_kind": "multi_sku_intro" if multi_sku_intro else "comparison",
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

    # A single-product heat-source shortcut is valid only after comparison
    # arbitration.  Otherwise the first explicit SKU in “A 和 B 的热源有何
    # 不同” would discard B before the two-entity evidence contract forms.
    explicit_heat_source_compatibility = _explicit_product_alcohol_stove_compatibility(text)
    if explicit_heat_source_compatibility:
        plan.update(explicit_heat_source_compatibility)
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
    # A relation request can list explicit products with enumeration marks
    # (A、B、C 三者是什么关系) rather than the binary conjunction "和".
    # Once two or more explicit references are present, its comparison intent
    # is carried by the complete utterance, not by one fixed separator.
    return any(term in text for term in ("区别", "不同", "对比", "比较", "关系", "哪个", "哪款", "更适合", "该买", "应该买", "买哪个"))


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
    # Reuse the canonical SKU extractor.  A loose regex can consume adjacent
    # natural-language characters after the last SKU, which turns an exact
    # multi-entity request into a false unresolved reference.
    sku_refs = list(dict.fromkeys(
        str(item or "").strip().upper().replace("_", "-")
        for item in customer_agent_service._extract_skus(text)
        if str(item or "").strip()
    ))
    if len(sku_refs) >= 2:
        return sku_refs[:3]
    for name in ("行山单锅", "激川单锅", "轻途套锅", "享野套锅"):
        if name in text:
            products.append(name)
    if products:
        return products
    if "和" in text:
        left, right = text.split("和", 1)
        right = right.split("的", 1)[0].split("，", 1)[0].split(",", 1)[0]
        candidate_refs = [left.strip("「」 ？?"), right.strip("「」 ？?")]
        # The conjunction is not itself evidence of two product identities.
        # In a scenario sentence it commonly joins needs (for example cooking
        # and boiling water); treating the entire clauses as products turns a
        # recommendation into a fabricated comparison.  Preserve the generic
        # natural-name fallback only for bounded product-shaped references;
        # explicit SKU and known-name paths above remain authoritative.
        product_suffixes = ("锅", "套锅", "炉", "炉具", "壶", "水壶", "杯", "盘", "烤盘", "煎盘", "版", "款")
        if all(
            1 < len(candidate) <= 40
            and not any(mark in candidate for mark in ("。", "！", "？", "；", "：", "\n"))
            and any(candidate.endswith(suffix) for suffix in product_suffixes)
            for candidate in candidate_refs
        ):
            return candidate_refs
    return []


def _is_multi_sku_intro_question(text: str, refs: list[str] | None = None) -> bool:
    products = refs if refs is not None else _extract_compare_product_refs(text)
    return len(products) >= 2 and any(
        term in str(text or "")
        for term in ("分别介绍", "分别说说", "分别讲讲", "各自介绍", "各自说说", "逐个介绍")
    )


def _has_following_recommendation_request(text: str) -> bool:
    value = str(text or "")
    if "推荐" not in value:
        return False
    return any(term in value for term in ("更适合", "适合", "选哪个", "选哪", "应该选", "应该买", "买哪个"))


def _is_catalog_count_question(text: str) -> bool:
    # Count intent is a grammatical category request, not a fixed sentence.
    # Accept optional discourse prefixes while requiring the quantifier to bind
    # directly to a supported category noun. This avoids confusing a product
    # field question such as "这口锅容量多少" with a catalog count.
    category_count = bool(re.search(
        r"(?:有\s*)?(?:多少|几)\s*(?:个|款|种|类)?\s*"
        r"(?:锅具|锅|炉具|炉子|炉|水具|水壶|配件|附件|餐具|桌椅|咖啡器具|茶具|烤盘|煎盘)"
        r"(?:产品|商品)?(?:\s*[？?！!。.]|\s*$)",
        text,
    ))
    if category_count:
        return True
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
    if "锅" in text:
        return "锅具"
    if "炉" in text:
        return "炉具"
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
