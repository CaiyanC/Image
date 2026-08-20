"""Trace-based release gate for the semantic/RAG development environment.

This is an offline evaluator for ``semantic_rag_deep_audit`` reports.  It does
not route customer questions, parse customer wording, or replace Flash's
semantic interpretation.  The gate only asks whether a real dev run produced
an answer that can be audited back to the same-SKU evidence packet, whether
the provider actually ran, and whether normal/stream/context checks were
consistent.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from semantic_rag_deep_audit import CASES, _semantic_provenance_flags
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.semantic_rag_deep_audit import CASES, _semantic_provenance_flags


PRODUCT_EVIDENCE_TYPES = {
    "product_db",
    "product_field",
    "product_qa",
    "knowledge_qa",
    "knowledge_document",
    "knowledge_base",
    "usage_care_knowledge",
}

FIELD_LABEL_ALIASES = {
    "capacity": {"capacity", "容量", "容积"},
    "weight": {"weight", "重量", "净重", "毛重", "gross_weight", "gross_weight_g"},
}

REQUIRED_SEQUENCE_IDS = {
    "deep_context_sequence",
    "deep_normal_stream_parity",
}


def _case_specs() -> dict[str, dict[str, Any]]:
    return {
        str(case.get("id") or "").strip(): case
        for case in CASES
        if str(case.get("id") or "").strip()
    }


def _compact_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s,，、_\-]+", "", text).casefold()


def _numeric_unit(value: Any) -> tuple[float, str] | None:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|g|克|kg|千克)(?![a-z])", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"ml", "毫升"}:
        return number, "ml"
    if unit in {"l", "升"}:
        return number * 1000.0, "ml"
    if unit in {"kg", "千克"}:
        return number * 1000.0, "g"
    return number, "g"


def _fact_variant_present(answer: str, variants: list[str]) -> bool:
    """Accept exact text or a unit-equivalent numeric rendering.

    This is limited to facts explicitly declared by a deep-audit case.  It is
    not a general evidence quote gate and never decides routing or retrieval.
    """
    compact_answer = _compact_text(answer)
    answer_numeric = _numeric_unit(answer)
    for variant in variants:
        compact_variant = _compact_text(variant)
        if compact_variant and compact_variant in compact_answer:
            return True
        variant_numeric = _numeric_unit(variant)
        if answer_numeric and variant_numeric and answer_numeric[1] == variant_numeric[1]:
            if abs(answer_numeric[0] - variant_numeric[0]) < 1e-6:
                return True
    return False


def _evidence_field_matches(item: dict[str, Any], field: str) -> bool:
    aliases = FIELD_LABEL_ALIASES.get(str(field or "").strip().casefold(), set())
    if not aliases:
        return False
    label = _compact_text(item.get("field_label") or item.get("field") or "")
    return any(_compact_text(alias) == label for alias in aliases)


def _rag_evidence_texts(record: dict[str, Any]) -> list[str]:
    """Return customer-visible RAG evidence text for an offline fact check.

    Same-SKU RAG evidence is normally a knowledge chunk or a ProductQa
    excerpt, not a structured ``field_label/value`` row.  The release gate
    must therefore inspect the selected evidence text when a field question
    has deliberately been adapted into the product-QA RAG lane.  This helper
    is diagnostic only; it never changes retrieval, routing, or the answer.
    """
    response = record.get("response")
    evidence = response.get("evidence") if isinstance(response, dict) else []
    if not isinstance(evidence, list):
        return []
    texts: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        for key in ("evidence_text", "value", "content"):
            text = str(item.get(key) or "").strip()
            compact = _compact_text(text)
            if compact and compact not in seen:
                seen.add(compact)
                texts.append(text)
    return texts


def _rag_field_fact_present(record: dict[str, Any], field: str) -> bool:
    """Check a declared audit fact against selected RAG text.

    Prefer an explicit field-labelled evidence row when one exists.  If the
    evidence is an atomic knowledge chunk, accept an equivalent value found
    in that chunk (including ``gross_weight_g: 1320.0`` beside an answer that
    says ``1320g``).  The field comes from the sealed audit case/Flash
    preplan; this is not a lexical classifier for customer requests.
    """
    response = record.get("response")
    evidence = response.get("evidence") if isinstance(response, dict) else []
    if not isinstance(evidence, list):
        evidence = []
    answer = str(record.get("answer") or "")
    labelled_values = [
        str(item.get("value") or "").strip()
        for item in evidence
        if isinstance(item, dict)
        and _evidence_field_matches(item, field)
        and str(item.get("value") or "").strip()
    ]
    if labelled_values:
        return _fact_variant_present(answer, labelled_values)

    evidence_texts = _rag_evidence_texts(record)
    if any(_fact_variant_present(answer, [text]) for text in evidence_texts):
        return True

    # Some profile chunks use a machine field suffix (for example
    # ``gross_weight_g``) and store the numeric value without repeating the
    # unit after the number.  Compare the answer's numeric facts to those
    # chunks only when the declared field name is present in the chunk.
    aliases = FIELD_LABEL_ALIASES.get(str(field or "").strip().casefold(), set())
    answer_numbers = [
        float(match)
        for match in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", answer)
    ]
    if not aliases or not answer_numbers:
        return False
    for text in evidence_texts:
        compact = _compact_text(text)
        if not any(_compact_text(alias) in compact for alias in aliases):
            continue
        evidence_numbers = [
            float(match)
            for match in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", text)
        ]
        if any(abs(answer_number - evidence_number) < 1e-6
               for answer_number in answer_numbers
               for evidence_number in evidence_numbers):
            return True
    return False


def _identity_only_rag_miss(record: dict[str, Any]) -> bool:
    """Whether a product result is intentionally identity-only after RAG miss.

    A sealed product-QA request may resolve a SKU while retrieval/entailment
    finds no answerable evidence.  The service is allowed to keep that
    identity for a transparent "资料不足" response, but it must not present
    the product as evidence-backed.  This distinction is specific to the
    RAG result contract and is not a customer-wording rule.
    """
    metadata = _body_metadata(record)
    if str(metadata.get("evidence_status") or "").strip().casefold() not in {
        "missing",
        "unavailable",
    }:
        return False
    policy = str(metadata.get("answer_policy") or "").strip().casefold()
    debug = _body_debug(record)
    mode = str(debug.get("agent_mode") or "").strip().casefold()
    return (
        metadata.get("field_evidence_missing") is True
        or policy in {"insufficient_evidence", "unsafe_request_insufficient_evidence"}
        or "knowledge_missing" in mode
        or "safe_missing" in mode
    )


def _body_metadata(record: dict[str, Any]) -> dict[str, Any]:
    response = record.get("response")
    if isinstance(response, dict) and isinstance(response.get("answer_metadata"), dict):
        return response["answer_metadata"]
    return {}


def _body_debug(record: dict[str, Any]) -> dict[str, Any]:
    response = record.get("response")
    if isinstance(response, dict) and isinstance(response.get("debug"), dict):
        return response["debug"]
    return {}


def _record_models(record: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    raw_models = record.get("models")
    if isinstance(raw_models, str):
        values.append(raw_models)
    elif isinstance(raw_models, list):
        values.extend(raw_models)
    response = record.get("response")
    if isinstance(response, dict):
        response_models = response.get("models")
        if isinstance(response_models, str):
            values.append(response_models)
        elif isinstance(response_models, list):
            values.extend(response_models)
        response_debug = response.get("debug")
        if isinstance(response_debug, dict):
            for call in response_debug.get("llm_calls") or []:
                if isinstance(call, dict):
                    values.append(call.get("model"))
            trace = response_debug.get("trace")
            if isinstance(trace, dict):
                for call in trace.get("llm_calls") or []:
                    if isinstance(call, dict):
                        values.append(call.get("model"))
    return {
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    }


def _semantic_preplan(record: dict[str, Any]) -> dict[str, Any]:
    debug = _body_debug(record)
    value = debug.get("semantic_preplan")
    return value if isinstance(value, dict) else {}


def _record_result_skus(record: dict[str, Any]) -> set[str]:
    return {
        str(item).strip().upper()
        for item in (record.get("result_skus") or [])
        if str(item).strip()
    }


def _record_evidence_skus(record: dict[str, Any]) -> set[str]:
    return {
        str(item).strip().upper()
        for item in (record.get("public_evidence_skus") or [])
        if str(item).strip()
    }


def _audit_issues(record: dict[str, Any], case: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    case_id = str(record.get("id") or case.get("id") or "unknown")
    provider_blocker = str(record.get("provider_blocker") or "").strip()
    if provider_blocker:
        return [f"{case_id}:provider_blocker:{provider_blocker}"]

    status = record.get("status")
    if status != 200:
        issues.append(f"{case_id}:http_status:{status}")
    answer = str(record.get("answer") or "").strip()
    question = str(record.get("question") or case.get("question") or "").strip()
    if not answer:
        issues.append(f"{case_id}:empty_answer")
    elif question and _compact_text(answer) == _compact_text(question):
        issues.append(f"{case_id}:answer_echoed_question")
    for flag in record.get("flags") or []:
        issues.append(f"{case_id}:audit_flag:{flag}")

    models = _record_models(record)
    if not models:
        issues.append(f"{case_id}:flash_trace_missing")
    elif not any("flash" in model.casefold() for model in models):
        issues.append(f"{case_id}:semantic_model_not_flash:{','.join(sorted(models))}")
    semantic = _semantic_preplan(record)
    if semantic.get("called") is not True:
        issues.append(f"{case_id}:semantic_preplan_not_called")
    response = record.get("response") if isinstance(record.get("response"), dict) else {}
    for provenance_flag in _semantic_provenance_flags(response):
        issues.append(f"{case_id}:{provenance_flag}")

    expected_skus = {
        str(item).strip().upper()
        for item in (case.get("expect_skus") or [])
        if str(item).strip()
    }
    actual_skus = _record_result_skus(record)
    if expected_skus and actual_skus != expected_skus:
        issues.append(f"{case_id}:result_skus:{sorted(actual_skus)}!=expected:{sorted(expected_skus)}")
    if case.get("expect_result") and not actual_skus:
        issues.append(f"{case_id}:expected_product_result_missing")
    if case.get("expect_no_result") and actual_skus:
        issues.append(f"{case_id}:unexpected_product_result:{sorted(actual_skus)}")

    metadata = _body_metadata(record)
    debug = _body_debug(record)
    fallback_reason = str(
        debug.get("semantic_fallback_reason")
        or semantic.get("fallback_reason")
        or metadata.get("fallback_reason")
        or ""
    ).strip()
    if fallback_reason:
        issues.append(f"{case_id}:semantic_fallback:{fallback_reason}")
    final_audit = metadata.get("final_answer_audit")
    if actual_skus:
        if not isinstance(final_audit, dict) or final_audit.get("passed") is not True:
            issues.append(f"{case_id}:final_answer_audit_not_passed")
        if isinstance(final_audit, dict) and final_audit.get("coverage_complete") is not True:
            issues.append(f"{case_id}:final_answer_coverage_incomplete")
    recommendation_narrative = metadata.get("recommendation_narrative")
    narrative_source = str(
        recommendation_narrative.get("source")
        if isinstance(recommendation_narrative, dict)
        else ""
    ).strip()
    if (
        actual_skus
        and str(record.get("answer_type") or "").strip() == "recommendation"
        and narrative_source == "sealed_same_sku_fact_fallback"
    ):
        # This fallback is safe but intentionally terse.  A release-quality
        # recommendation matrix must prove that Flash can express the complete
        # supported semantic factors from the sealed packet, rather than hide
        # a rejected/incomplete semantic draft behind deterministic field prose.
        issues.append(f"{case_id}:semantic_presentation_fallback_used")

    evidence_skus = _record_evidence_skus(record)
    if actual_skus and evidence_skus - actual_skus:
        issues.append(f"{case_id}:public_evidence_cross_sku:{sorted(evidence_skus - actual_skus)}")
    if actual_skus and actual_skus - evidence_skus and not _identity_only_rag_miss(record):
        issues.append(f"{case_id}:public_evidence_missing_result_sku:{sorted(actual_skus - evidence_skus)}")
    if expected_skus and actual_skus and not evidence_skus:
        if not _identity_only_rag_miss(record):
            issues.append(f"{case_id}:expected_sku_without_public_evidence")

    evidence = response.get("evidence") if isinstance(response.get("evidence"), list) else []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku") or "").strip().upper()
        source_type = str(item.get("source_type") or "").strip()
        if sku and actual_skus and sku not in actual_skus:
            issues.append(f"{case_id}:evidence_item_cross_sku:{sku}")
        if source_type in PRODUCT_EVIDENCE_TYPES and not sku:
            issues.append(f"{case_id}:product_evidence_without_sku")

    for field in case.get("required_evidence_fields") or []:
        field_name = str(field or "").strip().casefold()
        if not _rag_field_fact_present(record, field_name):
            issues.append(f"{case_id}:required_evidence_fact_missing:{field_name}")
    return list(dict.fromkeys(issues))


def _audit_context_sequence(sequence: dict[str, Any]) -> list[str]:
    sequence_id = str(sequence.get("id") or "deep_context_sequence").strip()
    issues: list[str] = []
    for flag in sequence.get("flags") or []:
        issues.append(f"{sequence_id}:flag:{flag}")
    for blocker in sequence.get("provider_blockers") or []:
        issues.append(f"{sequence_id}:provider_blocker:{blocker}")

    records = sequence.get("turns")
    if not isinstance(records, list) or len(records) != 4:
        issues.append(f"{sequence_id}:turn_count:{len(records) if isinstance(records, list) else 0}!=4")
        return list(dict.fromkeys(issues))

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            issues.append(f"{sequence_id}:turn_{index}:malformed")
            continue
        issues.extend(_audit_issues(record, {"id": f"{sequence_id}.turn_{index}"}))

    turn_skus = [_record_result_skus(record) if isinstance(record, dict) else set() for record in records]
    if not turn_skus[0]:
        issues.append(f"{sequence_id}:first_turn_no_result")
    if turn_skus[1] != turn_skus[0]:
        issues.append(f"{sequence_id}:field_followup_lost_identity")
    alternative_skus = turn_skus[2]
    if alternative_skus and turn_skus[0] & alternative_skus:
        issues.append(f"{sequence_id}:alternative_repeated_first_result")
    # A semantic alternative may have no direct match. That is a valid
    # evidence-bound result and must not pressure the service into inventing a
    # replacement merely to satisfy the gate. In that case, “刚才那款” still
    # refers to the most recent confirmed product from turn 2; when an
    # alternative exists, it refers to the alternative from turn 3.
    expected_last_followup_skus = alternative_skus or turn_skus[1]
    if turn_skus[3] != expected_last_followup_skus:
        issues.append(f"{sequence_id}:last_followup_lost_previous_identity")
    return list(dict.fromkeys(issues))


def _audit_stream_parity(sequence: dict[str, Any]) -> list[str]:
    sequence_id = str(sequence.get("id") or "deep_normal_stream_parity").strip()
    issues: list[str] = []
    for flag in sequence.get("flags") or []:
        issues.append(f"{sequence_id}:flag:{flag}")
    for blocker in sequence.get("provider_blockers") or []:
        issues.append(f"{sequence_id}:provider_blocker:{blocker}")
    if sequence.get("normal_status") != 200 or sequence.get("stream_status") != 200:
        issues.append(
            f"{sequence_id}:http_status:{sequence.get('normal_status')}/{sequence.get('stream_status')}"
        )
    normal_answer = str(sequence.get("normal_answer") or "").strip()
    stream_answer = str(sequence.get("stream_answer") or "").strip()
    if not normal_answer or not stream_answer:
        issues.append(f"{sequence_id}:empty_answer")
    if normal_answer != stream_answer:
        issues.append(f"{sequence_id}:answer_mismatch")
    normal_skus = {
        str(item).strip().upper()
        for item in (sequence.get("normal_result_skus") or [])
        if str(item).strip()
    }
    stream_skus = {
        str(item).strip().upper()
        for item in (sequence.get("stream_result_skus") or [])
        if str(item).strip()
    }
    if normal_skus != stream_skus:
        issues.append(f"{sequence_id}:result_sku_mismatch")
    for label in ("normal", "stream"):
        trace = sequence.get(f"{label}_semantic_trace")
        if not isinstance(trace, dict):
            issues.append(f"{sequence_id}:{label}_semantic_trace_missing")
            continue
        if trace.get("semantic_owned") is not True:
            issues.append(f"{sequence_id}:{label}_semantic_ownership_missing")
        if trace.get("semantic_preplan_called") is not True:
            issues.append(f"{sequence_id}:{label}_semantic_preplan_missing")
        models = {
            str(item or "").strip().casefold()
            for item in (trace.get("models") or [])
            if str(item or "").strip()
        }
        if not any("flash" in model for model in models):
            issues.append(f"{sequence_id}:{label}_flash_trace_missing")
        for flag in trace.get("provenance_flags") or []:
            issues.append(f"{sequence_id}:{label}:{flag}")
    normal_evidence = {
        str(item or "").strip().upper()
        for item in (sequence.get("normal_public_evidence_skus") or [])
        if str(item or "").strip()
    }
    stream_evidence = {
        str(item or "").strip().upper()
        for item in (sequence.get("stream_public_evidence_skus") or [])
        if str(item or "").strip()
    }
    if normal_skus and normal_evidence != normal_skus:
        issues.append(f"{sequence_id}:normal_public_evidence_mismatch")
    if stream_skus and stream_evidence != stream_skus:
        issues.append(f"{sequence_id}:stream_public_evidence_mismatch")
    return list(dict.fromkeys(issues))


def evaluate_report(report: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Return a RAG-specific gate result without mutating the report."""
    specs = _case_specs()
    issues: list[str] = []
    records = report.get("cases") if isinstance(report.get("cases"), list) else []
    if strict:
        base_url = str(report.get("base_url") or "").strip()
        try:
            base_port = urlparse(base_url).port
        except ValueError:
            base_port = None
        if base_port != 8001:
            issues.append(f"report:non_dev_base_url:{base_url or '<missing>'}")
        record_ids = [str(record.get("id") or "").strip() for record in records if isinstance(record, dict)]
        duplicate_ids = sorted({item for item in record_ids if record_ids.count(item) > 1 and item})
        if duplicate_ids:
            issues.append(f"report:duplicate_case_ids:{duplicate_ids}")
        missing_case_ids = sorted(set(specs) - set(record_ids))
        unexpected_case_ids = sorted(set(record_ids) - set(specs))
        if missing_case_ids:
            issues.append(f"report:missing_case_ids:{missing_case_ids}")
        if unexpected_case_ids:
            issues.append(f"report:unexpected_case_ids:{unexpected_case_ids}")
        if len(records) != len(specs):
            issues.append(f"report:case_count:{len(records)}!={len(specs)}")
    for record in records:
        if not isinstance(record, dict):
            issues.append("malformed_case_record")
            continue
        case_id = str(record.get("id") or "").strip()
        case = specs.get(case_id, {"id": case_id})
        issues.extend(_audit_issues(record, case))

    external_blocker_count = int(report.get("external_blocker_count") or 0)
    if external_blocker_count:
        issues.append(f"report:external_blocker_count:{external_blocker_count}")

    sequences = report.get("sequences") if isinstance(report.get("sequences"), list) else []
    if strict:
        sequence_ids = [str(sequence.get("id") or "").strip() for sequence in sequences if isinstance(sequence, dict)]
        missing_sequence_ids = sorted(REQUIRED_SEQUENCE_IDS - set(sequence_ids))
        if missing_sequence_ids:
            issues.append(f"report:missing_sequence_ids:{missing_sequence_ids}")
        if len(sequences) < len(REQUIRED_SEQUENCE_IDS):
            issues.append(f"report:sequence_count:{len(sequences)}<{len(REQUIRED_SEQUENCE_IDS)}")
    for sequence in sequences:
        if not isinstance(sequence, dict):
            issues.append("malformed_sequence")
            continue
        sequence_id = str(sequence.get("id") or "sequence")
        if sequence_id == "deep_context_sequence":
            issues.extend(_audit_context_sequence(sequence))
        elif sequence_id == "deep_normal_stream_parity":
            issues.extend(_audit_stream_parity(sequence))
        else:
            for flag in sequence.get("flags") or []:
                issues.append(f"{sequence_id}:flag:{flag}")
            for blocker in sequence.get("provider_blockers") or []:
                issues.append(f"{sequence_id}:provider_blocker:{blocker}")

    return {
        "name": "semantic_rag_dev_release_gate_v2",
        "passed": not issues,
        "case_count": len(records),
        "issue_count": len(list(dict.fromkeys(issues))),
        "issues": list(dict.fromkeys(issues)),
        "contract": {
            "strict_complete_case_matrix": strict,
            "dev_port_8001_required": strict,
            "flash_trace_required": True,
            "semantic_preplan_required": True,
            "semantic_ownership_required": True,
            "legacy_route_provenance_forbidden": True,
            "same_sku_evidence_skus_required_for_evidence_backed_results": True,
            "identity_only_rag_miss_may_have_no_public_evidence": True,
            "provider_blockers_fail_closed": True,
            "normal_stream_and_context_turns_must_be_checked": True,
            "normal_stream_semantic_trace_required": True,
            "context_identity_continuity_must_be_checked": True,
            "customer_language_routing_unchanged": True,
            "semantic_recommendation_presentation_fallback_forbidden": True,
        },
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python semantic_rag_release_gate.py <semantic_rag_deep_audit.json>")
        return 2
    report_path = Path(sys.argv[1])
    if not report_path.exists():
        print(json.dumps({"error": f"report_not_found:{report_path}"}, ensure_ascii=False))
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = evaluate_report(report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
