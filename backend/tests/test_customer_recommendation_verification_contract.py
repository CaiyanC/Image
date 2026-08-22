import pytest

from app.services.customer_recommendation_verification_contract import (
    CandidateVerification,
    build_semantic_recommendation_request_contract,
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


def test_explicit_charcoal_heat_source_does_not_match_generic_open_flame():
    contract = build_recommendation_request_contract("我只想用炭火，适合买哪种锅具？")
    charcoal, open_flame = verify_recommendation_candidates(
        contract,
        [
            _row("CHARCOAL", heat_source="炭火、明火"),
            _row("OPEN-FLAME", heat_source="明火直烧"),
        ],
    )

    assert contract.heat_sources == ["炭火"]
    assert charcoal.verification_level == "fully_verified"
    assert open_flame.verification_level == "rejected"
    assert "heat_source_condition_not_met" in open_flame.rejection_reasons


def test_explicit_non_split_structure_rejects_split_burners_without_sku_rules():
    contract = build_recommendation_request_contract(
        "我要装气罐的小炉头，不要分体的，推荐哪款？"
    )

    split, integrated, unknown = verify_recommendation_candidates(
        contract,
        [
            _row("SPLIT", category="炉具", product_name_cn="分体炉头", features="远程炉头"),
            _row("INTEGRATED", category="炉具", product_name_cn="一体炉", features="一体收纳"),
            _row("UNKNOWN", category="炉具", product_name_cn="户外炉具", features="便携耐用"),
        ],
    )

    assert contract.structure_preference == "non_split"
    assert "structure" in contract.hard_constraints
    assert split.verification_level == "rejected"
    assert "structure_condition_not_met" in split.rejection_reasons
    assert integrated.verification_level == "fully_verified"
    assert unknown.verification_level == "rejected"
    assert "structure" in unknown.unsupported_constraints


def test_semantic_contract_retains_explicit_charcoal_requirement_when_llm_omits_it():
    contract = build_recommendation_request_contract(
        "我只想用炭火，适合买哪种锅具？",
        semantic_constraints={"subject_kind": "cookware"},
    )

    charcoal, open_flame = verify_recommendation_candidates(
        contract,
        [
            _row("CHARCOAL", heat_source="炭火"),
            _row("OPEN-FLAME", heat_source="明火直烧"),
        ],
    )

    assert contract.heat_sources == ["炭火"]
    assert charcoal.verification_level == "fully_verified"
    assert open_flame.verification_level == "rejected"


def test_exact_316l_material_grade_is_a_hard_constraint_not_generic_stainless_steel():
    contract = build_recommendation_request_contract("\u6709\u6ca1\u6709316L\u4e0d\u9508\u94a2\u7684\u6237\u5916\u5957\u9505\uff1f")

    match, generic_stainless = verify_recommendation_candidates(
        contract,
        [
            _row("GRADE-316L", sub_category="\u5957\u9505", body_material="316L\u4e0d\u9508\u94a2"),
            _row("GRADE-304", sub_category="\u5957\u9505", body_material="304\u4e0d\u9508\u94a2"),
        ],
    )

    assert "316L\u4e0d\u9508\u94a2" in contract.materials
    assert match.verification_level == "fully_verified"
    assert generic_stainless.verification_level == "rejected"
    assert "material_condition_not_met" in generic_stainless.rejection_reasons


def test_request_contract_treats_approximate_liter_phrase_as_capacity_range():
    contract = build_recommendation_request_contract("一个人露营，推荐 1L 左右的小锅")

    assert contract.capacity_requirement == "numeric"
    assert (contract.capacity_min_ml, contract.capacity_max_ml) == (800, 1200)
    assert "capacity" in contract.hard_constraints


def test_request_contract_extracts_bare_capacity_range_next_to_product_noun():
    contract = build_recommendation_request_contract("推荐一个0.6到0.8升水壶")

    assert contract.capacity_requirement == "numeric"
    assert (contract.capacity_min_ml, contract.capacity_max_ml) == (600, 800)
    assert "capacity" in contract.hard_constraints


def test_request_contract_treats_capacity_above_phrase_as_lower_bound():
    contract = build_recommendation_request_contract("三个人露营，推荐容量在1L以上的锅")

    assert contract.capacity_requirement == "numeric"
    assert contract.capacity_min_ml == 1000
    assert contract.capacity_max_ml is None
    assert "capacity" in contract.hard_constraints


def test_request_contract_uses_validated_semantic_constraints_without_reparsing_question_words():
    contract = build_recommendation_request_contract(
        "想找露营用、背起来别太沉的那类。",
        semantic_constraints={
            "subject_kind": "cookware",
            "people": {"min": 2, "max": 2},
            "heat_sources": ["card_stove"],
            "scenarios": ["camping"],
            "weight_preference": "lightweight",
        },
    )

    assert contract.subject_category == "锅具"
    assert contract.subject_kind == "cookware"
    assert (contract.people_min, contract.people_max) == (2, 2)
    assert contract.heat_sources == ["卡式炉"]
    assert contract.scenario == ["camping"]
    assert contract.weight_preference == "lighter"
    assert {"people", "heat_source", "scenario"} <= set(contract.hard_constraints)
    assert "weight" in contract.soft_preferences
    assert all(item["provenance"] == "validated_semantic_preplan" for item in contract.field_provenance.values())


def test_semantic_contract_keeps_compound_product_forms_open_for_rag_coverage():
    contract = build_semantic_recommendation_request_contract(
        question="三个人露营，想要锅和水壶",
        semantic_constraints={
            "subject_kinds": ["cookware", "waterware"],
            "people": {"min": 3, "max": 3},
        },
        predicate_constraints=[],
        semantic_subject_text="锅和水壶",
    )

    assert contract is not None
    assert contract.subject_kinds == ["cookware", "waterware"]
    assert contract.subject_kind is None
    assert contract.subject_category is None
    assert contract.subject_scope_open is True
    assert (contract.people_min, contract.people_max) == (3, 3)


def test_explicit_accessory_subject_overrides_a_broad_semantic_cookware_scope():
    contract = build_recommendation_request_contract(
        "有没有户外餐具收纳包推荐下？",
        semantic_constraints={"subject_kind": "cookware"},
    )

    assert contract.subject_category == "配件"
    assert contract.subject_kind == "accessories"
    assert contract.subject_subtype == "storage_bag"
    assert contract.source_spans["subject"] == "收纳包"
    assert contract.field_provenance["subject_category"]["provenance"] == "current_turn_explicit_subject"


def test_storage_bag_subtype_rejects_unrelated_accessories():
    contract = build_recommendation_request_contract("户外餐具收纳包推荐一下")
    storage_bag, water_bag, knife_set = verify_recommendation_candidates(
        contract,
        [
            _row("BAG", product_name_cn="29L户外收纳包", category="配件", title_cn="户外炊具餐具收纳包"),
            _row("WATER", product_name_cn="稳稳水袋", category="配件", title_cn="户外饮水水袋"),
            _row("KNIFE", product_name_cn="拓界刀板套装", category="配件", title_cn="户外便携刀板套装"),
        ],
    )

    assert storage_bag.verification_level == "fully_verified"
    assert water_bag.verification_level == "rejected"
    assert knife_set.verification_level == "rejected"
    assert "subject_subtype_mismatch" in water_bag.rejection_reasons
    assert "subject_subtype_mismatch" in knife_set.rejection_reasons


def test_semantic_storage_preference_requires_same_sku_storage_evidence_without_reparsing_question_words():
    contract = build_recommendation_request_contract(
        "第一次带孩子野餐，想要一套好收纳的锅具。",
        semantic_constraints={
            "subject_kind": "cookware",
            "storage_preference": "compact_storage",
        },
    )

    marked, unmarked = verify_recommendation_candidates(
        contract,
        [
            _row("STORAGE", features="套娃式收纳，不占空间"),
            _row("UNMARKED", features="硬质氧化工艺"),
        ],
    )

    assert contract.storage_required is True
    assert "storage" in contract.soft_preferences
    assert contract.field_provenance["storage"]["provenance"] == "validated_semantic_preplan"
    assert marked.evidence_by_constraint["storage"]["status"] == "verified"
    assert unmarked.evidence_by_constraint["storage"]["status"] == "unsupported"


def test_semantic_affordable_price_preference_is_soft_and_uses_same_sku_price_positioning():
    contract = build_recommendation_request_contract(
        "预算别太高，推荐一套锅具。",
        semantic_constraints={
            "subject_kind": "cookware",
            "price_preference": "affordable",
        },
    )
    entry, mid, premium = verify_recommendation_candidates(
        contract,
        [
            _row("ENTRY", price_positioning="入门款"),
            _row("MID", price_positioning="中端"),
            _row("PREMIUM", price_positioning="高端"),
        ],
    )

    assert "price_positioning" not in contract.hard_constraints
    assert "budget" in contract.soft_preferences
    assert contract.field_provenance["price_positioning"]["provenance"] == "validated_semantic_preplan"
    assert entry.evidence_by_constraint["price_positioning"]["status"] == "verified"
    assert mid.evidence_by_constraint["price_positioning"]["status"] == "verified"
    assert premium.evidence_by_constraint["price_positioning"]["status"] == "conflict"
    assert premium.verification_level == "fully_verified"
    assert "budget" in premium.unsupported_preferences
    assert "price_positioning_condition_not_met" not in premium.rejection_reasons


def test_semantic_recommendation_scenario_requires_same_sku_usage_evidence():
    contract = build_recommendation_request_contract(
        "露营时想要一套不累赘的锅。",
        semantic_constraints={"subject_kind": "cookware", "scenarios": ["camping"]},
    )
    camping, unmarked = verify_recommendation_candidates(
        contract,
        [
            _row("CAMP", usage_scenarios="露营、野餐"),
            _row("UNMARKED", usage_scenarios="家庭厨房"),
        ],
    )

    assert camping.evidence_by_constraint["scenario"]["status"] == "verified"
    assert unmarked.verification_level == "rejected"
    assert "scenario_condition_not_met" in unmarked.rejection_reasons


def test_cookware_subject_rejects_a_water_container_even_when_catalog_category_is_broad():
    """Product identity must not be widened into a cookware recommendation.

    The source category is an inventory label and can be broad.  A row whose
    own identity is a water container is incompatible with the semantic
    cookware subject, even if that broad category says ``锅具``.
    """
    contract = build_recommendation_request_contract(
        "推荐能用酒精炉的锅",
        semantic_constraints={"subject_kind": "cookware", "heat_sources": ["alcohol_stove"]},
    )

    result = verify_recommendation_candidates(
        contract,
        [_row("BROAD-CATEGORY-KETTLE", product_name_cn="时谷水壶", heat_source="酒精炉")],
    )[0]

    assert result.verification_level == "rejected"
    assert result.evidence_by_constraint["subject"]["status"] == "conflict"
    assert "subject_category_mismatch" in result.rejection_reasons


def test_explicit_kettle_request_does_not_accept_a_water_cup():
    contract = build_recommendation_request_contract("推荐一个0.6到0.8升水壶")
    result = verify_recommendation_candidates(
        contract,
        [_row("CUP", product_name_cn="畅享水杯", category="水具", capacity="800ml")],
    )[0]

    assert contract.subject_subtype == "kettle"
    assert result.verification_level == "rejected"
    assert "subject_category_mismatch" in result.rejection_reasons


def test_request_contract_normalizes_people_ranges_and_budget():
    two = build_recommendation_request_contract("两个人徒步，预算中等，推荐轻便锅具")
    range_contract = build_recommendation_request_contract("四五个人露营，锅具怎么选")

    assert (two.people_min, two.people_max) == (2, 2)
    assert two.budget_level == "medium"
    assert "budget" in two.soft_preferences
    assert (range_contract.people_min, range_contract.people_max) == (4, 5)


def test_request_contract_parses_young_group_people_count():
    contract = build_recommendation_request_contract(
        "\u4e09\u4e2a\u5e74\u8f7b\u4eba\u9732\u8425\uff0c\u9002\u5408\u5e26\u4ec0\u4e48\u9505\u5177"
    )

    assert (contract.people_min, contract.people_max) == (3, 3)
    assert "people" in contract.hard_constraints


def test_request_contract_ignores_negated_people_range_and_keeps_positive_people_need():
    contract = build_recommendation_request_contract("5个人露营做饭，不要1-2人的锅，推荐大容量套锅")

    assert (contract.people_min, contract.people_max) == (5, 5)
    assert "people" in contract.hard_constraints


def test_four_people_rejects_explicit_two_to_three_person_product():
    contract = build_recommendation_request_contract("一家四口露营，推荐能明火加热的套锅")
    result = verify_recommendation_candidates(
        contract,
        [_row("SMALL", target_audience="适合2-3人", heat_source="明火直烧")],
    )[0]

    assert result.hard_constraints_passed is False
    assert "people_capacity_conflict" in result.rejection_reasons


def test_people_verification_rejects_fullwidth_dash_two_person_range_for_five_person_request():
    contract = build_recommendation_request_contract("5个人露营，推荐锅具")
    result = verify_recommendation_candidates(
        contract,
        [_row("PAIR", product_name_cn="1－2人露营锅")],
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
        "适合酒精炉的锅具",
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


def test_named_alcohol_stove_keeps_hotpot_as_a_hard_scenario_and_parses_soft_preferences():
    contract = build_recommendation_request_contract("那款酒精炉适合煮火锅，又稳又防风？")

    assert (contract.subject_category, contract.subject_kind, contract.subject_subtype) == (
        "炉具",
        "stove",
        "alcohol_stove",
    )
    assert contract.heat_sources == []
    assert contract.scenario == ["hotpot"]
    assert "scenario" in contract.hard_constraints
    assert contract.stability_required is True
    assert contract.windproof_required is True
    assert {"stability", "windproof"} <= set(contract.soft_preferences)


def test_semantic_subject_correction_records_current_turn_literal_provenance():
    contract = build_recommendation_request_contract(
        "那款酒精炉适合煮火锅，又稳又防风？",
        semantic_constraints={"subject_kind": "cookware"},
    )

    assert (contract.subject_category, contract.subject_kind, contract.subject_subtype) == (
        "炉具",
        "stove",
        "alcohol_stove",
    )
    assert contract.field_provenance["subject_category"] == {
        "source_turn": 1,
        "provenance": "current_turn_explicit_subject",
    }
    for field_name in ("scenario", "stability", "windproof"):
        assert contract.field_provenance[field_name] == {
            "source_turn": 1,
            "provenance": "current_turn",
        }


def test_literal_scenario_does_not_overwrite_validated_semantic_provenance():
    contract = build_recommendation_request_contract(
        "露营锅具推荐一下",
        semantic_constraints={"subject_kind": "cookware", "scenarios": ["camping"]},
    )

    assert contract.scenario == ["camping"]
    assert contract.field_provenance["scenario"] == {
        "source_turn": 1,
        "provenance": "validated_semantic_preplan",
    }


def test_action_governed_trailing_alcohol_stove_keeps_literal_requirements():
    contract = build_recommendation_request_contract("推荐适合煮火锅又稳又防风的酒精炉")

    assert (contract.subject_category, contract.subject_kind, contract.subject_subtype) == (
        "炉具",
        "stove",
        "alcohol_stove",
    )
    assert contract.heat_sources == []
    assert contract.scenario == ["hotpot"]
    assert {"stability", "windproof"} <= set(contract.soft_preferences)


def test_trailing_stove_without_recommendation_action_is_not_a_recommendation_subject():
    contract = build_recommendation_request_contract("适合煮火锅又稳又防风的酒精炉吗？")

    assert contract.subject_category is None
    assert contract.subject_kind is None
    assert contract.subject_subtype is None


def test_standalone_pot_remains_cookware_when_question_also_mentions_hotpot():
    contract = build_recommendation_request_contract("推荐一口锅煮火锅")

    assert contract.subject_category == "锅具"
    assert contract.subject_kind == "cookware"
    assert contract.scenario == ["hotpot"]


def test_hotpot_scenario_alone_does_not_create_a_cookware_subject():
    contract = build_recommendation_request_contract("推荐适合煮火锅的装备")

    assert contract.subject_category != "锅具"
    assert contract.subject_kind != "cookware"
    assert contract.scenario == ["hotpot"]


def test_hotpot_stove_preferences_require_same_sku_feature_or_positioning_evidence():
    contract = build_recommendation_request_contract("那款酒精炉适合煮火锅，又稳又防风？")
    verified, unsupported = verify_recommendation_candidates(
        contract,
        [
            _row(
                "VERIFIED",
                category="炉具",
                product_name_cn="户外酒精炉",
                usage_scenarios="适合煮火锅",
                features="支架稳固",
                positioning="防风设计",
            ),
            _row(
                "UNSUPPORTED",
                category="炉具",
                product_name_cn="便携酒精炉",
                title_cn="稳定防风酒精炉",
                usage_scenarios="火锅烹饪",
            ),
        ],
    )

    assert verified.verification_level == "fully_verified"
    assert {"stability", "windproof"} <= set(verified.verified_preferences)
    assert unsupported.verification_level == "fully_verified"
    assert {"stability", "windproof"} <= set(unsupported.unsupported_preferences)
    assert "stability" not in unsupported.verified_preferences
    assert "windproof" not in unsupported.verified_preferences

    answer = build_verified_recommendation_answer(contract, [
        _row(
            "UNSUPPORTED",
            category="炉具",
            product_name_cn="便携酒精炉",
            title_cn="稳定防风酒精炉",
            usage_scenarios="火锅烹饪",
        )
    ], [unsupported])
    assert "稳定性资料暂未明确" in answer
    assert "防风性资料暂未明确" in answer


def test_combustion_stability_does_not_verify_physical_stability():
    contract = build_recommendation_request_contract("那款酒精炉适合煮火锅，又稳又防风？")
    result = verify_recommendation_candidates(
        contract,
        [
            _row(
                "COMBUSTION-STABLE",
                category="炉具",
                product_name_cn="户外酒精炉",
                usage_scenarios="适合煮火锅",
                features="燃烧稳定",
                positioning="防风设计",
            )
        ],
    )[0]

    assert result.evidence_by_constraint["scenario"]["status"] == "verified"
    assert "windproof" in result.verified_preferences
    assert "stability" in result.unsupported_preferences
    assert "stability" not in result.verified_preferences


def test_combustion_stability_is_unsupported_while_windproof_candidate_remains_eligible():
    contract = build_recommendation_request_contract("那款酒精炉适合煮火锅，又稳又防风？")
    result = verify_recommendation_candidates(
        contract,
        [
            _row(
                "ALCOHOL-STOVE",
                category="炉具",
                product_name_cn="酒精炉",
                usage_scenarios="火锅烹饪",
                features="燃烧稳定",
                positioning="防风设计",
            )
        ],
    )[0]

    assert result.verification_level == "fully_verified"
    assert "windproof" in result.verified_preferences
    assert "stability" in result.unsupported_preferences
    assert "stability" not in result.verified_preferences


def test_placement_stability_verifies_physical_stability():
    contract = build_recommendation_request_contract("那款酒精炉适合煮火锅，又稳又防风？")
    result = verify_recommendation_candidates(
        contract,
        [
            _row(
                "PLACEMENT-STABLE",
                category="炉具",
                product_name_cn="酒精炉",
                usage_scenarios="火锅烹饪",
                features="放置稳定",
                positioning="防风设计",
            )
        ],
    )[0]

    assert "stability" in result.verified_preferences


def test_stove_subject_accepts_alcohol_stove_catalog_category():
    """A database category may name the stove subtype rather than ``炉具``."""
    contract = build_recommendation_request_contract(
        "recommend a stove",
        semantic_constraints={"subject_kind": "stove"},
    )

    result = verify_recommendation_candidates(
        contract,
        [
            _row(
                "ALCOHOL-STOVE",
                category="\u9152\u7cbe\u7089",
                product_name_cn="\u65cb\u7130\u9152\u7cbe\u7089",
            )
        ],
    )[0]

    assert result.subject_eligible is True
    assert result.evidence_by_constraint["subject"]["status"] == "verified"
    assert result.verification_level == "fully_verified"


def test_semantic_stove_kind_preserves_explicit_alcohol_subtype():
    contract = build_recommendation_request_contract(
        "酒精炉推荐一个",
        semantic_constraints={"subject_kind": "stove"},
    )

    assert (contract.subject_category, contract.subject_kind, contract.subject_subtype) == (
        "炉具",
        "stove",
        "alcohol_stove",
    )


def test_people_verification_accepts_single_person_business_evidence():
    """Chinese customer-count labels in stored product data are valid evidence."""
    contract = build_recommendation_request_contract(
        "recommend a stove for one person",
        semantic_constraints={"subject_kind": "stove", "people": {"min": 1, "max": 1}},
    )

    result = verify_recommendation_candidates(
        contract,
        [
            _row(
                "SINGLE-STOVE",
                category="\u7089\u5177",
                target_audience="\u9002\u5408\u5355\u4eba\u9732\u8425",
            )
        ],
    )[0]

    assert result.evidence_by_constraint["people"]["status"] == "verified"
    assert result.verification_level == "fully_verified"


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
    assert "subject_subtype" not in alcohol_answer


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
        [_row("MID")],
    )[0]

    assert result.hard_constraints_passed is True
    assert result.evidence_by_constraint["price_positioning"]["status"] == "unknown"
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


def test_answer_renders_serialized_list_evidence_as_customer_text():
    contract = build_recommendation_request_contract("")
    row = _row("LISTED")
    verification = CandidateVerification(
        sku="LISTED",
        subject_eligible=True,
        hard_constraints_passed=True,
        verification_level="fully_verified",
        evidence_by_constraint={
            "scenario": {"status": "verified", "raw_value": '["camping", "hiking"]'},
        },
    )

    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "[" not in answer
    assert "camping" in answer
    assert "hiking" in answer


def test_verified_answer_uses_singular_wording_for_one_candidate():
    contract = build_recommendation_request_contract("")
    row = _row("ONE")
    verification = verify_recommendation_candidates(contract, [row])[0]

    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "\u63a8\u8350\u4f18\u5148\u770b\u8fd9\u6b3e\uff1a" in answer
    assert "\u5019\u9009" not in answer
    assert "\u786c\u6027\u6761\u4ef6" not in answer


def test_affordable_answer_explains_the_budget_positioning():
    contract = build_recommendation_request_contract("\u9884\u7b97\u4e0d\u9ad8\uff0c\u63a8\u8350\u4e00\u6b3e\u9505")
    row = _row("ENTRY", price_positioning="\u5165\u95e8\u6b3e", features="\u9ad8\u6027\u4ef7\u6bd4")
    verification = verify_recommendation_candidates(contract, [row])[0]

    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert any(term in answer for term in ("\u9884\u7b97\u4e0d\u9ad8", "\u6027\u4ef7\u6bd4", "\u4ef7\u683c\u5b9a\u4f4d", "\u5b9e\u60e0"))


def test_answer_uses_only_same_sku_verified_evidence():
    contract = build_recommendation_request_contract("两个人露营，要支持明火的套锅")
    row = _row("PASS", product_name_cn="双人套锅", target_audience="适合1-2人", heat_source="明火")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "PASS" in answer
    assert "人数：1-2人" in answer
    assert "明火" in answer
    assert "[" not in answer


def test_unconstrained_multi_candidate_answer_compares_rows_before_asking_for_priority():
    contract = build_recommendation_request_contract("户外气炉推荐")
    rows = [
        _row(
            "LIGHT",
            category="炉具",
            product_name_cn="轻量炉",
            power="3200W",
            gross_weight_g=550,
            heat_source="高山气罐",
            usage_scenarios="轻量徒步，单人露营",
        ),
        _row(
            "POWER",
            category="炉具",
            product_name_cn="大火力炉",
            power="5500W",
            gross_weight_g=3480,
            heat_source="卡式气罐",
            usage_scenarios="营地大餐，户外爆炒",
        ),
    ]
    answer = build_verified_recommendation_answer(
        contract,
        rows,
        verify_recommendation_candidates(contract, rows),
    )

    assert "不足以负责任地只定一款" in answer
    assert "轻量炉（LIGHT）：功率3200W；重量550g；热源高山气罐" in answer
    assert "大火力炉（POWER）：功率5500W；重量3480g；热源卡式气罐" in answer
    assert "告诉我优先条件" in answer


def test_answer_discloses_unsupported_soft_preferences():
    contract = build_recommendation_request_contract("预算中等，想要轻一点的锅具")
    row = _row("UNKNOWN")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [row], [verification])

    assert "尚未验证" not in answer
    assert "重量资料暂未明确" in answer
    assert "预算资料暂未明确" in answer


def test_no_hard_constraint_match_returns_safe_answer_without_skus():
    contract = build_recommendation_request_contract("四个人露营，要支持燃气炉的套锅")
    row = _row("FAIL", target_audience="适合2-3人", heat_source="电磁炉")
    verification = verify_recommendation_candidates(contract, [row])[0]
    answer = build_verified_recommendation_answer(contract, [], [verification])

    assert "能验证所有硬性条件" in answer
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
    assert "人数资料暂未明确；稳定性资料暂未明确" in answer
    assert "尚未验证" not in answer
    assert "人数：" not in answer
    assert "稳定性：" not in answer


def test_mixed_verified_and_partial_stove_answer_keeps_their_status_distinct():
    contract = build_recommendation_request_contract(
        "recommend a stove for one person",
        semantic_constraints={"subject_kind": "stove", "people": {"min": 1, "max": 1}},
    )
    rows = [
        _row("FULL", category="\u7089\u5177", target_audience="\u9002\u5408\u5355\u4eba\u9732\u8425"),
        _row("PARTIAL", category="\u7089\u5177"),
    ]
    verifications = verify_recommendation_candidates(contract, rows)
    answer = build_verified_recommendation_answer(contract, rows, verifications)

    assert "\u5f53\u524d\u6ca1\u6709\u627e\u5230\u6240\u6709\u6761\u4ef6\u90fd\u80fd\u5b8c\u6574\u9a8c\u8bc1\u7684\u5546\u54c1" not in answer
    assert "\u5df2\u901a\u8fc7\u5f53\u524d\u53ef\u9a8c\u8bc1\u7684\u786c\u6027\u6761\u4ef6" in answer
    assert "\u63a8\u8350\u9505\u5177\u5019\u9009" not in answer
    assert "\u7089\u5177\u7c7b\u5546\u54c1" in answer


def test_fully_verified_candidates_precede_safe_partial_candidates():
    contract = build_recommendation_request_contract("两个人露营，推荐锅具")
    rows = [_row("PARTIAL"), _row("FULL", target_audience="适合1-2人")]
    verifications = verify_recommendation_candidates(contract, rows)

    selected = select_recommendation_candidates(rows, verifications)

    # A missing field is not a contradiction.  Keep non-conflicting partial
    # candidates after fully verified ones so a request for multiple options
    # can retain a usable comparison set without presenting the partial row
    # as fully verified.
    assert [row["sku"] for row in selected] == ["FULL", "PARTIAL"]


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


def test_merge_adds_current_turn_windproof_preference():
    inherited = build_recommendation_request_contract("推荐一个酒精炉")
    current = build_recommendation_request_contract("要防风的")

    effective, provenance = merge_recommendation_request_contracts(inherited, current, current_turn=2)

    assert effective.windproof_required is True
    assert "windproof" in effective.soft_preferences
    assert provenance["windproof"] == {"source_turn": 2, "provenance": "current_turn_addition"}


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
    assert result.evidence_by_constraint["price_positioning"]["status"] == "unknown"
    assert "budget" in result.unsupported_preferences




def test_other_recommendations_phrase_is_an_alternative_request():
    assert customer_service_service._asks_for_alternative_recommendation("还有其他推荐吗") is True


def test_griddle_direct_object_overrides_semantic_stove_subject():
    contract = build_recommendation_request_contract(
        "我有卡式炉，想买烤盘，哪些产品明确支持卡式炉？",
        semantic_constraints={"subject_kind": "stove", "heat_sources": ["card_stove"]},
    )

    assert (contract.subject_category, contract.subject_kind) == ("锅具", "cookware")
    assert contract.heat_sources == ["卡式炉"]
    assert contract.cleaning_required is False


def test_cleanability_preference_is_verified_and_ranked_from_same_sku_evidence():
    contract = build_recommendation_request_contract(
        "想买支持卡式炉的烤盘，优先推荐好清洁的。"
    )
    plain = _row("PLAIN", product_name_cn="普通烤盘", heat_source="卡式炉")
    easy_clean = _row(
        "CLEAN",
        product_name_cn="易洁烤盘",
        heat_source="卡式炉",
        surface_finish="水性不沾处理，便于清洁",
    )
    verifications = verify_recommendation_candidates(contract, [plain, easy_clean])
    selected = select_recommendation_candidates([plain, easy_clean], verifications)
    answer = build_verified_recommendation_answer(contract, selected, verifications)

    assert contract.cleaning_required is True
    assert selected[0]["sku"] == "CLEAN"
    cleaning_evidence = next(item for item in verifications if item.sku == "CLEAN").evidence_by_constraint["cleaning"]
    assert cleaning_evidence["field_source"] == "surface_finish"
    assert cleaning_evidence["raw_value"] == "水性不沾处理，便于清洁"
    assert "清洁便利" in answer and "便于清洁" in answer


def test_negated_heat_sources_do_not_become_positive_requirements():
    contract = build_recommendation_request_contract(
        "除去燃气炉和卡式炉，只看能配酒精炉的锅具。"
    )

    assert contract.subject_kind == "cookware"
    assert contract.heat_sources == ["酒精炉"]
    assert "炉具" in contract.excluded_categories


def test_explicit_sku_exclusion_is_preserved_and_rejected_by_subject_guard():
    contract = build_recommendation_request_contract(
        "除了 CW-C83，再推荐一款更轻的锅具。"
    )
    excluded, allowed = verify_recommendation_candidates(
        contract,
        [_row("CW-C83"), _row("CW-C06PRO")],
    )

    assert contract.exclusions == ["CW-C83"]
    assert excluded.verification_level == "rejected"
    assert excluded.rejection_reasons == ["excluded_sku"]
    assert allowed.subject_eligible is True


def test_recommendation_summary_renders_structured_capacity_without_json_keys():
    contract = build_recommendation_request_contract("推荐一款两个人用的锅具。")
    row = _row(
        "COOKSET",
        target_audience="1-2人",
        capacity='[{"label":"水壶","value":"约1.0L","unit":""},{"label":"大锅","value":"约1.7L","unit":""}]',
    )
    verifications = verify_recommendation_candidates(contract, [row])
    answer = build_verified_recommendation_answer(contract, [row], verifications)

    assert "水壶：约1.0L" in answer and "大锅：约1.7L" in answer
    assert "value：" not in answer and "label：" not in answer


def test_semantic_recommendation_predicates_keep_capacity_and_surface_finish_separate():
    question = "我们仨周末露营，想要一口至少一升、做三人份比较从容而且带不粘层的锅，帮我挑一款"
    contract = build_semantic_recommendation_request_contract(
        question=question,
        semantic_constraints={"subject_kind": "cookware", "people": {"min": 3, "max": 3}},
        predicate_constraints=[
            {
                "field": "capacity",
                "operator": ">=",
                "value": 1,
                "unit": "L",
                "evidence_span": "至少一升",
            },
            {
                "field": "surface_finish",
                "operator": "contains",
                "value": "不粘层",
                "unit": None,
                "evidence_span": "带不粘层",
            },
        ],
    )

    assert contract is not None
    assert contract.predicate_constraints[0]["value"] == 1000
    verified, missing_capacity, missing_coating = verify_recommendation_candidates(
        contract,
        [
            _row("MATCH", target_audience="3-4人", capacity="5L", surface_finish="水性不粘层"),
            _row("NO-CAPACITY", target_audience="3-4人", capacity="", surface_finish="水性不粘层"),
            _row("NO-COATING", target_audience="3-4人", capacity="5L", surface_finish="硬质氧化"),
        ],
    )

    assert verified.verification_level == "fully_verified"
    assert missing_capacity.verification_level == "partially_verified"
    assert "predicate:0:capacity" in missing_capacity.unsupported_constraints
    # Text predicates stay semantic: Flash compares this predicate with each
    # candidate's own sealed surface_finish evidence.
    assert missing_coating.verification_level == "fully_verified"
    assert contract.predicate_constraints[1]["field"] == "surface_finish"
    assert "predicate:1:surface_finish" not in contract.hard_constraints


def test_semantic_recommendation_contract_does_not_reparse_customer_wording():
    question = "周末三人做饭，锅至少装一升，表面要不粘，哪款更合适？"
    contract = build_semantic_recommendation_request_contract(
        question=question,
        semantic_constraints={"subject_kind": "cookware"},
        predicate_constraints=[
            {"field": "capacity", "operator": ">=", "value": 1000, "unit": "ml", "evidence_span": "至少装一升"},
            {"field": "surface_finish", "operator": "contains", "value": "不粘", "unit": None, "evidence_span": "表面要不粘"},
        ],
    )

    assert contract is not None
    assert contract.people_min is None
    assert [item["field"] for item in contract.predicate_constraints] == ["capacity", "surface_finish"]


def test_semantic_subject_text_binds_water_cup_subtype_for_same_sku_scope():
    contract = build_semantic_recommendation_request_contract(
        question="想找一款适合日常饮水的容器，推荐一款。",
        semantic_constraints={},
        predicate_constraints=[],
        semantic_subject_text="水杯",
    )

    assert contract is not None
    assert contract.subject_category == "水具"
    assert contract.subject_kind == "waterware"
    assert contract.subject_subtype == "cup"
    matched, kettle = verify_recommendation_candidates(
        contract,
        [
            _row(
                "CUP",
                category="水具",
                product_name_cn="轻便水杯",
                product_name_en="water cup",
            ),
            _row(
                "KETTLE",
                category="水具",
                product_name_cn="小方壶",
                product_name_en="camping kettle",
            ),
        ],
    )

    assert matched.verification_level != "rejected"
    assert kettle.verification_level == "rejected"
    assert "subject_subtype_mismatch" in kettle.rejection_reasons


def test_semantic_untyped_subject_leaves_catalogue_scope_to_same_sku_coverage():
    contract = build_semantic_recommendation_request_contract(
        question="户外餐具收纳包有推荐吗？",
        semantic_constraints={},
        predicate_constraints=[],
        semantic_subject_text="户外餐具收纳包",
    )

    assert contract is not None
    assert contract.subject_category is None
    assert contract.subject_scope_open is True
    match = verify_recommendation_candidates(
        contract,
        [
            _row(
                "BAG",
                category="配件",
                product_name_cn="29L户外收纳包",
                title_cn="户外炊具餐具收纳包",
            ),
        ],
    )[0]

    assert match.subject_eligible is True
    assert match.verification_level == "fully_verified"


def test_selector_can_preserve_rag_input_order_after_fact_verification():
    rows = [_row("RAG-FIRST"), _row("RAG-SECOND")]
    verifications = [
        CandidateVerification(
            sku="RAG-FIRST",
            subject_eligible=True,
            hard_constraints_passed=True,
            verification_level="fully_verified",
        ),
        CandidateVerification(
            sku="RAG-SECOND",
            subject_eligible=True,
            hard_constraints_passed=True,
            verification_level="fully_verified",
            verified_preferences=["weight"],
        ),
    ]

    assert [row["sku"] for row in select_recommendation_candidates(rows, verifications)] == [
        "RAG-SECOND",
        "RAG-FIRST",
    ]
    assert [
        row["sku"]
        for row in select_recommendation_candidates(
            rows,
            verifications,
            preserve_input_order=True,
        )
    ] == ["RAG-FIRST", "RAG-SECOND"]


def test_semantic_recommendation_verifies_people_and_heat_source_on_same_sku():
    question = "\u4e24\u4e2a\u4eba\u7528\uff0c\u5e76\u4e14\u652f\u6301\u9152\u7cbe\u7089"
    contract = build_semantic_recommendation_request_contract(
        question=question,
        semantic_constraints={"subject_kind": "cookware"},
        predicate_constraints=[
            {
                "field": "people",
                "operator": "=",
                "value": 2,
                "unit": "\u4eba",
                "evidence_span": "\u4e24\u4e2a\u4eba",
            },
            {
                "field": "heat_source",
                "operator": "supports",
                "value": "\u9152\u7cbe\u7089",
                "unit": "",
                "evidence_span": "\u652f\u6301\u9152\u7cbe\u7089",
            },
        ],
    )

    assert contract is not None
    assert "predicate:0:people" in contract.hard_constraints
    assert "predicate:1:heat_source" in contract.hard_constraints
    matched, wrong_source = verify_recommendation_candidates(
        contract,
        [
            _row("MATCH", target_audience="1-2\u4eba", heat_source="\u9152\u7cbe\u7089\u3001\u6c14\u7089"),
            _row("WRONG-SOURCE", target_audience="1-2\u4eba", heat_source="\u5361\u5f0f\u7089"),
        ],
    )

    assert matched.verification_level == "fully_verified"
    assert matched.evidence_by_constraint["predicate:1:heat_source"]["status"] == "verified"
    assert wrong_source.verification_level == "rejected"
    assert "heat_source_predicate_not_met" in wrong_source.rejection_reasons


def test_semantic_recommendation_accepts_flash_heat_source_ontology_value():
    question = "两个人用，并且支持酒精炉"
    contract = build_semantic_recommendation_request_contract(
        question=question,
        semantic_constraints={"subject_kind": "cookware"},
        predicate_constraints=[
            {
                "field": "heat_source",
                "operator": "supports",
                "value": "alcohol_stove",
                "unit": "",
                "evidence_span": "支持酒精炉",
            },
        ],
    )

    assert contract is not None
    assert contract.predicate_constraints[0]["value"] == "alcohol_stove"
    assert "predicate:0:heat_source" in contract.hard_constraints
    matched, wrong_source = verify_recommendation_candidates(
        contract,
        [
            _row("MATCH", heat_source="酒精炉、气炉"),
            _row("WRONG-SOURCE", heat_source="卡式炉"),
        ],
    )

    assert matched.evidence_by_constraint["predicate:0:heat_source"]["status"] == "verified"
    assert wrong_source.verification_level == "rejected"


def test_semantic_recommendation_binds_gas_stove_enum_to_natural_qi_stove_exclusion():
    question = "三个人露营想买锅，只要明确支持酒精炉的，不要气炉，推荐一款。"
    contract = build_semantic_recommendation_request_contract(
        question=question,
        semantic_constraints={"subject_kind": "cookware"},
        predicate_constraints=[
            {
                "field": "heat_source",
                "operator": "supports",
                "value": "alcohol_stove",
                "unit": "",
                "evidence_span": "明确支持酒精炉",
            },
            {
                "field": "heat_source",
                "operator": "not_supports",
                "value": "gas_stove",
                "unit": "",
                "evidence_span": "不要气炉",
            },
        ],
    )

    assert contract is not None
    assert [item["value"] for item in contract.predicate_constraints] == [
        "alcohol_stove",
        "gas_stove",
    ]
    matched, mixed_heat_sources, gas_only = verify_recommendation_candidates(
        contract,
        [
            _row("MATCH", heat_source="酒精炉"),
            _row("MIXED", heat_source="酒精炉\n气炉"),
            _row("GAS", heat_source="气炉"),
        ],
    )

    assert matched.verification_level == "fully_verified"
    assert mixed_heat_sources.verification_level == "rejected"
    assert gas_only.verification_level == "rejected"
    assert "predicate:1:heat_source" in mixed_heat_sources.conflicts


def test_semantic_recommendation_drops_predicate_whose_span_is_wrong_ontology():
    contract = build_semantic_recommendation_request_contract(
        question="两个人周末露营，主要烧水和煮面，帮我选一款锅。",
        semantic_constraints={"subject_kind": "cookware"},
        predicate_constraints=[
            {
                "field": "people",
                "operator": "=",
                "value": 2,
                "unit": "人",
                "evidence_span": "两个人",
            },
            {
                "field": "heat_source",
                "operator": "supports",
                "value": "户外炉具",
                "unit": "",
                "evidence_span": "露营",
            },
        ],
    )

    assert contract is not None
    assert [item["field"] for item in contract.predicate_constraints] == ["people"]
    assert "predicate:0:people" in contract.hard_constraints
    assert all("heat_source" not in item for item in contract.hard_constraints)


def test_semantic_recommendation_keeps_request_when_predicate_span_is_paraphrased():
    contract = build_semantic_recommendation_request_contract(
        question="两位同行周末露营，想挑一口适合煮面的锅。",
        semantic_constraints={
            "subject_kind": "cookware",
            "people": {"min": 2, "max": 2},
        },
        predicate_constraints=[
            {
                "field": "people",
                "operator": "=",
                "value": 2,
                "unit": "人",
                # This is a valid semantic paraphrase, but not a literal
                # substring of the current customer turn.
                "evidence_span": "两个人露营",
            },
        ],
    )

    assert contract is not None
    assert contract.people_min == 2
    assert contract.people_max == 2
    assert contract.predicate_constraints == []
    assert all("predicate:0:people" not in item for item in contract.hard_constraints)


def test_semantic_recommendation_does_not_promote_unanchored_heat_source_constraint():
    contract = build_semantic_recommendation_request_contract(
        question="两个人周末露营，主要烧水和煮面，帮我选一款锅。",
        semantic_constraints={"subject_kind": "cookware", "heat_sources": ["gas_stove"]},
        predicate_constraints=[
            {
                "field": "heat_source",
                "operator": "supports",
                "value": "燃气炉",
                "unit": "",
                "evidence_span": "烧水和煮面",
            },
        ],
    )

    assert contract is not None
    assert contract.heat_sources == []
    assert "heat_source" not in contract.hard_constraints
