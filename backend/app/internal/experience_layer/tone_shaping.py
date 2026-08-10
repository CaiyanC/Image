from __future__ import annotations

import re


_HARD_ANSWER_TYPES = {"product_detail", "recommendation"}
_HARD_INTENTS = {"product_detail", "recommendation", "recommend_products"}


def shape_answer_tone(answer: str, *, intent: str | None = None, answer_type: str | None = None) -> str:
    """Apply experience-layer wording only where it is safe.

    Clarification can be softened. Product detail and recommendation are
    decision-layer outputs and must stay exact.
    """
    value = str(answer or "").strip()
    normalized_intent = str(intent or "").strip()
    normalized_type = str(answer_type or "").strip()
    if normalized_type in _HARD_ANSWER_TYPES or normalized_intent in _HARD_INTENTS:
        return value
    if normalized_intent == "clarify" or normalized_type == "clarification":
        return soften_clarify_answer(value)
    return value


def soften_clarify_answer(answer: str) -> str:
    value = str(answer or "").strip()
    if not value:
        return "请提供具体商品名或 SKU，我再继续核对。"
    # Keep clarification customer-facing.  The old direction template exposed
    # orchestration wording and appended an unrelated follow-up to precise
    # missing-identity answers.
    value = re.sub(r"^先给你一个方向：\s*", "", value)
    value = re.sub(
        r"\s*你补充 SKU、产品名或使用场景后，我可以继续帮你查。?\s*$",
        "",
        value,
    ).strip()
    if "补充" in value and ("我可以" in value or "继续" in value):
        return value
    # A bounded, evidence-aware clarification already has a customer-facing
    # conclusion (for example a same-SKU missing field or a compatibility
    # boundary). Wrapping it in the generic “先给你一个方向” template makes
    # a precise answer sound evasive and appends an unrelated follow-up.
    if (
        "当前资料" in value
        or "当前页面" in value
        or "包装清单" in value
        or re.search(r"\b[A-Z]{1,4}-[A-Z0-9-]+\b", value)
        or any(term in value for term in ("材质：", "涂层/表面处理：", "配件结论：", "兼容性结论："))
    ):
        return value
    if any(term in value for term in ("商品名", "产品名", "SKU", "具体型号")):
        return value
    return f"{value} 请提供具体商品名或 SKU，我再继续核对。"
