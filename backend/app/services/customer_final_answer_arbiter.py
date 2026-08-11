"""Structural final-answer arbitration after semantic generation and grounding.

This module does not infer customer intent or product facts.  It only enforces
the contracts already produced by semantic planning, entity resolution,
evidence selection and answer coverage.
"""

from __future__ import annotations

import re

from . import customer_answer_coverage_contract


_INTERNAL_LABEL_RE = re.compile(
    r"(?:agent[\s_-]*mode|semantic[\s_-]*preplan|"
    r"entity[\s_-]*resolution[\s_-]*contract|field[\s_-]*contract|"
    r"模型判断|内部候选|候选\s*[一二三\d]+\s*[:：])",
    re.IGNORECASE,
)


def _missing_boundary(request_text: str) -> str:
    return f"关于“{request_text}”：当前同 SKU 资料未直接确认，无法确认。"


def _deduplicate_lines(answer: str) -> tuple[str, bool]:
    lines: list[str] = []
    seen: set[str] = set()
    repaired = False
    for raw_line in str(answer or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in seen:
            repaired = True
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines), repaired


def _deduplicate_equivalent_missing_boundaries(answer: str) -> tuple[str, bool]:
    """Keep one unsupported boundary per quoted customer request.

    Upstream semantic and coverage paths can phrase the same missing-data
    boundary differently.  The quoted request is the stable structural key;
    this cleanup does not infer facts or rewrite model prose.
    """
    lines: list[str] = []
    seen_requests: set[str] = set()
    repaired = False
    for line in str(answer or "").splitlines():
        match = re.match(r"^关于[“\"](.+?)[”\"]：(.+)$", line.strip())
        if match and any(term in match.group(2) for term in ("未直接确认", "未找到可直接确认", "无法确认")):
            request_text = match.group(1).strip()
            if request_text in seen_requests:
                repaired = True
                continue
            seen_requests.add(request_text)
        lines.append(line)
    return "\n".join(lines), repaired


def _normalize_skus(values) -> list[str]:
    return list(dict.fromkeys(
        str(item or "").strip().upper()
        for item in (values or [])
        if str(item or "").strip()
    ))


def arbitrate_final_answer(agent_result: dict) -> dict:
    """Return a structurally consistent answer plus an auditable verdict."""
    result = dict(agent_result or {})
    metadata = dict(
        result.get("answer_metadata")
        if isinstance(result.get("answer_metadata"), dict)
        else {}
    )
    result["answer_metadata"] = metadata
    repairs: list[str] = []
    blocking_findings: list[str] = []

    answer, deduplicated = _deduplicate_lines(str(result.get("answer") or ""))
    if deduplicated:
        repairs.append("duplicate_line_removed")
    answer, equivalent_boundary_removed = _deduplicate_equivalent_missing_boundaries(answer)
    if equivalent_boundary_removed:
        repairs.append("equivalent_missing_boundary_removed")

    coverage = customer_answer_coverage_contract.AnswerCoverageContract.from_dict(
        metadata.get("answer_coverage_contract")
    )
    if coverage is not None:
        answered_boundaries = {
            _missing_boundary(unit.request_text)
            for unit in coverage.request_units
            if unit.status == customer_answer_coverage_contract.ANSWERED
        }
        kept_lines = []
        for line in answer.splitlines():
            if line in answered_boundaries:
                repairs.append("contradictory_missing_boundary_removed")
                continue
            kept_lines.append(line)
        answer = "\n".join(kept_lines).strip()
        for request_text in coverage.unsupported_request_texts:
            boundary = _missing_boundary(request_text)
            if boundary not in answer.splitlines():
                answer = "\n".join(item for item in (answer, boundary) if item)
                repairs.append("unsupported_boundary_added")

    # Coverage completion can add a canonical boundary after the model has
    # already stated the same unsupported request in different words.  Run
    # the structural equivalence pass again after all additions are present.
    answer, equivalent_boundary_removed = _deduplicate_equivalent_missing_boundaries(answer)
    if equivalent_boundary_removed:
        repairs.append("equivalent_missing_boundary_removed")

    result["answer"] = answer
    if not answer:
        blocking_findings.append("empty_answer")
    if answer and _INTERNAL_LABEL_RE.search(answer):
        blocking_findings.append("internal_label_exposed")

    result_skus = _normalize_skus(result.get("result_skus"))
    evidence_skus = _normalize_skus(
        item.get("sku")
        for item in (result.get("evidence") or [])
        if isinstance(item, dict)
    )
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    entity_contract = (
        debug.get("entity_resolution_contract")
        if isinstance(debug.get("entity_resolution_contract"), dict)
        else {}
    )
    resolved_sku = (
        str(entity_contract.get("resolved_sku") or "").strip().upper()
        if entity_contract.get("status") == "resolved"
        else ""
    )
    allowed_skus = set(result_skus)
    if resolved_sku:
        allowed_skus.add(resolved_sku)
    if allowed_skus and any(sku not in allowed_skus for sku in evidence_skus):
        blocking_findings.append("cross_sku_evidence")

    audit = {
        "passed": not blocking_findings,
        "blocking_findings": list(dict.fromkeys(blocking_findings)),
        "repairs": list(dict.fromkeys(repairs)),
        "coverage_complete": (
            coverage is None or not coverage.unsupported_request_texts
        ),
        "result_skus": result_skus,
        "evidence_skus": evidence_skus,
        "resolved_sku": resolved_sku or None,
    }
    metadata["final_answer_audit"] = audit
    return result
