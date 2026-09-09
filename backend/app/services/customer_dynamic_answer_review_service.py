"""Model-mediated quality review for customer-service answers.

This module intentionally does not contain customer-facing templates or a
keyword answer router. The answer model decides when a second look is useful;
the reviewer compares the draft with the current evidence and historical case
signals, then either keeps it or writes a more natural draft. Product facts,
SKU selection, and provenance stay owned by the original answer contract.
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import settings
from . import customer_llm_service, customer_perf_service


_DECISIONS = {"keep", "revise"}
_INTERNAL_REVIEW_LIMIT = 24


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "…"


def _extract_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[index:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def _compact_evidence(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "evidence_id": _clip(item.get("evidence_id"), 100),
            "sku": _clip(item.get("sku"), 80) or None,
            "content": _clip(item.get("content"), 520),
            "fact_authority": bool(item.get("fact_authority")),
            "authority_level": _clip(item.get("authority_level"), 40),
        })
        if len(rows) >= _INTERNAL_REVIEW_LIMIT:
            break
    return rows


def _compact_cases(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        signal = item.get("case_signal")
        rows.append({
            "guidance_id": _clip(item.get("guidance_id"), 100) or None,
            "sku": _clip(item.get("sku"), 80) or None,
            "intent": _clip(item.get("intent"), 100) or None,
            "guidance": _clip(item.get("guidance"), 900),
            "case_signal": signal if isinstance(signal, dict) else {},
        })
        if len(rows) >= 4:
            break
    return rows


def _compact_history(value: Any) -> list[dict[str, str]]:
    """Give the reviewer the same conversational anchors as the answer model."""
    rows: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        content = _clip(item.get("content") or item.get("text"), 520)
        if not content:
            continue
        rows.append({
            "role": _clip(item.get("role"), 30) or "user",
            "content": content,
        })
    return rows[-8:]


def _compact_context_products(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            key: item[key]
            for key in ("sku", "product_name_cn", "name", "title", "capacity", "weight", "material")
            if item.get(key) not in (None, "", [], {})
        })
        if len(rows) >= 8:
            break
    return rows


def should_review_response(
    response: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> bool:
    """Let the answer and task complexity opt into a second model pass."""
    if not bool(getattr(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_ENABLED", False)):
        return False
    value = response if isinstance(response, dict) else {}
    if not _clip(value.get("answer"), 2400):
        return False
    hint = value.get("quality_review")
    # The primary answer model already receives the historical outcome packet.
    # Pay for a second pass only when that model explicitly says the draft has
    # a semantic quality concern; missing/low-confidence metadata alone is not
    # enough to add a second model latency hit.
    return isinstance(hint, dict) and hint.get("recommended") is True


def _review_packet(
    *,
    question: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "current_question": _clip(question, 900),
        "draft_answer": _clip(response.get("answer"), 2400),
        "answer_type": _clip(response.get("answer_type"), 50),
        "confidence": _clip(response.get("confidence"), 30),
        "uncertainty": _clip(response.get("uncertainty"), 30),
        "selected_skus": list(response.get("selected_skus") or [])[:8],
        "selected_evidence_ids": list(response.get("evidence_ids") or [])[:12],
        "conversation_history": _compact_history(
            payload.get("conversation_history") or payload.get("history")
        ),
        "previous_turn_memory": payload.get("previous_turn_memory") or {},
        "previous_context_products": _compact_context_products(
            payload.get("previous_context_products")
        ),
        "active_context_products": _compact_context_products(
            payload.get("active_context_products")
        ),
        "turn_identity_contract": payload.get("turn_identity_contract") or {},
        "evidence": _compact_evidence(payload.get("evidence")),
        "candidate_products": [
            item for item in (payload.get("candidate_products") or [])[:8]
            if isinstance(item, dict)
        ],
        "experience_cases": _compact_cases(
            payload.get("experience_cases")
            or payload.get("experience_guidance")
        ),
        "experience_outcome_signals": payload.get("experience_outcome_signals") or [],
    }


def _review_system_prompt() -> str:
    return (
        "你是商品客服回答的内部质量复核员，不直接向客户说话。"
        "请结合当前问题、同轮商品资料和历史案例信号，判断这份草稿是否真正可直接发给客户。"
        "重点看：是否回答了客户真正的问题，事实是否只来自当前资料，推荐或比较是否说清取舍，"
        "表达是否自然、简洁、可执行，是否把内部处理过程说给了客户听。"
        "历史案例只代表沟通经验，不能新增商品事实、选择 SKU 或替换当前资料。"
        "experience_outcome_signals 中的样本只帮助判断哪些表达动作可能减少顾虑；没有分母时不能声称提高了真实转化率。"
        "如果草稿已经可用，返回 keep；只有确实能改善时才返回 revise。"
        "revise 时只重写客户可见的 answer，保留原草稿已经确认的事实、SKU 和不确定边界，"
        "不要编造资料，也不要使用固定客服腔或提及资料库、检索、证据、经验卡、模型、流程。"
        "优先尊重 conversation_history、previous_turn_memory 和 active_context_products 中已经确认的商品指代；"
        "不要因为候选资料里出现更多商品就覆盖上一轮上下文。"
        "只返回 JSON："
        '{"decision":"keep|revise",'
        '"answer":"仅在 revise 时填写自然客服回复",'
        '"issues":["可选的内部问题摘要"],'
        '"confidence":"high|medium|low"}'
    )


async def review_answer(
    db: Session,
    *,
    question: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Review and, when useful, revise a draft without changing its facts."""
    if not should_review_response(response, payload):
        return response, {"attempted": False, "decision": "not_needed"}

    start = perf_counter()
    metadata: dict[str, Any] = {"attempted": True}
    try:
        call_metadata: dict[str, Any] = {}
        raw = await customer_llm_service.chat_completion(
            db,
            messages=[
                {"role": "system", "content": _review_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        _review_packet(
                            question=question,
                            payload=payload,
                            response=response,
                        ),
                        ensure_ascii=False,
                        default=str,
                    ),
                },
            ],
            temperature=0,
            max_tokens=max(
                256,
                min(
                    int(getattr(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_MAX_TOKENS", 420)),
                    900,
                ),
            ),
            purpose="customer_service_dynamic_answer_review",
            response_format={"type": "json_object"},
            thinking={"type": "disabled"},
            reasoning_effort=(
                str(getattr(settings, "CUSTOMER_SERVICE_DYNAMIC_REVIEW_REASONING_EFFORT", "none") or "")
                .strip()
                .lower()
                or None
            ),
            metadata=call_metadata,
        )
        reviewed = _extract_json_object(raw) or {}
        decision = str(reviewed.get("decision") or "").strip().lower()
        issues = [
            _clip(item, 180)
            for item in (reviewed.get("issues") or [])
            if _clip(item, 180)
        ][:6]
        metadata.update({
            "decision": decision if decision in _DECISIONS else "invalid",
            "issues": issues,
            "elapsed_ms": round(customer_perf_service.perf_ms(start), 2),
        })
        if decision == "revise":
            revised_answer = _clip(reviewed.get("answer"), 2400)
            if revised_answer:
                return {**response, "answer": revised_answer}, {
                    **metadata,
                    "changed": True,
                }
        if decision == "keep":
            return response, {**metadata, "changed": False}
        return response, {**metadata, "changed": False, "error": "invalid_review_result"}
    except Exception as exc:
        customer_perf_service.log_event(
            "customer_service.dynamic_review_error",
            error=type(exc).__name__,
        )
        return response, {
            **metadata,
            "decision": "unavailable",
            "changed": False,
            "error": type(exc).__name__,
            "elapsed_ms": round(customer_perf_service.perf_ms(start), 2),
        }
