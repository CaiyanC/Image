from backend.scripts.real_customer_service_acceptance import (
    SEQUENCES,
    _contains_unnegated_forbidden_term,
    evaluate,
)


def test_forbidden_advice_check_allows_explicit_prohibition():
    answer = "不要用醋、小苏打、碱水或加热煮沸清洁剂，这些做法可能伤锅。"
    assert not _contains_unnegated_forbidden_term(answer, "煮沸清洁剂")


def test_forbidden_advice_check_still_catches_positive_advice_after_contrast():
    answer = "不要用钢丝球，但是可以加热清洁剂。"
    assert _contains_unnegated_forbidden_term(answer, "可以加热清洁剂")


def test_suitability_gap_is_a_valid_clarification_without_sku():
    case_data = next(
        turn
        for sequence in SEQUENCES
        for turn in sequence["turns"]
        if turn["id"] == "recommend_pour_over"
    )
    result = evaluate(
        case_data,
        200,
        {
            "answer_type": "clarification",
            "answer": "目前目录没有明确标注适合手冲的产品，暂时无法确认哪些款式符合你的要求，也不能仅凭咖啡器具这个类别推断其用途。你可以补充产品上的相关说明，或允许我先整理一份相关候选清单，供你后续核实和确认；如果需要，我也可以继续帮你核对。",
            "result_skus": [],
            "needs_clarification": True,
            "conversation_id": "test-conversation",
            "debug": {
                "semantic_preplan": {"called": True},
                "model": "deepseek-v4-flash",
            },
        },
        100.0,
    )

    assert result["auto_pass"]


def test_suitability_gap_with_sku_does_not_pass_clarification_gate():
    case_data = next(
        turn
        for sequence in SEQUENCES
        for turn in sequence["turns"]
        if turn["id"] == "recommend_pour_over"
    )
    result = evaluate(
        case_data,
        200,
        {
            "answer_type": "clarification",
            "answer": "目前目录没有明确标注适合手冲的产品，建议先核实。",
            "result_skus": ["COFFEE-A"],
            "needs_clarification": True,
            "conversation_id": "test-conversation",
            "debug": {
                "semantic_preplan": {"called": True},
                "model": "deepseek-v4-flash",
            },
        },
        100.0,
    )

    assert not result["auto_pass"]
    assert "expected_result_skus_empty" in result["failed_checks"]
