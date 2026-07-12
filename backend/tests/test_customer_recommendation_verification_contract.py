import pytest

from app.services.customer_recommendation_verification_contract import (
    build_recommendation_request_contract,
    build_verified_recommendation_answer,
    merge_recommendation_request_contracts,
    prepare_recommendation_return_rows,
    select_recommendation_candidates,
    verify_recommendation_candidates,
)
from app.services import customer_service_service


def _row(sku: str, **overrides):
    row = {
        "sku": sku,
        "product_name_cn": sku,
        "category": "锅具",
        "sub_category": "套锅",
        "capacity": "",
        "gross_weight_g": None,
        "body_material": "硬质氧化铝",
        "heat_source": "",
        "features": "",
        "usage_scenarios": "",
        "target_audience": "",
        "positioning": "",
        "price_positioning": "",
    }
    row.update(overrides)
    return row


def test_request_contract_extracts_people_heat_and_soft_preferences():
    contract = build_recommendation_request_contract(
        "一家四口营地煮汤，容量要大但别太重，还希望能直接明火加热，推荐哪款套锅？"
    )

    assert contract.subject_category == "锅具"
    assert (contract.people_min, contract.people_max) == (4, 4)
    assert contract.heat_sources == ["明火"]
    assert {"capacity", "weight"} <= set(contract.soft_preferences)
    assert "heat_source" in contract.hard_constraints


def test_request_contract_normalizes_people_ranges_and_budget():
    two = build_recommendation_request_contract("两个人徒步，预算中等，推荐轻便锅具")
    range_contract = build_recommendation_request_contract("四五个人露营，锅具怎么选")

    assert (two.people_min, two.people_max) == (2, 2)
    assert two.budget_level == "medium"
    assert "budget" in two.soft_preferences
    assert (range_contract.people_min, range_contract.people_max) == (4, 5)


def test_four_people_rejects_explicit_two_to_three_person_product():
    contract = build_recommendation_request_contract("一家四口露营，推荐能明火加热的套锅")
    result = verify_recommendation_candidates(
        contract,
        [_row("SMALL", target_audience="适合2-3人", heat_source="明火直烧")],
    )[0]

    assert result.hard_constraints_passed is False
    assert "people_capacity_conflict" in result.rejection_reasons


def test_two_people_accepts_explicit_one_to_two_person_product():
    contract = build_recommendation_request_contract("两个人露营，推荐套锅")
    result = verify_recommendation_candidates(
        contract,
        [_row("PAIR", target_audience="适合1-2人")],
    )[0]

    assert result.hard_constraints_passed is True
    assert result.evidence_by_constraint["people"]["status"] == "verified"


def test_gas_stove_requires_explicit_same_sku_heat_source():
    contract = build_recommendation_request_contract("两个人露营，要能搭配燃气炉的套锅")
    verified, vague = verify_recommendation_candidates(
        contract,
        [
            _row("GAS", target_audience="适合1-2人", heat_source="燃气炉、卡式炉"),
            _row("VAGUE", target_audience="适合1-2人", features="两种燃料可选", usage_scenarios="户外烹饪"),
        ],
    )

    assert verified.hard_constraints_passed is True
    assert verified.evidence_by_constraint["heat_source"]["field_source"] == "heat_source"
    assert vague.hard_constraints_passed is True
    assert vague.verification_level == "partially_verified"
    assert vague.evidence_by_constraint["heat_source"]["status"] == "unknown"
    assert "heat_source" in vague.unsupported_constraints


def test_cassette_stove_as_recommendation_subject_is_not_a_heat_constraint():
    contract = build_recommendation_request_contract("推荐一个卡式炉")

    assert contract.subject_category == "炉具"
    assert contract.subject_kind == "stove"
    assert contract.heat_sources == []
    assert "heat_source" not in contract.hard_constraints


def test_cassette_stove_with_cookware_subject_is_a_heat_constraint():
    contract = build_recommendation_request_contract("推荐适合卡式炉的锅具")

    assert contract.subject_category == "锅具"
    assert contract.subject_kind == "cookware"
    assert contract.heat_sources == ["卡式炉"]
    assert "heat_source" in contract.hard_constraints


@pytest.mark.parametrize(
    "question",
    [
        "推荐能用液体酒精的锅具",
        "推荐使用酒精燃料的锅具",
        "哪些锅支持酒精炉",
    ],
)
def test_cookware_alcohol_heat_expressions_share_the_legacy_canonical_condition(question):
    contract = build_recommendation_request_contract(question)

    assert contract.subject_category == "锅具"
    assert contract.subject_kind == "cookware"
    assert contract.heat_sources == ["酒精炉"]
    assert "heat_source" in contract.hard_constraints


def test_alcohol_stove_subject_does_not_become_a_cookware_heat_condition():
    for question in ("推荐一个酒精炉", "酒精炉推荐"):
        contract = build_recommendation_request_contract(question)

        assert (contract.subject_category, contract.subject_kind, contract.subject_subtype) == (
            "炉具",
            "stove",
            "alcohol_stove",
        )
        assert contract.heat_sources == []


def test_alcohol_heat_verification_uses_explicit_same_sku_raw_evidence_only():
    contract = build_recommendation_request_contract("推荐能用液体酒精的锅具")
    liquid, stove, vague, unsupported = verify_recommendation_candidates(
        contract,
        [
            _row("LIQUID", heat_source="液体酒精"),
            _row("STOVE", heat_source="酒精炉"),
            _row("VAGUE", heat_source="多燃料"),
            _row("UNSUPPORTED", heat_source="卡式炉、燃气炉"),
        ],
    )

    for item, raw_value in ((liquid, "液体酒精"), (stove, "酒精炉")):
        assert item.evidence_by_constraint["heat_source"] == {
            "status": "verified",
            "field_source": "heat_source",
            "raw_value": raw_value,
        }
    for item in (vague, unsupported):
        assert item.verification_level == "rejected"
        assert item.evidence_by_constraint["heat_source"]["status"] == "conflict"
        assert "heat_source_condition_not_met" in item.rejection_reasons


def test_stove_subject_subtypes_are_directional():
    card = build_recommendation_request_contract("推荐一个卡式炉")
    alcohol = build_recommendation_request_contract("推荐一个酒精炉")
    broad = build_recommendation_request_contract("炉具推荐")

    assert (card.subject_category, card.subject_kind, card.subject_subtype) == ("炉具", "stove", "card_stove")
    assert (alcohol.subject_category, alcohol.subject_kind, alcohol.subject_subtype) == ("炉具", "stove", "alcohol_stove")
    assert (broad.subject_category, broad.subject_kind, broad.subject_subtype) == ("炉具", "stove", None)


def test_card_stove_subject_requires_product_identity_not_fuel_or_scene_text():
    contract = build_recommendation_request_contract("卡式炉推荐")
    card, alcohol, gas, grill = verify_recommendation_candidates(
        contract,
        [
            _row("CARD", category="炉具", product_name_cn="一方卡式炉"),
            _row("ALCOHOL", category="炉具", product_name_cn="旋焰酒精炉"),
            _row("GAS", category="炉具", product_name_cn="蓝翼分体式气炉", heat_source="卡式气罐"),
            _row("GRILL", category="炉具", product_name_cn="书本式烤炉", usage_scenarios="卡式炉露营搭配"),
        ],
    )

    assert card.verification_level == "fully_verified"
    assert card.evidence_by_constraint["subject_subtype"] == {
        "status": "verified",
        "field_source": "product_name_cn",
        "raw_value": "一方卡式炉",
        "subject_subtype": "card_stove",
    }
    for item in (alcohol, gas, grill):
        assert item.verification_level == "rejected"
        assert "subject_subtype_mismatch" in item.rejection_reasons


@pytest.mark.parametrize(
    ("count", "expected_returned", "truncated"),
    [(0, 0, False), (3, 3, False), (5, 5, False), (8, 5, True)],
)
def test_recommendation_return_rows_separate_total_from_displayed(count, expected_returned, truncated):
    rows = [_row(f"SKU-{index}") for index in range(count)]

    returned, metadata = prepare_recommendation_return_rows(rows, limit=5)

    assert len(returned) == expected_returned
    assert metadata == {
        "total_match_count": count,
        "returned_count": expected_returned,
        "is_truncated": truncated,
    }


def test_subject_only_stove_recommendation_uses_central_verifier_and_answer():
    rows = [
        _row("CARD", category="炉具", product_name_cn="一方卡式炉"),
        _row("ALCOHOL", category="炉具", product_name_cn="旋焰酒精炉"),
        _row("GAS", category="炉具", product_name_cn="蓝翼分体式气炉", heat_source="卡式气罐"),
    ]
    result = customer_service_service._post_filter_recommendation_result(
        None,
        "卡式炉推荐",
        {
            "answer_type": "recommendation",
            "answer": '["露营", "卡式气罐"]',
            "results": rows,
            "result_skus": [row["sku"] for row in rows],
            "candidate_skus": [row["sku"] for row in rows],
        },
    )

    assert result["result_skus"] == ["CARD"]
    assert result["answer_metadata"]["recommendation_contract"]["subject_subtype"] == "card_stove"
    assert result["debug"]["recommendation_post_filter_applied"] is True
    assert result["debug"]["recommendation_post_filter_matched_count"] == 1
    assert "[\"露营\"" not in result["answer"]
    assert result["debug"]["rejected_candidates"][0]["rejection_reasons"] == ["subject_subtype_mismatch"]


def test_verified_recommendation_answer_anchors_broad_and_specific_stove_subjects():
    broad_contract = build_recommendation_request_contract("炉具推荐")
    broad_rows = [_row("STOVE", category="炉具", product_name_cn="户外炉")]
    broad_verifications = verify_recommendation_candidates(broad_contract, broad_rows)
    broad_answer = build_verified_recommendation_answer(broad_contract, broad_rows, broad_verifications)

    alcohol_contract = build_recommendation_request_contract("酒精炉推荐")
    alcohol_rows = [_row("ALCOHOL", category="炉具", product_name_cn="旋焰酒精炉")]
    alcohol_verifications = verify_recommendation_candidates(alcohol_contract, alcohol_rows)
    alcohol_answer = build_verified_recommendation_answer(alcohol_contract, alcohol_rows, alcohol_verifications)

    assert "炉具类商品" in broad_answer
    assert "酒精炉" in alcohol_answer
    assert "[\"" not in broad_answer


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("卡式炉推荐", True),
        ("推荐一个酒精炉", True),
        ("炉具推荐", True),
        ("推荐适合卡式炉的锅具", True),
        ("四人、明火、轻一点的锅具推荐", True),
        ("锅具和烤盘哪个更适合", False),
        ("烤盘还是锅具", False),
        ("锅具与烤盘分别有什么优缺点", False),
        ("推荐锅具还是烤盘", False),
    ],
)
def test_central_subject_recommendation_entry_excludes_comparison_and_compound(question, expected):
    contract = build_recommendation_request_contract(question)

    assert customer_service_service._should_use_central_subject_recommendation(
        question=question,
        recommendation_contract=contract,
    ) is expected


def test_recommendation_result_skus_match_displayed_rows_when_truncated():
    rows = [
        _row(
            f"CUP-{index}",
            category="水具",
            product_name_cn=f"轻量水杯{index}",
            gross_weight_g=100 + index,
        )
        for index in range(8)
    ]
    result = customer_service_service._post_filter_recommendation_result(
        None,
        "轻便水杯推荐几个",
        {
            "answer_type": "recommendation",
            "answer": "旧推荐答案",
            "results": rows,
            "result_skus": [row["sku"] for row in rows],
            "candidate_skus": [row["sku"] for row in rows],
        },
    )

    assert result["result_skus"] == [f"CUP-{index}" for index in range(5)]
    assert result["candidate_skus"] == result["result_skus"]
    assert [row["sku"] for row in result["results"]] == result["result_skus"]
    assert result["answer_metadata"]["total_match_count"] == 8
    assert result["answer_metadata"]["returned_count"] == 5
    assert result["answer_metadata"]["is_truncated"] is True
    assert "共找到8款可供参考的商品，以下先展示前5款" in result["answer"]
    assert set(result["debug"]["all_verified_candidate_skus"]) == {f"CUP-{index}" for index in range(8)}
    for sku in result["result_skus"]:
        assert sku in result["answer"]
        assert any(item["sku"] == sku for item in result["debug"]["candidate_verifications"])


def test_lightweight_uses_numeric_weight_not_scenario_label():
    contract = build_recommendation_request_contract("想要轻一点的露营锅具")
    numeric, scenario_only = verify_recommendation_candidates(
        contract,
        [
            _row("LIGHT", gross_weight_g=650),
            _row("SCENE", usage_scenarios="轻量徒步、双人露营"),
        ],
    )

    assert "weight" in numeric.verified_preferences
    assert numeric.evidence_by_constraint["weight"]["raw_value"] == 650
    assert "weight" in scenario_only.unsupported_preferences
    assert "weight" not in scenario_only.verified_preferences


def test_budget_without_trustworthy_price_is_unsupported():
    contract = build_recommendation_request_contract("预算中等，推荐一套锅")
    result = verify_recommendation_candidates(
        contract,
        [_row("MID", price_positioning="中端高性价比")],
    )[0]

    assert result.hard_constraints_passed is True
    assert result.evidence_by_constraint["budget"]["status"] == "unsupported"
    assert "budget" in result.unsupported_preferences


def test_capacity_is_not_proved_by_family_picnic_scenario():
    contract = build_recommendation_request_contract("家庭露营，容量宽裕的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("FAMILY", usage_scenarios="家庭野餐")],
    )[0]

    assert result.evidence_by_constraint["capacity"]["status"] == "unsupported"
    assert "capacity" in result.unsupported_preferences


def test_wrong_subject_and_accessory_are_rejected():
    contract = build_recommendation_request_contract("推荐适合燃气炉的锅具")
    wrong, accessory = verify_recommendation_candidates(
        contract,
        [
            _row("CUP", category="水具", sub_category="水杯", heat_source="燃气炉"),
            _row("LID", category="配件", sub_category="锅盖", heat_source="燃气炉"),
        ],
    )

    assert "subject_category_mismatch" in wrong.rejection_reasons
    assert "accessory_scope" in accessory.rejection_reasons


def test_placeholder_values_are_not_evidence():
    contract = build_recommendation_request_contract("推荐能用燃气炉、轻一点的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("EMPTY", heat_source="/", gross_weight_g="/")],
    )[0]

    assert result.hard_constraints_passed is True
    assert result.verification_level == "partially_verified"
    assert result.evidence_by_constraint["heat_source"]["status"] == "unknown"
    assert "weight" in result.unsupported_preferences


def test_verified_rows_are_the_only_rows_eligible_for_results():
    contract = build_recommendation_request_contract("四个人露营，要支持明火的套锅")
    results = verify_recommendation_candidates(
        contract,
        [
            _row("PASS", target_audience="适合4人", heat_source="明火"),
            _row("FAIL", target_audience="适合2-3人", heat_source="明火"),
        ],
    )

    assert [item.sku for item in results if item.hard_constraints_passed] == ["PASS"]


def test_answer_uses_only_same_sku_verified_evidence():
    contract = build_recommendation_request_contract("两个人露营，要支持明火的套锅")
    row = _row("PASS", product_name_cn="双人套锅", target_audience="适合1-2人", heat_source="明火")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "PASS" in answer
    assert "人数：1-2人" in answer
    assert "明火" in answer
    assert "[" not in answer


def test_answer_discloses_unsupported_soft_preferences():
    contract = build_recommendation_request_contract("预算中等，想要轻一点的锅具")
    row = _row("UNKNOWN")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "尚未验证" in answer
    assert "重量" in answer
    assert "预算" in answer


def test_no_hard_constraint_match_returns_safe_answer_without_skus():
    contract = build_recommendation_request_contract("四个人露营，要支持燃气炉的套锅")
    row = _row("FAIL", target_audience="适合2-3人", heat_source="电磁炉")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [], [verification])

    assert "未找到符合条件" in answer
    assert "能验证所有硬性条件" in answer
    assert "FAIL" not in answer


def test_explicit_numeric_capacity_and_weight_become_hard_constraints():
    contract = build_recommendation_request_contract("推荐容量至少2L、重量不超过1kg并支持燃气炉的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("TOO-HEAVY", capacity="2.5L", gross_weight_g=1200, heat_source="燃气炉")],
    )[0]

    assert contract.capacity_min_ml == 2000
    assert contract.weight_max_g == 1000
    assert {"capacity", "weight", "heat_source"} <= set(contract.hard_constraints)
    assert result.hard_constraints_passed is False
    assert "weight_constraint_not_met" in result.rejection_reasons


def test_multi_condition_route_verifies_before_ranking(monkeypatch):
    rows = [
        _row("VALID", target_audience="适合4人", capacity="4L", gross_weight_g=900, heat_source="明火直烧"),
        _row("SMALL", target_audience="适合2-3人", capacity="3.5L", gross_weight_g=800, heat_source="明火直烧"),
        _row("NO-HEAT", target_audience="适合4人", capacity="4L", gross_weight_g=700, heat_source="电磁炉"),
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, category: rows)
    monkeypatch.setattr(customer_service_service, "_is_service_pot_or_cookware_set_candidate", lambda row: True)

    result = customer_service_service._structured_cookware_multi_condition_recommendation_result(
        None,
        "一家四口营地煮汤，容量要大但别太重，还希望能直接明火加热，推荐哪款套锅？",
    )

    assert result["result_skus"] == ["VALID"]
    assert result["candidate_skus"] == ["VALID"]
    assert result["answer_metadata"]["recommendation_contract"]["people_min"] == 4
    assert {item["sku"] for item in result["debug"]["rejected_candidates"]} == {"SMALL", "NO-HEAT"}
    assert "SMALL" not in result["answer"]


def test_multi_condition_route_returns_safe_result_when_no_candidate_verifies(monkeypatch):
    rows = [_row("SMALL", target_audience="适合2-3人", heat_source="明火直烧")]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, category: rows)
    monkeypatch.setattr(customer_service_service, "_is_service_pot_or_cookware_set_candidate", lambda row: True)

    result = customer_service_service._structured_cookware_multi_condition_recommendation_result(
        None,
        "一家四口营地煮汤，容量要大但别太重，还希望能直接明火加热，推荐哪款套锅？",
    )

    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert "未找到符合条件" in result["answer"]
    assert "能验证所有硬性条件" in result["answer"]
    assert result["debug"]["verified_candidate_skus"] == []


def test_post_filter_consumes_same_verification_and_does_not_reinsert_rejected_rows():
    rows = [
        _row("VALID", target_audience="适合1-2人", heat_source="燃气炉", gross_weight_g=650),
        _row("VAGUE", target_audience="适合1-2人", features="两种燃料可选", usage_scenarios="轻量徒步"),
    ]
    agent_result = {
        "answer_type": "recommendation",
        "answer": "旧答案推荐 VALID 和 VAGUE",
        "results": rows,
        "result_skus": ["VALID", "VAGUE"],
        "candidate_skus": ["VALID", "VAGUE"],
        "answer_metadata": {"source": "product_catalog_structured_recommendation"},
        "debug": {},
    }

    result = customer_service_service._post_filter_recommendation_result(
        None,
        "两个人海边露营，预算别太高，想要轻一点并能搭配燃气炉，选哪套锅合适？",
        agent_result,
    )

    assert result["result_skus"] == ["VALID"]
    assert result["candidate_skus"] == ["VALID"]
    assert "VAGUE" not in result["answer"]
    assert result["debug"]["verified_candidate_skus"] == ["VALID"]
    assert result["debug"]["rejected_candidates"] == []
    assert result["debug"]["partially_verified_candidates"][0]["sku"] == "VAGUE"


def test_post_filter_preserves_only_verified_skus_even_if_input_lists_rejected_sku():
    row = _row("REJECTED", target_audience="适合2-3人", heat_source="明火")
    result = customer_service_service._post_filter_recommendation_result(
        None,
        "一家四口露营，需要明火套锅，推荐哪款？",
        {
            "answer_type": "recommendation",
            "answer": "推荐 REJECTED",
            "results": [row],
            "result_skus": ["REJECTED"],
            "candidate_skus": ["REJECTED"],
            "answer_metadata": {},
            "debug": {},
        },
    )

    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert result["results"] == []


@pytest.mark.parametrize(
    ("question", "people", "heat_source", "budget", "soft_preferences"),
    [
        (
            "四个人自驾露营，想要容量宽裕、重量别太夸张，还要能放燃气炉上用，锅具怎么选？",
            (4, 4),
            "燃气炉",
            None,
            {"capacity", "weight"},
        ),
        (
            "两个人周末徒步做饭，预算中等，优先轻便收纳并且要适配明火，推荐什么锅？",
            (2, 2),
            "明火",
            "medium",
            {"weight", "budget", "portability", "storage"},
        ),
        (
            "两个人去海边露营，预算别太高，想要轻一点并能搭配燃气炉，选哪套锅合适？",
            (2, 2),
            "燃气炉",
            "low",
            {"weight", "budget"},
        ),
        (
            "一家四口营地煮汤，容量要大但别太重，还希望能直接明火加热，推荐哪款套锅？",
            (4, 4),
            "明火",
            None,
            {"capacity", "weight"},
        ),
    ],
)
def test_original_p03_cases_build_verifiable_contracts(
    question,
    people,
    heat_source,
    budget,
    soft_preferences,
):
    contract = build_recommendation_request_contract(question)

    assert contract.subject_category == "锅具"
    assert (contract.people_min, contract.people_max) == people
    assert heat_source in contract.heat_sources
    assert contract.budget_level == budget
    assert soft_preferences <= set(contract.soft_preferences)
    assert {"people", "heat_source"} <= set(contract.hard_constraints)


def test_unknown_people_is_partial_not_rejected():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    result = verify_recommendation_candidates(contract, [_row("UNKNOWN")])[0]

    assert result.verification_level == "partially_verified"
    assert result.hard_constraints_passed is True
    assert result.all_hard_constraints_verified is False
    assert result.has_hard_constraint_conflict is False
    assert result.evidence_by_constraint["people"]["status"] == "unknown"
    assert result.unsupported_constraints == ["people"]
    assert result.rejection_reasons == []


def test_conflicting_people_is_rejected_with_conflict():
    contract = build_recommendation_request_contract("四个人露营，推荐锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("CONFLICT", target_audience="适合2-3人")],
    )[0]

    assert result.verification_level == "rejected"
    assert result.hard_constraints_passed is False
    assert result.has_hard_constraint_conflict is True
    assert result.conflicts == ["people"]


def test_verified_people_is_fully_verified():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("VERIFIED", target_audience="适合1-2人")],
    )[0]

    assert result.verification_level == "fully_verified"
    assert result.all_hard_constraints_verified is True
    assert result.evidence_by_constraint["people"]["status"] == "verified"


def test_one_verified_and_one_unknown_hard_constraint_is_partial():
    contract = build_recommendation_request_contract("两个人露营，要用燃气炉的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("PARTIAL", target_audience="适合1-2人")],
    )[0]

    assert result.verification_level == "partially_verified"
    assert result.evidence_by_constraint["people"]["status"] == "verified"
    assert result.evidence_by_constraint["heat_source"]["status"] == "unknown"
    assert result.unsupported_constraints == ["heat_source"]


def test_any_hard_conflict_rejects_even_when_other_constraints_verify():
    contract = build_recommendation_request_contract("四个人露营，要用明火的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("REJECT", target_audience="适合2-3人", heat_source="明火直烧")],
    )[0]

    assert result.evidence_by_constraint["heat_source"]["status"] == "verified"
    assert result.verification_level == "rejected"
    assert result.conflicts == ["people"]


def test_partial_answer_discloses_unknown_hard_and_soft_constraints():
    contract = build_recommendation_request_contract("两个人露营，锅具要稳一点，推荐哪个？")
    row = _row("PARTIAL", gross_weight_g=600)
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "没有找到所有条件都能完整验证的商品" in answer
    assert "仅供参考" in answer
    assert "尚未验证：人数、稳定性" in answer
    assert "人数：" not in answer
    assert "稳定性：" not in answer


def test_fully_verified_candidates_take_priority_over_partial_candidates():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    rows = [_row("PARTIAL"), _row("FULL", target_audience="适合1-2人")]
    verifications = verify_recommendation_candidates(contract, rows)

    selected = select_recommendation_candidates(rows, verifications)

    assert [row["sku"] for row in selected] == ["FULL"]


def test_partial_candidates_are_returned_when_no_fully_verified_candidate_exists():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    rows = [_row("PARTIAL-A"), _row("PARTIAL-B")]
    verifications = verify_recommendation_candidates(contract, rows)

    selected = select_recommendation_candidates(rows, verifications)

    assert [row["sku"] for row in selected] == ["PARTIAL-A", "PARTIAL-B"]
    assert all(item.verification_level == "partially_verified" for item in verifications)


def test_rejected_candidate_is_never_selected_with_partial_candidates():
    contract = build_recommendation_request_contract("四个人露营，推荐锅具")
    rows = [_row("PARTIAL"), _row("REJECTED", target_audience="适合2-3人")]
    verifications = verify_recommendation_candidates(contract, rows)

    selected = select_recommendation_candidates(rows, verifications)

    assert [row["sku"] for row in selected] == ["PARTIAL"]


def test_scenario_label_does_not_verify_people():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("SCENE", usage_scenarios="双人露营")],
    )[0]

    assert result.evidence_by_constraint["people"]["status"] == "unknown"
    assert result.verification_level == "partially_verified"


def test_generic_stability_text_without_explicit_structure_is_unsupported():
    contract = build_recommendation_request_contract("两个人露营，锅具要稳一点")
    result = verify_recommendation_candidates(
        contract,
        [_row("SCENE", usage_scenarios="稳定露营场景")],
    )[0]

    assert "stability" in result.unsupported_preferences
    assert "stability" not in result.verified_preferences


def test_placeholder_hard_evidence_is_unknown_not_conflict():
    contract = build_recommendation_request_contract("两个人露营，要支持燃气炉的锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("PLACEHOLDER", target_audience="/", heat_source="/")],
    )[0]

    assert result.verification_level == "partially_verified"
    assert result.unsupported_constraints == ["people", "heat_source"]
    assert result.conflicts == []


def test_contract_serialization_round_trip_preserves_all_fields():
    contract = build_recommendation_request_contract("我一个人徒步，想轻一点，推荐一个锅。")
    contract.exclusions = ["OLD-SKU"]
    contract.relative_price_preference = "cheaper_than_anchor"
    contract.price_anchor_sku = "ANCHOR"
    contract.field_provenance = {"people": {"source_turn": 1, "provenance": "current_turn"}}

    restored = type(contract).from_dict(contract.to_dict())

    assert restored.to_dict() == contract.to_dict()


def test_merge_inherits_unmentioned_fields_and_adds_heat_source():
    inherited = build_recommendation_request_contract("我一个人徒步，想轻一点，推荐一个锅。")
    current = build_recommendation_request_contract("它能不能用酒精炉？")

    effective, provenance = merge_recommendation_request_contracts(inherited, current, current_turn=2)

    assert effective.subject_category == "锅具"
    assert (effective.people_min, effective.people_max) == (1, 1)
    assert effective.scenario == ["hiking"]
    assert effective.weight_preference == "lighter"
    assert effective.heat_sources == ["酒精炉"]
    assert provenance["people"]["provenance"] == "inherited"
    assert provenance["heat_sources"] == {"source_turn": 2, "provenance": "current_turn_addition"}


def test_merge_current_people_explicitly_overrides_inherited_people():
    inherited = build_recommendation_request_contract("两个人露营，推荐锅具")
    current = build_recommendation_request_contract("改成四个人用")

    effective, provenance = merge_recommendation_request_contracts(inherited, current, current_turn=2)

    assert (effective.people_min, effective.people_max) == (4, 4)
    assert provenance["people"] == {"source_turn": 2, "provenance": "current_turn_override"}


def test_relative_price_followup_inherits_contract_and_excludes_anchor():
    inherited = build_recommendation_request_contract("我一个人徒步，想轻一点，推荐一个锅。")
    current = build_recommendation_request_contract("有没有更便宜一点的替代？")

    effective, provenance = merge_recommendation_request_contracts(
        inherited,
        current,
        previous_result_skus=["ANCHOR", "BACKUP"],
        anchor_sku="ANCHOR",
        current_turn=3,
    )

    assert effective.subject_category == "锅具"
    assert effective.people_min == 1
    assert effective.weight_preference == "lighter"
    assert effective.relative_price_preference == "cheaper_than_anchor"
    assert effective.price_anchor_sku == "ANCHOR"
    assert effective.exclusions == ["ANCHOR"]
    assert provenance["relative_price_preference"]["source_turn"] == 3
    assert provenance["exclusions"] == {"source_turn": 3, "provenance": "system_exclusion"}


def test_relative_price_without_price_evidence_is_unsupported():
    contract = build_recommendation_request_contract("有没有更便宜一点的替代？")
    result = verify_recommendation_candidates(contract, [_row("ALT")])[0]

    assert contract.relative_price_preference == "cheaper_than_anchor"
    assert result.evidence_by_constraint["budget"]["status"] == "unsupported"
    assert "budget" in result.unsupported_preferences


def test_recommendation_context_product_field_is_not_rewritten_by_list_filter():
    original = {
        "answer_type": "product_detail",
        "answer": "该商品资料明确支持目标热源。",
        "results": [_row("ANCHOR")],
        "result_skus": ["ANCHOR"],
        "candidate_skus": ["ANCHOR"],
        "debug": {"agent_mode": "recommendation_context_product_field"},
    }

    result = customer_service_service._phase1_filter_alcohol_stove_cookware_result(
        None,
        original,
        question="它能不能用酒精炉？",
    )

    assert result is original
    assert result["result_skus"] == ["ANCHOR"]
    assert result["answer_type"] == "product_detail"
