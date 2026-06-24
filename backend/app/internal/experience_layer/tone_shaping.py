from __future__ import annotations


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
        return "先给你一个方向：我还需要再确认一下具体产品或场景。你补充 SKU、产品名或使用需求后，我可以继续帮你查。"
    if "先给你一个方向" in value:
        return value
    if "补充" in value and ("我可以" in value or "继续" in value):
        return value
    return f"先给你一个方向：{value} 你补充 SKU、产品名或使用场景后，我可以继续帮你查。"
