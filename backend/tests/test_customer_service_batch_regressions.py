"""Grouped regressions found during the frozen three-platform HTTP audit.

These tests intentionally cover customer-visible contracts rather than HTTP
status codes.  The full corpus is rerun only after this batch of root-cause
fixes is complete.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import customer_agent_intent_service as intent_service
from app.services import customer_field_contract
from app.services import customer_recommendation_verification_contract as recommendation_contract
from app.services import customer_service_service as service
from app.internal.experience_layer import tone_shaping


def test_semantic_recommendation_product_query_persists_recommendation_context():
    sources = service._sources_with_result_context(
        {
            "intent": "query_products",
            "answer_type": "product_query",
            "answer": "适合酒精炉的锅具可以看看激川单锅（CW-S10-A）。",
            "results": [{"sku": "CW-S10-A", "product_name_cn": "激川单锅"}],
            "result_skus": ["CW-S10-A"],
            "candidate_skus": ["CW-S10-A"],
            "answer_metadata": {
                "source": "validated_semantic_preplan_then_same_sku_verification",
                "recommendation_contract": {
                    "subject_category": "锅具",
                    "heat_sources": ["酒精炉"],
                },
            },
            "debug": {"agent_mode": "semantic_recommendation_contract"},
        },
        user_question="适合酒精炉的锅具推荐一下。",
    )

    meta = next(item for item in sources if item.get("type") == "agent_meta")
    recommendation_context = meta.get("recommendation_context") or {}
    assert recommendation_context.get("recommended_skus") == ["CW-S10-A"]
    assert (recommendation_context.get("recommendation_request_contract") or {}).get("heat_sources") == ["酒精炉"]


def test_multi_category_scopes_cover_stove_and_griddle_selection():
    scopes = service._multi_category_recommendation_scopes(
        "\u9732\u8425\u70e7\u70e4\u573a\u666f\uff0c\u7089\u5177\u548c\u70e4\u76d8\u600e\u4e48\u642d\u66f4\u5408\u9002\uff1f"
    )

    assert scopes == [
        ("\u7089\u5177", "\u7089\u5177\u63a8\u8350\u4e00\u4e2a"),
        ("\u70e4\u76d8", "\u70e4\u76d8\u63a8\u8350\u4e00\u4e2a"),
    ]


def test_gifting_boundary_covers_quality_question_marketing_claims():
    question = "\u996d\u76d2\uff08\u9ed1\u8272\u76d6\u5b50+\u786c\u8d28\u6c27\u5316\u94dd\u8eab\uff09\u54c1\u8d28\u51fa\u4f17\u5417\uff1f"
    answer = "\u54c1\u8d28\u51fa\u4f17\uff0c\u5305\u88c5\u7cbe\u7f8e\uff0c\u9002\u5408\u4f5c\u4e3a\u793c\u7269\u3002"

    bounded = service._bound_gifting_qa_answer_to_evidence(question, answer)

    assert "\u54c1\u8d28\u51fa\u4f17" not in bounded
    assert "\u5305\u88c5\u7cbe\u7f8e" not in bounded
    assert "\u9002\u5408\u4f5c\u4e3a\u793c\u7269" not in bounded
    assert "\u54c1\u8d28" in bounded
    assert "\u672a\u76f4\u63a5\u6807\u6ce8" in bounded or "\u65e0\u6cd5\u786e\u8ba4" in bounded


@pytest.mark.parametrize(
    "question",
    [
        "\u8fd9\u4e2a\u996d\u76d2\u8d28\u91cf\u600e\u4e48\u6837\uff1f",
        "\u8fd9\u4e2a\u996d\u76d2\u505a\u5de5\u597d\u5417\uff1f",
    ],
)
def test_gifting_boundary_covers_quality_synonyms(question):
    bounded = service._bound_gifting_qa_answer_to_evidence(question, "\u54c1\u8d28\u51fa\u4f17\u3002")

    assert "\u54c1\u8d28\u51fa\u4f17" not in bounded
    assert "\u54c1\u8d28" in bounded
    assert "\u65e0\u6cd5\u786e\u8ba4" in bounded


def test_scenario_recommendation_recognizes_campsite_stove_and_griddle_pairing():
    question = "\u8425\u5730\u98ce\u6bd4\u8f83\u5927\uff0c\u6211\u60f3\u7ed9\u7089\u5b50\u914d\u4e00\u4e2a\u70e4\u76d8\uff0c\u54ea\u79cd\u642d\u914d\u66f4\u7a33\u59a5\uff1f"

    assert intent_service._looks_like_scenario_recommendation_question(question)
    assert intent_service._looks_like_recommendation_question(question)


def test_novice_simple_boiling_and_noodle_need_enters_cookware_recommendation():
    question = "\u6211\u4e0d\u592a\u4f1a\u7528\uff0c\u80fd\u4e0d\u80fd\u8bf4\u7b80\u5355\u70b9\uff1f\u6211\u4e3b\u8981\u5c31\u662f\u70e7\u6c34\uff0c\u5076\u5c14\u716e\u9762\u3002"

    assert intent_service._looks_like_recommendation_question(question)
    assert intent_service._looks_like_generic_core_cookware_recommendation(question)


def test_stove_and_griddle_pairing_uses_two_catalogue_scopes():
    question = "\u8425\u5730\u98ce\u6bd4\u8f83\u5927\uff0c\u6211\u60f3\u7ed9\u7089\u5b50\u914d\u4e00\u4e2a\u70e4\u76d8\uff0c\u54ea\u79cd\u642d\u914d\u66f4\u7a33\u59a5\uff1f"

    assert service._phase1_is_stove_griddle_combo_scenario(question)
    assert service._multi_category_recommendation_scopes(question) == [
        ("\u7089\u5177", "\u7089\u5177\u63a8\u8350\u4e00\u4e2a"),
        ("\u70e4\u76d8", "\u70e4\u76d8\u63a8\u8350\u4e00\u4e2a"),
    ]


def test_ordinal_followup_inherits_detail_scope_when_the_product_kind_is_omitted():
    detail_context = {
        "candidate_skus": ["STOVE-1", "PAN-1"],
        "ordered_result_skus": ["STOVE-1", "PAN-1"],
        "ordinal_reference_scope_skus": {
            "\u7089\u5177": ["STOVE-1", "STOVE-2"],
            "\u9505\u5177": ["PAN-1", "PAN-2", "PAN-3"],
        },
        "product_scope": "\u70e4\u76d8",
        "source": "result",
    }

    assert service._ordinal_followup_target_sku(
        "\u7b2c\u4e8c\u4e2a\u9002\u5408\u65b0\u624b\u6e05\u6d01\u5417\uff1f",
        None,
        detail_context,
    ) == "PAN-2"


def test_multi_category_child_timeout_falls_back_to_verified_catalogue_rows(monkeypatch):
    async def timed_out_child(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    catalogue_rows = [
        {
            "sku": "GAS-1",
            "product_name_cn": "\u9632\u98ce\u71c3\u6c14\u7089",
            "category": "\u7089\u5177",
            "sub_category": "\u71c3\u6c14\u7089",
            "heat_source": "\u71c3\u6c14\u7089",
            "features": "\u9632\u98ce\u3001\u7a33\u5b9a\u652f\u6491",
            "lifecycle_status": "",
        },
        {
            "sku": "GRIDDLE-1",
            "product_name_cn": "\u4fbf\u643a\u70e4\u76d8",
            "category": "\u9505\u5177",
            "sub_category": "\u70e4\u76d8",
            "heat_source": "\u71c3\u6c14\u7089",
            "features": "\u805a\u80fd\u590d\u5e95\u3001\u9632\u98ce\u7a33\u5b9a",
            "lifecycle_status": "",
        },
    ]
    monkeypatch.setattr(intent_service, "process_intent_request", timed_out_child)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda *_args: catalogue_rows)

    result = asyncio.run(service._multi_category_recommendation_result(
        None,
        user_id="test-user",
        question="\u8425\u5730\u98ce\u6bd4\u8f83\u5927\uff0c\u6211\u6709\u71c3\u6c14\u7089\uff0c\u60f3\u914d\u4e00\u4e2a\u70e4\u76d8\uff0c\u600e\u4e48\u642d\u66f4\u7a33\uff1f",
    ))

    assert result is not None
    assert result["result_skus"] == ["GAS-1", "GRIDDLE-1"]
    assert all(scope.get("fallback_reason") == "child_timeout" for scope in result["debug"]["scopes"])


def test_ordinal_detail_followup_preserves_parent_candidate_order():
    recommendation_sources = service._sources_with_result_context(
        {
            "intent": "query_products",
            "answer_type": "product_query",
            "answer": "\u70e4\u76d8\u5019\u9009\uff1aPAN-1\u3001PAN-2\u3001PAN-3",
            "result_skus": ["PAN-1", "PAN-2", "PAN-3"],
            "candidate_skus": ["PAN-1", "PAN-2", "PAN-3"],
            "results": [],
            "sources": [],
            "debug": {"agent_mode": "explicit_category_recommendation_guard"},
        },
        user_question="\u70e4\u76d8\u63a8\u8350\u4e00\u4e0b",
    )
    parent_context = next(item for item in recommendation_sources if item.get("type") == "agent_meta")["candidate_context"]
    detail_sources = service._sources_with_result_context(
        {
            "intent": "product_detail",
            "answer_type": "product_detail",
            "answer": "PAN-1 \u7684\u5c3a\u5bf8\u548c\u6750\u8d28\u5df2\u786e\u8ba4\u3002",
            "result_skus": ["PAN-1"],
            "candidate_skus": ["PAN-1"],
            "results": [],
            "sources": [],
            "debug": {},
        },
        user_question="\u7b2c\u4e00\u4e2a\u70e4\u76d8\u7684\u5c3a\u5bf8\u548c\u6750\u8d28\u662f\u4ec0\u4e48\uff1f",
        inherited_candidate_context=parent_context,
    )
    detail_context = next(item for item in detail_sources if item.get("type") == "agent_meta")["candidate_context"]

    assert detail_context["ordered_result_skus"] == ["PAN-1", "PAN-2", "PAN-3"]
    assert service._ordinal_followup_target_sku("\u7b2c\u4e8c\u4e2a\u9002\u5408\u65b0\u624b\u6e05\u6d01\u5417\uff1f", None, detail_context) == "PAN-2"


def test_ordinal_freeform_followup_binds_the_resolved_candidate_sku(monkeypatch):
    observed: dict[str, str] = {}

    async def named_shortcut(_db, *, user_id, question):
        observed["user_id"] = user_id
        observed["question"] = question
        return {
            "answer": "\u5f53\u524d\u8d44\u6599\u672a\u6807\u6ce8\u8be5\u5546\u54c1\u7684\u6e05\u6d17\u65b9\u6cd5\u3002\u8bf7\u63d0\u4f9b\u5177\u4f53\u578b\u53f7\u6216 SKU\uff0c\u5e76\u4f18\u5148\u6309\u5546\u54c1\u8bf4\u660e\u4e66\u64cd\u4f5c\u3002",
            "debug": {},
        }

    monkeypatch.setattr(service, "_try_named_product_shortcut", named_shortcut)
    result = asyncio.run(service._ordinal_freeform_followup_result(
        None,
        user_id="test-user",
        question="\u7b2c\u4e8c\u4e2a\u9002\u5408\u65b0\u624b\u6e05\u6d01\u5417\uff1f",
        resolved_sku="PAN-2",
    ))

    assert observed == {
        "user_id": "test-user",
        "question": "PAN-2 \u7b2c\u4e8c\u4e2a\u9002\u5408\u65b0\u624b\u6e05\u6d01\u5417\uff1f",
    }
    assert result["debug"]["identity_source"] == "recommendation_context_ordinal"
    assert result["debug"]["ordinal_target_sku"] == "PAN-2"
    assert "\u4f60\u5f53\u524d\u95ee\u7684\u662f PAN-2" in result["answer"]
    assert "\u8bf7\u63d0\u4f9b\u5177\u4f53\u578b\u53f7\u6216 SKU" not in result["answer"]


def test_many_verified_candidates_use_a_bounded_shortlist_when_soft_weight_is_missing(monkeypatch):
    rows = [
        {
            "sku": f"SAFE-GROUP-{index}",
            "product_name_cn": f"\u591a\u4eba\u9732\u8425\u9505\u5177{index}",
            "category": "\u9505\u5177",
            "target_audience": "3-4 \u4eba\u9732\u8425\u73a9\u5bb6",
            "usage_scenarios": "\u5468\u672b\u8fd1\u90ca\u9732\u8425\uff0c\u5bb6\u5ead\u6237\u5916\u70f9\u996a",
            "capacity": "3L",
            "gross_weight_g": None,
            "features": "\u5927\u5bb9\u91cf\u9505\u5177\u5957\u88c5",
        }
        for index in range(3)
    ]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "\u4e09\u53e3\u4e4b\u5bb6\u5468\u672b\u8fd1\u90ca\u9732\u8425\uff0c\u9505\u5177\u522b\u592a\u91cd\u4f46\u5bb9\u91cf\u522b\u592a\u5c0f\u3002",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.9,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "recommendation_soft_preferences": ["\u5bb9\u91cf\u522b\u592a\u5c0f"],
                "unrepresented_recommendation_requirements": [],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"]
    assert "\u91cd\u91cf" in result["answer"]


def test_boiling_is_a_cookware_use_goal_not_an_unrepresented_requirement(monkeypatch):
    rows = [{
        "sku": "SAFE-BOIL-1",
        "product_name_cn": "\u5355\u4eba\u8f7b\u91cf\u9505",
        "category": "\u9505\u5177",
        "target_audience": "1-2 \u4eba\u9732\u8425\u73a9\u5bb6",
        "usage_scenarios": "\u516c\u56ed\u9732\u8425\uff0c\u516c\u56ed\u91ce\u9910",
        "capacity": "1.7L",
        "gross_weight_g": 500,
        "features": "\u8f7b\u91cf\u4fbf\u643a",
    }]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def grounded_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["content.usage_scenarios", "specs.capacity", "specs.gross_weight_g"]}],
            "answer": "\u5982\u679c\u8981\u5728\u516c\u56ed\u9732\u8425\u70e7\u6c34\uff0c\u53ef\u4ee5\u5148\u770b\u5355\u4eba\u8f7b\u91cf\u9505\uff0c\u8d44\u6599\u6807\u6ce8\u5bb9\u91cf1.7L\u3001\u91cd\u91cf500g\u3002",
        }

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", grounded_narrative)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "\u5973\u751f\u4e00\u4e2a\u4eba\u516c\u56ed\u91ce\u9910\uff0c\u60f3\u8f7b\u4e00\u70b9\u53c8\u80fd\u70e7\u6c34\u7684\u708a\u5177\u3002",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.9,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 1, "max": 1},
                    "scenarios": ["camping"],
                    "weight_preference": "lightweight",
                },
                "recommendation_soft_preferences": [],
                "unrepresented_recommendation_requirements": ["\u70e7\u6c34"],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-BOIL-1"]


def test_stove_pairing_use_goals_do_not_block_verified_stove_recommendation(monkeypatch):
    rows = [{
        "sku": "SAFE-STOVE-PAIR-1",
        "product_name_cn": "露营稳定炉具",
        "category": "炉具",
        "usage_scenarios": "露营烧烤、热饮加热",
        "target_audience": "露营用户",
        "features": "支撑稳定，火力可调",
    }]
    monkeypatch.setattr(service.customer_agent_service, "search_products", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def grounded_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["scenario", "features"]}],
            "answer": "优先看露营稳定炉具（SAFE-STOVE-PAIR-1），适合烧烤和热饮加热。",
        }

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", grounded_narrative)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "露营烧烤加热饮都要兼顾，炉具怎么搭更稳？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.9,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "subject_text": "露营烧烤加热饮都要兼顾的炉具搭配",
                "recommendation_constraints": {
                    "subject_kind": "stove",
                    "scenarios": ["camping"],
                },
                "unrepresented_recommendation_requirements": ["烧烤", "加热饮"],
                "recommendation_soft_preferences": [],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["SAFE-STOVE-PAIR-1"]


def test_unresolved_page_subject_bounded_answers_preserve_the_customer_predicate():
    cases = [
        (
            "\u8fd9\u6b3e\u7089\u5b50\u9700\u8981\u624b\u52a8\u70b9\u706b\u5bf9\u5417?",
            "\u7231\u8def\u5ba2\u5c0f\u946b",
            ("\u7535\u5b50", "\u624b\u52a8"),
        ),
        (
            "\u7c98\u4e0d\u7c98\u9505?",
            "8\u5bf8\u714e\u9505",
            ("\u6d82\u5c42", "\u4e0d\u7c98"),
        ),
        (
            "\u80fd\u7528\u5361\u5f0f\u7089\u7684\u6c14\u7f50\u5417?",
            "\u5361\u5f0f\u7089",
            ("\u6c14\u7f50", "\u63a5\u53e3"),
        ),
        (
            "\u90a3\u4e2a\u9488\u5934\u6709\u6ca1\u6709\u5bf9\u51c6\u7089\u76d8\u7684\u51f9\u69fd?",
            "\u5c0f\u9752\u7089",
            ("\u5bf9\u51c6", "\u51f9\u69fd"),
        ),
    ]
    for question, subject, expected_terms in cases:
        answer = service._inline_page_subject_bounded_answer(question, subject)
        assert answer
        assert all(term in answer for term in expected_terms), answer


class _ProductRowsDB:
    """Minimal read-only DB double for page-title identity tests."""

    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return SimpleNamespace(all=lambda: list(self.rows))


def test_unbound_canister_fit_enters_bounded_usage_route_before_catalogue_search():
    question = "气罐能完美放到单锅里面吗？"

    assert service._looks_like_compatibility_usage_question(question)
    assert service._is_product_usage_care_question(question)


def test_page_terse_category_identity_accepts_deictic_yes_no_wording():
    assert service._looks_like_page_terse_category_identity_question(
        "\u90a3\u4e2a\u6c34\u58f6\u5417?",
        "CS-G25",
    )


def test_unbound_accessory_availability_accepts_separate_sale_wording():
    assert service._is_unbound_accessory_availability_question(
        "\u70b9\u706b\u5668\u8ddf\u7ba1\u7ebf\u6709\u5355\u72ec\u914d\u4ef6\u5356\u4e48?"
    )


def test_specific_cup_type_is_a_category_availability_question():
    assert service._looks_like_category_availability_question("\u6709\u6ca1\u6709\u516c\u9053\u676f?")


def test_missing_adapter_delivery_complaint_is_a_missing_component_question():
    question = (
        "\u4f60\u8bf4\u6211\u4e70\u4e2a\u7089\u5b50\u4f60\u6ca1\u6709\u8f6c\u6362\u5934\u600e\u4e48\u6574\uff0c"
        "\u8fd9\u7089\u5b50\u4e2a\u8f6c\u5934\u8fd8\u4e0d\u662f\u4e00\u8d77\u5230\u7684\uff0c\u4f60\u7ed9\u6211\u5019\u8865\u7684\u5b8c\u4e86\uff0c"
        "\u73b0\u5728\u7528\u4e0d\u4e86\uff0c\u6211\u6ca1\u6709\u8f6c\u5411\u5934\u505a\u996d\u90fd\u505a\u4e0d\u4e86\u3002"
    )

    assert service._looks_like_missing_component_question(question)


def test_unbound_cause_and_cleaning_compound_keeps_both_requests():
    assert service._looks_like_unbound_cause_and_cleaning_question(
        "\u8fd9\u662f\u9152\u7cbe\u7684\u95ee\u9898\u4e48?\u8fd9\u79cd\u6750\u8d28\u5e94\u8be5\u600e\u4e48\u6e05\u6d17\u5e72\u51c0?"
    )


def test_two_lost_storage_bags_are_a_multi_product_replacement_request():
    assert service._looks_like_multi_product_replacement_accessory_question(
        "\u6211\u7684\u70e7\u6c34\u58f6\u548c\u9152\u7cbe\u7089\u7684\u6536\u7eb3\u888b\u4e22\u4e86\uff0c\u9152\u7cbe\u7089\u662fB02\uff0c\u70e7\u6c34\u58f6\u662f1.4L\u7684\u3002\u600e\u4e48\u4e70?"
    )
    assert not service._looks_like_multi_product_replacement_accessory_question(
        "\u6211\u7684\u9152\u7cbe\u7089\u6536\u7eb3\u888b\u4e22\u4e86\uff0c\u600e\u4e48\u4e70?"
    )


def test_alcohol_and_gas_stove_availability_is_a_mixed_catalogue_question():
    assert service._looks_like_mixed_stove_fuel_catalogue_question(
        "\u4f60\u8fd9\u7089\u5b50\u91cc\u5230\u5e95\u90fd\u5305\u62ec\u5565\u5440?\u6709\u9152\u7cbe\u7089\u548c\u74e6\u65af\u7089\u5417?"
    )


def test_constrained_semantic_recommendation_verifies_category_rows_missed_by_subject_recall(monkeypatch):
    narrow_recall = [{
        "sku": "RECALL-NO-MATCH",
        "product_name_cn": "普通露营锅",
        "category": "锅具",
        "heat_source": "卡式炉",
        "usage_scenarios": "露营",
    }]
    category_rows = [{
        "sku": "CATEGORY-ALCOHOL-MATCH",
        "product_name_cn": "轻量露营单锅",
        "category": "锅具",
        "heat_source": "酒精炉",
        "usage_scenarios": "双人露营",
    }]

    monkeypatch.setattr(service.customer_agent_service, "search_products", lambda *_args, **_kwargs: narrow_recall)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, ref: category_rows if ref == "锅具" else [])

    async def grounded_narrative(_db, *, rows, **_kwargs):
        assert [row["sku"] for row in rows] == ["CATEGORY-ALCOHOL-MATCH"]
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["scenario", "heat_source"]}],
            "answer": "轻量露营单锅有同 SKU 的酒精炉和露营场景证据。",
        }

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", grounded_narrative)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "露营用，能配酒精炉的锅具有哪些？",
        {"semantic_preplan": {
            "called": True,
            "route_family": "recommendation",
            "confidence": 0.9,
            "confidence_label": "high",
            "fallback_reason": "",
            "ambiguity": False,
            "subject_text": "露营用，能配酒精炉的锅具",
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "heat_sources": ["alcohol_stove"],
                "scenarios": ["camping"],
            },
            "unrepresented_recommendation_requirements": [],
            "recommendation_soft_preferences": [],
        }},
    ))

    assert result["result_skus"] == ["CATEGORY-ALCOHOL-MATCH"], result


def test_deterministic_mixed_stove_catalogue_keeps_its_verified_cards(monkeypatch):
    rows = [{
        "sku": "ALCOHOL-STOVE",
        "product_name_cn": "酒精炉",
        "category": "炉具",
        "heat_source": "液体酒精",
        "lifecycle_status": "常规品",
    }]
    rows.extend({
        "sku": f"GAS-STOVE-{index}",
        "product_name_cn": f"燃气炉{index}",
        "category": "炉具",
        "heat_source": "高山气罐",
        "lifecycle_status": "常规品",
    } for index in range(1, 6))
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, ref: rows if ref == "炉具" else [])

    question = "你这炉子里到底都包括啥呀?有酒精炉和瓦斯炉吗?"
    result = service._mixed_stove_fuel_catalogue_result(None, question)
    assert result is not None
    assert len(result["result_skus"]) == 6

    cleaned = service._clear_unrelated_catalogue_cards(question, result)

    assert cleaned["result_skus"] == [row["sku"] for row in rows]
    assert cleaned["results"] == rows
    assert not cleaned["debug"].get("catalogue_cards_cleared")


def test_recommendation_followup_is_not_treated_as_a_competing_page_product():
    question = "还有别的品牌推荐吗？"

    assert service._explicit_page_subject_from_question(question) == ""
    assert not service._explicit_page_subject_conflicts_with_anchor(
        question,
        page_product_name="小青炉",
    )


def test_compound_question_punctuation_does_not_create_a_phantom_product_subject():
    question = "这个是酒精的问题么？这种材质应该怎么清洗干净？"

    assert service._explicit_page_subject_from_question(question) == ""


def test_short_nonstick_question_uses_surface_field_not_usage_care():
    question = "锅是不粘锅吗？"
    contract = customer_field_contract.detect_field_contract(question)

    assert contract is not None
    assert contract.field_type == "surface_finish"
    assert service._looks_like_material_or_surface_detail_question(question)
    assert not service._is_product_usage_care_question(question)


def test_ignition_capability_question_uses_detail_contract_not_generic_usage_template():
    for question in ("没有电子点火是吗？", "这个不是远程点火的？"):
        contract = customer_field_contract.detect_field_contract(question)
        assert contract is not None
        assert contract.field_type == "usage_instruction"
        assert not service._is_product_usage_care_question(question)


def test_alcohol_finished_question_answers_fuel_handling_not_cleaning_template():
    answer = intent_service._compose_safety_usage_care_answer("我说的是酒精用完了怎么办？")

    assert "补充" in answer or "更换" in answer or "燃料" in answer
    assert "安全建议：户外使用炉具" not in answer


def test_fuel_holder_dimension_question_does_not_name_a_truncated_subject():
    question = "看不见装酒精、木炭的地方尺寸是多少？"

    assert service._explicit_page_subject_from_question(question) == ""
    assert customer_field_contract.requested_evidence_scope(question, "dimensions") == "component"
    assert customer_field_contract.requested_dimension_subtype(question) == "fuel_holder"


def test_exact_no_match_availability_answer_drops_alternative_catalogue_cards():
    question = "有没有公道杯？"
    result = {
        "answer_type": "product_query",
        "answer": (
            "目前在资料中暂未查到‘公道杯’。现有杯具是户外直饮杯或套装，"
            "没有出现名称或功能为‘公道杯’的产品。"
        ),
        "result_skus": ["TW-404-11", "TW-404-21", "TW-502"],
        "candidate_skus": ["TW-404-11", "TW-404-21", "TW-502"],
        "results": [{"sku": sku, "product_name_cn": "户外杯"} for sku in ("TW-404-11", "TW-404-21", "TW-502")],
        "sources": [{"sku": sku} for sku in ("TW-404-11", "TW-404-21", "TW-502")],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == []
    assert shaped["candidate_skus"] == []
    assert shaped["results"] == []
    assert shaped["sources"] == []


def test_page_nonstick_question_returns_same_sku_surface_conclusion(monkeypatch):
    product = SimpleNamespace(product_name_cn="小青炉", product_name_en="", sku="CS-G25")
    specs = SimpleNamespace(surface_finish="硬质氧化", body_material="硬质氧化铝")
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (product, specs, None, None),
    )

    result = service._semantic_outage_page_bounded_result(
        object(), "锅是不粘锅吗？", "CS-G25", {},
    )

    assert result is not None
    assert "不粘" in result["answer"]
    assert "硬质氧化" in result["answer"]
    assert "CS-G25" in result["answer"]


def test_page_nonstick_question_calls_out_page_category_when_anchor_is_not_cookware(monkeypatch):
    product = SimpleNamespace(product_name_cn="小青炉", product_name_en="", sku="CS-G25", category="炉具")
    specs = SimpleNamespace(surface_finish="硬质氧化", body_material="硬质氧化铝")
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (product, specs, None, None),
    )

    result = service._semantic_outage_page_bounded_result(
        object(), "锅是不粘锅吗？", "CS-G25", {},
    )

    assert result is not None
    assert "不是锅具" in result["answer"]
    assert "不能确认是不粘锅" in result["answer"]


def test_page_ignition_capability_question_answers_capability_not_steps(monkeypatch):
    product = SimpleNamespace(product_name_cn="小青炉", product_name_en="", sku="CS-G25")
    specs = SimpleNamespace(
        usage_instruction="按击点火装置，直到发出啪的声音。",
        surface_finish="硬质氧化",
        body_material="硬质氧化铝",
    )
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (product, specs, None, None),
    )

    result = service._semantic_outage_page_bounded_result(
        object(), "没有电子点火是吗？", "CS-G25", {},
    )

    assert result is not None
    assert "电子点火" in result["answer"]
    assert "按击点火装置" in result["answer"]
    assert "使用方法" not in result["answer"]


def test_page_formal_field_defers_ignition_and_component_dimensions_to_bounded_adapter():
    assert service._page_formal_field_should_defer_to_bounded_adapter(
        "没有电子点火是吗？", "usage_instruction",
    )
    assert service._page_formal_field_should_defer_to_bounded_adapter(
        "看不见装酒精、木炭的地方尺寸是多少？", "dimensions",
    )
    assert not service._page_formal_field_should_defer_to_bounded_adapter(
        "这款炉具怎么使用？", "usage_instruction",
    )


def test_fuel_replenishment_route_preempts_unrelated_cleaning_retrieval(monkeypatch):
    async def fail_if_retrieved(*_args, **_kwargs):
        raise AssertionError("fuel replenishment must not search cleaning QA first")

    monkeypatch.setattr(intent_service, "_search_usage_care_qa", fail_if_retrieved)
    result = asyncio.run(
        intent_service.answer_product_usage_care_request(
            object(),
            question="我说的是酒精用完了怎么办？",
            named_products=[SimpleNamespace(sku="CS-B14")],
        )
    )

    assert "燃料补充" in result["answer"]
    assert "清洁方法" not in result["answer"]
    assert result["results"] == []


def test_compound_alcohol_cause_question_has_explicit_same_sku_boundary():
    answer = service._compose_alcohol_cause_boundary_answer("这个是酒精的问题么？这种材质应该怎么清洗干净？")

    assert answer
    assert "酒精" in answer
    assert "当前同 SKU 资料未标注" in answer
    assert "不能仅凭材质判断" in answer


def test_dimension_missing_label_keeps_fuel_holder_scope():
    assert service._dimension_missing_display_label("fuel_holder", "尺寸") == "装酒精/木炭的燃料仓尺寸"


def test_page_recommendation_clarification_keeps_current_category_context():
    answer = service._page_context_recommendation_clarification_answer(
        page_name="小青炉", page_sku="CS-G25", category="炉具",
    )

    assert "小青炉" in answer
    assert "CS-G25" in answer
    assert "同类炉具" in answer


def test_page_recommendation_reports_when_catalogue_has_no_other_brand():
    answer = service._page_context_recommendation_clarification_answer(
        page_name="小青炉",
        page_sku="CS-G25",
        category="炉具",
        page_brand="alocs爱路客",
        other_brand_labels=[],
    )

    assert "暂未找到其他品牌" in answer
    assert "小青炉" in answer
    assert "同类炉具" in answer


def test_canister_quantity_question_does_not_use_connection_template():
    answer = intent_service._compose_safety_usage_care_answer("带几个气罐?")

    assert "连接前先确认" not in answer
    assert "未标注" in answer or "无法确认" in answer
    assert "随附" in answer or "数量" in answer or "包装" in answer


def test_vehicle_canister_storage_question_answers_storage_directly():
    answer = intent_service._compose_safety_usage_care_answer("气罐放后备箱安全吗?")

    assert "连接前先确认" not in answer
    assert "车内" in answer or "后备箱" in answer or "阴凉通风" in answer
    assert "存放" in answer or "放置" in answer


def test_alcohol_storage_question_does_not_fall_back_to_gas_canister_text():
    answer = intent_service._compose_safety_usage_care_answer("高浓度的酒精没用完怎么存放?")

    assert "酒精" in answer
    assert "气罐应放" not in answer
    assert "气罐说明书" not in answer


def test_compact_product_dump_is_removed_from_customer_answer():
    answer = service._sanitize_final_answer_text(
        "产品资料：内容信息:-中文标题:测试炉-英文标题:Test Stove-中文描述:内部描述\n"
        "处理建议：请按说明书确认。",
        {},
    )

    for internal_label in ("产品资料", "内容信息", "中文标题", "英文标题", "中文描述"):
        assert internal_label not in answer
    assert "处理建议" in answer


def test_bare_field_suffix_is_customer_facing_information():
    answer = service._sanitize_final_answer_text(
        "依据：热源字段显示为高山气罐。容量字段未标注。",
        {},
    )

    assert "字段" not in answer
    assert "热源信息" in answer
    assert "容量信息" in answer


def test_unique_page_title_containment_uses_catalogue_identity_without_sku_rule():
    db = _ProductRowsDB([
        SimpleNamespace(sku="CW-C84", product_name_cn="鸣泉水壶", product_name_en=""),
        SimpleNamespace(sku="CW-C83", product_name_cn="炊墨套锅", product_name_en=""),
    ])

    assert service._resolve_exact_page_subject_sku(db, "鸣泉") == "CW-C84"


def test_generic_preface_is_not_treated_as_an_explicit_product_subject():
    assert service._explicit_page_subject_from_question("炉具收到了，问一下这个材质是什么材质?") == ""
    assert service._explicit_page_subject_from_question("你好，内部尺寸直径多少?") == ""


def test_structured_query_and_owner_metadata_are_not_customer_visible():
    answer = service._sanitize_final_answer_text(
        "当前结构化商品库未找到符合条件的商品。查询类目：【炉具】；筛选条件：支持酒精炉。"
        "如果需要购买，或者联系负责人 Greta 确认库存。",
        {},
    )

    for internal_phrase in ("结构化商品库", "查询类目", "筛选条件", "负责人", "Greta"):
        assert internal_phrase not in answer
    assert "没有找到" in answer or "未找到" in answer or "当前资料" in answer
    assert "店铺客服" in answer or "客服" in answer


def test_usage_policy_noise_is_not_rendered_as_sticking_answer():
    answer = intent_service._compose_usage_care_answer(
        "煎锅炒菜粘锅吗?",
        [{
            "answer": "涉及涂层、热效率、省气等风险点；必须以检测报告、测试视频和客服FAQ为准；必须严格使用替代表达。",
        }],
        [],
        response_style="usage_guidance",
    )

    for internal_phrase in ("检测报告", "客服FAQ", "必须严格使用替代表达", "风险点"):
        assert internal_phrase not in answer
    assert "当前资料未标注" in answer or "清洁方法" in answer or "注意事项" in answer


def test_usage_care_no_hit_is_customer_facing():
    answer = intent_service._compose_usage_care_answer(
        "怎么保养壶?",
        [],
        [],
        response_style="usage_guidance",
    )

    assert "系统暂未配置" not in answer
    assert "当前资料未标注" in answer or "无法确认" in answer


def test_semantic_outage_clarification_does_not_expose_internal_service_state():
    result = service._semantic_preplan_unavailable_clarification_result(
        {"called": True, "fallback_reason": "llm_error: timeout"},
        question="推荐一个轻量锅",
    )

    assert result is not None
    assert "语义理解服务暂时不可用" not in result["answer"]
    assert "请" in result["answer"]


def test_installation_followup_with_card_slot_routes_to_installation():
    assert intent_service._detect_usage_care_subtype("燃气炉怎么卡进去的?有视频或者图片吗?") == "installation"


def test_alcohol_stove_fire_failure_does_not_assume_gas_canister():
    answer = intent_service._compose_safety_usage_care_answer("酒精炉怎么点不着?")

    assert "气罐连接" not in answer
    assert "酒精" in answer or "燃料" in answer
    assert "点火" in answer or "通风" in answer


def test_canister_storage_inside_cookware_is_not_connection_guidance():
    answer = intent_service._compose_safety_usage_care_answer("套锅里能装下230克气罐么?")

    assert "连接前先确认" not in answer
    assert "收纳" in answer or "尺寸" in answer or "无法确认" in answer


def test_unbound_canister_fit_question_does_not_leak_unrelated_catalogue_answer():
    question = "里面的气罐都可以用吗？"

    # The phrase contains “里面”, but the predicate asks compatibility.  It
    # must stay on the compatibility safety boundary instead of being treated
    # as a package-composition lookup that can surface unrelated SKU prose.
    assert intent_service._detect_usage_care_subtype(question) == "safety"
    assert intent_service._looks_like_canister_compatibility_question(question)


def test_fuel_predicate_accepts_natural_de_question_form():
    contract = intent_service.customer_field_contract.detect_field_contract(
        "这炉子是烧液体酒精的吗？"
    )

    assert contract is not None
    assert contract.field_type == "heat_source"


def test_usage_predicate_accepts_placement_wording():
    contract = intent_service.customer_field_contract.detect_field_contract(
        "炉头怎么放炉子里啊？"
    )

    assert contract is not None
    assert contract.field_type == "usage_instruction"


def test_explicit_solid_alcohol_requires_solid_alcohol_evidence():
    contract = recommendation_contract.build_recommendation_request_contract(
        "推荐一个支持固体酒精的酒精炉"
    )
    generic = {
        "sku": "GENERIC",
        "product_name_cn": "通用酒精炉",
        "category": "炉具",
        "heat_source": "酒精炉",
    }
    solid = {
        "sku": "SOLID",
        "product_name_cn": "固体酒精炉",
        "category": "炉具",
        "heat_source": "固体酒精",
    }

    results = recommendation_contract.verify_recommendation_candidates(contract, [generic, solid])

    assert getattr(contract, "fuel_subtype", None) == "固体酒精"
    assert results[0].verification_level == "rejected"
    assert results[1].hard_constraints_passed is True


def test_page_canister_storage_guard_covers_vehicle_and_nested_storage():
    assert service._looks_like_page_gas_canister_storage_question(
        "气罐放后备箱安全吗?", "CW-C84"
    )
    assert service._looks_like_page_gas_canister_storage_question(
        "套锅里能装下230克气罐么?", "CW-C83"
    )
    result = service._build_page_accessory_scope_clarification(
        request_sku_anchor="CW-C84",
        question="气罐放后备箱安全吗?",
        kind="gas_storage",
    )
    assert "后备箱" in result["answer"]
    assert "连接前先确认" not in result["answer"]


def test_alcohol_fire_failure_has_usage_precedence_over_heat_source_field():
    question = "酒精炉怎么点不着?"

    assert intent_service._looks_like_usage_care_question(question)
    assert service._is_product_usage_care_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "safety"


def test_unbound_solid_alcohol_compatibility_is_usage_not_heat_source_listing():
    question = "固体酒精能用吗?"

    assert intent_service._looks_like_usage_care_question(question)
    assert service._is_product_usage_care_question(question)
    assert not service._looks_like_recommendation_request(question)


def test_bundle_query_is_recognized_as_catalogue_scope():
    question = "有没有水壶和酒精炉套餐?"

    assert service._is_explicit_broad_catalogue_request(question)


def test_bundle_result_cards_follow_skus_named_in_answer():
    question = "有没有水壶和酒精炉套餐?"
    result = {
        "answer_type": "product_query",
        "answer": "有，时光煮水户外水壶套装（SKU: CW-K04PRO-37）。",
        "result_skus": ["CW-K04PRO-37", "CW-C84", "CW-C99A", "CW-K02-37", "CW-C65-3"],
        "candidate_skus": ["CW-K04PRO-37", "CW-C84", "CW-C99A", "CW-K02-37", "CW-C65-3"],
        "results": [
            {"sku": "CW-K04PRO-37"}, {"sku": "CW-C84"}, {"sku": "CW-C99A"},
            {"sku": "CW-K02-37"}, {"sku": "CW-C65-3"},
        ],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == ["CW-K04PRO-37"]
    assert shaped["candidate_skus"] == ["CW-K04PRO-37"]
    assert [row["sku"] for row in shaped["results"]] == ["CW-K04PRO-37"]


def test_customer_answer_replaces_provenance_phrase():
    answer = service._sanitize_final_answer_text(
        "有，时光煮水户外水壶套装（CW-K04PRO-37）。依据产品资料，该类目明确标注为水壶、酒精炉。",
        {},
    )

    assert "依据产品资料" not in answer
    assert "已核对信息" in answer


def test_customer_answer_removes_internal_owner_sentence():
    answer = service._sanitize_final_answer_text(
        "套装包含水壶和酒精炉。负责人是 Greta。",
        {},
    )

    assert "负责人" not in answer
    assert "水壶和酒精炉" in answer


def test_stainless_grade_or_requirement_is_verified_against_same_sku_material():
    contract = recommendation_contract.build_recommendation_request_contract("有没有304或者316的锅?")
    rows = [
        {"sku": "P304", "category": "锅具", "product_name_cn": "304锅", "body_material": "304不锈钢"},
        {"sku": "P430", "category": "锅具", "product_name_cn": "430锅", "body_material": "430不锈钢"},
    ]

    results = recommendation_contract.verify_recommendation_candidates(contract, rows)

    assert contract.materials == ["304不锈钢或316不锈钢"]
    assert results[0].hard_constraints_passed is True
    assert results[1].verification_level == "rejected"


def test_page_pairing_question_does_not_expand_to_unrelated_catalogue(monkeypatch):
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (None, None, None, None),
    )
    result = service._semantic_outage_page_bounded_result(
        object(),
        "这个炉子能配哪个烧水壶?",
        "CW-C84",
        {},
    )

    assert result is not None
    assert result["result_skus"] == []
    assert "配套" in result["answer"] or "兼容" in result["answer"]


def test_page_pairing_and_canister_availability_are_bounded(monkeypatch):
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (None, None, None, None),
    )
    pairing = service._semantic_outage_page_bounded_result(
        object(),
        "推荐一下配套的炉具?",
        "CW-C84",
        {},
    )
    availability = service._semantic_outage_page_bounded_result(
        object(),
        "气罐有吗?",
        "CS-G25",
        {},
    )

    assert pairing and pairing["result_skus"] == []
    assert availability and availability["result_skus"] == []
    assert "配套" in pairing["answer"] or "兼容" in pairing["answer"]
    assert "气罐" in availability["answer"]


def test_page_material_missing_component_and_multi_burner_are_bounded(monkeypatch):
    monkeypatch.setattr(
        service,
        "_phase1_product_bundle_by_ref",
        lambda *args, **kwargs: (None, None, None, None),
    )
    material = service._semantic_outage_page_bounded_result(
        object(),
        "材质是什么?涂层是什么?",
        "CS-G25",
        {},
    )
    missing = service._semantic_outage_page_bounded_result(
        object(),
        "安排一个杯子怎么没收到?",
        "CS-G25",
        {},
    )
    split = service._semantic_outage_page_bounded_result(
        object(),
        "一个罐可以分体几个炉?",
        "CS-G25",
        {},
    )

    assert material and material["result_skus"] == ["CS-G25"]
    assert "材质" in material["answer"] and "涂层" in material["answer"]
    assert missing and missing["result_skus"] == []
    assert "包装清单" in missing["answer"] or "组件" in missing["answer"]
    assert split and split["result_skus"] == []
    assert "多个炉头" in split["answer"] or "分体炉" in split["answer"]


def test_unbound_history_and_pairing_guards_require_identity():
    assert service._looks_like_unbound_historical_fuel_question(
        "我上次买的炉您是说用工业酒精才能发挥最大效果吧?"
    )
    assert service._looks_like_unbound_pairing_identity_question(
        "以前在淘宝上面买的，有没有配套的气炉?"
    )


def test_page_material_and_coating_fact_is_not_usage_care_priority():
    assert service._looks_like_material_or_surface_detail_question(
        "材质是什么材质?锅里的涂层是什么涂层?"
    )
    assert not service._looks_like_material_or_surface_detail_question(
        "涂层掉了怎么处理?"
    )


def test_catalogue_cards_align_to_skus_named_by_broad_answer():
    result = {
        "answer_type": "product_query",
        "answer": "目前列出 5 款：小青炉（CS-G25）、魔盒卡式炉（KD23-MFL）、ATRAX 黑蜘蛛分体炉（CS-G18-28）。",
        "result_skus": ["CS-G25", "KD23-MFL", "CS-G18-28", "CS-G26HM", "CS-G34", "CS-G35"],
        "candidate_skus": ["CS-G25", "KD23-MFL", "CS-G18-28", "CS-G26HM", "CS-G34", "CS-G35"],
        "results": [{"sku": sku} for sku in ["CS-G25", "KD23-MFL", "CS-G18-28", "CS-G26HM", "CS-G34", "CS-G35"]],
    }

    shaped = service._clear_unrelated_catalogue_cards("炉子?", result)

    assert shaped["result_skus"] == ["CS-G25", "KD23-MFL", "CS-G18-28"]
    assert [row["sku"] for row in shaped["results"]] == shaped["result_skus"]


def test_unresolved_entity_clarification_does_not_echo_truncated_question_fragments():
    bad_fragments = [
        ("因为我之前买的最高", "因为我之前买的最高功率4000w火锅肉都没怎么熟?"),
        ("是用", "是用明火点的嘛?"),
        ("这开门是调节", "这开门是调节火力?"),
        ("带炉子吗，炉子", "带炉子吗，炉子多少瓦桌子腿可以调节吗正品吗?"),
        ("是多大的炉子还", "是多大的炉子还是多大的盘?"),
        ("炉子咋这么小，固体酒精买", "炉子咋这么小，固体酒精买多大的能放进去?"),
    ]

    for entity_text, question in bad_fragments:
        assert service._safe_customer_entity_text(entity_text, question) is None


def test_unresolved_entity_clarification_keeps_explicit_sku_reference():
    assert service._safe_customer_entity_text("TW-422-紫", "TW-422-紫是什么材质？") == "TW-422-紫"


def test_speculative_unbound_answer_clears_broad_cards():
    result = {
        "answer_type": "chat",
        "answer": "目前没有找到风暴炉，可能是驭风防风炉；这只是推测，请提供具体型号。",
        "result_skus": [f"CS-G{i}" for i in range(1, 10)],
        "candidate_skus": [f"CS-G{i}" for i in range(1, 10)],
        "results": [{"sku": f"CS-G{i}"} for i in range(1, 10)],
    }

    shaped = service._clear_unrelated_catalogue_cards("风暴炉是哪个?", result)

    assert shaped["result_skus"] == []
    assert shaped["results"] == []


def test_unbound_quality_accessory_question_gets_identity_and_scope_boundary():
    question = "在你们家买的炉子，支架用了一次后就变形了，材质有点软，有其他质量更好的配件吗?"

    assert service._looks_like_unbound_quality_accessory_question(question)


def test_ignition_device_capability_is_not_ignition_failure():
    question = "这款带点火装置吗?"

    assert not intent_service._looks_like_usage_care_question(question)


def test_page_anchor_allows_deictic_feature_question_to_reach_page_contract():
    question = "这个炉子会挡风吗?"

    # An explicit API page SKU is already an identity anchor; the generic
    # deictic guard must not discard it before the same-page contract runs.
    assert service._looks_like_page_gas_canister_storage_question(question, "CW-C84") is False


def test_purchase_channel_detection_does_not_capture_fuel_or_product_buying_questions():
    assert not service._looks_like_purchase_channel_question("燃料酒精怎么理解?随处能买到?跟医用酒精不一样?")
    assert not service._looks_like_purchase_channel_question("杯子怎么买?")
    assert service._looks_like_purchase_channel_question("这个商品的购买渠道是什么?")


def test_general_fuel_definition_question_stays_usage_guidance():
    question = "燃料酒精怎么理解?随处能买到?跟医用酒精不一样?"

    assert intent_service._looks_like_general_fuel_definition_question(question)
    assert intent_service._looks_like_usage_care_question(question)


def test_underspecified_product_purchase_question_does_not_guess_catalogue_item():
    assert service._looks_like_unbound_product_purchase_question("杯子怎么买?")
    assert not service._looks_like_unbound_product_purchase_question("套锅哪里可以买到？")
    assert not service._looks_like_unbound_product_purchase_question("有没有推荐的卡式炉?")


def test_plain_category_recommendation_has_a_deterministic_scope():
    assert service._looks_like_unconstrained_category_recommendation_question("有没有炉头推荐?")
    assert service._looks_like_unconstrained_category_recommendation_question("有没有推荐的卡式炉?")
    assert not service._looks_like_unconstrained_category_recommendation_question("两个人徒步有没有炉具推荐?")


def test_customer_answer_sanitizes_backend_provenance_words():
    answer = service._sanitize_final_answer_text(
        "当前按数据库商品类目字段在【炉具】里筛到 3 款。当前知识库没有维护该字段。系统里记录的销售渠道包括：淘宝。",
        {},
    )

    assert "数据库" not in answer
    assert "知识库" not in answer
    assert "字段" not in answer
    assert "系统里记录" not in answer
    assert "商品目录" in answer or "当前资料" in answer


def test_customer_answer_converts_stringified_list_values_to_prose():
    answer = service._sanitize_final_answer_text(
        "特点：[\"轻量\", \"防风\"]；场景：['露营', '徒步']。",
        {},
    )

    assert "[" not in answer
    assert "轻量、防风" in answer
    assert "露营、徒步" in answer


def test_bundle_heat_source_question_does_not_accept_plain_cookware_sets():
    assert service._looks_like_bundle_heat_source_question("你好，有没有带炉的套装?")
    assert not service._looks_like_bundle_heat_source_question("有没有户外套装?")


def test_product_query_recommendation_gets_a_decision_lead():
    answer = service._shape_product_query_output(
        "小青炉，支持高山气罐；魔盒卡式炉，适合桌面露营。",
        [
            {"sku": "CS-G25", "product_name_cn": "小青炉", "category": "炉具", "features": "3200W"},
            {"sku": "KD23-MFL", "product_name_cn": "魔盒卡式炉", "category": "炉具", "features": "桌面露营"},
        ],
        ["CS-G25", "KD23-MFL"],
        question="有没有炉头推荐?",
    )

    assert "更推荐" in answer or "优先推荐" in answer


def test_unbound_installation_support_requires_identity():
    assert service._looks_like_unbound_installation_support_question(
        "我的雪炉中间小孔太小，无法把燃气头拧上去，请问是哪里操作不当?"
    )


def test_page_bundle_browse_is_not_replaced_by_page_field_guard():
    assert service._looks_like_bundle_heat_source_question(
        "有没有带炉的套装?（当前商品：小青炉）"
    )
    assert service._looks_like_bundle_heat_source_question(
        "有没有带炉的套装?"
    )


def test_product_noun_alone_is_not_usage_care_intent():
    assert not service._is_product_usage_care_question("是一个炉头？")
    assert not service._is_product_usage_care_question("包含酒精吗？")
    assert service._is_product_usage_care_question("这个炉子怎么使用？")


def test_clarification_tone_does_not_expose_internal_direction_template():
    answer = tone_shaping.soften_clarify_answer("请告诉我具体商品名或 SKU，我再继续核对这款商品。")

    assert "先给你一个方向" not in answer
    assert "请告诉我具体商品名或 SKU" in answer


def test_page_identity_conflict_is_language_level_not_sku_specific():
    assert service._explicit_page_subject_conflicts_with_anchor(
        "围雪炉支持远程打火吗？",
        page_product_name="小青炉",
    )
    assert not service._explicit_page_subject_conflicts_with_anchor(
        "小青炉支持远程打火吗？",
        page_product_name="小青炉",
    )
    assert not service._explicit_page_subject_conflicts_with_anchor(
        "这个用什么燃料？",
        page_product_name="小青炉",
    )


def test_generic_fuel_field_wording_uses_bounded_fuel_conclusion():
    question = "这个用什么燃料？"

    assert intent_service._looks_like_fuel_compatibility_usage_question(question)
    answer = intent_service._compose_safety_usage_care_answer(question)
    assert "燃料结论" in answer
    assert "安全建议" not in answer


def test_colloquial_fuel_predicates_resolve_to_heat_source_field():
    for question in ("还有燃料是啥？", "燃料是什么？", "烧什么燃料？"):
        contract = intent_service.customer_field_contract.detect_field_contract(question)
        assert contract is not None, question
        assert contract.field_type == "heat_source", question

    assert intent_service.customer_field_contract.detect_field_contract("燃料") is None


def test_generic_alcohol_choice_wording_is_fuel_compatibility_intent():
    question = "这个用什么酒精？"

    assert intent_service._looks_like_fuel_compatibility_usage_question(question)


def test_alcohol_purchase_wording_stays_general_fuel_guidance():
    question = "酒精从哪里买，买什么样的？"

    assert intent_service._looks_like_general_fuel_definition_question(question)
    assert service._is_product_usage_care_question(question)


def test_generic_alcohol_recommendation_wording_is_fuel_guidance_not_stove_selection():
    for question in ("酒精推荐什么样的？", "酒精该选什么规格？"):
        assert intent_service._looks_like_general_fuel_definition_question(question), question
        assert service._is_product_usage_care_question(question), question

    assert not intent_service._looks_like_general_fuel_definition_question("酒精炉推荐什么样的？")


def test_explicit_canister_brand_recommendation_is_a_category_request():
    questions = (
        "高山气罐品牌有推荐吗？",
        "卡式气罐哪个品牌可以考虑？",
    )

    for question in questions:
        assert service._is_explicit_broad_catalogue_request(question), question


def test_unbound_single_pot_question_requires_package_identity():
    assert service._looks_like_unbound_package_contents_question("这只只是一个单锅吗？")


def test_unbound_bare_cookware_package_question_requires_identity():
    assert service._looks_like_unbound_package_contents_question("\u53ea\u662f\u9505\u5417\uff1f")


def test_support_bracket_cookware_question_is_a_compatibility_boundary():
    assert service._looks_like_stove_support_compatibility_question(
        "\u4e00\u4e2a\u652f\u67b6\u4e00\u5b9a\u8981\u7528\u5417\uff1f\u8fd9\u4e2a\u98ce\u66b4\u7089\u54ea\u4e2a\u9505\u53ef\u4ee5\u4e0d\u7528\u8fd9\u4e2a\u652f\u67b6\uff1f"
    )


def test_generic_duration_question_does_not_promote_generic_canister_rows():
    assert service._has_only_generic_product_subject("\u6c14\u7f50\u80fd\u7528\u591a\u4e45?")
    assert not service._has_only_generic_product_subject("GX15-450G\u6c14\u7f50\u80fd\u7528\u591a\u4e45?")


def test_unknown_named_product_detail_requires_identity():
    assert service._unresolved_named_product_subject(
        None,
        "\u84dd\u7ffc\u6c14\u7089\u7684\u70e4\u8089\uff0c\u53ea\u9002\u54081~2\u4eba\u7684mini\u5c0f\u714e\u76d8\uff1f",
    ) == "\u84dd\u7ffc\u6c14\u7089"


def test_unresolved_page_material_only_question_is_not_treated_as_safety_compound():
    assert not service._looks_like_unresolved_page_compound_material_safety_question(
        "有没有涂层？（当前商品：水壶）",
        "水壶",
        None,
    )
    assert service._looks_like_unresolved_page_compound_material_safety_question(
        "这个壶是什么材质的？煲的开水喝安全吗？（当前商品：水壶）",
        "水壶",
        None,
    )


def test_generic_fuel_duration_precedes_generic_fuel_safety():
    question = "\u71c3\u6599\u4e00\u7f50\u80fd\u7528\u591a\u4e45?"

    assert intent_service._looks_like_fuel_duration_usage_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "duration"


def test_unbound_explicit_fuel_subtype_requires_product_identity():
    question = "\u8fd9\u9152\u7cbe\u7089\u53ef\u4ee5\u7528\u56fa\u4f53\u9152\u7cbe\u4e0d?"

    assert service._is_unbound_fuel_compatibility_question(question)
    assert service._requested_fuel_capability(question) == "\u56fa\u4f53\u9152\u7cbe"


def test_unbound_charcoal_compatibility_requires_product_identity():
    question = "\u8fd9\u4e2a\u53ef\u4ee5\u7528\u70ad\u706b\u5417?"

    assert service._is_unbound_fuel_compatibility_question(question)


def test_bare_solid_fuel_capability_question_requires_product_identity():
    question = "\u56fa\u4f53\u71c3\u6599\u53ef\u4ee5\u5417?"

    assert service._is_unbound_fuel_compatibility_question(question)


def test_safety_scope_question_clears_unrelated_broad_catalogue_cards():
    question = "\u54ea\u4e0d\u9002\u5408\u5728\u5bb6\u91cc\u7528\u554a\uff0c\u4e0d\u80fd\u653e\u5728\u7535\u6c60\u7089\u4e0a\u7528?"
    result = {
        "answer_type": "recommendation",
        "answer": "\u8fd9\u4e9b\u7089\u5177\u4e0d\u5efa\u8bae\u5728\u5ba4\u5185\u6216\u7535\u78c1\u7089\u4e0a\u4f7f\u7528\u3002",
        "result_skus": [f"CS-G{i}" for i in range(1, 10)],
        "candidate_skus": [f"CS-G{i}" for i in range(1, 10)],
        "results": [{"sku": f"CS-G{i}"} for i in range(1, 10)],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == []
    assert shaped["candidate_skus"] == []
    assert shaped["results"] == []


def test_home_or_electric_stove_safety_scope_is_not_a_catalogue_recommendation():
    question = "\u54ea\u4e0d\u9002\u5408\u5728\u5bb6\u91cc\u7528\u554a\uff0c\u4e0d\u80fd\u653e\u5728\u7535\u6c60\u7089\u4e0a\u7528?"

    assert service._looks_like_home_or_electric_stove_safety_question(question)
    assert not service._looks_like_recommendation_request(question)


def test_customer_answer_removes_markdown_control_markers():
    answer = service._sanitize_final_answer_text(
        "**\u6db2\u4f53\u9152\u7cbe**\u4e0d\u80fd\u9ed8\u8ba4\u9002\u914d `CS-B14`\u3002\n```\u8bf7\u6309\u8bf4\u660e\u4e66\u6838\u5bf9```",
        {},
    )

    assert "**" not in answer
    assert "```" not in answer
    assert "`" not in answer
    assert "\u6db2\u4f53\u9152\u7cbe" in answer


def test_answer_named_skus_present_in_verified_rows_are_kept_in_visible_cards():
    result = {
        "answer_type": "product_query",
        "answer": "液体燃料可查到 AA-1 和 BB-2。",
        "result_skus": ["BB-2"],
        "candidate_skus": ["BB-2"],
        "results": [{"sku": "BB-2", "product_name_cn": "乙炉"}],
        "debug": {
            "raw_results": [
                {"sku": "AA-1", "product_name_cn": "甲炉"},
                {"sku": "BB-2", "product_name_cn": "乙炉"},
            ],
        },
    }

    shaped = service._shape_answer_for_output(result)

    assert shaped["result_skus"] == ["BB-2", "AA-1"]
    assert shaped["candidate_skus"] == ["BB-2", "AA-1"]
    assert [row["sku"] for row in shaped["results"]] == ["BB-2", "AA-1"]


def test_existing_answer_sku_card_is_restored_from_verified_raw_rows():
    result = {
        "answer_type": "product_query",
        "answer": "液体燃料包括 AA-1。",
        "result_skus": ["AA-1"],
        "candidate_skus": ["AA-1"],
        "results": [],
        "debug": {"raw_results": [{"sku": "AA-1", "product_name_cn": "甲炉"}]},
    }

    shaped = service._shape_answer_for_output(result)

    assert [row["sku"] for row in shaped["results"]] == ["AA-1"]


def test_category_availability_cards_follow_product_names_in_customer_answer():
    question = "\u6ca1\u6709\u676f\u5b50?"
    result = {
        "answer_type": "product_query",
        "answer": "\u6709\u676f\u5b50\uff0c\u60a6\u4eab\u676f\u5957\u88c5\u8fd8\u5728\u6b63\u5e38\u4f9b\u5e94\u3002",
        "result_skus": ["AA-1", "BB-2", "CC-3", "DD-4", "EE-5"],
        "candidate_skus": ["AA-1", "BB-2", "CC-3", "DD-4", "EE-5"],
        "results": [
            {"sku": "AA-1", "product_name_cn": "\u60a6\u4eab\u676f\u5957\u88c5"},
            {"sku": "BB-2", "product_name_cn": "\u70e7\u6c34\u58f6"},
            {"sku": "CC-3", "product_name_cn": "\u6237\u5916\u9910\u5177"},
            {"sku": "DD-4", "product_name_cn": "\u6237\u5916\u9505"},
            {"sku": "EE-5", "product_name_cn": "\u6536\u7eb3\u5305"},
        ],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == ["AA-1"]
    assert [row["sku"] for row in shaped["results"]] == ["AA-1"]


def test_remote_ignition_uses_usage_instruction_contract():
    contract = intent_service.customer_field_contract.detect_field_contract(
        "\u56f4\u96ea\u7089\u652f\u6301\u8fdc\u7a0b\u6253\u706b\u5417?"
    )

    assert contract is not None
    assert contract.field_type == "usage_instruction"


def test_missing_previous_result_clarification_hides_internal_context():
    answer = service._sanitize_final_answer_text(
        "\u4f60\u8bf4\u7684\u201c\u8fd9\u4e9b\u201d\u6211\u8fd8\u6ca1\u6709\u53ef\u5f15\u7528\u7684\u4e0a\u4e00\u8f6e\u5546\u54c1\u7ed3\u679c\u3002\u8bf7\u544a\u8bc9\u6211\u5177\u4f53\u5546\u54c1\u540d\u6216 SKU\u3002",
        {},
    )

    assert "\u4e0a\u4e00\u8f6e" not in answer
    assert "\u53ef\u5f15\u7528" not in answer
    assert "\u5177\u4f53\u5546\u54c1\u540d" in answer


def test_recommendation_shape_adds_choice_to_neutral_data_sheet():
    shaped = service._shape_recommendation_output(
        "以下是三款炉具，资料标注使用场景和特征如下：\n小青炉（CS-G25）：3200W。",
        [
            {"sku": "CS-G25", "product_name_cn": "小青炉", "features": "3200W"},
            {"sku": "KD23-MFL", "product_name_cn": "魔盒卡式炉", "features": "桌面露营"},
        ],
        [],
    )
    assert shaped.startswith("更推荐小青炉（CS-G25）")


def test_recommendation_cards_follow_grounded_multi_product_narrative():
    shaped = service._shape_answer_for_output({
        "answer_type": "recommendation",
        "answer": "更推荐小青炉（CS-G25）。也可以看魔盒卡式炉（KD23-MFL）和 ATRAX黑蜘蛛分体炉（CS-G18-28）。",
        "results": [{"sku": "CS-G25", "product_name_cn": "小青炉"}],
        "evidence": [
            {"sku": "CS-G25", "field_label": "功率", "value": "3200W"},
            {"sku": "KD23-MFL", "field_label": "场景", "value": "桌面露营"},
            {"sku": "CS-G18-28", "field_label": "场景", "value": "高海拔徒步"},
        ],
        "debug": {
            "raw_results": [
                {"sku": "CS-G25", "product_name_cn": "小青炉"},
                {"sku": "KD23-MFL", "product_name_cn": "魔盒卡式炉"},
                {"sku": "CS-G18-28", "product_name_cn": "ATRAX黑蜘蛛分体炉"},
            ]
        },
    })

    assert shaped["result_skus"] == ["CS-G25", "KD23-MFL", "CS-G18-28"]


def test_canister_duration_is_not_misclassified_as_compatibility():
    assert not intent_service._looks_like_canister_compatibility_question("气罐能用多久？")
    assert not intent_service._looks_like_canister_compatibility_question("气罐能烧多久？")
    assert intent_service._looks_like_canister_compatibility_question("通用气罐能不能接上？")


def test_converter_purchase_question_is_accessory_scope():
    assert intent_service._looks_like_canister_addon_question(
        "直接买燃气罐就行吗？有没有什么转换头需要一起买的？"
    )


def test_alcohol_stove_target_is_not_rewritten_as_alcohol_compatible_cookware():
    assert not intent_service._looks_like_alcohol_stove_cookware_recommendation_question(
        "那能不能推荐一个酒精炉可以煮火锅的？"
    )
    assert not service._phase1_is_alcohol_stove_cookware_question(
        "那能不能推荐一个酒精炉可以煮火锅的？"
    )
    assert intent_service._looks_like_alcohol_stove_cookware_recommendation_question(
        "推荐一个支持酒精炉的锅具。"
    )


def test_safety_composer_answers_alcohol_combustion_without_gas_template():
    answer = intent_service._compose_safety_usage_care_answer("酒精燃烧会不会很猛或者爆炸？")

    assert "酒精" in answer
    assert "通风" in answer
    assert "气罐结论" not in answer


def test_safety_composer_handles_vehicle_liquid_alcohol_storage():
    answer = intent_service._compose_safety_usage_care_answer("液体酒精车载安全吗？")

    assert "车内" in answer or "车载" in answer or "高温" in answer
    assert "气罐结论" not in answer


def test_safety_composer_handles_full_stove_washing_boundary():
    answer = intent_service._compose_safety_usage_care_answer("整个炉可以冲洗吗？")

    assert "整台炉具" in answer or "整机" in answer
    assert "气罐结论" not in answer


def test_safety_composer_handles_igniter_replacement_question():
    answer = intent_service._compose_safety_usage_care_answer("点火器有卖的吗，可以更换不？")

    assert "更换" in answer or "配件" in answer
    assert "气罐结论" not in answer


def test_safety_composer_handles_canister_duration_without_connection_claim():
    answer = intent_service._compose_safety_usage_care_answer("气罐能用多久？")

    assert "使用时长" in answer or "容量" in answer
    assert "兼容性结论" not in answer


def test_liquid_alcohol_amount_does_not_use_solid_piece_answer():
    answer = intent_service._compose_duration_usage_care_answer(
        "液体酒精一次加多少毫升？",
        [],
        [],
    )

    assert "液体酒精" in answer or "毫升" in answer
    assert "每次应放多少块" not in answer
    assert "用量和烧水时间" not in answer


def test_alcohol_runtime_question_uses_duration_answer_not_generic_safety():
    answer = intent_service._compose_safety_usage_care_answer("酒精能烧多久？")

    assert "使用时长" in answer or "燃烧时间" in answer or "多久" in answer
    assert "当前资料未维护更细的安全说明" not in answer


def test_ignition_instruction_does_not_use_fault_troubleshooting_template():
    question = "小青炉怎么点火？"

    assert intent_service._detect_usage_care_subtype(question) == "usage_instruction"
    answer = intent_service._compose_usage_care_answer(
        question,
        [],
        [],
        response_style="usage_guidance",
    )
    assert "使用说明" in answer or "点火" in answer
    assert "先关闭阀门，停止继续点火" not in answer


def test_canister_fault_does_not_use_quantity_or_package_answer():
    answer = intent_service._compose_safety_usage_care_answer("气罐不出气怎么办？")

    assert any(term in answer for term in ("阀门", "接口", "检查", "停止使用"))
    assert "数量" not in answer
    assert "购买状态" not in answer


def test_canister_dedicated_type_question_does_not_use_quantity_answer():
    answer = intent_service._compose_safety_usage_care_answer("这个气罐是不是专用的？")

    assert "兼容性" in answer or "适配" in answer or "气罐类型" in answer
    assert "数量" not in answer
    assert "购买状态" not in answer


def test_alcohol_disposal_question_never_recommends_drain_disposal():
    answer = intent_service._compose_safety_usage_care_answer(
        "高浓度酒精没用完可以倒下水道吗？"
    )

    assert "下水道" not in answer or any(term in answer for term in ("不要", "不能", "禁止"))
    assert any(term in answer for term in ("处置", "当地要求", "危险废物", "联系人工客服", "不要"))


def test_customer_sanitizer_removes_internal_keyword_catalogue_fields():
    answer = service._sanitize_final_answer_text(
        "小青炉：材质：不锈钢；关键词库：camping stove，keyword: outdoor burner，priority: A；"
        "中文标题：爱路客户外炉具小青炉；热源：高山气罐。",
        {},
    )

    assert "关键词库" not in answer
    assert "keyword:" not in answer
    assert "priority:" not in answer
    assert "中文标题" not in answer
    assert "小青炉" in answer
    assert "热源" in answer


def test_customer_sanitizer_removes_catalogue_filtering_jargon():
    answer = service._sanitize_final_answer_text(
        "当前已核对资料未找到符合条件的商品，可以尝试放宽筛选条件。"
        "你提到的要求，当前还不能用同 SKU 的已验证资料作为筛选条件。",
        {},
    )

    assert "筛选条件" not in answer
    assert "同 SKU 的已验证资料" not in answer
    assert "条件" in answer or "商品资料" in answer


def test_customer_sanitizer_replaces_previous_round_orchestration_wording():
    answer = service._sanitize_final_answer_text(
        "上一轮我们讨论的是小青炉（CS-G25），没有提到水壶。",
        {},
    )

    assert "上一轮" not in answer
    assert "前面" in answer or "此前" in answer


def test_uncertain_single_product_answer_clears_broad_catalogue_cards():
    result = {
        "answer": "抱歉，您说的‘这只’没有指明具体产品，我无法直接判断。资料里包含多款锅具。",
        "answer_type": "product_query",
        "result_skus": ["CW-C69-1", "CW-C06PRO", "CW-C71", "CW-C74", "CW-C78"],
        "candidate_skus": ["CW-C69-1", "CW-C06PRO", "CW-C71", "CW-C74", "CW-C78"],
        "results": [{"sku": sku} for sku in ["CW-C69-1", "CW-C06PRO", "CW-C71", "CW-C74", "CW-C78"]],
        "sources": [{"sku": sku} for sku in ["CW-C69-1", "CW-C06PRO", "CW-C71", "CW-C74", "CW-C78"]],
    }

    shaped = service._clear_unrelated_catalogue_cards("这只只是一个单锅吗?", result)

    assert shaped["result_skus"] == []
    assert shaped["candidate_skus"] == []
    assert shaped["results"] == []
    assert shaped["sources"] == []


def test_non_browse_answer_cards_align_to_skus_named_in_bounded_conclusion():
    named_skus = ["CW-C69-1", "CW-C71"]
    broad_skus = named_skus + [
        "CW-C06PRO", "CW-C78", "CW-C74", "CW-C83", "CW-C93",
        "CW-C96", "CW-C65", "CW-C99", "CW-C82", "CW-C70",
    ]
    result = {
        "answer": (
            "如果您指的是小方锅套装（CW-C69-1），它不是单锅；"
            "如果您指的是3L单锅（CW-C71），则是单个锅。"
        ),
        "answer_type": "product_query",
        "result_skus": broad_skus,
        "candidate_skus": broad_skus,
        "results": [{"sku": sku} for sku in broad_skus],
        "sources": [{"sku": sku} for sku in broad_skus],
    }

    shaped = service._clear_unrelated_catalogue_cards("这只只是一个单锅吗?", result)

    assert shaped["result_skus"] == named_skus
    assert shaped["candidate_skus"] == named_skus
    assert [row["sku"] for row in shaped["results"]] == named_skus
    assert [row["sku"] for row in shaped["sources"]] == named_skus


def test_compound_field_preface_is_not_treated_as_a_product_subject():
    assert service._explicit_page_subject_from_question("有便携带吗，壶容量多大，什么材质?") == ""


def test_category_recommendation_with_page_context_is_broad_catalogue_intent():
    question = "推荐一下卡式炉，使用方便，安全一点的?（当前商品：小青炉）"

    assert service._is_explicit_broad_catalogue_request(question)


def test_plain_type_selection_for_a_category_is_bounded_category_intent():
    # A customer asking which kind of stove head to use is a category-level
    # selection ask, not an invitation for the LLM to dump every retrieved row.
    question = "\u7528\u4ec0\u4e48\u6837\u7684\u7089\u5934???"

    assert service._looks_like_unconstrained_category_recommendation_question(question)


def test_price_banded_package_inclusion_is_detected_as_an_unverified_field():
    question = "400\u591a\u5957\u88c5\u91cc \u6709\u6ca1\u6709\u6c34\u58f6?"

    assert service._looks_like_price_banded_package_inclusion_question(question)
    assert not service._looks_like_price_banded_package_inclusion_question("\u5957\u88c5\u91cc\u6709\u6ca1\u6709\u6c34\u58f6?")


def test_category_recommendation_filters_unavailable_lifecycle_rows(monkeypatch):
    rows = [
        {
            "sku": "AVAILABLE-STOVE",
            "product_name_cn": "\u5728\u552e\u7089\u5177",
            "category": "\u7089\u5177",
            "lifecycle_status": "\u5e38\u89c4\u54c1",
        },
        {
            "sku": "OLD-STOVE",
            "product_name_cn": "\u8001\u6b3e\u7089\u5177",
            "category": "\u7089\u5177",
            "lifecycle_status": "\u8001\u6b3e\u65e0\u8d27\u4e0d\u8865",
        },
    ]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    result = service._explicit_category_recommendation_result(None, "\u6709\u6ca1\u6709\u7089\u5177\u63a8\u8350?")

    assert result is not None
    assert result["result_skus"] == ["AVAILABLE-STOVE"]


def test_high_heat_split_burner_usage_is_a_generic_safety_boundary_not_a_new_sku_rule():
    question = "\u6e29\u5ea6\u9ad8\u8fd8\u662f\u5f97\u7528\u5206\u4f53\u7089\u5934\u4e86\u5427?"

    assert intent_service._looks_like_high_heat_split_burner_usage_question(question)
    assert intent_service._looks_like_usage_care_question(question)
    # Keep the existing safety subtype; do not introduce an exact-utterance
    # subtype whose only purpose is to satisfy this one sentence.
    assert intent_service._detect_usage_care_subtype(question) == "safety"
    answer = intent_service._compose_safety_usage_care_answer(question)
    assert "分体" in answer
    assert "气罐" in answer or "高温" in answer


def test_high_heat_split_burner_boundary_is_compositional_not_an_exact_sentence_rule():
    for question in (
        "高温烹饪时远程炉头是不是更安全？",
        "猛火长时间使用分体式炉具要注意什么？",
    ):
        assert intent_service._looks_like_high_heat_split_burner_usage_question(question)
        assert intent_service._detect_usage_care_subtype(question) == "safety"
    assert not intent_service._looks_like_high_heat_split_burner_usage_question("推荐哪款分体炉头？")


def test_electric_heat_source_question_returns_an_explicit_boundary():
    answer, status = service._phase1_heat_source_capability_answer(
        None,
        {
            "sku": "GENERIC-COOKWARE",
            "product_name_cn": "测试锅具",
            "heat_source": "明火直烧、卡式炉",
        },
        "能用电磁炉吗？",
    )

    assert status == "not_listed"
    assert "未显示支持电磁炉" in answer
    assert "明火直烧" in answer


def test_multi_fuel_choice_answers_each_explicit_alternative():
    answer, _status = service._phase1_heat_source_capability_answer(
        None,
        {
            "sku": "GENERIC-STOVE",
            "product_name_cn": "测试炉具",
            "heat_source": "固体酒精",
        },
        "推荐用酒精块还是木炭？",
    )

    assert "固体酒精" in answer
    assert "木炭" in answer
    assert "不能" in answer or "未显示支持" in answer or "未标注" in answer


def test_page_current_item_availability_keeps_page_identity_boundary():
    assert service._looks_like_page_current_item_availability_question(
        "没有炉头？（当前商品：小青炉）"
    )
    assert not service._looks_like_page_current_item_availability_question(
        "有没有炉头推荐？（当前商品：小青炉）"
    )


def test_page_current_item_availability_does_not_expose_broad_catalogue_results(monkeypatch):
    product = SimpleNamespace(
        id="page-product",
        sku="CS-G25",
        product_name_cn="小青炉",
        product_name_en="",
        category="炉具",
    )

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return product

    class _DB:
        def query(self, _model):
            return _Query()

    monkeypatch.setattr(service, "_resolve_exact_sku_variant", lambda _db, sku: sku)
    result = service._apply_request_sku_anchor_guard(
        _DB(),
        question="没有炉头？（当前商品：小青炉）",
        request_anchor_sku="CS-G25",
        phase1_plan={},
        agent_result={
            "answer_type": "product_query",
            "answer": "现有炉具包括小青炉、魔盒卡式炉、分体炉。",
            "result_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "candidate_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "results": [],
            "answer_metadata": {"source": "structured_catalogue"},
            "debug": {},
        },
    )

    assert result["result_skus"] == []
    assert "小青炉" in result["answer"]
    assert "炉头" in result["answer"]
    assert "魔盒卡式炉" not in result["answer"]


def test_accessory_storage_bag_scope_is_a_catalogue_category():
    assert service._semantic_catalog_product_ref("有没有户外餐具收纳包推荐下？") == "配件"


def test_natural_page_availability_also_clears_broad_catalogue_cards():
    result = service._clear_unrelated_catalogue_cards(
        "没有炉头？（当前商品：小青炉）",
        {
            "answer_type": "product_query",
            "answer": "现有炉具包括小青炉、魔盒卡式炉、黑蜘蛛分体炉。",
            "result_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "candidate_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "results": [],
            "sources": [],
            "debug": {},
        },
    )

    assert result["result_skus"] == []
    assert "小青炉" in result["answer"]
    assert "炉头" in result["answer"]
    assert "魔盒卡式炉" not in result["answer"]


def test_output_shaper_preserves_original_page_context_for_card_hygiene():
    result = service._shape_answer_for_output(
        {
            "answer_type": "product_query",
            "answer": "现有炉具包括小青炉、魔盒卡式炉、黑蜘蛛分体炉。",
            "result_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "candidate_skus": ["CS-G25", "KD23-MFL", "CS-G18-28"],
            "results": [],
            "sources": [],
            "answer_metadata": {},
            "debug": {
                "plan": {
                    "raw_question": "没有炉头？",
                    "original_question": "没有炉头？（当前商品：小青炉）",
                }
            },
        }
    )

    assert result["result_skus"] == []
    assert "小青炉" in result["answer"]
    assert "炉头" in result["answer"]
    assert "魔盒卡式炉" not in result["answer"]


def test_explicit_fuel_subtype_does_not_fall_back_to_generic_stove_safety():
    answer = intent_service._compose_safety_usage_care_answer("这个可以用酒精块吗？")

    assert "酒精块" in answer or "固体酒精" in answer
    assert "安全建议：户外使用炉具" not in answer
    assert "未标注" in answer or "无法确认" in answer


def test_fuel_aliases_keep_solid_fuel_as_a_subtype():
    question = "固体燃料可以吗？"

    assert intent_service._detect_usage_care_subtype(question) == "safety"
    answer = intent_service._compose_safety_usage_care_answer(question)
    assert "固体酒精" in answer
    assert "安全建议：户外使用炉具" not in answer


def test_alcohol_stove_high_altitude_question_stays_usage_boundary():
    answer = intent_service._compose_safety_usage_care_answer("酒精炉在高原能用吗？")

    assert "高原" in answer or "高海拔" in answer
    assert "结构化商品库" not in answer


def test_alcohol_stove_cookware_pairing_is_not_a_catalogue_filter():
    answer = intent_service._compose_safety_usage_care_answer("酒精炉可以用玻璃水壶吗？")

    assert "玻璃水壶" in answer or "配套" in answer or "兼容" in answer
    assert "结构化商品库" not in answer
    assert "筛选条件" not in answer


def test_ambiguous_electric_stove_wording_requires_heat_source_clarification():
    assert service._looks_like_ambiguous_electric_stove_question("电炉哪个可以用？")


def test_solid_fuel_aliases_become_the_same_recommendation_constraint():
    contract = recommendation_contract.build_recommendation_request_contract("推荐支持酒精块的炉具")

    assert contract.subject_category == "炉具"
    assert contract.fuel_subtype == "固体酒精"
    assert "fuel_subtype" in contract.hard_constraints


def test_charcoal_compatibility_does_not_treat_open_flame_as_a_direct_answer():
    answer = intent_service._compose_safety_usage_care_answer("这个可以用炭火吗？")

    assert "炭火" in answer
    assert "明火直烧" not in answer or "不等同" in answer
    assert "安全建议：户外使用炉具" not in answer


def test_canister_fit_inside_cookware_is_a_storage_question():
    question = "气罐能完美放到单锅里面吗？"

    assert intent_service._looks_like_canister_storage_fit_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "safety"


def test_explicit_accessory_combination_does_not_recommend_unrelated_products():
    question = "有没有可以选择的配件点火和调节开关一起？"

    assert service._is_unbound_accessory_availability_question(question)


def test_stove_head_subject_wins_over_supporting_canister_noun():
    question = "\u6211\u8981\u88c5\u6c14\u7f50\u5565\u7684\uff0c\u6709\u6ca1\u6709\u5c0f\u7089\u5934\u63a8\u8350\u554a\uff0c\u4e0d\u8981\u5206\u4f53\u7684?"

    assert service._semantic_catalog_product_ref(question) == "\u7089\u5177"


def test_accessory_combination_scope_clears_unrelated_catalogue_rows():
    question = "\u6709\u6ca1\u6709\u53ef\u4ee5\u9009\u62e9\u7684\u914d\u4ef6\u70b9\u706b\u548c\u8c03\u8282\u5f00\u5173\u4e00\u8d77?"
    result = {
        "answer": "\u66f4\u63a8\u8350\u7a33\u7a33\u6c34\u888b\uff08AC-19\uff09\u3002",
        "answer_type": "recommendation",
        "result_skus": ["AC-19", "TW-429B"],
        "candidate_skus": ["AC-19", "TW-429B"],
        "results": [
            {"sku": "AC-19", "product_name_cn": "\u7a33\u7a33\u6c34\u888b", "category": "\u914d\u4ef6", "features": "\u9732\u8425\u50a8\u6c34"},
            {"sku": "TW-429B", "product_name_cn": "\u65b9\u5c7f\u5c0f\u96ea\u62c9\u7897", "category": "\u9910\u5177", "features": "\u591a\u7528\u9014"},
        ],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == []
    assert "\u540c\u65f6\u660e\u786e\u6807\u6ce8" in shaped["answer"]
    assert shaped["debug"]["agent_mode"] == "accessory_combination_evidence_scope_guard"


def test_canister_adapter_question_cannot_become_a_canister_recommendation():
    question = "\u8fd9\u4e2a\u7528\u54ea\u4e2a\u6c14\u7f50\uff0c\u9700\u8981\u8f6c\u63a5\u5934\u5417?"
    result = {
        "answer": "\u66f4\u63a8\u8350 230g\u9ad8\u5c71\u9ad8\u5bd2\u6c14\u7f50\uff08GX14-230G\uff09\u3002",
        "answer_type": "recommendation",
        "result_skus": ["GX14-230G", "GX15-450G"],
        "candidate_skus": ["GX14-230G", "GX15-450G"],
        "results": [
            {"sku": "GX14-230G", "product_name_cn": "230g\u9ad8\u5c71\u9ad8\u5bd2\u6c14\u7f50", "category": "\u71c3\u6599"},
            {"sku": "GX15-450G", "product_name_cn": "450g\u9ad8\u5c71\u9ad8\u5bd2\u6c14\u7f50", "category": "\u71c3\u6599"},
        ],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["result_skus"] == []
    assert "\u517c\u5bb9\u6027\u7ed3\u8bba" in shaped["answer"]
    assert shaped["debug"]["agent_mode"] == "canister_compatibility_answer_scope_guard"


def test_bundle_followup_recommendation_keeps_only_bundle_rows(monkeypatch):
    rows = [
        {
            "sku": "SET-1",
            "product_name_cn": "\u9732\u8425\u9505\u5177\u5957\u88c5",
            "category": "\u9505\u5177",
            "features": "\u9505\u5177\u5957\u88c5\uff0c\u542b\u9505\u548c\u714e\u76d8",
            "lifecycle_status": "\u5e38\u89c4\u54c1",
        },
        {
            "sku": "SINGLE-1",
            "product_name_cn": "3L\u5355\u9505",
            "category": "\u9505\u5177",
            "features": "\u5355\u9505",
            "lifecycle_status": "\u5e38\u89c4\u54c1",
        },
    ]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    question = "\u5957\u88c5\u8fd8\u6709\u6ca1\u6709\u5176\u4ed6\u63a8\u8350\uff0c\u5c31\u53ea\u6709\u8fd9\u4e00\u5957\u6b3e\u5f0f\uff0c\u662f\u4e0d?"
    result = service._explicit_category_recommendation_result(None, question)

    assert result is not None
    assert result["result_skus"] == ["SET-1"]
    assert "SET-1" in result["answer"]
    assert "SINGLE-1" not in result["answer"]


def test_explicit_fuel_subtype_does_not_fall_back_to_generic_safety_text():
    question = "\u8fd9\u6b3e\u53ef\u4ee5\u7528\u56fa\u4f53\u9152\u7cbe\u5417?"
    result = {
        "answer": "\u5b89\u5168\u5efa\u8bae\uff1a\u6237\u5916\u4f7f\u7528\u7089\u5177\u65f6\u5e94\u4fdd\u6301\u901a\u98ce\u3002",
        "answer_type": "product_usage_care",
        "result_skus": ["CW-C84"],
        "candidate_skus": ["CW-C84"],
        "results": [
            {
                "sku": "CW-C84",
                "product_name_cn": "\u9e23\u6cc9\u6c34\u58f6",
                "heat_source": "\u660e\u706b\u76f4\u70e7\u3001\u5361\u5f0f\u7089\u3001\u5206\u4f53\u7089\u3001\u4e00\u4f53\u7089",
            }
        ],
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert "\u672a\u663e\u793a\u652f\u6301\u56fa\u4f53\u9152\u7cbe" in shaped["answer"]
    assert "\u5b89\u5168\u5efa\u8bae\uff1a\u6237\u5916\u4f7f\u7528\u7089\u5177" not in shaped["answer"]


def test_safety_composer_handles_canister_fit_inside_cookware():
    answer = intent_service._compose_safety_usage_care_answer("气罐能完美放到单锅里面吗？")

    assert "收纳" in answer or "尺寸" in answer or "放入" in answer
    assert "气罐结论" not in answer
    assert "G09" not in answer


def test_canister_type_definition_is_not_rewritten_as_connection_question():
    answer = intent_service._compose_safety_usage_care_answer("高山气罐就是大罐是吧？")

    assert "大小" in answer or "容量" in answer
    assert "兼容性结论" not in answer


def test_standalone_burner_head_recommendation_uses_accessory_scope(monkeypatch):
    rows = [
        {
            "sku": "ACCESSORY-BURNER",
            "product_name_cn": "分体炉头配件",
            "category": "配件",
            "features": "炉头配件，适配说明另列",
            "lifecycle_status": "常规品",
        },
        {
            "sku": "COMPLETE-STOVE",
            "product_name_cn": "小青炉",
            "category": "炉具",
            "features": "整炉，含炉体和支架",
            "lifecycle_status": "常规品",
        },
    ]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    question = "有没有炉头推荐？"

    assert service._semantic_catalog_product_ref(question) == "配件"
    result = service._explicit_category_recommendation_result(None, question)

    assert result is not None
    assert result["result_skus"] == ["ACCESSORY-BURNER"]
    assert "COMPLETE-STOVE" not in str(result.get("answer") or "")


def test_storage_bag_recommendation_does_not_include_unrelated_accessory_scope(monkeypatch):
    rows = [
        {
            "sku": "BAG-1",
            "product_name_cn": "户外餐具收纳包",
            "category": "配件",
            "features": "餐具收纳包，便携收纳",
            "lifecycle_status": "常规品",
        },
        {
            "sku": "SPICE-1",
            "product_name_cn": "便携调料瓶套装",
            "category": "配件",
            "features": "调料瓶套装，户外调味",
            "lifecycle_status": "常规品",
        },
    ]
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    result = service._explicit_category_recommendation_result(
        None,
        "有没有户外餐具收纳包推荐下？",
    )

    assert result is not None
    assert result["result_skus"] == ["BAG-1"]
    assert "SPICE-1" not in str(result.get("answer") or "")


def test_no_match_answer_clears_unrelated_cards_for_unlisted_category():
    result = service._clear_unrelated_catalogue_cards(
        "有没有公道杯？",
        {
            "answer_type": "product_query",
            "answer": "当前资料没有“公道杯”可推荐。",
            "result_skus": [f"UNRELATED-{i}" for i in range(10)],
            "candidate_skus": [f"UNRELATED-{i}" for i in range(10)],
            "results": [{"sku": f"UNRELATED-{i}"} for i in range(10)],
            "sources": [{"sku": f"UNRELATED-{i}"} for i in range(10)],
        },
    )

    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert result["results"] == []
    assert result["sources"] == []


def test_answer_card_alignment_accepts_ascii_and_fullwidth_sku_variant():
    result = service._clear_unrelated_catalogue_cards(
        "有没有炉头推荐？",
        {
            "answer_type": "recommendation",
            "answer": "更推荐旋焰炉芯（CS-B14(LX)）。\n另有爱路客酒精炉芯（PA-CS-B02-001-42）。",
            "result_skus": ["CS-B14（LX）", "PA-CS-B02-001-42"],
            "candidate_skus": ["CS-B14（LX）", "PA-CS-B02-001-42"],
            "results": [
                {"sku": "CS-B14（LX）", "product_name_cn": "旋焰炉芯"},
                {"sku": "PA-CS-B02-001-42", "product_name_cn": "爱路客酒精炉芯"},
            ],
            "sources": [],
        },
    )

    assert result["result_skus"] == ["CS-B14（LX）", "PA-CS-B02-001-42"]
    assert len(result["results"]) == 2


def test_multi_heat_source_question_keeps_electric_and_charcoal_alternatives():
    question = "咱们的烧水壶可以用电磁炉或者速燃碳烧水吗？"

    assert service._requested_fuel_capabilities(question) == ["电磁炉", "木炭"]
    answer, _status = service._phase1_multi_fuel_capability_answer(
        {
            "sku": "GENERIC-KETTLE",
            "product_name_cn": "测试烧水壶",
            "heat_source": "明火直烧",
        },
        question,
        asked_fuels=["电磁炉", "木炭"],
    )

    assert "电磁炉" in answer
    assert "木炭" in answer
    assert "热源" in answer
    assert "燃料选择结论" not in answer
    assert "不能" in answer or "未显示支持" in answer or "未标注" in answer


def test_fuel_choice_with_no_verified_option_states_do_not_choose_either():
    answer, _status = service._phase1_multi_fuel_capability_answer(
        {
            "sku": "GENERIC-STOVE",
            "product_name_cn": "测试炉具",
            "heat_source": "明火直烧",
        },
        "推荐用酒精块还是木炭？",
        asked_fuels=["固体酒精", "木炭"],
    )

    assert "固体酒精" in answer
    assert "木炭" in answer
    assert "不建议" in answer


def test_fuel_storage_comparison_is_not_a_product_recommendation():
    question = "气罐和酒精放车上哪个安全一点？"

    assert intent_service._looks_like_fuel_storage_comparison_question(question)
    assert not service._looks_like_recommendation_request(question)
    answer = intent_service._compose_safety_usage_care_answer(question)
    assert "车内" in answer or "车上" in answer or "后备箱" in answer
    assert "两者都不建议" in answer or "都不建议" in answer or "不能把任何一种" in answer
    assert "GX14" not in answer and "GX15" not in answer


def test_universal_kettle_heat_source_question_answers_not_all():
    question = "是不是所有烧水壶都可以用？"

    assert intent_service._looks_like_universal_heat_source_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "safety"
    answer = intent_service._compose_safety_usage_care_answer(question)
    assert "不是所有" in answer
    assert "同款" in answer or "SKU" in answer or "热源" in answer


def test_universal_heat_source_boundary_does_not_consume_utensil_choice():
    question = "我另外买锅铲的话，选不锈钢还是硅胶的，不锈钢会伤锅吗，还是都可以用？"

    assert intent_service._looks_like_utensil_material_safety_question(question)
    assert not intent_service._looks_like_universal_heat_source_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "utensil_material"


def test_generic_entity_clarification_never_echoes_greeting_fragment():
    class _Contract:
        entity_text = "你好这个锅头"
        field_type = "product_qa"

        def to_dict(self):
            return {"entity_text": self.entity_text, "field_type": self.field_type}

    result = service._build_phase2_entity_state_response(
        None,
        "你好这个锅头可以用电池炉吗？",
        {"action": "generic_clarification", "contract": _Contract(), "products": []},
    )

    assert "你好这个锅头" not in result["answer"]
    assert "这个商品" in result["answer"]


def test_why_use_non_card_stove_canister_is_compatibility_question():
    assert intent_service._looks_like_canister_compatibility_question(
        "这个炉子为什么用不卡式炉的气罐？"
    )


def test_general_alcohol_safety_and_medical_alcohol_questions_enter_usage_boundary():
    assert intent_service._looks_like_usage_care_question("酒精燃烧会不会爆炸？")
    assert intent_service._looks_like_general_fuel_definition_question("酒精在药店买的那个能用不？")


def test_unbound_alcohol_boil_time_is_not_recommended_as_cookware():
    question = "两块酒精，一小时十分钟，一壶水都没烧开，只是加热用的吗？"

    assert intent_service._looks_like_usage_care_question(question)
    assert intent_service._looks_like_fuel_duration_usage_question(question)
    assert not intent_service._looks_like_alcohol_stove_cookware_recommendation_question(question)


def test_alcohol_runtime_question_keeps_duration_subtype_over_definition_explainer():
    question = "那个酒精可以用多久的？"

    assert intent_service._looks_like_fuel_duration_usage_question(question)
    assert intent_service._detect_usage_care_subtype(question) == "duration"


def test_alcohol_spill_cleaning_question_keeps_fire_safety_scope():
    answer = intent_service._compose_safety_usage_care_answer("存酒精怎么擦干净？")

    assert "远离火源" in answer or "通风" in answer
    assert "清洁方法" not in answer


def test_direct_stove_canister_connection_is_compatibility_question():
    assert intent_service._looks_like_canister_compatibility_question(
        "我应该是直接把我的分体式炉子然后接到气罐就行了是吧？"
    )


def test_semantic_recommendation_keeps_unrepresentable_multi_component_bundle_requirement():
    question = "\u63a8\u8350\u4e00\u6b3e2\u4eba\u5f92\u6b65\u9505\u7076\u6c14\u7f50\u5957\u88c5\uff1f"
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        question,
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.95,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 2, "max": 2},
                    "scenarios": ["hiking"],
                },
                "unrepresented_recommendation_requirements": ["\u9505\u7076\u6c14\u7f50\u5957\u88c5"],
            },
        },
    ))

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["debug"]["agent_mode"] == "semantic_recommendation_unrepresented_requirement_clarification"
    assert "\u9505\u7076\u6c14\u7f50\u5957\u88c5" in result["answer"]


def test_semantic_recommendation_treats_unforced_stability_as_soft_preference(monkeypatch):
    rows = [
        {
            "sku": "CW-STABLE-1",
            "product_name_cn": "3人露营锅",
            "category": "锅具",
            "usage_scenarios": "3人露营",
            "target_audience": "3人家庭露营",
            "capacity": "3L",
            "gross_weight_g": 500,
            "features": "适合稳定放置",
        }
    ]
    monkeypatch.setattr(service.customer_agent_service, "search_products", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def narrative_available(*_args, **_kwargs):
        return {
            "answer": "推荐 3人露营锅（CW-STABLE-1）。",
            "ranked_candidate_indexes": [0],
            "evidence_usage": [],
        }

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", narrative_available)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "推荐一款三人露营稳定性优先的锅具",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.95,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "subject_text": "锅具",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "people": {"min": 3, "max": 3},
                    "scenarios": ["camping"],
                },
                "unrepresented_recommendation_requirements": ["稳定性"],
                "recommendation_soft_preferences": [],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["CW-STABLE-1"]


def test_cookware_is_catalogue_subject_when_alcohol_stove_is_a_constraint():
    assert service._semantic_catalog_product_ref("推荐一个支持酒精炉的锅具") == "锅具"


def test_plural_recommendation_persists_verified_candidate_domain_for_comparison():
    result = {
        "intent": "recommend_products",
        "answer_type": "recommendation",
        "answer": "优先推荐家庭露营锅具套装一（CW-TEST-1）。",
        "result_skus": ["CW-TEST-1"],
        "candidate_skus": ["CW-TEST-1"],
        "results": [
            {"sku": "CW-TEST-1", "product_name_cn": "家庭露营锅具套装一"},
        ],
        "debug": {"all_verified_candidate_skus": ["CW-TEST-1", "CW-TEST-2"]},
    }

    sources = service._sources_with_result_context(
        result,
        user_question="适合家庭露营的锅有哪些？",
    )
    candidate_context = next(
        item["candidate_context"]
        for item in sources
        if item.get("type") == "agent_meta" and item.get("candidate_context")
    )

    assert candidate_context["candidate_skus"] == ["CW-TEST-1", "CW-TEST-2"]
    assert service._context_skus_for_pair_followup(candidate_context) == ["CW-TEST-1", "CW-TEST-2"]


def test_verified_recommendation_falls_back_to_summary_when_narrative_is_unavailable(monkeypatch):
    rows = [
        {
            "sku": "CW-TEST-1",
            "product_name_cn": "家庭露营锅具套装一",
            "category": "锅具",
            "features": "锅具套装，适合家庭露营",
            "usage_scenarios": "家庭露营",
            "target_audience": "家庭露营用户",
            "capacity": "1.5L",
        },
        {
            "sku": "CW-TEST-2",
            "product_name_cn": "家庭露营锅具套装二",
            "category": "锅具",
            "features": "锅具套装，适合家庭露营",
            "usage_scenarios": "家庭露营",
            "target_audience": "家庭露营用户",
            "capacity": "3L",
        },
    ]
    monkeypatch.setattr(service.customer_agent_service, "search_products", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: rows)

    async def narrative_unavailable(*_args, **kwargs):
        kwargs["diagnostics"].append({"stage": "grounding_review", "status": "rejected"})
        return None

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", narrative_unavailable)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "适合家庭露营的锅有哪些？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "route_hint": "recommendation",
                "question_type": "recommendation",
                "confidence": 0.95,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "subject_text": "锅",
                "recommendation_constraints": {
                    "subject_kind": "cookware",
                    "scenarios": ["camping"],
                },
                "recommendation_constraint_evidence_spans": {
                    "subject_kind": ["锅"],
                    "scenarios": ["露营"],
                },
                "unrepresented_recommendation_requirements": [],
                "recommendation_soft_preferences": [],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert result["result_skus"] == ["CW-TEST-1", "CW-TEST-2"]
    assert "家庭露营" in result["answer"]


def test_gift_recommendation_preserves_gifting_context_in_fact_fallback():
    preserve = getattr(service, "_preserve_recommendation_customer_context", None)
    assert callable(preserve)

    result = preserve(
        "哪种户外锅具适合送礼？",
        {
            "answer_type": "recommendation",
            "answer": "以下是当前核验通过的候选：小方锅套装（CW-TEST-1）。",
            "result_skus": ["CW-TEST-1"],
            "candidate_skus": ["CW-TEST-1"],
        },
    )

    assert "送礼" in result["answer"] or "礼物" in result["answer"] or "适合" in result["answer"]


def test_negated_accessory_scope_keeps_semantic_cookware_subject():
    contract = recommendation_contract.build_recommendation_request_contract(
        "如果只买锅具，不要炉具和配件，给我一款两个人用的。",
        semantic_constraints={
            "subject_kind": "cookware",
            "people": {"min": 2, "max": 2},
        },
    )

    assert contract.subject_category == "锅具"
    assert contract.subject_kind == "cookware"
    assert (contract.people_min, contract.people_max) == (2, 2)
    rows = [
        {
            "sku": "COOK-2P",
            "product_name_cn": "两人单锅",
            "category": "锅具",
            "target_audience": "1-2人露营者",
            "features": "适合两人煮食",
        },
        {
            "sku": "ACCESSORY-1",
            "product_name_cn": "锅夹配件",
            "category": "配件",
            "target_audience": "",
            "features": "锅具配件",
        },
        {
            "sku": "STOVE-1",
            "product_name_cn": "便携炉具",
            "category": "炉具",
            "target_audience": "1-2人",
            "features": "燃气炉",
        },
    ]
    verified = recommendation_contract.verify_recommendation_candidates(contract, rows)

    assert verified[0].verification_level == "fully_verified"
    assert verified[0].sku == "COOK-2P"
    assert all(item.sku != "ACCESSORY-1" for item in verified if item.verification_level == "fully_verified")
    assert all(item.sku != "STOVE-1" for item in verified if item.verification_level == "fully_verified")


def test_coffee_cookware_goal_expands_and_ranks_a_small_fast_boiling_pot(monkeypatch):
    initial_rows = [{
        "sku": "COFFEE-SET",
        "product_name_cn": "露营咖啡小锅",
        "category": "锅具",
        "target_audience": "露营用户",
        "usage_scenarios": "露营咖啡",
        "capacity": "1800ML",
        "features": "适合户外烹饪",
    }]
    catalogue_rows = [
        *initial_rows,
        {
            "sku": "CW-C93",
            "product_name_cn": "速沸小锅",
            "category": "锅具",
            "target_audience": "单人露营",
            "usage_scenarios": "露营烧水、泡咖啡",
            "capacity": "1000ML",
            "features": "95秒速沸，适合烧水",
        },
        {
            "sku": "GRIDDLE-1",
            "product_name_cn": "户外煎盘",
            "category": "锅具",
            "target_audience": "露营用户",
            "usage_scenarios": "露营早餐",
            "capacity": "2300ML",
            "features": "煎盘、煎锅，适合煎烤",
        },
    ]
    monkeypatch.setattr(service.customer_agent_service, "search_products", lambda *_args, **_kwargs: initial_rows)
    monkeypatch.setattr(service, "_phase1_catalog_rows", lambda _db, _ref: catalogue_rows)

    async def grounded_narrative(*_args, **_kwargs):
        return {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["specs.capacity"]}],
            "answer": "优先看这款小锅，资料显示容量适合快速烧水。",
        }

    monkeypatch.setattr(service, "_semantic_recommendation_narrative", grounded_narrative)
    result = asyncio.run(service._semantic_recommendation_contract_result(
        None,
        "适合泡咖啡的小锅有吗？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "recommendation",
                "confidence": 0.95,
                "confidence_label": "high",
                "fallback_reason": "",
                "ambiguity": False,
                "subject_text": "小锅",
                "recommendation_constraints": {"subject_kind": "cookware"},
                "recommendation_soft_preferences": ["泡咖啡"],
                "unrepresented_recommendation_requirements": [],
            },
        },
    ))

    assert result["answer_type"] == "recommendation"
    assert "CW-C93" in result["result_skus"]
    assert result["result_skus"][0] == "CW-C93"
    assert "泡咖啡" in result["answer"] or "烧水" in result["answer"]
    assert "GRIDDLE-1" not in result["answer"]


def test_generic_liquid_alcohol_tent_question_answers_safety_before_sku():
    answer = intent_service._compose_safety_usage_care_answer(
        "液体酒精炉在帐篷里能用吗？为什么？"
    )

    assert "帐篷" in answer
    assert "密闭" in answer or "不可" in answer or "不要" in answer
    assert "通风" in answer
    assert "请提供具体商品名或 SKU" not in answer.split("安全提醒", 1)[0]


def test_environmental_fuel_safety_answer_survives_fuel_evidence_guard():
    question = "\u6db2\u4f53\u9152\u7cbe\u7089\u5728\u5e10\u7bf7\u91cc\u80fd\u7528\u5417\uff1f\u4e3a\u4ec0\u4e48\uff1f"
    original_answer = (
        "\u5b89\u5168\u7ed3\u8bba\uff1a\u4e0d\u8981\u5728\u5e10\u7bf7\u5185\u6216\u5176\u4ed6\u5bc6\u95ed\u3001"
        "\u901a\u98ce\u4e0d\u8db3\u7684\u7a7a\u95f4\u4f7f\u7528\u71c3\u70e7\u578b\u7089\u5177\u3002"
    )
    result = {
        "answer_type": "product_usage_care",
        "answer": original_answer,
        "result_skus": [],
        "candidate_skus": [],
        "results": [],
        "sources": [],
        "debug": {},
    }

    shaped = service._clear_unrelated_catalogue_cards(question, result)

    assert shaped["answer"] == original_answer
    assert shaped["debug"].get("agent_mode") != "explicit_fuel_subtype_evidence_scope_guard"


def test_tent_fuel_safety_bypasses_unbound_fuel_identity_guard():
    question = "液体酒精炉在帐篷里能用吗？为什么？"
    bypass = getattr(service, "_is_unbound_environmental_fuel_safety_question", None)

    assert service._is_unbound_fuel_compatibility_question(question)
    assert callable(bypass)
    assert bypass(question)


def test_generic_tent_fuel_usage_route_reaches_safety_answer(monkeypatch):
    question = "液体酒精炉在帐篷里能用吗？为什么？"
    monkeypatch.setattr(intent_service, "_explicit_products_from_question", lambda _db, _text: [])
    monkeypatch.setattr(intent_service, "_narrow_contents_grounding_products", lambda _db, _text, products: products)

    async def no_product_evidence(*_args, **_kwargs):
        return [], [], {
            "product_qa_ms": 0,
            "knowledge_search_ms": 0,
            "rerank_ms": 0,
            "filtered_or_downgraded": [],
        }

    monkeypatch.setattr(intent_service, "_search_usage_care_qa", no_product_evidence)
    result = asyncio.run(
        intent_service.answer_product_usage_care_request(
            None,
            question=question,
            named_products=[],
        )
    )

    assert result is not None
    assert result["debug"]["agent_mode"] == "product_usage_care_fast_path"
    assert "帐篷" in result["answer"]
    assert "通风" in result["answer"]
    assert "请提供具体商品名或 SKU" not in result["answer"].split("安全提醒", 1)[0]


def test_ordinal_followup_uses_named_category_order_when_context_is_mixed():
    context = {
        "ordinal_reference_skus": ["GAS-1", "KETTLE-1", "POT-1"],
        "ordinal_reference_scope_skus": {
            "炉具": ["GAS-1"],
            "水具": ["KETTLE-1"],
            "锅具": ["POT-1"],
        },
    }

    assert service._ordinal_followup_target_sku(
        "第一个烧水壶的容量是多少？", context, None
    ) == "KETTLE-1"


def test_unsupported_gifting_marketing_claim_is_replaced_by_evidence_boundary():
    helper = getattr(service, "_bound_gifting_qa_answer_to_evidence", None)
    assert callable(helper)
    answer = helper(
        "饭盒适合送人吗？",
        "非常适合！包装精美、品质出众，是送给户外露营爱好者的绝佳礼物。",
    )

    assert "包装精美" not in answer
    assert "品质出众" not in answer
    assert "绝佳礼物" not in answer
    assert "未直接标注" in answer or "无法确认" in answer or "资料" in answer
