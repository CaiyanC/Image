from __future__ import annotations


def infer_secondary_intents(text: str, primary_intent: str | None = None) -> dict:
    """Infer non-authoritative experience hints without changing primary intent."""
    value = str(text or "").strip()
    secondary: list[str] = []

    patterns = (
        ("gift_scenario", ("礼物", "送人", "送朋友", "送客户", "当礼物")),
        ("summary_intent", ("简单说", "简单讲", "一句话", "概括", "总结")),
        ("purchase_intent", ("能买吗", "怎么买", "下单", "购买", "链接")),
        ("evaluation_intent", ("怎么样", "好不好", "值不值", "靠谱吗")),
    )
    for tag, terms in patterns:
        if any(term in value for term in terms):
            secondary.append(tag)

    return {
        "primary_intent": primary_intent,
        "secondary_intents": secondary,
    }
