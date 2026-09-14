"""Generic grounding protocol for customer-service answers.

This module deliberately contains no product-topic vocabulary.  It does not
decide whether a product supports a particular use, nor does it manufacture a
customer-facing fallback.  The answer model owns semantic interpretation; the
runtime only checks that the model returned a usable JSON object and that its
optional provenance fields point at evidence that was actually supplied in
the current turn.

Semantic support is reviewed by the model-mediated reviewer.  Keeping the
runtime contract structural makes the same mechanism work for specifications,
compatibility, usage, recommendations, comparisons, after-sales questions,
and future product fields without adding a new ``if`` branch per topic.
"""

from __future__ import annotations

from typing import Any


_ANSWER_TYPES = {
    "product_detail",
    "recommendation",
    "comparison",
    "faq",
    "clarification",
}


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _normalised_strings(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def available_evidence_ids(payload: dict[str, Any]) -> set[str]:
    return {
        str(item.get("evidence_id") or "").strip()
        for item in (payload.get("evidence") or [])
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
    }


def available_skus(payload: dict[str, Any]) -> set[str]:
    """Collect identifiers already present in this turn, without selecting one."""
    values: set[str] = set()
    for key in (
        "explicit_product_skus",
        "bound_product_skus",
        "catalogue_subject_skus",
    ):
        values.update(
            item.upper()
            for item in _normalised_strings(payload.get(key))
        )
    for key in (
        "candidate_products",
        "active_context_products",
        "previous_context_products",
    ):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and str(item.get("sku") or "").strip():
                values.add(str(item["sku"]).strip().upper())
    for item in payload.get("evidence") or []:
        if isinstance(item, dict) and str(item.get("sku") or "").strip():
            values.add(str(item["sku"]).strip().upper())
    return values


def needs_selection_metadata_repair(
    response: dict[str, Any] | None,
    payload: dict[str, Any],
) -> bool:
    """Detect a direct selection missing its redundant UI/provenance mirror.

    ``answer`` remains the customer-facing source of meaning.  This helper
    only asks for a second model pass when the model itself declared a
    recommendation/comparison, gave a non-clarifying answer, and omitted the
    selection mirror despite receiving bound evidence.  It never selects a
    candidate in the runtime.
    """
    if not isinstance(response, dict):
        return False
    answer_type = str(response.get("answer_type") or "").strip().lower()
    if answer_type not in {"recommendation", "comparison"}:
        return False
    if bool(response.get("needs_clarification")):
        return False
    if _normalised_strings(response.get("selected_skus")):
        return False
    return bool(available_evidence_ids(payload) and available_skus(payload))


def _issue(code: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "reason": reason, **extra}


def answer_protocol_issues(
    response: dict[str, Any] | None,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return only structural/provenance issues; never inspect question wording.

    The model may omit optional provenance when it has no reliable attribution.
    When it does provide an identifier, the identifier must refer to the
    current evidence packet.  This catches stale-context leakage and malformed
    streaming responses while leaving semantic judgment to the model.
    """
    if not isinstance(response, dict):
        return [_issue(
            "invalid_answer_json",
            "上游没有返回可解析的答案对象。",
        )]

    answer = str(response.get("answer") or "").strip()
    if not answer:
        return [_issue(
            "invalid_answer_json",
            "答案对象没有包含可发送给顾客的 answer。",
        )]

    issues: list[dict[str, Any]] = []
    evidence_ids = available_evidence_ids(payload)
    selected_evidence_ids = _normalised_strings(response.get("evidence_ids"))
    unknown_evidence_ids = [
        item for item in selected_evidence_ids if item not in evidence_ids
    ]
    if unknown_evidence_ids:
        issues.append(_issue(
            "unknown_evidence_reference",
            "答案引用了当前轮次没有提供的证据标识。",
            evidence_ids=unknown_evidence_ids[:12],
        ))

    known_skus = available_skus(payload)
    selected_skus = [item.upper() for item in _normalised_strings(response.get("selected_skus"))]
    unknown_selected_skus = [item for item in selected_skus if item not in known_skus]
    if unknown_selected_skus and known_skus:
        issues.append(_issue(
            "unknown_sku_reference",
            "答案选择了当前轮次没有提供的商品标识。",
            skus=unknown_selected_skus[:8],
        ))

    claims = response.get("claims")
    claims_items = claims if isinstance(claims, list) else []
    if claims is not None and not isinstance(claims, list):
        issues.append(_issue(
            "invalid_claims_shape",
            "claims 必须是数组，或省略该可选字段。",
        ))
    for index, claim in enumerate(claims_items):
        if not isinstance(claim, dict):
            issues.append(_issue(
                "invalid_claim",
                "claims 中存在不是对象的条目。",
                claim_index=index,
            ))
            continue
        claim_evidence_ids = _normalised_strings(claim.get("evidence_ids"))
        unknown_claim_evidence = [
            item for item in claim_evidence_ids if item not in evidence_ids
        ]
        if unknown_claim_evidence:
            issues.append(_issue(
                "unknown_claim_evidence_reference",
                "claim 引用了当前轮次没有提供的证据标识。",
                claim_index=index,
                evidence_ids=unknown_claim_evidence[:8],
            ))
        claim_skus = _normalised_strings(claim.get("skus"))
        if claim.get("sku") not in (None, ""):
            claim_skus.append(str(claim.get("sku")))
        unknown_claim_skus = [
            item.upper() for item in claim_skus if item.upper() not in known_skus
        ]
        if unknown_claim_skus and known_skus:
            issues.append(_issue(
                "unknown_claim_sku_reference",
                "claim 绑定了当前轮次没有提供的商品标识。",
                claim_index=index,
                skus=list(dict.fromkeys(unknown_claim_skus))[:8],
            ))

    answer_type = str(response.get("answer_type") or "").strip().lower()
    if answer_type and answer_type not in _ANSWER_TYPES:
        issues.append(_issue(
            "invalid_answer_type",
            "answer_type 不属于当前协议允许的值。",
            answer_type=answer_type,
        ))
    return issues


def grounding_repair_instruction(issues: list[dict[str, Any]]) -> str:
    """Ask the same answer model to repair a structural/provenance issue."""
    return (
        "上一版回答没有完全通过当前轮次的答案协议。请重新阅读 current_question、对话上下文和 evidence，"
        "只输出一个合法 JSON object；answer 必须是可直接发送给顾客的自然中文。"
        "如果引用 evidence_ids、selected_skus 或 claims，只能使用当前 payload 中确实存在的标识；"
        "不要凭空补充商品事实，不要把一个商品的资料归给另一个商品。"
        "语义上能确认的部分直接回答，不能由当前证据确认的部分自然说明具体缺口；"
        "不要复述内部检查、重试或系统流程。"
        "本轮协议问题：" + str(issues[:8])
    )


def selection_metadata_repair_instruction() -> str:
    """Ask the same model to mirror an already-made semantic selection."""
    return (
        "上一版 answer 已经给出了推荐或比较结论，但没有同步填写本轮答案协议中的选择信息。"
        "请重新阅读 current_question、对话上下文和 evidence，保留能够被 evidence 支持的自然回答，"
        "并补齐 selected_skus 以及实际使用的 evidence_ids；claims 只有在能准确归属时才填写。"
        "如果当前证据不足以作出可靠选择，就把 needs_clarification 设为 true，不要从候选顺序猜选。"
        "不要改变事实边界，不要提及本次复核或内部处理。"
    )


__all__ = [
    "answer_protocol_issues",
    "available_evidence_ids",
    "available_skus",
    "grounding_repair_instruction",
    "needs_selection_metadata_repair",
    "selection_metadata_repair_instruction",
]
