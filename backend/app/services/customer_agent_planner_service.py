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
    # A timeout already consumed the whole semantic-planning budget. Retrying
    # it here only doubles the customer's wait and then activates a legacy
    # outage route. Other transport failures can still be transient and get
    # one retry.
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
        # Retry only statuses that can plausibly be transient.  In particular,
        # a 402 from the provider means the configured account has no balance;
        # repeating the same paid request cannot recover it and only adds
        # latency. Authentication, permission, validation, and not-found
        # responses likewise remain fail-closed without a pointless retry.
        return status_code in {408, 409, 425, 429} or 500 <= status_code <= 599
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

_EXPLICIT_NUMERIC_VERSION_RE = re.compile(
    r"(?:(?:\bv\s*)(\d+(?:\.\d+)+)|(\d+(?:\.\d+)+)\s*(?:版本|版))",
    re.IGNORECASE,
)


def _semantic_subject_omits_explicit_numeric_version(question: str, subject: str) -> bool:
    """Validate subject-span retention; never infer a product or SKU."""
    question_versions = {
        str(match.group(1) or match.group(2) or "").strip().lower()
        for match in _EXPLICIT_NUMERIC_VERSION_RE.finditer(str(question or ""))
        if str(match.group(1) or match.group(2) or "").strip()
    }
    if not question_versions:
        return False
    subject_versions = {
        str(match.group(1) or match.group(2) or "").strip().lower()
        for match in _EXPLICIT_NUMERIC_VERSION_RE.finditer(str(subject or ""))
        if str(match.group(1) or match.group(2) or "").strip()
    }
    return not question_versions.issubset(subject_versions)


SEMANTIC_PREPLAN_ROUTE_HINTS = {
    "usage_care",
    "recommendation",
    "accessory",
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
    "comparison_overview",
    "recommendation",
    "structured_query",
    "generic_query",
    "no_match",
    "navigation",
    "safety_procedure",
    "recommendation_change",
    "comparison_justification",
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
    # This is a semantic discourse scope, not a product identity.  The
    # service binds it to the opaque result positions supplied in the current
    # conversation; the provider must never emit a SKU for it.
    "prior_results",
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
    "general_chat",
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
    "predicate_constraints",
    "structured_query_constraints",
    "unrepresented_recommendation_requirements",
    "recommendation_evidence_requirements",
    "recommendation_soft_preferences",
    "recommendation_followup_action",
    "information_scope",
    "subject_text", "canonical_fields", "ambiguity", "evidence_required", "evidence_kind", "qa_evidence_query", "qa_evidence_queries", "supplemental_qa_evidence_query", "compound", "intent_coverage", "context_usage", "context_result_indexes", "decision_requested", "reasoning_summary",
}
# These two values are server-side context hints placed in the planner input.
# A provider may echo them back while returning an otherwise valid plan. They
# are not part of the semantic output contract and must not erase route
# ownership through the generic unknown-key check.
SEMANTIC_PREPLAN_CONTEXT_ECHO_KEYS = {
    "has_unique_current_turn_catalog_product_name",
    "unique_current_turn_catalog_product_mention",
}
# Some providers add a second, convenience-shaped view of product context to
# the semantic response.  The canonical ``entities`` packet is the only model
# output that may describe current-turn mentions; these decorations are not
# part of the plan and must not make an otherwise valid recommendation fall
# back to the legacy parser.  Dropping them also prevents a model-created
# identity from entering downstream catalogue resolution.
SEMANTIC_PREPLAN_PROVIDER_DECORATION_KEYS = {
    "comparison_participants",
    "product_anchor",
    # Older/alternate Flash response shapes sometimes echo these convenience
    # views alongside the canonical semantic plan.  They do not carry route
    # ownership or catalogue facts; entities and recommendation fields are the
    # only values consumed downstream.  Treat them as provider decoration so a
    # valid semantic recommendation is not converted into a legacy fallback
    # merely because the provider added these keys.
    "product_mention",
    "recommendation_context",
}
# These keys are added to an accepted plan by the server for tracing and
# fallback diagnostics.  A later semantic repair may re-submit that accepted
# plan as its context; they are not part of the provider's semantic contract
# and must not become ``unexpected_keys`` on that second validation.
SEMANTIC_PREPLAN_SERVER_METADATA_KEYS = {
    "called",
    "purpose",
    "confidence_label",
    "accepted_or_overridden",
    "override_reason",
    "fallback_reason",
    "llm_call_count",
    "llm_call_count_delta",
    "raw_preview",
    "preplan_model",
    "preplan_temperature",
    "preplan_max_tokens",
    "preplan_json_mode",
    "preplan_thinking_disabled",
    "preplan_latency_ms",
    "provider_usage_available",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "reasoning_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "semantic_retry_count",
    "semantic_retry_error",
    "semantic_context_repair_unavailable",
    "semantic_context_repair_error",
    "semantic_adapter_source",
    "accessory_scope_recovery",
    "repair_failure",
    "error",
    "provider_status_code",
    "provider_model",
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
        "qa_evidence_queries": [],
        "supplemental_qa_evidence_query": "",
        "compound": False,
        "intent_coverage": "full",
        "context_usage": "none",
        "context_result_indexes": [],
        "decision_requested": False,
        "information_scope": "",
        "recommendation_constraints": {},
        "predicate_constraints": [],
        "structured_query_constraints": [],
        "unrepresented_recommendation_requirements": [],
        "recommendation_evidence_requirements": [],
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
        # The full semantic contract can legitimately contain several fields,
        # entities and provenance clauses. Provider tokenization has produced
        # truncated JSON below the historical 512-token cap even with thinking
        # disabled, so keep enough output room for the contract to close.
        "max_tokens": max(768, int(settings.SEMANTIC_PREPLAN_MAX_TOKENS)),
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
    result["provider_status_code"] = (metadata or {}).get("provider_status_code")
    result["provider_model"] = (metadata or {}).get("provider_model")
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
    if family == "general_chat":
        return {"route_hint": "clarification", "question_type": "field", "subtype": "generic_query"}
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
    allowed = {"subject_kind", "people", "heat_sources", "scenarios", "weight_preference", "price_preference", "storage_preference", "dishwasher_safe"}
    if any(key not in allowed for key in value):
        return None
    result: dict[str, Any] = {}
    subject_kind = value.get("subject_kind")
    if subject_kind is not None:
        if (
            not isinstance(subject_kind, str)
            or subject_kind not in {"cookware", "waterware", "stove", "coffee_gear", "accessories"}
        ):
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
    dishwasher_safe = value.get("dishwasher_safe")
    if dishwasher_safe is not None:
        if dishwasher_safe is not True:
            return None
        result["dishwasher_safe"] = True
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
    """Validate bounded semantic context without reinterpreting its wording.

    The Flash preplan owns the meaning of these strings.  They are passed to
    retrieval and answer writing as customer context; they are never product
    facts and never act as a literal answer gate.  Deterministic code only
    protects the request size and JSON shape.
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
    """Validate bounded semantic priorities supplied by the preplan."""
    return _validated_unrepresented_recommendation_requirements(value)


def _validated_recommendation_evidence_requirements(value: Any) -> list[str] | None:
    """Validate bounded semantic suitability context for RAG and writing.

    This array is deliberately not a lexical gate.  Same-SKU verification still
    owns numeric, material, heat-source, and other structured product facts;
    this array carries the meaning that those fields cannot fully encode.
    """
    return _validated_unrepresented_recommendation_requirements(value)


_SEMANTIC_STRUCTURED_QUERY_OPERATORS = {
    "material": {"contains"},
    "surface_finish": {"contains", "="},
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
    allow_empty_value_scope: bool = False,
) -> list[dict[str, Any]] | None:
    """Validate semantic predicate structure without accepting product facts.

    The values remain provisional customer-language spans.  The structured
    contract adapter later proves each span occurs in the original question,
    then evaluates it against a product's own database columns.
    """
    if value is None:
        return []
    if value == []:
        return []
    if not isinstance(value, list) or not (1 <= len(value) <= 8):
        return None
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"field", "operator", "value", "evidence_span", "unit", "importance"}:
            return None
        field = customer_field_contract.semantic_preplan_field_type(item.get("field"))
        operator = str(item.get("operator") or "").strip()
        # Providers occasionally express compatibility as a text containment
        # test ("heat_source contains card_stove") even though the sealed
        # product contract names the relation ``supports``.  Normalize that
        # typed relation here; do not reject the whole semantic request or
        # re-read the customer's wording with a second parser.
        if field == "heat_source" and operator in {"contains", "="}:
            operator = "supports"
        evidence_span = str(item.get("evidence_span") or "").strip()
        raw_value = item.get("value")
        unit = item.get("unit")
        importance = str(item.get("importance") or "required").strip().lower()
        if (
            field not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS
            or operator not in _SEMANTIC_STRUCTURED_QUERY_OPERATORS[field]
            or not evidence_span
            or len(evidence_span) > 80
            or EXPLICIT_SKU_RE.search(evidence_span)
            or PLAIN_EXPLICIT_SKU_RE.search(evidence_span)
            or importance not in {"required", "preferred"}
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
        # Numeric predicates are transport data, not free-form semantic
        # labels.  A provider occasionally emits a sentinel such as
        # ``"unknown"`` for a preference like “轻便”.  Treat that one item as
        # malformed so recommendation-level partial retention can keep the
        # rest of the model's meaning (for example the hiking scene) instead
        # of sending an unusable numeric predicate to the verifier and losing
        # the whole recommendation.
        if field in {"capacity", "weight", "people"}:
            numeric_value = (
                isinstance(normalized_value, list)
                and operator == "between"
                and len(normalized_value) == 2
                and all(type(part) in {int, float} for part in normalized_value)
            ) or type(normalized_value) in {int, float}
            if not numeric_value:
                return None
        # The quoted span proves current-turn provenance; the model may
        # normalize its meaning (for example, “表面要不粘” to the
        # surface-finish value “不粘涂层”).  Requiring that normalized value to
        # occur verbatim in the span recreated the old wording gate and made
        # harmless paraphrases lose otherwise valid predicates.
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
        # Keep the migration shape backward-compatible for callers that still
        # emit the original five-key predicate object. New semantic plans may
        # add importance so the executor can distinguish eligibility from
        # ranking without interpreting customer wording in Python.
        if "importance" in item:
            normalized["importance"] = importance
        if normalized not in result:
            result.append(normalized)
    return result


def _literal_customer_phrase_partition(question: str, values: Any) -> list[str]:
    """Compatibility helper for callers that still need a bounded text list.

    Semantic context may be a paraphrase of the customer's wording.  It is not
    an answer phrase contract, so this helper no longer performs substring
    matching against the current turn.
    """
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(
        phrase
        for phrase in (str(item or "").strip() for item in values)
        if phrase and len(phrase) <= 80
    ))


def _recommendation_semantic_context_present(value: dict[str, Any] | None) -> bool:
    """Whether a recommendation plan contains meaning the executor can use.

    ``decision_requested`` only says that the customer wants a choice.  It is
    not a product scope or a preference by itself.  Keeping that distinction
    structural prevents a provider response that lost the whole sentence from
    becoming an arbitrary catalogue recommendation.
    """
    if not isinstance(value, dict):
        return False
    constraints = value.get("recommendation_constraints")
    result_context_selection = bool(
        str(value.get("context_usage") or "").strip() == "result_context"
        and value.get("context_result_indexes")
        and bool(value.get("decision_requested"))
    )
    return bool(
        isinstance(constraints, dict) and constraints
        or str(value.get("subject_text") or "").strip()
        or value.get("predicate_constraints")
        or value.get("structured_query_constraints")
        or value.get("recommendation_evidence_requirements")
        or value.get("unrepresented_recommendation_requirements")
        or value.get("recommendation_soft_preferences")
        or result_context_selection
    )


def _validate_semantic_preplan(
    data: dict[str, Any] | None,
    *,
    raw_content: str = "",
    customer_question: str = "",
) -> dict[str, Any]:
    if not isinstance(data, dict):
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_json")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    data = dict(data)
    for key in SEMANTIC_PREPLAN_SERVER_METADATA_KEYS:
        data.pop(key, None)
    for key in SEMANTIC_PREPLAN_CONTEXT_ECHO_KEYS:
        data.pop(key, None)
    for key in SEMANTIC_PREPLAN_PROVIDER_DECORATION_KEYS:
        data.pop(key, None)
    # Providers occasionally wrap product mentions in one semantic entity
    # packet instead of the compact list requested by the contract. Preserve
    # those participant spans and their scope; catalogue resolution still
    # seals every identity before any product fact can be returned.
    entity_packet = data.get("entities")
    if isinstance(entity_packet, dict):
        product_mentions = entity_packet.get("product_mentions")
        data["entities"] = product_mentions if isinstance(product_mentions, list) else []
        if not str(data.get("entity_scope") or "").strip():
            data["entity_scope"] = entity_packet.get("entity_scope") or ""
    provider_subtype_hint = str(data.get("subtype") or "").strip()
    if (
        provider_subtype_hint in {"comparison", "comparison_justification"}
        and isinstance(data.get("entities"), list)
        and len(data.get("entities") or []) >= 2
    ):
        # Two model-supplied participant slots define a pairwise contract even
        # when the provider mislabeled that contract as product-bound QA. This
        # normalizes route shape only; it does not infer identities or a winner.
        data["route_family"] = "comparison"
        data["route_hint"] = "comparison"
        data["question_type"] = "comparison"
        data["subtype"] = (
            "comparison_justification"
            if provider_subtype_hint == "comparison_justification"
            else ""
        )
    for short_key, long_key in SEMANTIC_PREPLAN_SHORT_KEY_MAP.items():
        if long_key not in data and short_key in data:
            data[long_key] = data[short_key]
    forbidden = sorted(key for key in data if key in SEMANTIC_PREPLAN_FORBIDDEN_KEYS)
    route_family = str(data.get("route_family") or "").strip()
    route_hint = str(data.get("route_hint") or "").strip()
    question_type = str(data.get("question_type") or "").strip()
    provider_subtype = str(data.get("subtype") or "").strip()
    defaults = _semantic_route_family_defaults(route_family)
    if defaults:
        route_hint = route_hint or str(defaults.get("route_hint") or "")
        question_type = question_type or str(defaults.get("question_type") or "")
        data["subtype"] = data.get("subtype") or defaults.get("subtype") or ""
        if defaults.get("unknown_field"):
            data["unknown_field"] = True
    confidence, confidence_label = _semantic_confidence_parts(data.get("confidence"))
    # ``route_family`` is the semantic decision.  ``route_hint`` is only a
    # compatibility label for the older executor, and providers sometimes
    # return a useful description there (for example, "recommendation with a
    # compatibility preference") instead of the legacy enum.  Do not throw
    # away an otherwise valid semantic plan because of that presentation
    # detail; derive the compatibility label from the already accepted route
    # family.  This keeps natural-language interpretation with Flash and keeps
    # the local adapter concerned only with the transport shape.
    if route_hint not in SEMANTIC_PREPLAN_ROUTE_HINTS:
        route_hint = str(defaults.get("route_hint") or "") if defaults else ""
    if question_type and question_type not in SEMANTIC_PREPLAN_QUESTION_TYPES:
        # Like route_hint, question_type is a compatibility label.  A
        # descriptive provider value must not erase the already valid route
        # family; use that family's canonical transport shape instead.
        question_type = str(defaults.get("question_type") or "") if defaults else ""
    raw_entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    entities: list[str] = []
    for raw_entity in raw_entities[:8]:
        # The compact semantic schema permits a structured product mention
        # (``{entity_type: product, entity_value: ...}``) as well as the
        # legacy string form.  This is a shape adaptation only: the value is
        # still required to occur in the customer turn and is later sealed by
        # EntityResolutionContract, so it never accepts an LLM SKU decision.
        if isinstance(raw_entity, dict):
            entity_type = str(
                raw_entity.get("entity_type") or raw_entity.get("type") or ""
            ).strip()
            if entity_type and entity_type != "product":
                continue
            candidate = raw_entity.get("entity_value")
            if candidate is None:
                candidate = raw_entity.get("name")
            if candidate is None:
                candidate = raw_entity.get("entity_name")
            if candidate is None:
                candidate = raw_entity.get("entity")
        else:
            candidate = raw_entity
        if not isinstance(candidate, str):
            continue
        entity = candidate.strip()
        if entity:
            entities.append(entity)
    raw_context_result_indexes = data.get("context_result_indexes", [])
    if not isinstance(raw_context_result_indexes, list):
        invalid_result = _empty_semantic_preplan(called=True, fallback_reason="invalid_context_result_indexes")
        invalid_result["raw_preview"] = _safe_preview(raw_content)
        return invalid_result
    context_result_indexes: list[int] = []
    for raw_index in raw_context_result_indexes:
        # These are one-based opaque handles supplied by the server.  They are
        # not SKUs and cannot select anything outside the persisted result set.
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            invalid_result = _empty_semantic_preplan(called=True, fallback_reason="invalid_context_result_indexes")
            invalid_result["raw_preview"] = _safe_preview(raw_content)
            return invalid_result
        if raw_index < 1 or raw_index > 12 or raw_index in context_result_indexes:
            invalid_result = _empty_semantic_preplan(called=True, fallback_reason="invalid_context_result_indexes")
            invalid_result["raw_preview"] = _safe_preview(raw_content)
            return invalid_result
        context_result_indexes.append(raw_index)
    field_hint = data.get("field_hint")
    field_hint = str(field_hint).strip() if field_hint is not None and str(field_hint).strip() else None
    raw_subtype = str(data.get("subtype") or "").strip()
    subtype = raw_subtype
    entity_scope = str(data.get("entity_scope") or "").strip()
    # Providers use a few descriptive labels for the same discourse scope
    # (for example ``prior_context`` or ``prior_selection``).  Normalize that
    # transport variation before schema validation.  It does not resolve an
    # identity and it does not inspect customer wording; the service later
    # maps the scope only to server-owned opaque result positions.
    entity_scope_lower = entity_scope.lower()
    if (
        entity_scope_lower.startswith(("prior_", "previous_"))
        or entity_scope_lower in {"result_context", "result_set"}
    ):
        entity_scope = "prior_results"
    information_scope = str(data.get("information_scope") or "").strip()
    field_type = str(data.get("field_type") or "").strip()
    decision_requested = (
        data.get("decision_requested") is True
        or str(data.get("decision_requested") or "").strip().lower()
        in {"true", "yes", "selection", "select", "choice", "choose", "recommendation"}
    )
    if not route_family:
        route_family = _semantic_route_family_from_legacy(route_hint, question_type, subtype)
    if route_family not in SEMANTIC_PREPLAN_ROUTE_FAMILIES:
        route_family = ""
    defaults = _semantic_route_family_defaults(route_family)
    if defaults:
        route_hint = route_hint or str(defaults.get("route_hint") or "")
        question_type = question_type or str(defaults.get("question_type") or "")
        data["subtype"] = data.get("subtype") or defaults.get("subtype") or ""
        subtype = str(data.get("subtype") or "").strip()
        if defaults.get("unknown_field"):
            data["unknown_field"] = True
    if subtype not in SEMANTIC_PREPLAN_SUBTYPES:
        if route_family == "comparison":
            # The subtype is descriptive context, not a second intent router.
            # Preserve the already validated comparison route and normalize a
            # provider-specific label to the ordinary relation contract. The
            # semantic model still owns the criterion and result-context
            # handles; no product identity or fact is inferred here.
            subtype = "relation_comparison"
        # Providers sometimes use a descriptive subtype such as
        # ``single_product_fact`` or the canonical field name.  Once the
        # schema-valid route already says this is a product-bound fact, that
        # descriptive label must not erase the route's established detail
        # shape.  This only normalizes route structure: the FieldContract
        # still applies its allowlist and the service still seals entity and
        # same-SKU evidence independently.
        if route_family == "product_bound_qa":
            subtype = str(defaults.get("subtype") or "")
        elif route_family == "unknown_realtime":
            # Providers may describe the commercial fact as
            # ``purchasability`` / ``availability`` instead of reusing the
            # implementation enum. Keep the semantic safety route and map it
            # to its existing contract subtype; no field, product, or answer
            # is inferred here.
            subtype = "commercial_realtime"
        else:
            subtype = ""
    if entity_scope not in SEMANTIC_PREPLAN_ENTITY_SCOPES:
        entity_scope = ""
    if information_scope not in SEMANTIC_PREPLAN_INFORMATION_SCOPES:
        information_scope = ""
    field_type = customer_field_contract.semantic_preplan_field_type(field_type)
    field_hint = customer_field_contract.semantic_preplan_field_type(field_hint) if field_hint else None
    if field_type not in SEMANTIC_PREPLAN_FIELD_TYPES:
        field_type = ""
    raw_canonical_fields = data.get("canonical_fields") if isinstance(data.get("canonical_fields"), list) else []
    normalized_canonical_fields = [
        customer_field_contract.semantic_preplan_field_type(item)
        for item in raw_canonical_fields
    ]
    unknown_canonical_fields = [
        str(raw_item or "").strip()
        for raw_item, normalized_item in zip(raw_canonical_fields, normalized_canonical_fields)
        if str(raw_item or "").strip()
        and (not normalized_item or normalized_item not in SEMANTIC_PREPLAN_FIELD_TYPES)
    ]
    canonical_fields = list(dict.fromkeys(item for item in normalized_canonical_fields if item in SEMANTIC_PREPLAN_FIELD_TYPES and item))
    # Catalogue listings may ask for display columns such as product name and
    # SKU. Those columns describe how returned rows should be presented; they
    # are not product-bound identity fields and are not executable filters.
    # Keep the semantic catalogue scope and let the live catalogue executor
    # render its own verified name/SKU columns. An explicit current-turn SKU
    # is deliberately excluded from this normalization because it belongs to
    # the product-bound identity contract instead.
    catalogue_display_fields = {"product_name_cn", "product_name_en", "sku"}
    catalogue_display_listing_shape = (
        route_family == "structured_query"
        and question_type in {"count", "filter"}
        and canonical_fields
        and set(canonical_fields).issubset(catalogue_display_fields)
        and not any(
            EXPLICIT_SKU_RE.search(entity) or PLAIN_EXPLICIT_SKU_RE.search(entity)
            for entity in entities
        )
    )
    if catalogue_display_listing_shape:
        canonical_fields = ["category"]
        data["canonical_fields"] = ["category"]
        if str(data.get("field_type") or "").strip() in catalogue_display_fields:
            data["field_type"] = "category"
    raw_evidence_kind = str(data.get("evidence_kind") or "").strip()
    # The source scope is model-owned semantic context. Once Flash explicitly
    # says that the customer wants an answer according to a knowledge source,
    # keep that provenance contract even if it also returned a generic-chat
    # family or a usage-care subtype. This does not inspect the customer's
    # wording or select any document; the document RAG executor does that.
    if information_scope == "knowledge_base_meta" and not entities and not canonical_fields:
        route_family = "knowledge_base_meta"
        route_hint = "clarification"
        question_type = "field"
        data["evidence_required"] = False
    elif route_family == "knowledge_base_meta":
        information_scope = "knowledge_base_meta"
    # Let the model's own usage-care signal correct an accidental catalogue
    # family label.  This keeps category-level safety/maintenance guidance in
    # the non-product writer without inspecting the customer's wording or
    # adding another phrase route.  A named/anchored product remains product
    # bound and is not changed here.
    model_marks_usage_care = bool(data.get("qa_or_usage_care")) or subtype in {
        "safety_procedure",
        "usage_care",
    }
    if (
        route_family in {"structured_query", "generic_query"}
        and model_marks_usage_care
        and not entities
        and not canonical_fields
    ):
        route_family = "general_chat"
        route_hint = "clarification"
        question_type = "safety" if subtype == "safety_procedure" else "usage"
        subtype = subtype if subtype in {"safety_procedure", "usage_care"} else "usage_care"
        data["evidence_required"] = False
        data["qa_or_usage_care"] = True
    # Category-level care guidance may still carry the model's internal
    # ``care``/``usage_instruction`` labels (and a generic noun such as
    # “锅”) even though it has no product entity.  Those labels describe the
    # kind of guidance requested; they are not a structured product field.
    # Clear them before the general-chat invariant below so the semantic plan
    # reaches the category RAG writer instead of being rejected and handed to
    # the legacy recovery/template path.
    general_care_field_shape = bool(canonical_fields) and set(canonical_fields).issubset(
        {"cleaning", "care", "usage_instruction"}
    )
    if (
        route_family == "general_chat"
        and not entities
        and (model_marks_usage_care or general_care_field_shape)
    ):
        canonical_fields = []
        field_type = ""
        field_hint = None
        data["canonical_fields"] = []
        data["field_type"] = ""
        data["field_hint"] = None
        data["qa_or_usage_care"] = True
    # Backward-compatible semantic shape: before ``evidence_kind`` became a
    # required key, a product-bound plan with no canonical field was already
    # the model's only way to say “use same-SKU QA”.  Preserve that semantic
    # decision rather than allowing aliases to reclassify it as a column.
    evidence_kind = raw_evidence_kind or (
        "product_qa"
        if route_family == "product_bound_qa" and not canonical_fields and not field_type and not field_hint
        else "structured_field"
    )
    # Recommendation selection has its own request/evidence contract.
    # This product-fact retrieval label must not invalidate a complete plan.
    if route_family == "recommendation":
        evidence_kind = "structured_field"
    # A catalogue browse/list/count is itself the structured retrieval scope;
    # provider labels such as "none" or "catalog" describe the operation but
    # are not a separate evidence class. Normalize that transport variation so
    # display-column requests can reach the catalogue RAG executor.
    if route_family == "structured_query":
        evidence_kind = "structured_field"
    # Product navigation establishes or clarifies identity; it does not answer
    # a product fact. Provider evidence labels are therefore non-authoritative
    # and must not erase an otherwise complete navigation decision.
    if route_family == "product_navigation":
        evidence_kind = "structured_field"
        data["evidence_required"] = False
    # General guidance is explicitly non-evidentiary in the route ontology.
    # Provider-specific labels such as "general_knowledge" describe how the
    # model thought about the turn, but cannot turn a general-chat route into
    # a catalogue fact request or invalidate the otherwise complete decision.
    if route_family == "general_chat":
        evidence_kind = "structured_field"
        data["evidence_required"] = False
    if evidence_kind not in {"structured_field", "product_qa"}:
        # The provider sometimes returns a transport-shaped label such as
        # ``structured``/``field``/``qa`` instead of the two public evidence
        # classes.  This is a schema compatibility issue, not a different
        # customer intent. Preserve the already accepted semantic route and
        # choose the source class from the model's explicit field contract;
        # never infer a field, product, or fact here. Comparison and
        # product-bound plans are especially important because dropping them
        # at this point loses the named identity before RAG can run.
        evidence_kind_aliases = {
            "structured": "structured_field",
            "field": "structured_field",
            "structured_fields": "structured_field",
            "structured_fact": "structured_field",
            "qa": "product_qa",
            "productqa": "product_qa",
            "product_qa_evidence": "product_qa",
        }
        normalized_alias = evidence_kind_aliases.get(evidence_kind.casefold())
        if normalized_alias:
            evidence_kind = normalized_alias
        elif route_family in {"comparison", "product_bound_qa"}:
            evidence_kind = "structured_field" if (
                canonical_fields or field_type or field_hint
            ) else "product_qa"
        else:
            result = _empty_semantic_preplan(called=True, fallback_reason="invalid_evidence_kind")
            result["raw_preview"] = _safe_preview(raw_content)
            result["raw_evidence_kind"] = raw_evidence_kind
            return result
    # A realtime-safe route never retrieves product QA. Providers sometimes
    # carry a generic product-QA evidence label while correctly classifying
    # the whole question as current purchasability/availability; retain the
    # safety route and normalize the non-answering source shape.
    if route_family == "unknown_realtime":
        evidence_kind = "structured_field"
    # A non-decisive comparison overview asks for recorded same-field
    # differences. Some provider schemas label that retrieval as product_qa
    # despite also returning the explicit overview subtype. Normalize this
    # internal schema contradiction before it can suppress available
    # structured evidence; no field or product fact is inferred here.
    if (
        route_family == "comparison"
        and subtype == "comparison_overview"
        and not bool(data.get("decision_requested"))
        and not canonical_fields
        and not field_type
        and not field_hint
    ):
        evidence_kind = "structured_field"
    # A formal field and product-QA evidence are mutually exclusive semantic
    # claims.  The allowlisted canonical field is the semantic decision about
    # what the customer asked; evidence_kind only selects the downstream source
    # class.  Preserve the accepted field and normalize its incompatible source
    # class to structured evidence.  This never derives a field from wording,
    # identity, or data -- it prevents an incidental QA label from erasing the
    # model's explicit high-confidence field contract.
    if evidence_kind == "product_qa" and (canonical_fields or field_type or field_hint):
        evidence_kind = "structured_field"
    # ``product_qa`` is a semantic decision that the customer asks for a
    # product-specific capability, judgement, or procedure for which the
    # authoritative source is same-SKU QA rather than a structured column.
    # It intentionally clears compatibility mirrors as well: otherwise a
    # keyword/alias from the question would silently recreate the very field
    # the model rejected.  Identity and QA evidence are sealed downstream.
    if evidence_kind == "product_qa":
        # A knowledge-base procedure may be retrieved from product QA/profile
        # chunks as category evidence.  The document executor keeps the
        # answer unbound and forbids product recommendation; rejecting this
        # source label here only hands the turn to the old usage-care route.
        if route_family not in {"product_bound_qa", "comparison", "knowledge_base_meta"}:
            result = _empty_semantic_preplan(called=True, fallback_reason="product_qa_outside_product_bound_route")
            result["raw_preview"] = _safe_preview(raw_content)
            return result
        canonical_fields = []
        field_type = ""
        field_hint = None
    qa_evidence_query = str(data.get("qa_evidence_query") or "").strip()[:160]
    supplemental_qa_evidence_query = str(data.get("supplemental_qa_evidence_query") or "").strip()[:160]
    if (
        route_family == "comparison"
        and evidence_kind == "product_qa"
        and subtype != "comparison_overview"
        and not qa_evidence_query
    ):
        # The full turn is a semantic retrieval hint, not a parsed predicate.
        # Keeping it prevents a provider repair that omitted its prose query
        # from erasing the comparison criterion before same-SKU RAG runs.
        qa_evidence_query = str(question or "").strip()[:160]
    intent_coverage = str(data.get("intent_coverage") or "full").strip().lower()
    if intent_coverage not in {"full", "partial"}:
        intent_coverage = "full"
    if evidence_kind != "product_qa" and route_family != "knowledge_base_meta":
        qa_evidence_query = ""
    # A mixed turn may request a formal recorded field and a second,
    # non-column product capability.  The model owns that split; this parser
    # only retains its bounded retrieval phrase for later same-SKU evidence
    # validation.  It never derives a phrase from wording or provides facts.
    if supplemental_qa_evidence_query and (
        route_family not in {"product_bound_qa", "comparison"}
        or evidence_kind != "structured_field"
        or not canonical_fields
    ):
        supplemental_qa_evidence_query = ""
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
    # General advice is deliberately outside the product-fact pipeline.  A
    # semantic model may choose it for a preparation checklist or category
    # tradeoff, but that route may never carry an entity or a public field
    # claim into the non-evidentiary chat writer.
    if route_family == "general_chat":
        if entities or canonical_fields or field_type or field_hint:
            result = _empty_semantic_preplan(called=True, fallback_reason="general_chat_with_product_fact")
            result["raw_preview"] = _safe_preview(raw_content)
            return result
        evidence_kind = "structured_field"
        data["evidence_required"] = False
    # A pairwise decision must name the single formal criterion that makes one
    # participant more suitable. A non-decisive "what differs" comparison is
    # distinct: its empty field list asks the executor to present only recorded
    # same-field differences, without choosing a winner or inventing a default
    # suitability criterion.
    if (
        route_family == "comparison"
        and len(entities) >= 2
        and not canonical_fields
        and evidence_kind != "product_qa"
        and subtype != "comparison_overview"
    ):
        # The semantic model has already identified a named-participant
        # comparison, but the requested criterion may be a natural capability
        # or suitability concept rather than a published table field. Do not
        # discard that meaning merely because the formal enum is empty. Route
        # it through same-SKU product knowledge; RAG/Flash decide relevance
        # from the complete turn below.
        evidence_kind = "product_qa"
        if not qa_evidence_query:
            qa_evidence_query = str(customer_question or "").strip()[:160]
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
    # ``entities`` is a semantic mention packet, not proof that every span is
    # a product participant.  A category recommendation can legitimately
    # contain several catalogue nouns (for example a heat source and the
    # requested cookware form).  Only a product-scoped packet, or explicit SKU
    # identities, can establish the pairwise shape that needs comparison
    # repair.  This keeps the repair semantic and prevents a normal category
    # filter from being stolen by the comparison contract.
    product_participant_scope = entity_scope in {
        "resolved_product",
        "unique_product_name",
        "product_like",
        "ambiguous_product",
        "ambiguous_product_name",
        "unresolved_product",
        "unresolved_product_like",
    }
    explicit_product_identity = any(
        EXPLICIT_SKU_RE.search(entity) or PLAIN_EXPLICIT_SKU_RE.search(entity)
        for entity in entities
    )
    if (
        len(entities) >= 2
        and route_family == "structured_query"
        and (product_participant_scope or explicit_product_identity)
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="pairwise_factual_requires_comparison_contract")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A request to choose between two named products is comparison work even
    # when the semantic model initially labels it recommendation.  The model
    # still owns the criterion; this merely rejects the internally inconsistent
    # route shape so the same semantic repair pass can express that criterion
    # through the comparison contract before any recommendation executor sees
    # the participants.
    # ``entities`` is a product-mention packet, but a provider can still put
    # ordinary recommendation spans in it. Do not make the entire
    # recommendation unexecutable solely because that optional packet is
    # polluted; the service validates actual catalogue identities separately.
    if (
        route_family == "comparison"
        and len(entities) + len(context_result_indexes) < 2
        and not forbidden
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="invalid_comparison_participants")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A comparison between named catalogue participants is inherently
    # evidence-backed. If the provider accidentally carries the generic-chat
    # ``evidence_required=false`` default alongside those entities, preserve
    # the comparison and let the same-SKU executor decide what can actually be
    # supported. Do not erase the participants and send the turn to a generic
    # recovery route.
    if route_family == "comparison" and not bool(data.get("evidence_required", True)):
        data["evidence_required"] = True
    if (
        route_family == "recommendation"
        and not bool(data.get("evidence_required", True))
        and not data.get("recommendation_constraints")
        and not str(data.get("subject_text") or "").strip()
        and not data.get("predicate_constraints")
        and not data.get("recommendation_evidence_requirements")
        and not data.get("recommendation_soft_preferences")
        and not str(data.get("subject_text") or "").strip().lower() in {"cookware", "waterware", "stove"}
        and not (
            str(data.get("context_usage") or "").strip() == "result_context"
            and context_result_indexes
            and decision_requested
        )
        and not (
            entity_scope == "prior_results"
            and decision_requested
        )
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="non_evidentiary_recommendation")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # Some constrained-model responses place the public top-level
    # ``unrepresented_recommendation_requirements`` key inside the adjacent
    # constraints object.  This is a structural placement error, not a cue to
    # infer a requirement from wording: move only that exact model-supplied
    # key, only when no top-level value exists, then run the ordinary strict
    # schemas below.  Any other unknown constraint key remains invalid.
    raw_constraints = data.get("recommendation_constraints")
    # The public shape is an object, but a model can wrap its one broad scope
    # in a singleton list.  Unwrap that transport variation without mapping a
    # customer category to an internal subject kind.
    if (
        isinstance(raw_constraints, list)
        and len(raw_constraints) == 1
        and isinstance(raw_constraints[0], dict)
    ):
        raw_constraints = raw_constraints[0]
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
    # ``recommendation_constraints`` belongs to the recommendation contract.
    # Flash may still echo that optional object while describing a comparison,
    # product-bound fact, or another route.  It is not part of those routes'
    # meaning and must not invalidate the complete semantic plan; the
    # downstream executor only reads it for an actual recommendation.  Keep
    # the route owned by the model and validate this object only where it is
    # semantically consumed.
    recommendation_constraints = (
        _validated_recommendation_constraints(raw_constraints)
        if route_family == "recommendation"
        else {}
    )
    # Formal predicates describe customer requirements independently of the
    # operation that consumes them.  Recommendations and catalogue filters use
    # the same model-authored structure; deterministic code only validates its
    # type and later binds it to the current question and same-SKU fields.
    raw_predicate_constraints = (
        data.get("predicate_constraints")
        if "predicate_constraints" in data
        else data.get("structured_query_constraints")
    )
    predicate_constraints = (
        _validated_structured_query_constraints(
            raw_predicate_constraints,
            allow_empty_category_scope=(
                route_family == "structured_query"
                and not entities
                and set(canonical_fields) == {"category"}
            ),
            # A collection, brand, or product-level catalogue request names a
            # stored database value as its retrieval scope.  It is not a numeric
            # or compatibility predicate, so its validated contract deliberately
            # carries an empty predicate list and lets the catalogue-value executor
            # prove the supplied value against the live column.
            allow_empty_value_scope=(
                route_family == "structured_query"
                and
                not entities
                and len(canonical_fields) == 1
                and canonical_fields[0] in {"series", "brand", "product_level"}
            ),
        )
        if route_family in {"structured_query", "recommendation"}
        else []
    )
    structured_query_constraints = predicate_constraints
    unrepresented_requirements = _validated_unrepresented_recommendation_requirements(
        data.get("unrepresented_recommendation_requirements")
    )
    evidence_requirements = _validated_recommendation_evidence_requirements(
        data.get("recommendation_evidence_requirements")
    )
    soft_preferences = _validated_recommendation_soft_preferences(
        data.get("recommendation_soft_preferences")
    )
    if recommendation_constraints is None and route_family == "recommendation":
        # Subject text and the semantic recommendation route remain usable
        # even when the optional broad-scope mirror is malformed.  Retrieval
        # still proves the actual catalogue scope and every product fact later
        # on; dropping this one optional mirror is safer than reviving a
        # lexical category router or discarding the whole turn.
        recommendation_constraints = {}
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
    if route_family == "recommendation" and raw_subtype == "accessory":
        # Preserve the provider's explicit accessory subtype when a later
        # schema-repair pass incorrectly defaults the broad subject to
        # cookware. This is a semantic consistency adaptation; candidate
        # selection still requires live category evidence downstream.
        recommendation_constraints = dict(recommendation_constraints)
        recommendation_constraints["subject_kind"] = "accessories"
    if predicate_constraints is None:
        if route_family == "recommendation":
            # A malformed optional typed-predicate array must not revoke an
            # otherwise healthy model-owned recommendation route.  Keep the
            # complete customer request and the model's semantic requirements
            # for same-SKU adjudication; no malformed predicate is executed.
            # This is safer than handing the turn to a legacy category route,
            # which loses both the requested product form and ranking goal.
            valid_predicates: list[dict[str, Any]] = []
            if isinstance(raw_predicate_constraints, list):
                for raw_predicate in raw_predicate_constraints:
                    validated_predicate = _validated_structured_query_constraints(
                        [raw_predicate]
                    )
                    if validated_predicate:
                        valid_predicates.extend(validated_predicate)
            predicate_constraints = list(dict.fromkeys(
                json.dumps(item, ensure_ascii=False, sort_keys=True)
                for item in valid_predicates
            ))
            predicate_constraints = [
                json.loads(item) for item in predicate_constraints
            ]
            structured_query_constraints = predicate_constraints
        else:
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
        # This optional narrative array never selects candidates.  A malformed
        # entry must be discarded rather than invalidating independently
        # allowlisted, grounded recommendation constraints.
        unrepresented_requirements = []
    if soft_preferences is None:
        # Soft preferences are explanatory context, not an executable filter.
        # If a provider returns this optional array in a malformed shape, keep
        # the independently valid semantic route and let the recommendation
        # executor work from the question/evidence requirements. Clearing the
        # route here made healthy requests fall into the legacy catalogue
        # templates, which is exactly the behaviour this semantic ownership
        # boundary is meant to prevent.
        soft_preferences = []
    if evidence_requirements is None:
        # This optional array is only a literal semantic boundary. A malformed
        # provider value must not erase the rest of an otherwise valid route,
        # but it also must never become an inferred product requirement.
        evidence_requirements = []
    # Recommendation-owned semantic context cannot coherently live on an
    # unconstrained catalogue browse. The model has already supplied the
    # meaning-bearing requirements, so repair the transport shape in place
    # instead of discarding the whole turn when a provider labels it
    # structured_query. This is a schema normalization: it does not infer a
    # product, field, or value and keeps the same semantic requirements for
    # the recommendation/RAG executor.
    if route_family == "structured_query" and (
        unrepresented_requirements
        or evidence_requirements
        or soft_preferences
    ):
        route_family = "recommendation"
        route_hint = "recommendation"
        question_type = "recommendation"
        decision_requested = True
        data["route_family"] = route_family
        data["route_hint"] = route_hint
        data["question_type"] = question_type
        data["decision_requested"] = True
        data["evidence_required"] = True
    if recommendation_constraints and route_family != "recommendation":
        result = _empty_semantic_preplan(called=True, fallback_reason="recommendation_constraints_outside_recommendation")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if predicate_constraints and route_family not in {"structured_query", "recommendation"}:
        result = _empty_semantic_preplan(called=True, fallback_reason="predicate_constraints_outside_supported_route")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    if (
        predicate_constraints
        and route_family == "structured_query"
        and not set(item["field"] for item in predicate_constraints).issubset(set(canonical_fields))
    ):
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
        # Display columns (name/SKU) belong to the catalogue row shape, not to
        # a named-product fact.  The normalization above intentionally maps
        # that shape to the catalogue scope; keep the generic listing contract
        # from being reclassified by this later product-field guard.
        and not (
            catalogue_display_listing_shape
            and canonical_fields == ["category"]
        )
    ):
        result = _empty_semantic_preplan(
            called=True,
            fallback_reason="named_nonfilter_field_in_structured_query",
        )
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # A collection/value request without a product entity is a database
    # catalogue query, irrespective of the language used for the stored value.
    # Do not let a provider relabel the same semantic field as generic chat,
    # knowledge-base meta, or contents merely because the value is English or
    # otherwise not in the local ontology. The repair pass retains semantic
    # ownership and must recover the customer's value span.
    catalogue_value_fields = {"series", "brand", "category", "product_level"}
    if (
        not entities
        and canonical_fields
        and set(canonical_fields).issubset(catalogue_value_fields)
        # A recommendation can carry a catalogue category as its search
        # scope.  That does not turn the customer's request for a choice into
        # a collection listing.  Only routes which do not already own a
        # product-selection task need this schema repair.
        and route_family not in {"structured_query", "product_bound_qa", "recommendation"}
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="catalogue_value_requires_structured_query")
        result["semantic_route_family_hint"] = "structured_query"
        result["semantic_confidence_hint"] = confidence
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    # An entity-less request to list a named collection or browse a product
    # class is still a catalogue query.  Providers occasionally label that
    # relationship as KB metadata or contents/accessories even while their
    # subtype says it is a listing/browse request.  Preserve no inferred field
    # or value here: return it to the semantic repair pass so the model owns
    # the structured field and customer value span, then the service verifies
    # that span against the live database before exposing rows.
    unbound_catalogue_browse = (
        not entities
        and confidence >= 0.9
        and route_family in {"knowledge_base_meta", "contents_accessories", "generic_query"}
        and (
            raw_subtype.endswith("_listing")
            or raw_subtype.endswith("_browse")
        )
    )
    if unbound_catalogue_browse:
        result = _empty_semantic_preplan(
            called=True,
            fallback_reason="unbound_catalogue_browse_requires_structured_query",
        )
        result["semantic_route_family_hint"] = "structured_query"
        result["semantic_confidence_hint"] = confidence
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
    # An otherwise empty structured route must be repaired by semantic
    # planning before execution; otherwise legacy retrieval may expose an
    # unrelated first QA/KB answer as a catalogue fact.
    if (
        route_family == "structured_query"
        and route_hint == "query_products"
        and question_type == "filter"
        and confidence >= 0.9
        and not entities
        and not str(data.get("subject_text") or "").strip()
        and (
            not canonical_fields
            or canonical_fields == ["category"]
            or set(canonical_fields).issubset({"series", "brand", "product_level"})
        )
        and not structured_query_constraints
    ):
        result = _empty_semantic_preplan(called=True, fallback_reason="incomplete_structured_query_scope")
        result["semantic_route_family_hint"] = "structured_query"
        result["semantic_confidence_hint"] = confidence
        if len(canonical_fields) == 1 and canonical_fields[0] in {"series", "brand", "category", "product_level"}:
            result["catalogue_field_candidate"] = canonical_fields[0]
        elif raw_subtype == "category":
            # The provider's category subtype is a semantic collection signal
            # even when its compact repair omitted canonical_fields. Preserve
            # only that allowlisted field candidate; the live-value adapter
            # must still prove the category against the database.
            result["catalogue_field_candidate"] = "category"
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    recommendation_followup_action = str(data.get("recommendation_followup_action") or "").strip()
    # This is optional planner metadata, not a second intent contract.  Flash
    # sometimes uses a harmless value such as ``new`` for an ordinary fresh
    # recommendation.  Only ``alternative`` has execution meaning; ignore
    # other recommendation-local decorations instead of throwing a healthy
    # semantic plan into the legacy router.
    if recommendation_followup_action not in {"", "alternative"}:
        # Only the one execution-significant value is retained.  Other model
        # decorations such as “new” do not change meaning and must not make an
        # otherwise valid product-care/general-guidance plan fail into a
        # second repair pass.
        recommendation_followup_action = ""
    if recommendation_followup_action and route_family != "recommendation":
        result = _empty_semantic_preplan(called=True, fallback_reason="recommendation_followup_action_outside_recommendation")
        result["raw_preview"] = _safe_preview(raw_content)
        return result
    context_usage = str(data.get("context_usage") or "none").strip()[:40]
    if context_result_indexes:
        # The model itself selected opaque prior-result handles.  Normalising
        # the companion label is schema housekeeping, not an intent decision.
        context_usage = "result_context"
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
            "supplemental_qa_evidence_query": supplemental_qa_evidence_query,
            "compound": bool(data.get("compound", False)),
            "intent_coverage": intent_coverage,
            "context_usage": context_usage,
            "context_result_indexes": context_result_indexes,
            "decision_requested": decision_requested,
            "information_scope": information_scope,
            "recommendation_constraints": recommendation_constraints,
            "predicate_constraints": predicate_constraints,
            "structured_query_constraints": structured_query_constraints,
            "unrepresented_recommendation_requirements": unrepresented_requirements,
            "recommendation_evidence_requirements": evidence_requirements,
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
    if route_family == "product_bound_qa" and intent_coverage == "partial":
        result["fallback_reason"] = "incomplete_product_bound_multi_intent"
    if forbidden:
        result["fallback_reason"] = "forbidden_keys:" + ",".join(forbidden)
        result["route_hint"] = ""
        result["confidence"] = 0.0
    extra_keys = sorted(key for key in data if key not in SEMANTIC_PREPLAN_ALLOWED_KEYS and key not in SEMANTIC_PREPLAN_FORBIDDEN_KEYS)
    if extra_keys:
        result["fallback_reason"] = "unexpected_keys:" + ",".join(extra_keys[:8])
        result["route_hint"] = ""
        result["confidence"] = 0.0
    # A product turn can carry both a formal field and a capability/judgement
    # that has no formal field.  Dropping the latter while accepting the former
    # produces a plausible but incomplete answer.  Return this malformed
    # semantic partition to the same LLM repair path so it owns the whole-turn
    # interpretation; deterministic code never invents a replacement field.
    if (
        route_family in {"product_bound_qa", "comparison"}
        and len(raw_canonical_fields) >= 2
        and unknown_canonical_fields
        and not result.get("fallback_reason")
    ):
        comparison_qa_concepts = {
            "storage_preference": "storage",
            "durability": "durability",
            "handling": "handling",
            "suitability": "suitability",
        }
        mapped_concepts = [comparison_qa_concepts.get(field) for field in unknown_canonical_fields]
        if route_family == "comparison" and all(mapped_concepts):
            # Semantic output has explicitly separated a formal comparison
            # field from a non-column comparison concept. Preserve both for
            # the sealed composite executor; no lexical routing is inferred.
            result["comparison_qa_concepts"] = mapped_concepts
        else:
            result["fallback_reason"] = (
                "unknown_canonical_field_in_comparison"
                if route_family == "comparison"
                else "unknown_canonical_field_in_multi_intent"
            )
    return result


def _preserve_semantic_route_after_repair_failure(
    initial_data: dict[str, Any] | None,
    *,
    raw_content: str,
    failure_reason: str,
    error: Exception,
) -> dict[str, Any] | None:
    """Keep a usable semantic route when a *schema repair* transport fails.

    The first semantic response has already interpreted the whole customer
    turn.  A later repair call is only there to fix JSON shape; it must not be
    allowed to erase that interpretation and hand the same sentence to the
    legacy keyword routes.  We salvage only fields that can be validated by
    the normal semantic schema again.  No product, SKU, catalogue value, or
    missing constraint is created here.

    This is intentionally narrower than accepting an arbitrary failed plan:
    the original response must name a supported route with at least medium
    confidence, and the sanitized response must pass the ordinary validator.
    If either condition is not met, callers still fail closed.
    """
    if not isinstance(initial_data, dict):
        return None
    route_family = str(initial_data.get("route_family") or "").strip()
    if not route_family:
        route_family = _semantic_route_family_from_legacy(
            str(initial_data.get("route_hint") or "").strip(),
            str(initial_data.get("question_type") or "").strip(),
            str(initial_data.get("subtype") or "").strip(),
        )
    if route_family not in SEMANTIC_PREPLAN_ROUTE_FAMILIES - {""}:
        return None
    confidence, _ = _semantic_confidence_parts(initial_data.get("confidence"))
    if confidence < 0.65 or bool(initial_data.get("ambiguity")):
        return None
    if any(key in initial_data for key in SEMANTIC_PREPLAN_FORBIDDEN_KEYS):
        return None

    # Strip provider-only context echoes and unknown response decorations. The
    # public semantic validator remains the only authority for the salvaged
    # route shape.
    sanitized = {
        key: value
        for key, value in initial_data.items()
        if key in SEMANTIC_PREPLAN_ALLOWED_KEYS
        or key in SEMANTIC_PREPLAN_CONTEXT_ECHO_KEYS
    }
    sanitized.pop("has_unique_current_turn_catalog_product_name", None)
    sanitized.pop("unique_current_turn_catalog_product_mention", None)
    sanitized["route_family"] = route_family
    defaults = _semantic_route_family_defaults(route_family)
    sanitized["route_hint"] = str(
        sanitized.get("route_hint") or defaults.get("route_hint") or ""
    )
    sanitized["question_type"] = str(
        sanitized.get("question_type") or defaults.get("question_type") or ""
    )
    sanitized["recommendation_constraints"] = (
        _validated_recommendation_constraint_subset(
            initial_data.get("recommendation_constraints")
        )
        if route_family == "recommendation"
        else initial_data.get("recommendation_constraints", {})
    )
    if sanitized["recommendation_constraints"] is None:
        sanitized["recommendation_constraints"] = {}
    if route_family == "recommendation":
        for key, validator in (
            (
                "unrepresented_recommendation_requirements",
                _validated_unrepresented_recommendation_requirements,
            ),
            ("recommendation_evidence_requirements", _validated_recommendation_evidence_requirements),
            ("recommendation_soft_preferences", _validated_recommendation_soft_preferences),
        ):
            # Optional semantic context must not make a known route disappear
            # when only that context has malformed provider shape. Invalid
            # optional entries are dropped, never reinterpreted or invented.
            validated = validator(initial_data.get(key))
            sanitized[key] = validated if validated is not None else []

    preserved = _validate_semantic_preplan(sanitized, raw_content=raw_content)
    if preserved.get("fallback_reason"):
        return None
    preserved.update(
        {
            "semantic_repair_unavailable": True,
            "semantic_repair_error": type(error).__name__,
            "semantic_repair_failure_reason": str(failure_reason or "")[:120],
            "accepted_or_overridden": "preserved_after_semantic_repair_failure",
            "override_reason": "valid_semantic_route_preserved_after_repair_transport_failure",
        }
    )
    return preserved


def _semantic_preplan_messages_legacy(
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
                "Required keys: route_family, subtype, entities, subject_text, canonical_fields, confidence, ambiguity, evidence_required, evidence_kind, qa_evidence_query, context_usage, context_result_indexes, decision_requested, information_scope, reasoning_summary. "
                "When the customer explicitly asks for accessories, add subject_kind=accessories; accessories are a distinct catalogue scope from cookware, waterware, stove, and coffee gear. "
                "For route_family=recommendation, use a small reusable set of formal scope/predicate keys. Preserve every other independently stated condition as an exact customer-language phrase in recommendation_evidence_requirements when the selected product is expected to satisfy it, or in recommendation_soft_preferences when it only helps rank or explain the choice. Decide that partition from the complete request and conversational meaning, not from a fixed phrase list. Subjective experience or outcome preferences such as wanting something simple, practical, easy to store, easy to choose, or beginner-friendly are soft preferences unless the customer explicitly makes them non-negotiable or names a concrete capability, product form, or constraint; do not turn an unrecorded quality adjective into a hard no-match condition. A concrete use goal such as boiling water or cooking noodles may remain a recommendation evidence requirement, but lack of a literal catalogue label for simplicity or convenience must be disclosed in prose rather than vetoing otherwise relevant same-SKU candidates. These phrases are retrieval and writing inputs only; they never prove a product fact. Never include product names, SKUs, candidates, database values, reasons about a particular product, or an answer in recommendation_constraints. "
                "For route_family=recommendation or structured_query with explicit formal conditions, add predicate_constraints: an array of 1-8 objects {field,operator,value,evidence_span,unit,importance}. field must be one of material,surface_finish,capacity,weight,dimensions,people,color,heat_source,usage_scene,waterproof. operator must be: material/usage_scene contains; surface_finish/color/dimensions contains or =; heat_source supports or not_supports; numeric fields >=,>,<=,<,=,between; waterproof =. Set importance=required for a condition that must be met and importance=preferred for a condition used to rank otherwise usable products. evidence_span must be an exact customer phrase in this turn, and each textual value must be a verbatim substring of that evidence_span. For structured_query, each predicate field must also be in canonical_fields and mirror the array in structured_query_constraints during migration. A generic catalogue kind is subject scope in subject_text, not a predicate. Never include a product name, SKU, candidate, database value, answer, or inferred condition. "
                "For a catalogue count or an unconstrained list whose only scope is a generic product kind (for example, how many stoves are recorded), use route_family=structured_query, route_hint=query_products, subject_text for that kind, canonical_fields=[category], and structured_query_constraints=[]; category describes the database membership scope here and MUST NOT appear as a predicate object. For a catalogue list constrained only by a stored collection, brand, or product-level value, likewise use structured_query with canonical_fields containing exactly series, brand, or product_level, preserve the customer-provided value in subject_text, and return structured_query_constraints=[]: the executor validates that value against the database column rather than treating it as an inferred predicate. "
                "subject_text is the database-retrieval scope, not a loose head noun: retain the most specific customer-stated product kind and its meaning-bearing modifier. Do not reduce a storage box, folding box, coffee grinder, tea set, or other compound product kind to a generic single noun when the modifier changes the catalogue scope. When the customer combines an explicitly named but unverified product with a generic catalogue request, preserve the named subject as an entity candidate and mark ambiguity or unresolved scope rather than silently discarding it and listing the generic category. "
                "subject_kind means the thing the customer is actually seeking: waterware is for a vessel explicitly requested to carry or boil water, cookware is for a pot, pan, griddle, or cooking vessel, stove is for a burner or heat source, and coffee_gear is for an explicitly requested grinder or coffee-brewing apparatus. Do not select cookware merely because water can also be heated in cookware or because a coffee grinder is used outdoors. weight_preference is only an explicit physical-mass requirement (for example light, heavy, weight, or carrying load). Compactness, storage, or not taking space is not weight_preference; use storage_preference=compact_storage for an explicit non-binding storage preference, and preserve an explicitly non-negotiable storage requirement in unrepresented_recommendation_requirements. "
                "When decision_requested is true and the customer contrasts two or more product forms that all belong to one allowed broad subject_kind, emit that shared subject_kind so the evidence executor has a bounded catalogue scope. This does not decide which form wins and does not create a product-form constraint; the later semantic writer may choose only from sealed same-SKU evidence. "
                "Every recommendation constraint must be explicitly stated by the customer in this turn or supplied by an explicit prior-turn customer preference; omit it when it is merely plausible or typical. In particular, do not infer people, heat_sources, scenarios, weight_preference, appearance, packaging, prestige, or presentation quality from the product category, a generic outdoor word, or the fact that a customer asks for a recommendation. A request to choose something as a gift must preserve the gift use itself as a soft preference. Do not invent an appearance or packaging preference merely because the item will be a gift, and never combine an inferred appearance/packaging criterion with gifting suitability; preserve those as separate preferences only when the customer explicitly states both. "
                "For a recommendation that explicitly asks to replace the prior recommendation, set recommendation_followup_action=alternative; otherwise omit it. This is only allowed when an explicit prior customer preference is supplied. A short follow-up that only names a product category or direction (for example, '锅具' after a broad gift recommendation) narrows the current recommendation scope; it is not a replacement request and must not set recommendation_followup_action=alternative. "
                "Before returning a recommendation plan, inspect every explicit customer requirement. When one customer expression contains multiple independently allowed requirements, emit every matching allowed constraint rather than letting one suppress another. If a single requested product form explicitly combines multiple components (for example a pot, burner, and canister bundle), do not collapse that form to one broad subject_kind; preserve the exact combined phrase in unrepresented_recommendation_requirements when the ontology cannot represent the whole combination. If a must-have eligibility condition cannot be put in recommendation_constraints without inventing a meaning, it MUST appear verbatim in unrepresented_recommendation_requirements. Do not turn a non-binding preference into an eligibility gap merely because the ontology cannot encode it. "
                "route_family enum: structured_query,recommendation,comparison,product_bound_qa,product_navigation,unresolved_product_like,negative_product_like,unknown_realtime,contents_accessories,generic_query,knowledge_base_meta,general_chat,clarification. Use general_chat for ordinary conversation that can be answered without claiming a catalogue product fact: greetings, capability questions, general outdoor preparation checklists, beginner education, category-level tradeoffs, or general safety guidance. For a category-level hazardous-operation question with no named catalogue product, use general_chat with subtype=safety_procedure, entities=[], canonical_fields=[], evidence_required=false. For general_chat set entities=[], canonical_fields=[], evidence_required=false, and do not request catalogue retrieval. Use recommendation when the customer asks the assistant to identify, choose, find, or recommend an actual catalogue item/product. This includes asking what single item to give as a gift or what would be practical for a beginner when no category is named: keep the product scope broad if necessary, set decision_requested=true, and preserve the recipient, use, storage, budget, or other priorities as semantic recommendation inputs. General_chat is only for guidance that does not ask the assistant to choose a concrete item; it must not name an unverified product category as a recommendation. Use comparison only for named catalogue products, never merely for generic product forms. A request for the complete range, types, or models inside one explicitly named catalogue category is structured_query over category, not generic_query and not recommendation. When the customer asks for a bounded number of relevant choices, asks you to select options, or asks who each choice suits, use recommendation even if the same turn also contains catalogue-discovery wording such as which products exist. A request to prepare for camping or choose equipment is recommendation only when it seeks actual products rather than general decision guidance. Use knowledge_base_meta only when the user asks about a knowledge-base document itself, its contents, rules, or principles rather than requesting a product fact. For a knowledge_base_meta procedure or rule question, qa_evidence_query may be a concise Chinese retrieval phrase that preserves the requested subject and operation (for example, cookware non-stick coating cleaning/maintenance); it is a search signal only, never an answer or fact. A named-product question about operating steps, safety rules, prohibited actions, cleaning, maintenance, or any other product field is product_bound_qa even if its answer may later use a manual or knowledge-base document as evidence. "
                "entity_scope enum: generic_scope,category_scope,product_like,resolved_product,ambiguous_product,unresolved_product,negative_product,prior_results. Use prior_results when the current turn chooses, compares, or asks about products represented only by the supplied opaque prior-result positions; never put a SKU or product name there. "
                "field_type enum: " + ",".join(sorted(SEMANTIC_PREPLAN_FIELD_TYPES)) + ". "
                "evidence_kind is required for every product_bound_qa request. Use structured_field only when the customer directly asks for a recorded field value. Use product_qa when the customer asks a product-specific capability, judgement, procedure, or compatibility fact that is not identical to one structured field; then canonical_fields MUST be [] and no field_type/field_hint may be emitted. For product_qa, qa_evidence_query is required: return a concise semantic retrieval phrase for the customer's intent, with no product name, SKU, database value, or answer. Preserve the customer's concrete operative condition rather than replacing it with an abstract category: for a question about whether low heat can be adjusted for simmering, the retrieval phrase must retain the low-heat adjustment and simmering condition, not merely say slow-cooking performance. For example, describe gifting suitability, authenticity verification, flame adjustability, household compatibility, durability, or load-bearing as the requested capability. For every other evidence_kind set qa_evidence_query="". Durability is not lifecycle_status; whether a product is suitable as a present is not whether a purchase includes a promotional gift; authenticity verification is not certification; adjustability is not a numeric power rating; household compatibility is not a list of usage scenes; and load-bearing is not net weight, headcount, or volume. These are ontology boundaries, not product facts: keep them product_qa so only a later same-SKU QA evidence contract may answer. "
                "canonical_fields is an ordered array of one or more field concepts; use every independently requested field. A number, unit, model marker, capacity, size, color, or version that occurs only inside the product mention belongs only to subject_text and MUST NOT create an additional canonical field, structured filter, recommendation condition, or ambiguity. Add a field only when the customer's predicate independently asks for that fact. subject_text is the product mention only, never a SKU decision. For one named product, asking which or what usage settings/scenarios it suits is a direct usage_scene structured_field request. Use product_qa instead only for a personalised suitability judgement whose condition is not the stored usage-scene field. "
                "For a comparison between two or more named products, entities is mandatory: put each verbatim product mention in entities in mention order (at least two items). Any factual request that asks for those named participants' respective values is route_family=comparison even when it asks for no winner; structured_query is only for filters over a product set, never a pairwise product fact. canonical_fields must contain only published formal fields. When a comparison asks a formal field together with a non-field attribute (for example people together with packing/storage, durability, handling, or suitability), keep the formal field in canonical_fields, use evidence_kind=structured_field, and put one concise retrieval phrase for the non-field attribute in supplemental_qa_evidence_query. Do not emit the non-field attribute in canonical_fields and do not silently drop it. The executor compares the formal field from structured same-SKU evidence and separately validates the supplemental QA for each participant. For a generic non-decisive request such as 'what is the difference' with no criterion, use evidence_kind=structured_field, canonical_fields=[], subtype=comparison_overview, decision_requested=false, and qa_evidence_query='': this asks for a factual overview of recorded differences only, not a winner and not QA retrieval. If the criterion is a product-specific capability, procedure, compatibility, judgement, or performance fact that is not identical to one structured field, set evidence_kind=product_qa, canonical_fields=[], and provide qa_evidence_query; never substitute a merely related structured field. Set decision_requested=true only when the customer explicitly asks which named participant wins a stated criterion, including which is lighter, heavier, larger, cheaper, more suitable, or should be chosen; otherwise false. When the customer asks which named product is more suitable for a stated use, recipient, or scenario, that is a choice request even if the criterion is a natural-language suitability concept rather than a formal field; keep decision_requested=true and preserve the complete criterion for product_qa retrieval. Never infer a preference from a product name, version label, or SKU, and never invent, normalize, or choose a SKU. "
                "A request such as 'what is different about their material' or 'what is the difference in capacity/weight/heat source' has an explicit formal criterion: keep that criterion in canonical_fields and compare it directly. "
                "Do not choose recommendation merely because a question asks where, what, or which: recommendation requires asking for options or advice, not a fact about one product. "
        "information_scope enum: knowledge_base_meta when the customer explicitly asks according to a knowledge base, document, FAQ, or manual, or asks about that source's contents, rules, or principles rather than requesting products; otherwise an empty string. A knowledge_base_meta turn has no product candidates unless a later provenance-bound retrieval supplies them. "
                "brand=manufacturer or brand owner; questions asking whose brand, maker, or which company a named product is from are brand. "
                "category=the product kind, class, merchandise type, or taxonomy bucket. A request for which kind, class, category, or type a product is belongs to category. "
                "series=a named product family, collection, or product line, never a generic product kind/class. Use series only when the requested relationship is to a named family, collection, line, or range; "
                "do not reinterpret a generic classification request as series merely because the product also has a series value. launch_date=market introduction time; "
                "material=the product body's recorded material; surface_finish=the coating, non-stick treatment, or other outer-surface finish. A request for 不粘涂层、涂层、不粘表面 or surface treatment belongs to surface_finish, never material; do not use a body-material value to represent a coating. positioning=target customer/problem, intended role, or brand strategy. A predicate about a product's need, use case, problem, role, or job-to-be-done is positioning even when it uses a broad word such as 'targeted at' or 'for'; it does not become target_audience unless it asks who the users are. "
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
                "A request about returns, refunds, exchanges, replacement eligibility, or a seven-day return policy is a product-bound QA policy question, not after_sales_contact; set evidence_kind=product_qa with canonical_fields=[] and a concise Chinese qa_evidence_query. "
                "inventory=current stock or in-stock availability; lifecycle_status is only the catalogue lifecycle label and must not be used as realtime stock, product durability, expected usable years, service life, or replacement interval. Any question about current purchasability (whether a named product can still be bought now, is currently sold, or is available today) is unknown_realtime, never product_qa: static QA, listing-channel, or lifecycle text cannot prove it. "
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
                "weight=the recorded product mass or carrying-weight fact, including natural questions such as whether a named product feels heavy to carry, hold, or wear; answer from the weight field and do not substitute a QA claim about portability. "
                "If generic wording such as how big could genuinely mean either physical dimensions or capacity, mark ambiguity instead of using a number in the product name to guess. "
                "For multi-component sets, keep capacity for volume and dimensions for physical size; return both when both are asked. "
                "heat_source=compatible stove types, heating methods, fuel sources, gas-canister types, or whether direct flame/charcoal/wood/induction is supported. A question asking which fuels or canisters a named product supports directly requests heat_source. "
                "power=rated output, maximum output, wattage, electrical power consumption, burner output, heat output, or firepower. A request for rated output or power must use power, not specification merely because it is a technical parameter; the same applies to maximum output, which must not be routed to product_qa. Operating duration, fuel endurance, burn time, runtime, or how long a consumable load lasts are not power: when the formal taxonomy has no direct field for that product-specific fact, retain route_family=product_bound_qa with canonical_fields=[] so the sealed same-SKU QA evidence stage can evaluate it. "
                "usage_instruction=operating or usage steps for the product, including how a named product should be used or what to note on first use; a request about stove, fuel, or heating compatibility remains heat_source even if phrased as how compatibility should be stated. "
                "dishwasher=only whether the product is explicitly dishwasher-safe or compatible with a dishwashing machine. "
                "generic machine-wash or washing-machine compatibility belongs to cleaning, not dishwasher; never translate generic machine-wash wording into dishwasher. "
                "cleaning=manual cleaning methods, washing steps, wiping, rinsing, detergents, or laundry-machine compatibility, excluding explicit dishwasher compatibility. "
                "care=maintenance, upkeep, drying before storage, rust prevention, protection, or long-term storage practices. Care and maintenance remain care even when the evidence shares a usage-instruction document; do not relabel them as cleaning or usage_instruction. "
                "Cleaning plus storage asks for both cleaning and care; product-name words are not fields. "
                "product_level=the catalogue's grade or tier label such as A-class or B-class; category=the merchandise type such as cookware, stove, or accessory. "
                "people=a numeric or bounded group-size fact. target_audience=the user personas, customer types, or groups the product is intended for; it is not a numeric headcount. "
                "selling_point=the named product's benefits, highlights, advantages, differentiators, or reasons it is worth choosing. Asking why one already named product is worth choosing is a product_bound_qa selling_point fact, not recommendation. When the same request also asks for limitations, cautions, tradeoffs, drawbacks, or what needs attention, it is not a single selling_point field: use product_bound_qa with evidence_kind=product_qa, canonical_fields=[], and one qa_evidence_query preserving both the positive and limiting sides of the request. "
                "technical_advantages=concrete product technologies, engineering mechanisms, technical structures, or technical capabilities recorded for the product; do not use selling_point merely because a technical fact is also beneficial. "
                "Use selling_point for customer-facing value propositions and general highlights, and technical_advantages for how the product achieves a capability through a named technology, mechanism, structure, or technical implementation. "
                "recommendation requires asking the assistant to select, rank, or propose product options; it is not triggered by asking for the merits of one named product. "
                "For a pronoun follow-up with a conversation, classify only the requested field; do not infer or output an identity. "
                "A multi-item family list/difference request is structured_query with canonical_fields=[series], not one product detail. "
                "A product switch with no fact is product_navigation with canonical_fields=[] and evidence_required=false; a switch plus any fact or procedure is product_bound_qa. "
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
                "active_product_anchor: "
                + json.dumps(context.get("active_product_anchor") or {}, ensure_ascii=False)
                + "\n"
                "database_field_value_hints: "
                + json.dumps(context.get("database_field_value_hints") or [], ensure_ascii=False)
                + "\n"
                "explicit_prior_customer_preference_texts: "
                + json.dumps(context.get("prior_customer_preference_texts") or [], ensure_ascii=False)
                + "\n"
                "active_product_anchor is a server-provided prior-turn identity only. When it is non-empty and this turn uses a pronoun or omits the product subject while asking a product fact, set context_usage=entity_anchor; select the requested canonical_fields from this turn and do not repeat the anchor as a newly extracted entity. For a comparison that explicitly contrasts one newly named product with the prior-turn product, set context_usage=entity_anchor and include both verbatim identities in entities; do not use the anchor for catalogue queries, recommendations, unrelated comparisons, or when the current turn clearly replaces the prior product. prior_result_context_indexes is a list of one-based opaque handles from prior_result_context_indexes in the input. Use it when the customer refers to one or more products previously shown in the conversation (including deictic, elliptical, or omitted-product comparisons); preserve the referenced result order and never invent a SKU or product identity. Put current-turn literal product names in entities, and put prior-result handles only in context_result_indexes. Use an empty list when the current turn does not refer to a prior result. A new recommendation that adds a scenario, group size, capacity, heat source, budget, portability, or another fit requirement is a fresh catalogue search unless the customer also means to choose among the previously shown items; do not populate context_result_indexes merely because prior results exist. A bare category continuation such as narrowing the product kind is also not a result choice. prior_result_context_semantics is discourse metadata only: it can tell you that the prior result was a comparison or recommendation and that a choice was recorded, but it contains no product identity or fact. Use it to understand the conversational task before choosing route_family; do not require the customer to restate the prior products.\n"
                "database_field_value_hints are only schema-grounding candidates whose matched_text occurs in the current question; they are not product facts and must never be returned as an answer. If a matched hint is a named collection/line and the user asks which products it contains, use route_family=structured_query, canonical_fields=[series], and preserve the matched customer phrase in subject_text. Do not infer a field from an unmatched hint. Return every required key. Select canonical_fields only from the field_type enum above; do not copy a field from an output example."
            ),
        },
    ]


def _legacy_semantic_preplan_messages(
    *,
    question: str,
    deterministic_plan: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """Build one compact, model-owned interpretation of the current turn.

    Older versions embedded a long handbook of phrase-specific routing advice.
    Besides acting like a hidden rules engine, it encouraged providers to echo
    input context until JSON was truncated. This packet defines only the stable
    output shape, the public field ontology, and evidence boundaries.
    """
    field_types = ",".join(sorted(SEMANTIC_PREPLAN_FIELD_TYPES))
    system = (
        "Return exactly one complete JSON object, with no markdown, explanation, or extra keys. Interpret the whole current customer turn; do not use keyword matching. You are not answering the customer and must never output a product fact, SKU, candidate, database value, price, stock, or answer. "
        "Use exactly these keys: route_family,subtype,entities,subject_text,entity_scope,canonical_fields,confidence,ambiguity,evidence_required,evidence_kind,qa_evidence_query,supplemental_qa_evidence_query,compound,intent_coverage,context_usage,context_result_indexes,decision_requested,information_scope,recommendation_constraints,predicate_constraints,recommendation_evidence_requirements,recommendation_soft_preferences,recommendation_followup_action,reasoning_summary,qa_or_usage_care. Use empty strings, arrays, or objects when a key is unused. Do not repeat input/context keys. "
        "route_family is one of structured_query,recommendation,comparison,product_bound_qa,product_navigation,unresolved_product_like,negative_product_like,unknown_realtime,contents_accessories,generic_query,knowledge_base_meta,general_chat,clarification. recommendation means the customer wants the catalogue to help choose, buy, or give a concrete item; it includes an unbound gift or practical-gear choice, and applies even when the category is only implied by the requested use. If a turn names an item kind and asks for the best fit for a scenario, group, heat source, cooking task, storage need, or other use condition, it is a recommendation, not a structured browse. structured_query is only for browsing, listing, filtering, or counting a catalogue set when the customer is not asking the assistant to choose a product. comparison relates named products. product_bound_qa asks about one named or anchored product. general_chat is non-catalogue guidance where the customer is not asking to choose or locate a catalogue item. unknown_realtime covers current commercial facts such as purchasability, price, or inventory. product_navigation is a bare product switch or open request. For a category-level safety, operation, cleaning, or maintenance question without a named or anchored product, use general_chat with qa_or_usage_care=true, subtype=safety_procedure or usage_care, entities=[], canonical_fields=[], evidence_required=false; a category noun alone does not make such a turn a structured catalogue listing. If the customer explicitly asks according to a knowledge base, document, FAQ, or manual, preserve that source scope with route_family=knowledge_base_meta and information_scope=knowledge_base_meta, entities=[], and canonical_fields=[], and do not replace the source-bounded answer with general knowledge. Use knowledge_base_meta when the customer asks for a knowledge-base document's rules, principles, or contents; it is a general RAG question and does not require a product name or SKU. For knowledge_base_meta procedure or rule questions, fill qa_evidence_query with a concise Chinese retrieval phrase that preserves the subject and requested operation; it guides document retrieval only and is not an answer or product fact. "
        "entities contains only verbatim current-turn product mentions. subject_text preserves the requested product/category or full identity-bearing name, including every stated version or edition; never shorten a versioned identity. A validated page or conversation anchor may be used with context_usage=entity_anchor but must not be copied as a newly extracted entity. Recommendation context may use context_usage=recommendation_context and recommendation_followup_action=alternative only for a requested replacement. prior_result_context_indexes is an input-only list of one-based opaque result positions; when the current turn refers to those prior products, return the positions in context_result_indexes in the order needed for the answer. Never output a SKU, product name, or catalogue fact for an opaque position. Use entity_scope=prior_results when the turn clearly operates on that supplied prior-result set even if the positions need server-side binding; do not invent a product identity. The input may also contain prior_result_context_semantics describing only the prior answer's discourse kind (comparison, recommendation, or result), how many opaque results it contained, and whether the prior answer recorded a choice. Use that state to interpret elliptical follow-ups such as choosing among prior comparison results or asking about the recorded choice; it is not product evidence and must not be copied into entities or the answer. When information_scope=knowledge_base_meta, keep the answer inside the supplied document evidence and do not silently downgrade the request to general chat. "
         "canonical_fields is an ordered subset of: " + field_types + ". Use directly recorded fields only. evidence_kind=structured_field for those fields; use product_qa and a concise customer-language qa_evidence_query for a named-product capability, judgement, procedure, compatibility, safety, durability, suitability, policy, or broad evidence-supported overview. There is no durability canonical field. A broad overview should not infer one field. Only select selling_point for a direct highlights/reasons-to-choose request. Whether a setting or adjustment is available is product_qa unless the customer explicitly asks for operating steps. For a mixed turn, retain every requested formal field and put only the independent non-column meaning in supplemental_qa_evidence_query. This includes a recorded field followed by a practical sufficiency or suitability question: for example, a capacity question that also asks whether the product is enough for a stated group and cooking task keeps capacity in canonical_fields and uses supplemental_qa_evidence_query such as ‘是否适合两个人煮面’. Treat ‘够不够/是否够用/是否适合/能否满足’ as a judgement about the stated use when they appear in the question; do not dismiss the group or task as mere background in that case. A turn that only asks for the recorded value, with a use scene supplied merely as context, may remain field-only. Do not collapse the whole turn into field-only merely because one part is a recorded field, and do not put the product name, SKU, or a database fact in the supplemental query. Set compound=true when both parts are represented; intent_coverage is full only when all requested meaning is represented. "
        "For recommendation or structured_query, put every explicit formal eligibility condition in predicate_constraints as {field,operator,value,evidence_span,unit,importance}. Supported fields: material,surface_finish,capacity,weight,dimensions,people,color,heat_source,usage_scene,waterproof. Numeric operators: >=,>,<=,<,=,between; material/usage_scene: contains; surface_finish/color/dimensions: contains or =; heat_source: supports or not_supports; waterproof: =. material means the product body's material; surface_finish means a coating, non-stick treatment, or other outer-surface finish. Therefore 不粘涂层、涂层、不粘表面 and surface treatment must use surface_finish, never material. Normalize numeric values and units while copying evidence_span exactly from this turn. Distinguish a product's recorded people specification from the customer's practical group context: a statement that the customer is shopping for a group, or wants something comparatively suitable for that group, is practical-fit context. Preserve its headcount in recommendation evidence or ranking context, but do not emit a required people predicate unless the customer explicitly asks for a product's supported/serving headcount or makes that headcount a non-negotiable eligibility condition. Phrases describing an outcome such as 比较适合、够用、吃饱 or 一起露营 are not literal catalogue labels and should be answered conditionally from same-SKU capacity and relevant scene evidence. Do not discard an explicit current-turn fit detail merely because it is practical context rather than a formal database predicate: a stated group/headcount, capacity goal, cooking task, portability or storage need, budget direction, cleaning preference, or named heat source must remain represented in recommendation_evidence_requirements or recommendation_soft_preferences as appropriate. A practical group statement need not become a required people predicate, but it must remain available for same-SKU capacity and scenario reasoning. The current turn owns these requirements; prior recommendation result positions never replace them. importance is required only for an obligation or eligibility condition; use preferred for a ranking preference, and do not convert a preference into hard rejection merely because it is expressed as a product property. An affordability or budget preference without an exact price, an explicit price ceiling, or a named price-positioning requirement is a ranking preference only: put it in recommendation_soft_preferences, never in recommendation_evidence_requirements or predicate_constraints, and do not reject a candidate merely because the catalogue lacks a price. Keep the requested item kind in subject_text. recommendation_constraints may contain only a confident broad subject_kind (cookware,waterware,stove,coffee_gear,accessories); otherwise use {}. Put non-field must-haves in recommendation_evidence_requirements and ranking or explanation preferences in recommendation_soft_preferences. A request to identify products that meet a compatibility, use, or quality condition, or to put qualifying products first, is still product selection even when it asks which products; use recommendation and preserve the condition instead of returning an unconstrained category browse. Use structured_query only for genuine browsing, listing, or counting without a choice, prioritization, or product-fit condition. Decide from meaning, not a fixed phrase list. These values guide retrieval and never prove a product fact. For recommendation, decision_requested=true when the customer asks the assistant to make a concrete choice rather than merely browse; this includes an explicitly singular choice. Keep it false only when no choice is requested. "
        "Core field distinctions: category=product kind; series=named family or collection and must not replace category; sku=item/product code, model is distinct, barcode is EAN/UPC/GTIN. dimensions are measurements, capacity is volume, weight is mass. people is numeric group size; target_audience is a persona or group. heat_source is compatible heating/fuel type; power is rated output, not specification. A cooking action or dish such as 烧水、煮面、煮饭、烹饪 does not imply a heat_source; only an explicitly named stove, fuel, heating method, or compatibility request can establish that field. material is body material while surface_finish is coating/non-stick/surface treatment; do not collapse those fields. accessories are included parts; gift means a promotional free item only, while gifting suitability is product_qa. dishwasher is explicit dishwasher compatibility; cleaning and care remain separate. Current purchasability is unknown_realtime, never inferred from lifecycle_status. Related specifications never prove a different capability. "
        "confidence is low,medium,or high. ambiguity is true only when material meanings conflict. reasoning_summary is one short audit sentence."
    )
    user = {
        "question": question,
        "has_conversation_id": bool(context.get("conversation_id")),
        "has_recommendation_context": bool(context.get("has_recommendation_context")),
        "active_product_anchor": context.get("active_product_anchor") or {},
        "has_page_product_anchor": bool(context.get("has_page_product_anchor")),
        "has_unique_current_turn_catalog_product_name": bool(context.get("has_unique_current_turn_catalog_product_name")),
        "unique_current_turn_catalog_product_mention": str(context.get("unique_current_turn_catalog_product_mention") or ""),
        "database_field_value_hints": context.get("database_field_value_hints") or [],
        "explicit_prior_customer_preference_texts": context.get("prior_customer_preference_texts") or [],
        "prior_result_context_indexes": context.get("prior_result_context_indexes") or [],
        "prior_result_context_semantics": context.get("prior_result_context_semantics") or {},
        "prior_result_context_note": "These are opaque one-based positions from the immediately available prior result set. They carry no product facts. If prior_result_context_semantics includes a recorded choice position, use that position for a follow-up about the already selected item; otherwise preserve all positions needed by the current request.",
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _semantic_preplan_messages(
    *,
    question: str,
    deterministic_plan: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the small semantic contract used by the live planner.

    This deliberately describes the output vocabulary instead of teaching a
    phrase-to-route table.  Retrieval and evidence code can work with a
    structured plan without deciding what a natural-language turn means.
    """
    route_families = ",".join(sorted(SEMANTIC_PREPLAN_ROUTE_FAMILIES - {""}))
    field_types = ",".join(sorted(SEMANTIC_PREPLAN_FIELD_TYPES - {"", "recommendation", "unknown"}))
    system = (
        "You are the semantic interpreter for a product assistant. Read the complete customer turn and its supplied "
        "conversation context. Return exactly one JSON object and no explanation. Do not answer the customer and do "
        "not output a product fact, SKU, price, stock, candidate, or database value. Do not route by isolated words. "
        "Use these keys only: route_family,route_hint,question_type,entities,subject_text,entity_scope,canonical_fields,"
        "field_type,field_hint,subtype,confidence,ambiguity,evidence_required,evidence_kind,qa_evidence_query,"
        "qa_evidence_queries,supplemental_qa_evidence_query,compound,intent_coverage,context_usage,context_result_indexes,"
        "decision_requested,information_scope,recommendation_constraints,predicate_constraints,structured_query_constraints,"
        "unrepresented_recommendation_requirements,recommendation_evidence_requirements,recommendation_soft_preferences,"
        "recommendation_followup_action,qa_or_usage_care,unknown_field,reason,reasoning_summary. "
        f"route_family must be one of: {route_families}. Use recommendation when the customer wants the assistant to "
        "choose or prioritize actual catalogue products; use structured_query for browsing/listing/counting a set "
        "without asking the assistant to choose; use comparison for two or more product participants; use "
        "product_bound_qa for a fact, capability, procedure, judgement, or overview about one named or anchored product; "
        "use knowledge_base_meta for a request explicitly bounded to a supplied knowledge source; use general_chat for "
        "non-catalogue guidance; use unknown_realtime for current commercial information; use clarification only when "
        "the meaning cannot be represented safely. The remaining route families are safe semantic outcomes for the "
        "corresponding unresolved, contents, navigation, or generic catalogue cases. "
        "The compatibility route_hint is only a transport label and must be one of usage_care,recommendation,accessory,product_detail,query_products,knowledge_base_answer,comparison,unknown_field,clarification; "
        "question_type must be one of safety,count,filter,field,contents_accessories,comparison,recommendation,usage,unknown_field,followup,navigation. "
         "entities are verbatim product mentions from the current turn only. subject_text preserves the requested "
         "physical product, catalogue category, collection, or full versioned identity; it is not a desired outcome or decision role. "
         "For an unbound gift request, keep a broad physical catalogue scope such as the explicitly stated activity's products instead of "
         "treating ‘gift’ as a product form, and preserve gift suitability separately in recommendation_soft_preferences. Context result indexes are opaque one-based "
         "positions supplied by the server; use them only when the current turn refers to those prior results and never "
         "turn them into product identities. When a current turn refers to a product from a prior recommendation and "
         "asks for another/replacement option that changes or improves a stated criterion, this is a new recommendation "
         "search: use route_family=recommendation, context_usage=recommendation_context, decision_requested=true, and "
         "set recommendation_followup_action=alternative (do not leave it empty, even when the customer states only "
         "the comparative criterion). Preserve the current criterion in the recommendation evidence or "
         "preference fields and let the server exclude the prior recommendation by its opaque context. Do not answer "
         "the anchored product's field in this shape. A turn that only asks for the anchored product's recorded field "
         "remains product_bound_qa with context_usage=result_context. "
        f"canonical_fields may contain only these recorded fields: {field_types}. Use product_qa for a named-product "
        "meaning that is not a recorded field, with a concise customer-language qa_evidence_query. Preserve every "
        "independent customer requirement: formal eligibility conditions go in predicate_constraints, non-column "
        "must-haves go in recommendation_evidence_requirements or unrepresented_recommendation_requirements, and "
         "ranking or explanation preferences go in recommendation_soft_preferences. Keep recommendation_constraints "
        "as a JSON object, never a list, with only subject_kind, people, heat_sources, scenarios, weight_preference, price_preference, storage_preference, or dishwasher_safe. subject_kind is only one of cookware,waterware,stove,coffee_gear,accessories; it is a broad scope, not a translated product title. Keep a category such as 烤盘 verbatim in subject_text. people is {min,max}; heat_sources uses card_stove,gas_stove,alcohol_stove,open_flame,induction; scenarios uses camping,hiking,self_drive,seaside,soup. Do not turn a preference into a hard condition just because it sounds useful. predicate_constraints use {field,operator,value,evidence_span,unit,importance}; values and "
        "evidence_span come from the current turn, while later code checks product evidence. Supported operators are material/usage_scene=contains, surface_finish/color/dimensions=contains or =, heat_source=supports or not_supports, waterproof==, and capacity/weight/people use numeric comparison operators. recommendation_evidence_requirements and recommendation_soft_preferences are short strings, not nested objects. Numeric meaning, people, "
         "capacity, weight, dimensions, heating compatibility, material, and surface finish are separate concepts. Every recommendation requirement or preference must be semantically entailed by the current question or an explicit prior customer preference; never infer a plausible shopping criterion from the requested category or use. In particular, a request to choose a gift must preserve the gift use itself, but it does not imply appearance, packaging, prestige, or presentation quality. Add any such criterion only when the customer actually states it, and keep gift suitability separate from an independently stated appearance/packaging preference so evidence for one cannot establish the other. Semantically distinguish a ranking preference from a product-fit requirement: when the customer explicitly asks for an item to be truly/really suitable, dedicated, explicitly supported, or required for a named method, role, or use, preserve that named method/role/use as a required concrete fit in recommendation_evidence_requirements or unrepresented_recommendation_requirements. For example, asking for products truly suitable for pour-over coffee requires evidence that the same product has the requested pour-over form or capability; a related coffee workflow tool is not a substitute. Ordinary use context or a casual preference remains soft when the customer has not made this stronger fit request. "
         "Confidence is low, medium, or high; reasoning_summary is a short audit note, not hidden reasoning. "
         "Set decision_requested=true when the customer asks you to choose or prioritize one concrete catalogue item, including one gift or one item for a beginner. For a comparison, it is also true when the customer asks which participant is better, more suitable, more appropriate, or should be chosen, even when the same turn lists comparison dimensions; it is false only for a neutral differences/specification comparison with no requested verdict. Keep it false for an open-ended category list or general advice that does not ask for a concrete product choice. "
         "For a mixed request, intent_coverage is full only when every independent part is represented."
    )
    user = {
        "question": question,
        "deterministic_plan_context": deterministic_plan,
        "has_recommendation_context": bool(context.get("has_recommendation_context")),
        "active_product_anchor": context.get("active_product_anchor") or {},
        "has_page_product_anchor": bool(context.get("has_page_product_anchor")),
        "database_field_value_hints": context.get("database_field_value_hints") or [],
        "prior_result_context_indexes": context.get("prior_result_context_indexes") or [],
        "prior_result_context_semantics": context.get("prior_result_context_semantics") or {},
        "explicit_prior_customer_preference_texts": (
            context.get("explicit_prior_customer_preference_texts")
            or context.get("prior_customer_preference_texts")
            or []
        ),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _semantic_recommendation_followup_messages(
    *,
    question: str,
    semantic_preplan: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the narrow semantic check for an ambiguous recommendation follow-up."""
    system = (
        "Return exactly one JSON object and no explanation. You are resolving only the discourse action of the current "
        "turn; do not answer the customer and do not output a product fact, SKU, candidate, or database value. "
        "Use exactly these keys: recommendation_followup_action,relative_fields. "
        "recommendation_followup_action must be either alternative or none. Use alternative only when the customer is "
        "asking for another/replacement catalogue option relative to the prior recommendation, including a request that "
        "the replacement be better on a stated dimension. Use none when the customer asks for a recorded field of the "
        "anchored product, chooses among already shown products, narrows a category, or starts a normal recommendation "
        "with new fit requirements without asking for a replacement. relative_fields is an array containing only formal "
        "field names explicitly used as the relative criterion; use an empty array when there is no such criterion. "
        "For a replacement explicitly requested to be lighter, heavier, lower-weight, or otherwise easier to carry by mass, "
        "include weight. For an explicitly relative capacity, size, or other catalogue comparison, include the corresponding "
        "formal field when it is present in the allowed field schema. Do not omit a relative field merely because the "
        "customer used natural comparative wording rather than a numeric value. "
        "Interpret the complete customer turn and the supplied discourse state, not isolated words."
    )
    current_plan = {
        key: semantic_preplan.get(key)
        for key in (
            "route_family",
            "question_type",
            "canonical_fields",
            "context_usage",
            "context_result_indexes",
            "decision_requested",
            "recommendation_constraints",
            "recommendation_evidence_requirements",
            "recommendation_soft_preferences",
            "recommendation_followup_action",
        )
    }
    user = {
        "question": question,
        "has_recommendation_context": bool(context.get("has_recommendation_context")),
        "prior_result_context_semantics": context.get("prior_result_context_semantics") or {},
        "current_semantic_plan": current_plan,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


async def classify_semantic_recommendation_followup(
    db,
    *,
    question: str,
    semantic_preplan: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve only the recommendation-vs-field discourse action with Flash.

    This is intentionally separate from catalogue retrieval: it has no product
    identity or fact authority and only repairs an omitted typed action on a
    context-sensitive semantic plan.
    """
    runtime_settings = _semantic_preplan_runtime_settings()
    runtime_settings["max_tokens"] = 128
    metadata: dict[str, Any] = {}
    try:
        raw_content = await customer_llm_service.chat_completion(
            db,
            _semantic_recommendation_followup_messages(
                question=str(question or "").strip(),
                semantic_preplan=semantic_preplan if isinstance(semantic_preplan, dict) else {},
                context=context if isinstance(context, dict) else {},
            ),
            temperature=runtime_settings["temperature"],
            max_tokens=runtime_settings["max_tokens"],
            purpose="semantic_recommendation_followup",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
            metadata=metadata,
        )
    except Exception as exc:
        return {
            "called": True,
            "recommendation_followup_action": "",
            "relative_fields": [],
            "fallback_reason": f"llm_error:{type(exc).__name__}",
        }
    data = _extract_json_object(str(raw_content or "")) or {}
    action = str(data.get("recommendation_followup_action") or "").strip().lower()
    if action not in {"alternative", "none"}:
        action = ""
    relative_fields = [
        str(item or "").strip()
        for item in (data.get("relative_fields") or [])
        if str(item or "").strip() in customer_field_contract.FORMAL_DETAIL_FIELDS
    ]
    result = {
        "called": True,
        "recommendation_followup_action": action,
        "relative_fields": list(dict.fromkeys(relative_fields)),
        "fallback_reason": "" if action else "invalid_or_empty_semantic_followup_action",
        "followup_model": str(metadata.get("request_model") or runtime_settings.get("model") or ""),
        "followup_latency_ms": metadata.get("elapsed_ms"),
        "followup_total_tokens": (
            (metadata.get("usage") or {}).get("total_tokens")
            if isinstance(metadata.get("usage"), dict)
            else None
        ),
    }
    return result


def _semantic_comparison_decision_messages(
    *,
    question: str,
    semantic_preplan: dict[str, Any],
) -> list[dict[str, str]]:
    """Build a narrow verdict-request review for a comparison turn."""
    system = (
        "Return exactly one JSON object and no explanation: {\"decision_requested\":true|false}. "
        "Judge only whether the complete customer turn asks the assistant to choose, recommend, prefer, or name a "
        "better/more suitable comparison participant. Return true when the customer asks which participant is better, "
        "more suitable, more appropriate, worth choosing, or should be bought, even when the same turn also requests "
        "specific comparison dimensions. Return false for a neutral request that only asks for differences, facts, or "
        "a side-by-side comparison without asking for a verdict. Do not answer the customer, choose a participant, "
        "output a product identity, or inspect product facts. Interpret the whole turn rather than isolated words."
    )
    current_plan = {
        key: semantic_preplan.get(key)
        for key in (
            "route_family",
            "question_type",
            "canonical_fields",
            "decision_requested",
            "reasoning_summary",
        )
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "current_semantic_plan": current_plan},
                ensure_ascii=False,
            ),
        },
    ]


async def classify_semantic_comparison_decision(
    db,
    *,
    question: str,
    semantic_preplan: dict[str, Any],
) -> dict[str, Any]:
    """Repair only an omitted comparison verdict request with Flash."""
    runtime_settings = _semantic_preplan_runtime_settings()
    metadata: dict[str, Any] = {}
    try:
        raw_content = await customer_llm_service.chat_completion(
            db,
            _semantic_comparison_decision_messages(
                question=str(question or "").strip(),
                semantic_preplan=semantic_preplan if isinstance(semantic_preplan, dict) else {},
            ),
            temperature=0,
            max_tokens=64,
            purpose="semantic_comparison_decision_review",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
            metadata=metadata,
        )
    except Exception as exc:
        return {
            "called": True,
            "decision_requested": False,
            "fallback_reason": f"llm_error:{type(exc).__name__}",
        }
    data = _extract_json_object(str(raw_content or "")) or {}
    decision_requested = data.get("decision_requested")
    if type(decision_requested) is not bool:
        return {
            "called": True,
            "decision_requested": False,
            "fallback_reason": "invalid_semantic_comparison_decision",
        }
    return {
        "called": True,
        "decision_requested": decision_requested,
        "fallback_reason": "",
        "review_model": str(metadata.get("request_model") or runtime_settings.get("model") or ""),
        "review_latency_ms": metadata.get("elapsed_ms"),
        "review_total_tokens": (
            (metadata.get("usage") or {}).get("total_tokens")
            if isinstance(metadata.get("usage"), dict)
            else None
        ),
    }


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


async def _repair_semantic_preplan_output(
    db,
    *,
    question: str,
    raw_content: str,
    failure_reason: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    runtime_settings = _semantic_preplan_runtime_settings()
    # Keep repair on exactly the same public semantic schema as the initial
    # preplan. A duplicated, stale mini-prompt had dropped newer route
    # families and structured fields, turning valid customer meaning into an
    # avoidable legacy fallback.
    messages = _semantic_preplan_messages(
        question=question,
        deterministic_plan={},
        context=context if isinstance(context, dict) else {},
    )
    # Repair is a second reading of the same turn, not a hidden route table.
    # Keep one schema-level instruction here so a validation failure cannot
    # turn into a growing collection of phrase- or failure-specific prompts.
    messages[0]["content"] += (
        " The previous semantic JSON did not satisfy an internal schema check. Re-read the complete customer turn "
        "and repair only the JSON shape while preserving all meaning the customer actually expressed. Do not use "
        "literal phrase matching, do not follow the diagnostic as a routing instruction, and do not add or remove "
        "requirements merely to satisfy a field enum. Use the same schema and ontology as the initial interpretation; "
        "represent non-column needs in the semantic requirement or preference arrays, keep product identity spans "
        "verbatim, and leave product facts, SKU values, candidates, and answers to later retrieval. Return exactly "
        "one complete JSON object with no explanation."
    )
    messages[1]["content"] = json.dumps(
        {
            "question": question,
            "previous_output": _safe_preview(raw_content, 5000),
            "internal_diagnostic": str(failure_reason or "")[:200],
            "conversation_context": context if isinstance(context, dict) else {},
        },
        ensure_ascii=False,
    )
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

    '''
    # Kept below only while the old branch is being removed.  It is
    # unreachable by construction; semantic repair must not branch on a
    # customer-language failure label.
    if failure_reason == "product_bound_qa_requires_entity_anchor":
        messages = [
            {
                "role": "system",
                "content": (
                    "Return only one complete semantic-preplan JSON object. The previous plan treated a subject "
                    "with no single-product entity/SKU/validated page or conversation anchor as product_bound_qa, which is invalid. "
                    "Re-read the whole customer turn and choose its actual route: structured_query for listing or "
                    "querying members of a family/series/category/product set; recommendation when the customer asks "
                    "you to select products; clarification when the scope truly cannot be identified. Never return "
                    "product_bound_qa unless the turn itself contains one named product entity or the supplied context "
                    "contains a single active/page product anchor. For a stored family, "
                    "series, brand, category, or product-level listing, keep the literal subject_text, use the matching "
                    "canonical field, and leave structured_query_constraints empty so the database adapter resolves "
                    "the exact stored value. Do not output a product, SKU, fact, candidate, or customer answer. Include "
                    "all required semantic-preplan keys. Diagnostic: product_bound_qa_requires_entity_anchor."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "previous_output": _safe_preview(raw_content, 1000),
                        "identity_context": {
                            "has_active_product_anchor": bool(
                                (context or {}).get("active_product_anchor")
                            ),
                            "has_page_product_anchor": bool(
                                (context or {}).get("has_page_product_anchor")
                            ),
                            "has_named_product_in_current_turn": bool(
                                (context or {}).get("has_unique_current_turn_catalog_product_name")
                            ),
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    if failure_reason == "unknown_canonical_field_in_comparison":
        # The broad ontology prompt can make a small model repeat an illegal
        # mixed-field list. Keep this as a semantic repair, but isolate the
        # one valid contract shape instead of letting prose rules compete.
        messages = [
            {
                "role": "system",
                "content": (
                    "Return only JSON. Repair a named factual comparison with a non-formal requested dimension. "
                    "Use exactly: route_family=comparison, route_hint=comparison, question_type=comparison, "
                    "subtype=relation_comparison, evidence_kind=product_qa, canonical_fields=[], field_type='', "
                    "field_hint='', decision_requested=false, evidence_required=true, ambiguity=false, compound=true, "
                    "intent_coverage=full, context_usage=none, information_scope='', recommendation_constraints={}, "
                    "structured_query_constraints=[], unrepresented_recommendation_requirements=[], "
                    "recommendation_soft_preferences=[]. Preserve the two verbatim product entities. qa_evidence_query "
                    "must be a concise Chinese phrase covering every requested comparison dimension, without product names, "
                    "SKU, value, or answer. Include subject_text, confidence=high, reasoning_summary, and all required keys."
                ),
            },
            {"role": "user", "content": f"question: {question}\nprevious_output: {_safe_preview(raw_content, 1000)}"},
        ]
    messages[0]["content"] += (
        " The prior semantic JSON violated this contract. Repair its schema; "
        "preserve only customer-stated intent and return every required key."
    )
    if failure_reason == "low_confidence_empty_semantic_route":
        messages[0]["content"] += (
            " The prior read was low-confidence and carried no subject, entity, "
            "field, predicate, or conversation handle. Re-read the complete "
            "customer turn before choosing a route. Use general_chat only when "
            "the turn genuinely asks for non-catalogue guidance or ordinary "
            "conversation; if it asks to find, choose, recommend, or provide "
            "bounded product options, use recommendation; if it only asks to "
            "browse or list a catalogue set, use structured_query. Do not answer, "
            "greet, invent a product, or copy a deterministic route hint; return "
            "the semantic route and every meaning-bearing requirement that the "
            "whole sentence supports."
        )
    if failure_reason == "recommendation_scope_only_recheck":
        messages[0]["content"] += (
            " The previous plan correctly chose recommendation but may have "
            "kept only a broad product scope. Re-read the complete current turn "
            "and preserve every independently stated purpose, group, task, "
            "compatibility, capacity, portability, storage, budget, cleaning, "
            "or other fit detail in the appropriate semantic requirement or "
            "preference field. A detail that has no formal field belongs in the "
            "corresponding semantic array; do not drop it merely because it is "
            "not a database column. If the turn truly contains no additional "
            "fit detail, keep the same broad recommendation scope. Keep "
            "route_family=recommendation and decision_requested=true; do not "
            "change it to structured_query, general_chat, or comparison, and do "
            "not select a product, SKU, value, evidence, or answer."
        )
    if failure_reason == "unique_catalog_product_name_generic_route":
        messages[0]["content"] += (
            " The current turn contains a server-validated unique catalog product name, but the prior output "
            "treated that identity as a generic catalogue request or an unconstrained recommendation. "
            "A catalog name may also resemble a product category; that resemblance is not evidence that the customer "
            "asks to select a category item. Re-evaluate the complete customer question. "
            "If it asks for a fact, capability, procedure, judgement, or overview about that named product, return "
            "route_family=product_bound_qa with subject_text equal to the verbatim product mention, "
            "evidence_required=true, evidence_kind=product_qa, canonical_fields=[], and a concise qa_evidence_query. "
            "Otherwise preserve the appropriate non-product route. Do not invent an entity, SKU, value, evidence, or answer."
        )
    if failure_reason == "semantic_subject_omitted_identity_variant":
        messages[0]["content"] += (
            " The prior subject_text omitted an explicit identity-bearing numeric version from the customer's product mention. "
            "Re-evaluate the complete turn and preserve that version in subject_text exactly; do not shorten it to a family name, "
            "do not resolve a SKU, and do not create any product fact or answer."
        )
    if failure_reason == "empty_product_qa_field_semantics":
        messages[0]["content"] += (
            " The prior semantic JSON chose empty product_qa. Re-evaluate the complete customer meaning rather than copying "
            "that incomplete shape. Keep product_qa with an empty field only for a genuinely broad overview, capability, "
            "procedure, judgement, safety, compatibility, or other fact outside the formal taxonomy. When the customer directly "
            "requests an existing recorded field, return only the corresponding allowlisted canonical_fields and structured_field "
            "evidence kind. In particular, a direct request for customer-facing benefits, highlights, differentiators, or reasons "
            "to choose one named product is selling_point. Do not infer a field from the product name, invent a field, SKU, value, "
            "evidence, or answer."
        )
    if failure_reason in {
        "unknown_canonical_field_in_multi_intent",
        "unknown_canonical_field_in_comparison",
    }:
        messages[0]["content"] += (
            " The prior output mixed an allowlisted structured field with another customer-requested meaning that is not in the formal field enum. "
            "Do not silently drop either part and do not collapse a directly recorded field into a broad QA query. Re-evaluate the complete turn. "
            "Retain every directly requested allowlisted field in canonical_fields with evidence_kind=structured_field, and put only the separate "
            "product-specific capability, judgement, procedure, safety, compatibility, or performance meaning into one concise "
            "supplemental_qa_evidence_query. Set compound=true and intent_coverage=full only when both parts are represented. Do not substitute a nearby "
            "structured field for an unrepresented meaning, and do not invent a field, answer, or fact. For a comparison preserve both participants and set "
            "decision_requested=false unless the customer explicitly asks which product is better, more suitable, or should be chosen."
        )
        if failure_reason == "unknown_canonical_field_in_comparison":
            messages[0]["content"] += (
                " This is a mixed factual comparison. The previous output named a non-field comparison dimension, "
                "so return route_family=comparison and keep each valid formal dimension in canonical_fields; put only the non-field comparison "
                "dimension into supplemental_qa_evidence_query. Keep the same two entities and decision_requested=false. The executor will bind "
                "both structured and supplemental evidence to each participant's same SKU."
            )
    if failure_reason == "incomplete_product_bound_multi_intent":
        messages[0]["content"] += (
            " The prior compound semantic JSON requires an independent coverage confirmation for this named-product turn. Re-read the complete question "
            "and represent every independently requested product fact. A broad product_qa query must not absorb a directly requested formal field: retain "
            "every allowlisted recorded field in canonical_fields with evidence_kind=structured_field, and put only the separate non-column fact in "
            "supplemental_qa_evidence_query. If every requested fact is genuinely outside the formal taxonomy, product_qa remains valid. Return "
            "intent_coverage=full only after every requested fact is represented. Remember that supported fuel or gas-canister types are heat_source, "
            "and rated or maximum output is power; when both are independently requested, return both canonical fields. Do not invent a field, product, SKU, value, evidence, or answer."
        )
    if failure_reason in {
        "pairwise_recommendation_requires_comparison_contract",
        "invalid_comparison_decision_criterion",
        "missing_comparison_decision_criterion",
        "pairwise_factual_requires_comparison_contract",
        "invalid_comparison_subtype",
        "relation_comparison_missing_decision",
    }:
        messages[0]["content"] += (
            " This is a named two-or-more-product comparison. MUST return route_family=comparison, "
            "route_hint=comparison, and question_type=comparison. For a generic non-decisive "
            "difference request with no explicit criterion, use subtype=comparison_overview, "
            "evidence_kind=structured_field, and canonical_fields=[]. Otherwise use "
            "subtype=relation_comparison. Preserve decision_requested exactly: true only for "
            "a requested winner and false for a request to list the participants' respective facts. "
            "Translate the requested field or "
            "condition into only the existing formal canonical_fields taxonomy (for example scenario to "
            "usage_scene, people to people, heat compatibility to heat_source, "
            "or lightness to weight); never return recommendation as its field."
        )
    if failure_reason == "invalid_comparison_decision_criterion":
        messages[0]["content"] += (
            " The prior comparison criterion was not wholly in the formal field allowlist. "
            "Do not drop any requested comparison dimension and do not rename it to a nearby field. "
            "Return the mixed comparison as route_family=comparison, subtype=relation_comparison, "
            "evidence_kind=product_qa, canonical_fields=[], decision_requested=false, with the same two "
            "entities and one concise qa_evidence_query covering all requested dimensions. This is a factual "
            "side-by-side request, not a winner selection or catalogue recommendation."
        )
    if failure_reason == "relation_comparison_missing_decision":
        messages[0]["content"] += (
            " The prior JSON is internally invalid: it already selected subtype=relation_comparison, which means the customer requests a winner on its stated criterion, "
            "but it set decision_requested=false. Repair this exact inconsistency by returning decision_requested=true while preserving the semantic participants and requested canonical field. "
            "Do not choose a participant, SKU, value, evidence, or answer."
        )
    if failure_reason == "comparison_overview_requires_semantic_confirmation":
        messages[0]["content"] += (
            " Independently re-read the complete comparison question. Confirm comparison_overview with "
            "decision_requested=false only when the customer asks to list general recorded differences, has no "
            "explicit comparison dimension, and does not ask which participant is better, more suitable, or should "
            "be chosen. An explicit comparison dimension must be preserved even when the customer does not ask for "
            "a winner: use canonical_fields for published formal dimensions; if any requested dimension such as "
            "packing/storage, carrying burden, durability, handling, or suitability is not one formal field, use "
            "evidence_kind=product_qa, canonical_fields=[], and a qa_evidence_query covering every requested "
            "dimension. If the customer asks for a winner on a stated need, use relation_comparison with "
            "decision_requested=true and "
            "represent that need through the permitted comparison evidence contract. Preserve the verbatim "
            "participants; never choose a participant or invent a product fact."
        )
    if failure_reason == "context_followup_misclassified":
        messages[0]["content"] += (
            " The supplied discourse state says the immediately preceding answer contained multiple sealed "
            "comparison results, but the previous JSON treated this non-empty turn as general_chat and returned "
            "no current entities or opaque result handles. Re-read the complete current question together with "
            "the supplied prior-result context. If the turn continues that comparison or asks the assistant to "
            "choose among those prior results, the valid plan is a product decision over result_context: return "
            "route_family=recommendation, decision_requested=true, set "
            "context_usage=result_context, and return the needed opaque context_result_indexes in their result "
            "order. Do not downgrade this to general_chat merely because the choice is a judgement or tradeoff; "
            "the later executor will obtain the sealed same-SKU evidence. Preserve decision_requested according "
            "to the customer's actual request. Do not ask the customer "
            "to repeat product names, do not output a SKU/product identity/fact, and do not use ordinal-word matching. "
            "If the turn is genuinely unrelated, keep general_chat and leave the context handles empty."
        )
        messages[0]["content"] += (
            " Never return general_chat together with result_context handles: that is an incomplete semantic shape. "
            "When the previous discourse is a comparison and the current turn asks to advise, choose, or reaffirm "
            "one of those results, return route_family=recommendation, context_usage=result_context, preserve the "
            "opaque handles, and set decision_requested=true. When it asks for a fact about prior results, use the "
            "appropriate product_bound_qa or comparison shape instead. Keep general_chat only when the current turn "
            "is unrelated and return no context handles."
        )
    if failure_reason == "general_chat_with_product_fact":
        messages[0]["content"] += (
            " The previous semantic JSON is internally contradictory: it selected general_chat while also "
            "carrying a product entity or product-field claim. Re-read the complete current turn and repair the "
            "semantic ownership. If the customer asks for a fact, capability, compatibility, procedure, safety "
            "judgement, usage/care instruction, or other answer about that named or anchored product, return "
            "route_family=product_bound_qa with the same verbatim entity, evidence_kind=product_qa, "
            "evidence_required=true, canonical_fields=[], and one concise qa_evidence_query that describes the "
            "customer's request. If the customer is actually asking for category-level or product-independent "
            "guidance, return general_chat with entities=[], canonical_fields=[], field_type='', field_hint=null, "
            "evidence_required=false, and no catalogue fact claim. Do not use a literal phrase matcher, do not "
            "invent an entity, SKU, field, value, evidence, or answer, and do not return general_chat together "
            "with product entities or result handles."
        )
    if failure_reason == "comparison_scope_underrepresented":
        messages[0]["content"] += (
            " The previous comparison JSON is internally incomplete: the supplied execution context contains a "
            "sealed multi-product decision, but the JSON flattened the turn into broad product_qa with no formal "
            "criterion, no supplemental comparison query, and no decision. Re-read the complete customer question. "
            "Preserve every independently requested formal comparison dimension in canonical_fields; put any "
            "separate non-column dimension in supplemental_qa_evidence_query; set evidence_kind according to the "
            "resulting contract and set decision_requested=true when the customer asks which participant should be "
            "chosen. If the customer truly asks only for factual product-QA differences without a winner, preserve "
            "that factual shape and its complete qa_evidence_query. Keep the same participant entities and never "
            "choose a SKU, value, evidence, or answer in this planning response."
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
                "participants. Do not invent a missing participant. When the "
                "customer instead contrasts generic product forms or asks for "
                "category-level tradeoffs, preparation guidance, or a checklist, "
                "repair this as route_family=general_chat with no entities, "
                "canonical_fields=[], and evidence_required=false so it can be "
                "answered without catalogue product claims. Use clarification "
                "only when the customer genuinely needs a missing named product "
                "fact."
            )
    if failure_reason == "non_evidentiary_comparison":
        messages[0]["content"] += (
            " The prior output carried an inconsistent evidence_required=false "
            "default. If the prior entities contain named catalogue participants, "
            "preserve route_family=comparison, keep those entities, and set "
            "evidence_required=true so same-SKU evidence can decide what is "
            "supported. Use product_qa with a concise query for a non-tabular "
            "criterion. Only use general_chat with no entities when the complete "
            "question is genuinely product-independent. Do not erase named "
            "participants or invent a category-level substitute."
        )
    if failure_reason == "non_evidentiary_recommendation":
        messages[0]["content"] += (
            " The prior output requested a recommendation while explicitly "
            "requiring no evidence and providing no executable product scope. "
            "This remains a catalogue recommendation because the prior semantic "
            "route already requested actual products. Return "
            "route_family=recommendation with evidence_required=true and every "
            "applicable allowlisted recommendation_constraints taken from the "
            "whole customer request. Do not select a product or infer a constraint; "
            "if a requirement cannot be represented, preserve its exact span in "
            "unrepresented_recommendation_requirements."
        )
    if failure_reason == "structured_query_contains_recommendation_context":
        messages[0]["content"] += (
            " The previous JSON mixed route_family=structured_query with recommendation-owned semantic context. "
            "Re-read the whole customer turn. If the customer asks which actual products satisfy a compatibility, "
            "use, quality, or other fit condition, or asks to prioritize qualifying products, return "
            "route_family=recommendation with decision_requested=true. Preserve the requested product form in "
            "subject_text, put every represented formal condition in predicate_constraints, and keep remaining "
            "must-haves or ranking preferences in their recommendation arrays. Use structured_query only for a "
            "genuine browse/list/count with no product choice or fit condition. Do not return a category-only "
            "browse, select a product, or invent a fact."
        )
    if failure_reason in {
        "invalid_structured_query_constraints",
        "structured_query_constraints_outside_structured_query",
        "structured_query_constraints_field_mismatch",
        "named_nonfilter_field_in_structured_query",
        "missing_structured_query_constraints",
        "incomplete_structured_query_scope",
        "catalogue_value_requires_structured_query",
        "unbound_catalogue_browse_requires_structured_query",
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
        if failure_reason in {
            "incomplete_structured_query_scope",
            "catalogue_value_requires_structured_query",
            "unbound_catalogue_browse_requires_structured_query",
        }:
            messages[0]["content"] += (
                " The customer is requesting a catalogue listing, not a knowledge-base, contents, or generic-chat "
                "answer. Re-read the full customer wording and return route_family=structured_query, "
                "route_hint=query_products, question_type=filter. Preserve a named stored collection in subject_text "
                "with canonical_fields=[series] (or brand/product_level for those exact collection questions) and "
                "structured_query_constraints=[]. Use canonical_fields=[category] only when the customer names a "
                "generic product class. For a generic category, subject_text must be the exact category phrase from the "
                "customer question; never replace it with a database label, composite category, synonym, SKU, or answer. "
                "Do not answer from QA/KB or invent a SKU."
            )
        elif set(prior_fields).issubset({"category"}):
            messages[0]["content"] += (
                " This is a catalogue count or unconstrained category list, not a multi-condition filter. "
                "Keep route_family=structured_query and route_hint=query_products; put the requested product kind "
                "only in subject_text, keep canonical_fields=[category], and return "
                "structured_query_constraints=[] with no category predicate."
            )
        elif "category" in prior_fields and all(
            field in _SEMANTIC_STRUCTURED_QUERY_OPERATORS or field == "category"
            for field in prior_fields
        ):
            messages[0]["content"] += (
                " The generic product kind is a retrieval scope, not a filter "
                "dimension. Keep it only in subject_text, remove category from "
                "canonical_fields and from structured_query_constraints, and keep "
                "only the independently requested executable filter fields with "
                "their literal customer spans. Do not invent a predicate or a "
                "product candidate."
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
        elif failure_reason == "incomplete_structured_query_scope":
            messages[0]["content"] += (
                " The previous structured route omitted its catalogue scope. Re-read the complete customer question. "
                "For a list/count constrained by a stored series, brand, product level, or category, preserve the "
                "customer's exact value in subject_text and set canonical_fields to the matching allowlisted field "
                "with structured_query_constraints=[]. For a generic product kind, use subject_text with "
                "canonical_fields=[category]. Do not use QA/KB evidence as a substitute for the missing scope, and "
                "do not invent a product or SKU."
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
            "fact or changing the route. When the customer explicitly seeks a "
            "pot, pan, griddle, water vessel, burner, grinder, or coffee-brewing "
            "apparatus, recommendation_constraints MUST include the corresponding "
            "allowed subject_kind. A product kind is itself a valid bounded "
            "catalogue scope and must not be omitted merely because no other "
            "filter is stated."
        )
    if failure_reason == "missing_recommendation_semantic_context":
        messages[0]["content"] += (
            " The previous response kept the recommendation label but lost the "
            "meaning needed to search the catalogue. Re-read the complete "
            "customer turn and preserve the requested product kind plus every "
            "explicit must-have condition and ranking preference in the allowed "
            "recommendation fields or semantic arrays. Do not turn this into a "
            "comparison, catalogue listing, or generic chat, do not select a "
            "product, and do not invent a fact. If a condition has no formal "
            "field, preserve its customer meaning in the appropriate semantic "
            "requirement array so the later same-SKU evidence step can decide "
            "whether it is verifiable."
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

    '''

async def _repair_unanchored_set_scope_semantically(db, *, question: str) -> dict[str, Any] | None:
    """Let Flash classify an unanchored subject with a tiny closed contract."""
    runtime = _semantic_preplan_runtime_settings()
    messages = [
        {
            "role": "system",
            "content": (
                "Return JSON only with exactly {route_family,set_field,subject_text,subject_kind,unrepresented_requirements}. Re-read the complete customer turn. "
                "route_family must be structured_query, recommendation, or clarification. Use structured_query "
                "when the customer asks to list/query members of a product set; then set_field must be exactly one "
                "of series, brand, category, product_level, subject_text must be the exact literal set phrase from "
                "the customer turn, subject_kind must be empty, and unrepresented_requirements must be empty. "
                "Use recommendation when the customer asks you to select catalogue products, requests a bounded number of relevant choices, "
                "or asks who each choice suits, even if the turn also asks which products exist. For recommendation set_field must be empty, "
                "subject_kind must be exactly cookware, waterware, stove, or coffee_gear, and unrepresented_requirements must contain at most three "
                "material requirements copied verbatim from the customer turn that do not fit subject_kind. "
                "Use clarification when no set scope can be identified; then all four other values must be empty. "
                "Never output a product, SKU, fact, or answer."
            ),
        },
        {"role": "user", "content": json.dumps({"question": question}, ensure_ascii=False)},
    ]
    try:
        content = await customer_llm_service.chat_completion(
            db,
            messages=messages,
            temperature=runtime["temperature"],
            max_tokens=160,
            purpose="semantic_preplan_set_scope_repair",
            api_model_override=runtime["model"],
            response_format=runtime["response_format"],
            thinking=runtime["thinking"],
        )
        data = _extract_json_object(content)
    except Exception:
        return None
    if not isinstance(data, dict) or set(data) != {
        "route_family", "set_field", "subject_text", "subject_kind", "unrepresented_requirements",
    }:
        return None
    route_family = str(data.get("route_family") or "").strip()
    set_field = str(data.get("set_field") or "").strip()
    subject_text = str(data.get("subject_text") or "").strip()
    subject_kind = str(data.get("subject_kind") or "").strip()
    raw_requirements = data.get("unrepresented_requirements")
    requirements = (
        [str(item or "").strip() for item in raw_requirements if str(item or "").strip()]
        if isinstance(raw_requirements, list)
        else []
    )
    if len(requirements) > 3 or any(item not in question for item in requirements):
        return None
    if subject_text and subject_text not in question:
        return None
    if (
        route_family == "structured_query"
        and set_field in {"series", "brand", "category", "product_level"}
        and subject_text
        and not subject_kind
        and not requirements
    ):
        return _validate_semantic_preplan({
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "entities": [],
            "subject_text": subject_text,
            "canonical_fields": [set_field],
            "field_type": set_field,
            "structured_query_constraints": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
            "reasoning_summary": "Flash classified an unanchored product-set query.",
        }, raw_content=content)
    if (
        route_family == "recommendation"
        and not set_field
        and subject_text
        and subject_kind in {"cookware", "waterware", "stove", "coffee_gear"}
    ):
        return _validate_semantic_preplan({
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "subtype": "recommendation",
            "entities": [],
            "subject_text": subject_text,
            "canonical_fields": [],
            "field_type": "",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "recommendation_constraints": {"subject_kind": subject_kind},
            "unrepresented_recommendation_requirements": requirements,
            "recommendation_soft_preferences": [],
            "context_usage": "none",
            "decision_requested": False,
            "reasoning_summary": "Flash classified an unanchored bounded product selection request.",
        }, raw_content=content)
    return None


def _is_unanchored_product_set_display_shape(
    result: dict[str, Any],
    *,
    question: str,
    context: dict[str, Any],
) -> bool:
    """Detect a schema contradiction without classifying words or products."""
    fields = set(result.get("canonical_fields") or [])
    return bool(
        result.get("route_family") == "product_bound_qa"
        and not result.get("entities")
        and not bool(context.get("has_unique_current_turn_catalog_product_name"))
        and not customer_agent_service._extract_skus(question)
        and not result.get("context_result_indexes")
        and {"product_name_cn", "sku"}.issubset(fields)
        and fields <= {"product_name_cn", "product_name_en", "sku"}
        and not result.get("fallback_reason")
    )


def _semantic_product_bound_requires_entity_anchor(
    result: dict[str, Any],
    *,
    question: str,
    context: dict[str, Any],
) -> bool:
    """Reject a product-QA route that has no product identity at all.

    This is an invariant of the semantic contract, not a second intent
    classifier: a product-bound answer needs either a model-resolved entity or
    an identity supplied by the surrounding page/conversation context.  When
    that invariant is false, the same semantic planner gets one chance to
    reread the complete turn and choose recommendation, catalogue query,
    general guidance, or clarification.
    """
    if result.get("route_family") != "product_bound_qa":
        return False
    if result.get("entities"):
        return False
    if result.get("context_result_indexes"):
        return False
    if context.get("active_product_anchor") or context.get("has_page_product_anchor"):
        return False
    if context.get("has_unique_current_turn_catalog_product_name"):
        return False
    if customer_agent_service._extract_skus(question):
        return False
    return True


async def _semantic_supplemental_qa_is_independent(
    db,
    *,
    question: str,
    canonical_fields: list[str],
    supplemental_qa_evidence_query: str,
) -> bool | None:
    """Let the semantic model decide whether a proposed supplement is factual.

    The caller supplies no product identity, database value, or answer.  The
    closed boolean is therefore an intent-boundary decision only; the normal
    FieldContract and evidence layers retain all customer-fact authority.
    """
    runtime_settings = _semantic_preplan_runtime_settings()
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON: {\"independent\":boolean}. You review the semantic boundary of one customer "
                "turn; do not answer the customer, resolve a product, infer a SKU, choose a field, or use database "
                "facts. Decide true only if the complete question contains an independently requested concrete product "
                "fact that is not semantically covered by the union of the stated formal fields. A separately requested "
                "capability, judgement, procedure, safety, compatibility, or performance fact can be independent. A "
                "supplement that merely restates, combines, paraphrases, broadens, or asks for an explanation of the "
                "formal fields is false, even when it uses different words. Courtesy scaffolding, conversational softeners, "
                "or a generic request for a response are also false. Interpret the complete sentence rather than matching "
                "individual words."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": str(question or ""),
                    "formal_canonical_fields": list(canonical_fields or []),
                    "proposed_supplemental_product_qa": str(supplemental_qa_evidence_query or ""),
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
            max_tokens=min(int(runtime_settings["max_tokens"]), 96),
            purpose="semantic_supplemental_intent_review",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return None
    payload = _extract_json_object(content)
    value = payload.get("independent") if isinstance(payload, dict) else None
    return value if isinstance(value, bool) else None


async def _semantic_compound_supplemental_query(
    db,
    *,
    question: str,
    canonical_fields: list[str],
    runtime_settings: dict,
) -> dict[str, Any]:
    """Separate a retrievable capability from an evaluative safety request.

    This is intentionally a semantic adapter, not a field alias table.  The
    formal field remains owned by the parent FieldContract; the child query is
    allowed to retrieve only a distinct, directly stated product capability.
    """
    messages = [
        {"role": "system", "content": (
            "Return only JSON: {capability_query:string,safety_evaluation_requested:boolean}. "
            "Separate the non-column product intent in the complete question from the listed formal fields. "
            "capability_query must contain only a distinct, directly retrievable capability, compatibility, use condition, "
            "or behavior; it must not repeat a formal field, its value, a product name, SKU, or an answer. "
            "When a customer asks whether something is safe and also asks a concrete capability or condition, set "
            "safety_evaluation_requested=true and make capability_query the concrete capability, never a safety guarantee. "
            "For example, an ask about material safety plus use at altitude should retrieve altitude-use compatibility, "
            "not material safety. Return an empty capability_query when there is no separate retrievable capability."
        )},
        {"role": "user", "content": json.dumps(
            {"question": question, "formal_canonical_fields": canonical_fields}, ensure_ascii=False
        )},
    ]
    try:
        raw = await customer_llm_service.chat_completion(
            db, messages, temperature=0,
            max_tokens=min(int(runtime_settings["max_tokens"]), 96),
            purpose="semantic_compound_supplemental_query",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return {"capability_query": "", "safety_evaluation_requested": False}
    payload = _extract_json_object(str(raw or "")) or {}
    # ``query`` is accepted only for a short-lived model-output migration;
    # downstream treats it as semantic output and never parses it lexically.
    capability_query = str(payload.get("capability_query") or payload.get("query") or "").strip()[:160]
    return {
        "capability_query": capability_query,
        "safety_evaluation_requested": bool(payload.get("safety_evaluation_requested")),
    }


async def _semantic_product_field_supplemental_review(
    db,
    *,
    question: str,
    canonical_fields: list[str],
    runtime_settings: dict[str, Any],
) -> dict[str, Any]:
    """Check whether a formal-field turn also asks an independent judgement.

    A customer can ask for a recorded value and, in the same sentence, ask
    what that value means for a concrete use.  The primary preplan may
    serialize only the field because both parts share one noun.  This review
    keeps that semantic distinction in the LLM layer; it never selects an
    entity, field, value, candidate, or answer.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON: {\"independent\":boolean,\"supplemental_query\":string}. "
                "Review the complete customer question against the already selected formal product fields. "
                "Do not answer, resolve a product, choose a SKU, use a database value, or infer evidence. "
                "independent=true only when the question asks for a separate product-specific capability, "
                "suitability judgement, compatibility condition, procedure, or practical conclusion that is "
                "not itself the recorded field. A question that merely asks for the field value, even with a "
                "background use scene, is false. When a field question also asks whether the recorded value is "
                "enough or suitable for a stated group and task, that practical judgement is independent and "
                "must be preserved. supplemental_query must be a concise Chinese retrieval phrase for only "
                "that separate intent, preserving its stated condition, without a product name, SKU, database "
                "value, or answer. Return an empty supplemental_query when independent=false."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": str(question or ""),
                    "formal_canonical_fields": list(canonical_fields or []),
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        raw = await customer_llm_service.chat_completion(
            db,
            messages,
            temperature=0,
            max_tokens=min(int(runtime_settings["max_tokens"]), 120),
            purpose="semantic_product_field_supplemental_review",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return {"independent": False, "supplemental_query": "", "fallback_reason": "review_error"}
    payload = _extract_json_object(str(raw or "")) or {}
    independent = payload.get("independent") is True
    query = str(payload.get("supplemental_query") or "").strip()[:160] if independent else ""
    if independent and not query:
        independent = False
    return {
        "independent": independent,
        "supplemental_query": query,
        "fallback_reason": "" if independent else "no_independent_product_fact",
    }


async def _semantic_compound_product_qa_queries(
    db,
    *,
    question: str,
    runtime_settings: dict,
) -> list[str]:
    """Return independent retrieval scopes for a compound product-QA turn."""
    try:
        raw = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": (
                    "Return only JSON: {items:[{query:string,source_span:string}]}. Split the complete customer question into its independently requested "
                    "product capabilities, judgements, procedures, compatibility facts, or conditions. query is a concise retrieval phrase for exactly "
                    "one requested fact, without product names, SKU, values, answers, or inferred facts. source_span must be the exact uninterrupted customer "
                    "words that ask that fact, copied verbatim from the complete question; include the full condition and predicate, not a shorter inferred property. "
                    "Return one to three items in customer-intent order. Every item must correspond one-to-one to an explicit customer clause. "
                    "Do not emit a prerequisite property, possible evidence type, rationale, or intermediate concept merely because it could help answer "
                    "another explicit clause; keep that explicit clause as one query. Do not combine genuinely separate customer conditions into one query."
                    " A broad request for an overview, notable points, preparation, or general usage advice is one query, not separate "
                    "selection and usage sub-queries."
                )},
                {"role": "user", "content": json.dumps({"question": question}, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=min(int(runtime_settings["max_tokens"]), 160),
            purpose="semantic_compound_product_qa_queries",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return []
    payload = _extract_json_object(str(raw or "")) or {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    source_spans = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_span = str(item.get("source_span") or "").strip()[:160]
        query = str(item.get("query") or "").strip()[:160]
        if query and source_span and source_span in question:
            source_spans.append(source_span)
    if source_spans:
        return list(dict.fromkeys(source_spans))[:3]
    # Accept the former query-only shape during the model-output migration.
    values = payload.get("queries") if isinstance(payload.get("queries"), list) else []
    return list(dict.fromkeys(str(value or "").strip()[:160] for value in values if str(value or "").strip()))[:3]


async def _semantic_gift_field_scope_review(db, *, question: str, runtime_settings: dict) -> dict[str, Any] | None:
    """Disambiguate promotional gifts from product gifting suitability semantically."""
    try:
        raw = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": (
                    "Return only JSON: {promotional_gift_requested:boolean,product_qa_query:string}. "
                    "Decide from the complete customer question whether it asks whether a purchase includes a promotional free gift, giveaway, or bonus item. "
                    "If it instead asks whether the named product is suitable to give someone as a present, set promotional_gift_requested=false "
                    "and return a concise product_qa_query for gifting suitability only. Exclude every other condition in the same question, including "
                    "dishwasher, material, size, price, use, cleaning, compatibility, or any other field. Do not return a product name, SKU, value, answer, or new fact."
                )},
                {"role": "user", "content": json.dumps({"question": question}, ensure_ascii=False)},
            ], temperature=0, max_tokens=min(int(runtime_settings["max_tokens"]), 96),
            purpose="semantic_gift_field_scope_review", api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"], thinking=runtime_settings["thinking"],
        )
    except Exception:
        return None
    payload = _extract_json_object(str(raw or "")) or {}
    value = payload.get("promotional_gift_requested")
    if not isinstance(value, bool):
        return None
    return {"promotional_gift_requested": value, "product_qa_query": str(payload.get("product_qa_query") or "").strip()[:160]}


async def _repair_semantic_recommendation_constraint_partition(
    db,
    *,
    question: str,
    invalid_constraints: Any,
    invalid_predicate_constraints: Any,
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
                "Output exactly {\"recommendation_constraints\":object,\"predicate_constraints\":array,\"unrepresented_recommendation_requirements\":array}. "
                "recommendation_constraints may contain only subject_kind (cookware|waterware|stove|coffee_gear), people ({min,max}), "
                "heat_sources (card_stove|gas_stove|alcohol_stove|open_flame|induction), scenarios (camping|hiking|self_drive|seaside|soup), "
                "weight_preference (lightweight), price_preference (affordable|premium), storage_preference (compact_storage), and dishwasher_safe (true). "
                "predicate_constraints must contain every explicit formal requirement as {field,operator,value,evidence_span,unit}; fields are material,surface_finish,capacity,weight,dimensions,people,color,heat_source,usage_scene,waterproof and operators follow their ordinary typed meaning. Normalize numeric units, keep evidence_span as an exact customer substring, and never include product facts. Keep only constraints explicitly stated by the customer. For heat_source, a cooking action or dish is not an explicit stove or fuel; only a named source or compatibility request may produce that field. Every material customer requirement that cannot use those typed fields "
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
                    "invalid_predicate_constraints": invalid_predicate_constraints,
                    "invalid_unrepresented_recommendation_requirements": invalid_unrepresented_requirements,
                },
                ensure_ascii=False,
            ),
        },
    ]
    for attempt in range(2):
        attempt_messages = [dict(message) for message in messages]
        if attempt:
            attempt_messages[0]["content"] += (
                " Your preceding unrepresented_recommendation_requirements values were not exact "
                "substrings of the customer question. Do not translate, summarize, or use English "
                "labels: copy the customer's original characters exactly, or return an empty array."
            )
        try:
            content = await customer_llm_service.chat_completion(
                db,
                attempt_messages,
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
            "recommendation_constraints", "predicate_constraints", "unrepresented_recommendation_requirements",
        }:
            continue
        constraints = _validated_recommendation_constraints(data.get("recommendation_constraints"))
        predicates = _validated_structured_query_constraints(data.get("predicate_constraints"))
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
        if constraints is None or predicates is None or unrepresented is None:
            continue
        if any(item not in question for item in unrepresented) or any(
            str(item.get("evidence_span") or "") not in question
            for item in predicates
        ):
            continue
        return {
            "recommendation_constraints": constraints,
            "predicate_constraints": predicates,
            "structured_query_constraints": predicates,
            "unrepresented_recommendation_requirements": unrepresented,
        }
    return None


async def _recover_semantic_recommendation_context_packet(
    db,
    *,
    question: str,
    subject_text: str,
    subject_kind: str,
    reasoning_summary: str,
) -> dict[str, list[str]] | None:
    """Recover omitted recommendation meaning without choosing a product.

    This is intentionally a small semantic extraction packet. It compares the
    whole customer turn with the already accepted broad recommendation scope
    and returns only the customer-owned fit language that the RAG executor
    needs. It does not resolve a category, identity, SKU, evidence, or answer.
    """
    runtime_settings = _semantic_preplan_runtime_settings()
    messages = [
        {
            "role": "system",
            "content": (
                "Return only JSON with exactly these keys: "
                "recommendation_evidence_requirements, recommendation_soft_preferences, "
                "unrepresented_recommendation_requirements. Read the whole customer "
                "turn, not only the broad product scope. Put every independently stated "
                "condition that the selected product is expected to satisfy into "
                "recommendation_evidence_requirements; put a condition that only helps "
                "rank or explain an otherwise usable product into "
                "recommendation_soft_preferences. Preserve the customer's meaning in "
                "short Chinese phrases; these are retrieval and writing inputs, never "
                "product facts. If a must-have cannot be represented safely by those "
                "semantic phrases or the typed predicate contract, copy the exact "
                "customer substring into unrepresented_recommendation_requirements. "
                "A broad product kind, a request to recommend, and courtesy wording are "
                "not requirements by themselves. Do not output a route, product name, "
                "SKU, candidate, database value, answer, or explanation."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": str(question or ""),
                    "accepted_subject_text": str(subject_text or ""),
                    "accepted_subject_kind": str(subject_kind or ""),
                    "prior_reasoning_summary": str(reasoning_summary or ""),
                },
                ensure_ascii=False,
            ),
        },
    ]
    for attempt in range(2):
        attempt_messages = [dict(message) for message in messages]
        if attempt:
            attempt_messages[0]["content"] += (
                " Recheck that every concrete selection condition in the question is "
                "represented in one of the three arrays; do not leave a condition only "
                "in the prior reasoning summary. Any unrepresented must-have must be "
                "copied exactly from the question."
            )
        try:
            raw = await customer_llm_service.chat_completion(
                db,
                attempt_messages,
                temperature=runtime_settings["temperature"],
                max_tokens=min(int(runtime_settings["max_tokens"]), 220),
                purpose="semantic_recommendation_context_recovery",
                api_model_override=runtime_settings["model"],
                response_format=runtime_settings["response_format"],
                thinking=runtime_settings["thinking"],
            )
        except Exception:
            continue
        data = _extract_json_object(str(raw or ""))
        if not isinstance(data, dict):
            continue
        evidence = _validated_recommendation_evidence_requirements(
            data.get("recommendation_evidence_requirements")
        )
        soft = _validated_recommendation_soft_preferences(
            data.get("recommendation_soft_preferences")
        )
        unrepresented = _validated_unrepresented_recommendation_requirements(
            data.get("unrepresented_recommendation_requirements")
        )
        if evidence is None or soft is None or unrepresented is None:
            continue
        if any(item not in question for item in unrepresented):
            continue
        return {
            "recommendation_evidence_requirements": evidence,
            "recommendation_soft_preferences": soft,
            "unrepresented_recommendation_requirements": unrepresented,
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


async def _semantic_product_qa_scope_review(
    db,
    *,
    question: str,
    runtime_settings: dict[str, Any],
) -> bool | None:
    """Ask the semantic layer whether a product-QA turn has independent facts.

    The review receives no SKU, product value, field, candidate, answer, or
    initial plan. It cannot route or answer the turn; it only resolves the
    multi-intent shape that controls whether later same-SKU evidence may keep
    a supported part while safely identifying an unverified independent part.
    """
    try:
        raw = await customer_llm_service.chat_completion(
            db,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only JSON: {compound:boolean}. You are a semantic intent-shape auditor, not a router or answer writer. "
                        "Read the complete customer question. compound=true only when it independently asks two or more product facts, capabilities, conditions, procedures, judgements, or comparisons that need separate evidence; "
                        "compound=false for one broad product overview, preparation, tradeoff, or decision-support request even if it has several words. "
                        "For example, a question asking whether a product is durable AND whether it can hold boiling water is compound=true; "
                        "a question asking generally what to know before using it is compound=false. "
                        "Questions such as 'what is worth noting', 'what are its main points', or 'what should I know about using it' are one broad overview and compound=false, "
                        "unless the customer separately asks another independent fact or condition. "
                        "A single suitability judgment whose wording includes a user type and use scenario (for example whether it suits a beginner for pour-over coffee) is one fact, compound=false; "
                        "do not split its user type, scenario, or product name into extra questions. "
                        "Do not infer a product, SKU, value, evidence, or answer."
                    ),
                },
                {"role": "user", "content": json.dumps({"question": str(question or "")}, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=min(int(runtime_settings["max_tokens"]), 80),
            purpose="semantic_product_qa_scope_review",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
        )
    except Exception:
        return None
    payload = _extract_json_object(str(raw or "")) or {}
    return payload.get("compound") if isinstance(payload.get("compound"), bool) else None


async def _legacy_plan_customer_question_semantic(
    db,
    question: str,
    deterministic_plan: dict | None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Retired semantic planner body kept inert until the file is split."""
    return None
    '''
    text = str(question or "").strip()
    if not text:
        return _empty_semantic_preplan(fallback_reason="empty_question")
    deterministic_plan = deterministic_plan if isinstance(deterministic_plan, dict) else {}
    context = context if isinstance(context, dict) else {}
    context = dict(context)
    context["database_field_value_hints"] = _database_field_value_hints(db, text)
    messages = _semantic_preplan_messages(question=text, deterministic_plan=deterministic_plan, context=context)
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
    if initial_unrepresented_requirements is None:
        initial_unrepresented_requirements = []
    initial_soft_preferences = (
        _validated_recommendation_soft_preferences(
            initial_semantic_data.get("recommendation_soft_preferences")
        )
        if isinstance(initial_semantic_data, dict)
        else []
    )
    if initial_soft_preferences is None:
        initial_soft_preferences = []
    initial_evidence_requirements = (
        _validated_recommendation_evidence_requirements(
            initial_semantic_data.get("recommendation_evidence_requirements")
        )
        if isinstance(initial_semantic_data, dict)
        else []
    )
    if initial_evidence_requirements is None:
        initial_evidence_requirements = []
    # A comparison route is semantic intent. If that route is explicit but the
                "evidence_kind": "structured_field",
                "recommendation_constraints": {"subject_kind": "accessories"},
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
                "fallback_reason": "",
                "accepted_or_overridden": "literal_accessory_scope_recovery",
                "override_reason": "typed_current_turn_accessory_scope",
                "entity_scope": "category_scope",
                "intent_coverage": "full",
                "reasoning_summary": "Current-turn accessory scope recovered for catalogue verification.",
            })
            result["accessory_scope_recovery"] = "literal_current_turn_contract"
    # A high-confidence recommendation with an identified subject or formal
    # customer fields but no executable subject contract is incomplete semantic
    # output, not permission for a legacy keyword planner to decide the need.
    # Send only that semantic object back through the same schema repair path.
    # The repair remains an allowlisted LLM decision; deterministic code never
    # derives a subject kind from the customer's wording.
    recommendation_constraints = result.get("recommendation_constraints")
    # A product-bound fact contract must have an independently established
    # single-product anchor.  A family/category phrase with identity fields is
    # a set query, not permission to collapse that set to the first matching
    # catalogue row.  Reject the inconsistent semantic shape and let the same
    # model repair the whole-sentence route; no keyword or product family is
    # inferred here.
    if _is_unanchored_product_set_display_shape(result, question=text, context=context):
        result["fallback_reason"] = "product_bound_qa_requires_entity_anchor"
    if _semantic_product_bound_requires_entity_anchor(result, question=text, context=context):
        # A category-level usage/care or safety question has no product to
        # seal.  Keep it as semantic general guidance instead of sending an
        # identity-free product-QA shape through a repair loop and eventually
        # into a missing-product response.  This is an identity invariant, not
        # a phrase route; named/current products still remain product_bound_qa.
        if bool(result.get("qa_or_usage_care")) or str(result.get("route_hint") or "").strip() == "usage_care":
            result.update({
                "route_family": "general_chat",
                "route_hint": "general_chat",
                "question_type": "general_guidance",
                "entities": [],
                "subject_text": "",
                "canonical_fields": [],
                "field_type": "",
                "field_hint": None,
                "evidence_required": False,
                "evidence_kind": "structured_field",
                "qa_evidence_query": "",
                "context_usage": "none",
                "context_result_indexes": [],
                "decision_requested": False,
                "accepted_or_overridden": "normalized",
                "override_reason": "identity_free_usage_care_is_general_guidance",
                "fallback_reason": "",
                "ambiguity": False,
            })
        else:
            result["fallback_reason"] = "product_bound_qa_requires_entity_anchor"
    # A named-product question already understood as a factual request cannot
    # safely fall through to a legacy catalogue/KB route merely because the
    # first semantic JSON left its canonical field as ``unknown``.  Give the
    # same semantic model one bounded schema repair; the deterministic layer
    # still accepts only an allowlisted field and never supplies one itself.
    if (
        result.get("route_family") == "product_bound_qa"
        and result.get("question_type") == "field"
        and bool(result.get("evidence_required"))
        # ``product_qa`` deliberately represents a product fact outside the
        # formal field taxonomy.  An empty formal field is therefore its
        # valid completed shape, not a reason to discard semantic intent and
        # reopen a legacy field shortcut.
        and str(result.get("evidence_kind") or "").strip() != "product_qa"
        and str(result.get("field_type") or "") in {"", "unknown"}
        and set(result.get("canonical_fields") or []) <= {"unknown"}
        and not result.get("fallback_reason")
    ):
        result["fallback_reason"] = "unclassified_product_bound_field"
    # A provider can understand an identity comparison in its reasoning but
    # serialize the whole coordinated phrase as one product-bound subject.
    # That shape cannot be entity-sealed. Ask the same semantic model to split
    # the participants; deterministic code still supplies no product or SKU.
    compressed_subject = str(result.get("subject_text") or "").strip()
    if (
        result.get("route_family") == "product_bound_qa"
        and (
            len(result.get("entities") or []) >= 2
            or (
                not (result.get("entities") or [])
                and any(joiner in compressed_subject for joiner in ("和", "与", "跟", "及", "、", "/"))
                and any(term in text for term in ("同一款", "同款", "同一个产品", "区别", "差异", "关系", "相比", "对比"))
            )
        )
        and not result.get("fallback_reason")
    ):
        result["fallback_reason"] = "pairwise_factual_requires_comparison_contract"
    # ``product_qa`` is the valid shape for an open product fact, but a model
    # can also omit a directly requested formal field and leave the same empty
    # shape.  This is only a structural trigger for a second semantic reading:
    '''

async def plan_customer_question_semantic(
    db,
    question: str,
    deterministic_plan: dict | None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Interpret one turn once, then hand the semantic plan to RAG.

    The planner is deliberately not a catalogue router.  Flash owns the
    meaning of the complete turn; local code only validates the public JSON
    envelope and keeps product facts out of it.  A malformed envelope gets
    one generic same-schema reread.  Candidate retrieval, same-SKU facts and
    answer writing happen downstream.
    """
    text = str(question or "").strip()
    if not text:
        return _empty_semantic_preplan(fallback_reason="empty_question")

    deterministic_plan = deterministic_plan if isinstance(deterministic_plan, dict) else {}
    context = dict(context) if isinstance(context, dict) else {}
    context["database_field_value_hints"] = _database_field_value_hints(db, text)
    runtime_settings = _semantic_preplan_runtime_settings()
    messages = _semantic_preplan_messages(
        question=text,
        deterministic_plan=deterministic_plan,
        context=context,
    )
    metadata: dict[str, Any] = {}
    call_count = 0
    try:
        raw_content = await customer_llm_service.chat_completion(
            db,
            messages,
            temperature=runtime_settings["temperature"],
            max_tokens=runtime_settings["max_tokens"],
            purpose="semantic_preplan",
            api_model_override=runtime_settings["model"],
            response_format=runtime_settings["response_format"],
            thinking=runtime_settings["thinking"],
            metadata=metadata,
        )
        call_count += 1
    except Exception as exc:
        call_count += 1
        result = _empty_semantic_preplan(
            called=True,
            fallback_reason=f"llm_error:{type(exc).__name__}",
        )
        result["error"] = str(exc)[:240]
        result["llm_call_count"] = call_count
        result["llm_call_count_delta"] = call_count
        _apply_semantic_preplan_observability(result, metadata, runtime_settings)
        return result

    result = _validate_semantic_preplan(
        _extract_json_object(str(raw_content or "")),
        raw_content=str(raw_content or ""),
        customer_question=text,
    )
    if result.get("fallback_reason"):
        try:
            repaired_content = await _repair_semantic_preplan_output(
                db,
                question=text,
                raw_content=str(raw_content or ""),
                failure_reason=str(result.get("fallback_reason") or ""),
                context=context,
            )
            call_count += 1
            result = _validate_semantic_preplan(
                _extract_json_object(str(repaired_content or "")),
                raw_content=str(repaired_content or ""),
                customer_question=text,
            )
            result["semantic_repaired"] = True
        except Exception as exc:
            call_count += 1
            result["semantic_repair_unavailable"] = True
            result["semantic_repair_error"] = type(exc).__name__

    # The first semantic read can compress a formal field plus a practical
    # judgement into a field-only shape.  Ask a small, typed completeness
    # reviewer to preserve an independent non-column intent when present; the
    # downstream service already knows how to merge that intent through the
    # sealed same-SKU QA/RAG path.  This is semantic arbitration, not a word
    # matcher or a product-specific evidence gate.
    if (
        not result.get("fallback_reason")
        and str(result.get("route_family") or "").strip() == "product_bound_qa"
        and str(result.get("evidence_kind") or "").strip() == "structured_field"
        and list(result.get("canonical_fields") or [])
        and not str(result.get("supplemental_qa_evidence_query") or "").strip()
    ):
        supplemental_review = await _semantic_product_field_supplemental_review(
            db,
            question=text,
            canonical_fields=list(result.get("canonical_fields") or []),
            runtime_settings=runtime_settings,
        )
        call_count += 1
        result["semantic_product_field_supplemental_review"] = supplemental_review
        supplemental_query = str(supplemental_review.get("supplemental_query") or "").strip()
        if supplemental_review.get("independent") is True and supplemental_query:
            result["supplemental_qa_evidence_query"] = supplemental_query
            result["compound"] = True
            result["intent_coverage"] = "full"

    result["llm_call_count"] = call_count
    result["llm_call_count_delta"] = call_count
    _apply_semantic_preplan_observability(result, metadata, runtime_settings)
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

    # A customer who says “想买/帮我选 … 有哪些适合 … 的选择” is asking
    # for a decision shortlist.  Let that decision intent win over the broad
    # “有哪些” catalogue-list grammar; the semantic planner then ranks sealed
    # SKU evidence instead of dumping the whole category.
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
    if len(_extract_compare_product_refs(text)) < 2:
        return False
    if "vs" in text.lower() or "VS" in text:
        return True
    # A relation request can list explicit products with enumeration marks
    # (A、B、C 三者是什么关系) rather than the binary conjunction "和".
    # Once two or more explicit references are present, its comparison intent
    # is carried by the complete utterance, not by one fixed separator.
    return any(term in text for term in (
        "区别", "不同", "差异", "对比", "比较", "关系", "同一款", "同款",
        "同一个产品", "一样", "相同", "哪个", "哪款", "更适合", "该买", "应该买", "买哪个",
    ))


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
        # In an identity/relation comparison, the right product is followed
        # directly by the predicate ("A 和 B 是同一款吗").  Bound the product
        # span before that predicate so model-unavailable fallback can still
        # seal both catalogue identities instead of treating the whole clause
        # as a product name.
        right = re.split(
            r"(?:是|是否|是不是)?(?:同一款|同款|同一个产品|一样|相同)"
            r"|(?:有)?(?:什么|哪些)?(?:区别|不同|差异)"
            r"|[？?。！!；;]",
            right,
            maxsplit=1,
        )[0]
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
    # "火力多大" asks for burner output, not physical dimensions.  This is a
    # field-intent precedence rule, independent of product identity.
    if "火力" in text or any(term in text for term in ("功率", "瓦数", "多少瓦")):
        return "功率"
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
    if _looks_like_scenario_selection_question(text) or _looks_like_scenario_statement_recommendation(text):
        return True
    if any(term in text for term in ("推荐", "买什么", "买哪款", "选哪款", "该买哪", "买什么产品")):
        return True
    if (
        any(term in text for term in ("想买", "想找", "需要", "帮我选"))
        and any(term in text for term in ("选择", "适合"))
        and any(term in text for term in ("有哪些", "哪些", "哪几", "哪款"))
    ):
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


def _has_two_person_signal(text: str) -> bool:
    return any(term in text for term in ("两个人", "2人", "两人", "二人"))
