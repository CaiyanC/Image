from app.internal.experience_layer.implicit_intent import infer_secondary_intents
from app.internal.experience_layer.query_rewrite import build_retrieval_query
from app.internal.experience_layer.tone_shaping import shape_answer_tone


def test_infer_secondary_intents_preserves_primary_intent():
    result = infer_secondary_intents("适合当礼物吗", primary_intent="recommendation")

    assert result["primary_intent"] == "recommendation"
    assert "gift_scenario" in result["secondary_intents"]


def test_build_retrieval_query_rewrites_only_ambiguous_customer_phrasing():
    assert build_retrieval_query("简单说下") == "产品核心信息总结"
    assert build_retrieval_query("能买吗") == "购买建议"
    assert build_retrieval_query("炊墨套锅手柄是什么材质") == "炊墨套锅手柄是什么材质"


def test_shape_answer_tone_only_softens_clarify_answers():
    clarify = shape_answer_tone(
        "请先告诉我要查询哪款产品。",
        intent="clarify",
        answer_type="clarification",
    )
    product_detail = shape_answer_tone(
        "炊墨套锅（CW-T01）：手柄材质：铝合金。",
        intent="product_detail",
        answer_type="product_detail",
    )
    recommendation = shape_answer_tone(
        "推荐：行山单锅（CW-P01）\n理由：CW-P01：更贴合当前需求。",
        intent="recommendation",
        answer_type="recommendation",
    )

    assert "先给你一个方向" in clarify
    assert "补充" in clarify
    assert product_detail == "炊墨套锅（CW-T01）：手柄材质：铝合金。"
    assert recommendation == "推荐：行山单锅（CW-P01）\n理由：CW-P01：更贴合当前需求。"
