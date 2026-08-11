from backend.scripts.real_customer_service_acceptance import _contains_unnegated_forbidden_term


def test_forbidden_advice_check_allows_explicit_prohibition():
    answer = "不要用醋、小苏打、碱水或加热煮沸清洁剂，这些做法可能伤锅。"
    assert not _contains_unnegated_forbidden_term(answer, "煮沸清洁剂")


def test_forbidden_advice_check_still_catches_positive_advice_after_contrast():
    answer = "不要用钢丝球，但是可以加热清洁剂。"
    assert _contains_unnegated_forbidden_term(answer, "可以加热清洁剂")
