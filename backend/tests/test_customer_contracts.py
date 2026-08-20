import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from app.models.product import Product
from app.services import customer_agent_planner_service, customer_entity_resolution_contract, customer_field_contract, customer_recommendation_verification_contract, customer_service_service
from app.services.customer_entity_resolution_contract import build_entity_resolution_contract, build_entity_resolution_contract_observation
from app.services.customer_field_contract import (
    classify_product_qa_evidence_type,
    detect_field_contract,
    field_contract_metadata,
    is_supported_detail_field,
    product_detail_field_label,
    qa_evidence_matches_field,
    resolve_requested_field_contract,
    semantic_preplan_field_type,
    strip_leading_entity_reference_modifier,
)


def _product(sku: str, name: str, category: str = "锅具") -> Product:
    return Product(id=f"id-{sku}", sku=sku, product_name_cn=name, product_name_en=name, category=category)


@pytest.mark.parametrize(
    ("question", "field_type"),
    [
        ("某商品的货号是多少", "sku"),
        ("某商品的SKU是什么", "sku"),
        ("某商品的型号是多少", "model"),
        ("某商品大小是多少", "dimensions"),
        ("某商品收纳尺寸是多少", "dimensions"),
        ("某商品规格是什么", "specification"),
        ("某商品容量是多少", "capacity"),
        ("某商品净重是多少", "weight"),
        ("某商品几个人用", "people"),
        ("某商品材质是什么", "material"),
        ("某商品颜色是什么", "color"),
        ("某商品适用热源是什么", "heat_source"),
        ("某商品能进洗碗机吗", "dishwasher"),
        ("某商品有赠品吗", "gift"),
        ("某商品多少钱", "price"),
        ("某商品包含什么", "accessories"),
    ],
)
def test_field_contract_classifies_shared_aliases(question, field_type):
    assert detect_field_contract(question).field_type == field_type


@pytest.mark.parametrize("product_code", ["ZX-NO-SKU", "AB_SKU_2026"])
def test_field_alias_inside_product_code_is_not_a_field_contract(product_code):
    assert detect_field_contract(f"{product_code} 到手价多少？") is None


def test_field_contract_maps_supported_canonical_fields_into_semantic_allowlist():
    assert semantic_preplan_field_type("sku") == "sku"
    assert semantic_preplan_field_type("model") == "model"
    assert semantic_preplan_field_type("capacity") == "capacity"


def test_customer_visible_heat_source_label_never_leaks_canonical_field_name():
    assert product_detail_field_label("heat_source") == "适用热源"


def test_sku_and_model_number_are_distinct_customer_contracts():
    """A record key is not evidence of a manufacturer model number.

    The catalogue has ``products.sku`` but no ``products.model`` column.  SKU
    questions may therefore answer from that column; model-number questions
    must remain a distinct, safely-missing formal field.
    """
    assert detect_field_contract("某商品的SKU是什么").field_type == "sku"
    assert detect_field_contract("某商品的货号是多少").field_type == "sku"
    assert detect_field_contract("某商品的型号是多少").field_type == "model"
    assert is_supported_detail_field("sku") is True
    assert is_supported_detail_field("model") is False


def test_semantic_preplan_uses_the_formal_canonical_taxonomy_for_safe_fields():
    assert semantic_preplan_field_type("manual") == "manual"
    assert semantic_preplan_field_type("after_sales_contact") == "after_sales_contact"
    assert semantic_preplan_field_type("shipping") == "shipping"
    assert semantic_preplan_field_type("stock") == "inventory"
    assert semantic_preplan_field_type("contents") == "accessories"
    assert semantic_preplan_field_type("fuel") == "heat_source"
    assert semantic_preplan_field_type("fuel_source") == "heat_source"
    assert semantic_preplan_field_type("fuel_type") == "heat_source"


def test_semantic_preplan_ignores_provider_decorations_without_losing_meaning_requirements():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "subject_text": "cookware",
            "canonical_fields": [],
            "evidence_kind": "structured_field",
            "confidence": 0.92,
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "decision_requested": True,
            "recommendation_constraints": {"subject_kind": "cookware"},
            "unrepresented_recommendation_requirements": ["\u4e0d\u7c98\u6d82\u5c42"],
            "recommendation_evidence_requirements": [],
            "recommendation_soft_preferences": [],
            # Gemini/Flash sometimes echoes these convenience fields. They
            # are not part of the canonical semantic plan and must not turn a
            # valid recommendation into a legacy-route fallback.
            "comparison_participants": [],
            "product_anchor": {},
        }
    )

    assert result["route_family"] == "recommendation"
    assert result["confidence"] == 0.92
    assert result["fallback_reason"] == ""
    assert result["unrepresented_recommendation_requirements"] == ["\u4e0d\u7c98\u6d82\u5c42"]


def test_semantic_preplan_preserves_supplemental_same_sku_qa_for_mixed_product_fact():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "示例水袋",
            "canonical_fields": ["certification"],
            "field_type": "certification",
            "field_hint": "certification",
            "evidence_kind": "structured_field",
            "supplemental_qa_evidence_query": "是否可以直接装开水",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The question asks for one recorded certification and one separate capability.",
        }
    )

    assert result["canonical_fields"] == ["certification"]
    assert result["supplemental_qa_evidence_query"] == "是否可以直接装开水"
    assert not result["fallback_reason"]


def test_semantic_preplan_preserves_supplemental_same_sku_qa_for_mixed_comparison():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "entities": ["Alpha", "Beta"],
            "subject_text": "Alpha and Beta",
            "canonical_fields": ["weight"],
            "field_type": "weight",
            "field_hint": "weight",
            "evidence_kind": "structured_field",
            "supplemental_qa_evidence_query": "packing and storage convenience",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The comparison asks for weight and storage.",
        }
    )

    assert result["canonical_fields"] == ["weight"]
    assert result["supplemental_qa_evidence_query"] == "packing and storage convenience"
    assert not result["fallback_reason"]


def test_semantic_compound_adapter_separates_capability_from_safety_evaluation(monkeypatch):
    """A semantic subtask must retrieve compatibility, never manufacture safety."""
    prompts = []

    async def fake_chat_completion(_db, messages, **_kwargs):
        prompts.append(messages)
        return '{"capability_query":"high-altitude use compatibility","safety_evaluation_requested":true}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service._semantic_compound_supplemental_query(
            None,
            question="Is Sample stove material safe for high-altitude use?",
            canonical_fields=["material"],
            runtime_settings={"max_tokens": 512, "model": "test", "response_format": None, "thinking": None},
        )
    )

    assert result == {
        "capability_query": "high-altitude use compatibility",
        "safety_evaluation_requested": True,
    }
    assert "not material safety" in prompts[0][0]["content"]


def test_compound_supplement_keeps_safe_missing_as_rag_fallback_only():
    safe_missing = {"debug": {"agent_mode": "sealed_product_qa_safe_missing"}}
    grounded = {"debug": {"agent_mode": "sealed_same_sku_knowledge_rag"}}

    assert customer_service_service._is_sealed_product_qa_safe_missing(safe_missing)
    assert not customer_service_service._is_sealed_product_qa_safe_missing(grounded)


def test_compound_supplement_uses_same_sku_rag_before_qa_fallback(monkeypatch):
    calls = []

    async def rag_grounded(_db, question, phase1_plan):
        calls.append(("rag", question, phase1_plan["semantic_preplan"]["qa_evidence_query"]))
        return {"debug": {"agent_mode": "sealed_same_sku_knowledge_rag"}, "result_skus": ["SKU-1"]}

    monkeypatch.setattr(customer_service_service, "_try_sealed_same_sku_knowledge_answer", rag_grounded)

    result, query = asyncio.run(
        customer_service_service._resolve_sealed_supplemental_product_evidence(
            None,
            question="Sample stove material safety plus altitude use?",
            semantic_preplan={
                "subject_text": "Sample stove",
                "supplemental_qa_evidence_query": "high-altitude compatibility",
            },
        )
    )

    assert query == "high-altitude compatibility"
    assert result["debug"]["agent_mode"] == "sealed_same_sku_knowledge_rag"
    assert calls == [
        ("rag", "Sample stove high-altitude compatibility", "high-altitude compatibility"),
    ]


def test_compound_supplement_keeps_rag_miss_instead_of_structured_field_fallback(monkeypatch):
    calls = []
    qa_safe_missing = {
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
        "result_skus": ["SKU-1"],
        "results": [{"sku": "SKU-1", "product_name_cn": "示例锅"}],
    }

    async def qa(_db, question, *, phase1_plan):
        calls.append(("qa", question, phase1_plan["semantic_preplan"]["qa_evidence_query"]))
        return qa_safe_missing

    async def rag(_db, question, phase1_plan):
        calls.append(("rag", question, phase1_plan["semantic_preplan"]["qa_evidence_query"]))
        return None

    async def forbidden_structured(*_args, **_kwargs):
        raise AssertionError("semantic supplemental RAG miss must not use structured field writer")

    monkeypatch.setattr(customer_service_service, "_try_product_qa_shortcut_with_semantic_selection", qa)
    monkeypatch.setattr(customer_service_service, "_try_sealed_same_sku_knowledge_answer", rag)
    monkeypatch.setattr(customer_service_service, "_try_same_sku_structured_best_effort_answer", forbidden_structured)

    result, query = asyncio.run(
        customer_service_service._resolve_sealed_supplemental_product_evidence(
            None,
            question="示例锅两人使用够吗？",
            semantic_preplan={
                "subject_text": "示例锅",
                "supplemental_qa_evidence_query": "两人使用是否够用",
            },
        )
    )

    assert query == "两人使用是否够用"
    assert result is qa_safe_missing
    assert calls == [
        ("rag", "示例锅 两人使用是否够用", "两人使用是否够用"),
        ("rag", "示例锅 两人使用是否够用", "两人使用是否够用"),
        ("rag", "示例锅 两人使用是否够用", "两人使用是否够用"),
        ("qa", "示例锅 两人使用是否够用", "两人使用是否够用"),
    ]


def test_rag_safety_boundary_does_not_upgrade_compatibility_to_a_guarantee():
    answer, bounded = customer_service_service._bound_unsupported_rag_safety_guarantee(
        "You can use it without worry; there will be no problem.",
        {"evidence_quotes": ["adapted to high-altitude conditions"]},
        "The product is adapted to high-altitude conditions.",
    )

    assert bounded is True
    assert "adapted to high-altitude conditions" in answer
    assert "保证" in answer


def test_semantic_preplan_requests_repair_when_model_reports_partial_multi_intent_coverage():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "示例商品",
            "canonical_fields": ["product_name_en"],
            "field_type": "product_name_en",
            "evidence_kind": "structured_field",
            "intent_coverage": "partial",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "A second independently requested product fact was not represented.",
        }
    )

    assert result["intent_coverage"] == "partial"
    assert result["fallback_reason"] == "incomplete_product_bound_multi_intent"


def test_semantic_preplan_preserves_compound_product_qa_signal():
    """The semantic layer, not a lexical fallback, marks two product facts.

    A compound product-QA plan lets the evidence layer retain a supported part
    while safely identifying any independently requested part without direct
    same-SKU evidence.
    """
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "示例水袋",
            "canonical_fields": [],
            "evidence_kind": "product_qa",
            "qa_evidence_query": "耐用性和特定暴露条件",
            "compound": True,
            "intent_coverage": "full",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The customer independently asks durability and an exposure condition.",
        }
    )

    assert result["compound"] is True
    assert not result["fallback_reason"]


def test_semantic_product_qa_scope_review_uses_the_full_question_not_keywords(monkeypatch):
    """The bounded second semantic review owns multi-intent shape detection."""
    seen: dict = {}

    async def fake_completion(_db, *, messages, **_kwargs):
        seen["payload"] = json.loads(messages[-1]["content"])
        return '{"compound":true}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_completion)

    import asyncio

    result = asyncio.run(
        customer_agent_planner_service._semantic_product_qa_scope_review(
            SimpleNamespace(),
            question="Can it perform one task and remain in a specific environment?",
            runtime_settings={"model": "test", "response_format": None, "thinking": None, "max_tokens": 80},
        )
    )

    assert result is True
    assert seen["payload"] == {
        "question": "Can it perform one task and remain in a specific environment?"
    }


def test_supplemental_same_sku_qa_is_held_for_semantic_composition_after_formal_field_repair():
    """A positive supplement is not appended before semantic composition.

    The semantic plan owns the mixed intent.  The provenance helper preserves
    the same-SKU QA packet, while the async composition writer owns the final
    wording so a subjective QA conclusion cannot bypass grounding.
    """
    result = {
        "answer": "示例水袋（AC-19）的产品认证：食品级认证。",
        "result_skus": ["AC-19"],
        "answer_metadata": {"evidence_field": "certification"},
    }
    supplemental = {
        "answer": "同 SKU 问答确认：可以直接装开水。",
        "result_skus": ["AC-19"],
        "answer_metadata": {"evidence_sku": "AC-19", "evidence_field": "product_qa"},
    }

    merged = customer_service_service._merge_supplemental_product_qa_into_field_answer(
        result,
        supplemental=supplemental,
        supplemental_query="是否可以直接装开水",
    )

    assert "食品级认证" in merged["answer"]
    assert "可以直接装开水" not in merged["answer"]
    assert merged["answer_metadata"]["supplemental_product_qa"]["evidence_sku"] == "AC-19"
    assert merged["answer_metadata"]["supplemental_product_qa"]["awaiting_semantic_composition"] is True


def test_sealed_context_anchor_is_eligible_for_compound_field_execution():
    assert "recommendation_context_anchor" in customer_service_service._PHASE2_EXACT_ENTITY_MATCHES


@pytest.mark.skip(reason="Retired legacy preplan gate; the semantic owner now receives every ordinary turn directly.")
def test_named_product_fact_always_reaches_semantic_preplan_before_legacy_recommendation_words():
    assert customer_service_service._should_call_semantic_preplan(
        "示例露营壶适合露营吗？",
        {"primary_intent": "recommend_products"},
        conversation_id=None,
        has_named_product=True,
    ) is True


@pytest.mark.skip(reason="Retired legacy preplan gate; the semantic owner now receives every ordinary turn directly.")
def test_declarative_unrouted_turn_reaches_semantic_preplan_for_navigation_interpretation():
    assert customer_service_service._should_call_semantic_preplan(
        "示例露营壶",
        {"primary_intent": "query_products"},
        conversation_id=None,
        has_named_product=False,
    ) is True


def test_semantic_navigation_identity_confirmation_cannot_be_repaired_into_a_name_token_field():
    result = {
        "answer_type": "product_detail",
        "result_skus": ["CS-EXAMPLE"],
        "answer_metadata": {"source": "semantic_product_navigation_contract"},
        "debug": {"agent_mode": "semantic_product_navigation_contract"},
    }

    assert customer_service_service._enforce_field_evidence_policy(
        None,
        "先查看含炉字的示例商品。",
        result,
    ) is result


def test_explicit_price_positioning_contract_rejects_conflicting_semantic_price():
    """A displayed canonical label is a deterministic contract boundary.

    Semantic planning remains the primary interpreter for natural wording, but
    it cannot turn the formal field label ``价格定位`` into realtime ``价格``.
    """
    result = resolve_requested_field_contract(
        "它的价格定位",
        planner_plan={
            "semantic_preplan": {
                "called": True,
                "canonical_fields": ["price"],
                "field_type": "price",
                "confidence": 0.95,
            },
        },
        subject="它",
        subject_is_catalog_exact=True,
    )

    assert result["field_type"] == "price_positioning"
    assert result["canonical_fields"] == ["price_positioning"]


def test_compound_semantic_product_qa_preempts_a_single_explicit_field_predicate():
    """A complete semantic multi-QA turn must not lose one half to an alias."""
    result = resolve_requested_field_contract(
        "\u793a\u4f8b\u7089\u5177\u5982\u4f55\u8fa8\u522b\u771f\u4f2a\uff1f\u80fd\u5728\u7535\u78c1\u7089\u4e0a\u7528\u5417\uff1f",
        planner_plan={
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "evidence_kind": "product_qa",
                "canonical_fields": [],
                "confidence": 0.95,
                "compound": True,
                "fallback_reason": "",
            },
        },
    )

    assert result["field_type"] is None
    assert result["source"] == "validated_semantic_product_qa"


def test_legacy_unknown_fact_guard_yields_to_formal_price_positioning_contract():
    """A legacy realtime-fact guard cannot preempt a formal product field."""
    assert customer_service_service._unknown_product_fact_result("它的价格定位") is None


def test_entity_subject_normalization_removes_generic_lookup_preamble():
    assert strip_leading_entity_reference_modifier("帮我查一下1-2人野营锅") == "1-2人野营锅"


def test_comparison_plan_precedes_single_product_heat_source_shortcut():
    plan = customer_agent_planner_service.plan_customer_question(
        "旋焰酒精炉(CS-B14)和小圆炉(CS-G35)适用热源有什么不同？"
    )

    assert plan["primary_intent"] == "comparison"
    assert plan["must_compare_both_products"] is True
    assert plan["product_refs"] == ["CS-B14", "CS-G35"]


def test_semantic_comparison_preplan_preserves_verbatim_participants_and_field_contract():
    """Comparison meaning and its participants come from semantic planning, not aliases."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "entities": ["示例甲", "示例乙"],
            "subject_text": "示例甲和示例乙",
            "canonical_fields": ["people"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Two product participants are compared on a person-count field.",
        }
    )

    assert preplan["route_family"] == "comparison"
    assert preplan["route_hint"] == "comparison"
    assert preplan["question_type"] == "comparison"
    assert preplan["entities"] == ["示例甲", "示例乙"]
    assert preplan["canonical_fields"] == ["people"]


def test_semantic_comparison_preplan_normalizes_structured_product_mentions():
    """Provider JSON entity objects must preserve their verbatim mentions for sealing."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "comparison_overview",
            "entities": [
                {"entity_type": "product", "entity_value": "示例甲"},
                {"entity_type": "product", "entity_value": "示例乙"},
            ],
            "subject_text": "示例甲和示例乙",
            "canonical_fields": [],
            "evidence_kind": "structured_field",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Two named products need a factual overview.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["entities"] == ["示例甲", "示例乙"]


def test_semantic_comparison_preplan_accepts_provider_entity_packet_and_pairwise_subtype():
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "subtype": "comparison",
            "entities": {
                "product_mentions": ["示例甲", "示例乙"],
                "entity_scope": "ambiguous_product",
            },
            "subject_text": "示例甲和示例乙",
            "canonical_fields": ["capacity", "people"],
            "evidence_kind": "structured_field",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "decision_requested": True,
            "reasoning_summary": "Two named products are compared on recorded fields.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["route_family"] == "comparison"
    assert preplan["entities"] == ["示例甲", "示例乙"]
    assert preplan["canonical_fields"] == ["capacity", "people"]


def test_semantic_free_text_partition_preserves_bounded_semantic_context():
    question = "给我搭个不插电、好带走的简单组合，别塞一堆不相关的。"

    assert customer_agent_planner_service._literal_customer_phrase_partition(
        question,
        ["简单组合", "simple combination", "别塞一堆不相关的", "no irrelevant items"],
    ) == ["简单组合", "simple combination", "别塞一堆不相关的", "no irrelevant items"]


def test_semantic_structured_comparison_overview_is_not_replaced_by_legacy_field_guess():
    """An empty semantic comparison field list is an intentional overview contract."""
    assert customer_service_service._semantic_structured_comparison_overview_contract(
        {
            "route_family": "comparison",
            "subtype": "comparison_overview",
            "evidence_kind": "structured_field",
            "canonical_fields": [],
            "decision_requested": False,
        }
    )


def test_explicit_product_identity_question_preserves_direct_answer_obligation():
    assert customer_service_service._explicit_product_identity_question(
        "围雪炉酒精版和酒精汽油版是同一款吗？"
    )
    assert customer_service_service._explicit_product_identity_question(
        "这两个 SKU 是不是同一个产品？"
    )
    assert not customer_service_service._explicit_product_identity_question(
        "这两款的材质一样吗？"
    )


def test_semantic_comparison_preserves_explicit_non_decision_flag():
    """Factual differences must not be turned into a product recommendation."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "relation_comparison",
            "entities": ["示例甲", "示例乙"],
            "subject_text": "示例甲和示例乙",
            "canonical_fields": ["weight"],
            "evidence_kind": "structured_field",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The customer asks which named product is lighter.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["decision_requested"] is False


def test_semantic_comparison_normalizes_provider_name_type_entity_objects():
    """A schema-equivalent provider entity object must retain comparison participants."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "relation_comparison",
            "entities": [
                {"name": "CW-C83", "type": "product"},
                {"name": "CW-C95", "type": "product"},
            ],
            "subject_text": "CW-C83 and CW-C95",
            "canonical_fields": ["material"],
            "evidence_kind": "structured_field",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Compare the recorded materials for two products.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["entities"] == ["CW-C83", "CW-C95"]
    assert preplan["canonical_fields"] == ["material"]


def test_semantic_comparison_normalizes_provider_entity_name_objects():
    """The verbose provider schema must retain the same sealed participants."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "comparison_overview",
            "entities": [
                {
                    "entity_type": "product",
                    "entity_name": "京享水壶",
                    "entity_scope": "resolved_product",
                },
                {
                    "entity_type": "product",
                    "entity_name": "小方壶",
                    "entity_scope": "resolved_product",
                },
            ],
            "subject_text": "京享水壶和小方壶",
            "canonical_fields": [],
            "evidence_kind": "structured_field",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Compare the two named products.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["entities"] == ["京享水壶", "小方壶"]


def test_semantic_comparison_normalizes_provider_entity_key_objects():
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "comparison_overview",
            "entities": [
                {"entity": "炊墨套锅", "entity_scope": "product_like"},
                {"entity": "轻途套锅", "entity_scope": "product_like"},
            ],
            "subject_text": "炊墨套锅与轻途套锅",
            "canonical_fields": [],
            "evidence_kind": "structured_field",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Compare the two named products.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["entities"] == ["炊墨套锅", "轻途套锅"]


def test_comparison_overview_normalizes_incompatible_product_qa_evidence_kind():
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "comparison_overview",
            "entities": ["京享水壶", "小方壶"],
            "subject_text": "京享水壶和小方壶",
            "canonical_fields": [],
            "evidence_kind": "product_qa",
            "qa_evidence_query": "实际区别",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Present recorded differences without choosing.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["evidence_kind"] == "structured_field"
    assert preplan["qa_evidence_query"] == ""


def test_non_recommendation_route_ignores_stray_recommendation_constraints():
    """An optional recommendation object must not erase a valid comparison."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "route_hint": "comparison",
            "question_type": "comparison",
            "subtype": "relation_comparison",
            "entities": ["CW-C83", "CW-C06PRO"],
            "subject_text": "CW-C83 和 CW-C06PRO",
            "canonical_fields": ["weight"],
            "evidence_kind": "structured_field",
            "recommendation_constraints": {"unsupported_provider_scope": "choice"},
            "decision_requested": True,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "Compare the named participants by weight.",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["route_family"] == "comparison"
    assert preplan["recommendation_constraints"] == {}


def test_semantic_comparison_preplan_rejects_missing_participants():
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "entities": [],
            "subject_text": "示例甲和示例乙",
            "canonical_fields": ["people"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "A comparison must expose each participant.",
        }
    )

    assert preplan["route_hint"] == ""
    assert preplan["fallback_reason"] == "invalid_comparison_participants"


@pytest.mark.skip(reason="Retired provider-specific comparison subtype gate; the semantic contract no longer requires that label.")
def test_semantic_comparison_preplan_rejects_unknown_subtype_for_semantic_repair():
    """A provider-specific comparison label cannot silently bypass the overview contract."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "comparison",
            "question_type": "comparison",
            "subtype": "product_comparison",
            "entities": ["sample A", "sample B"],
            "subject_text": "sample A and sample B",
            "canonical_fields": [],
            "evidence_kind": "product_qa",
            "qa_evidence_query": "their differences",
            "decision_requested": False,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "A broad factual comparison needs the formal overview shape.",
        }
    )

    assert preplan["fallback_reason"] == "invalid_comparison_subtype"
    assert preplan["route_family"] == ""


def test_semantic_preplan_preserves_formal_field_over_conflicting_qa_source():
    """The model owns the field meaning; code only normalizes its source class."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "entities": ["sample product"],
            "subject_text": "sample product",
            "canonical_fields": ["emotional_value"],
            "evidence_kind": "product_qa",
            "qa_evidence_query": "customer experience",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "conflicting semantic evidence contract",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["canonical_fields"] == ["emotional_value"]
    assert preplan["evidence_kind"] == "structured_field"


def test_semantic_single_product_field_clears_legacy_prefix_comparison_state():
    """A validated singular field cannot inherit a parser-created second SKU."""
    plan = {
        "primary_intent": "comparison",
        "answer_type": "comparison",
        "product_refs": ["AP01-98", "AP01"],
        "must_compare_both_products": True,
        "must_make_choice": True,
        "tasks": [{"type": "product_compare", "products": ["AP01-98", "AP01"]}],
    }
    semantic_preplan = {
        "called": True,
        "route_family": "product_bound_qa",
        "canonical_fields": ["series"],
        "field_type": "series",
        "confidence": 0.9,
    }

    customer_service_service._apply_semantic_single_field_route_precedence(
        plan,
        semantic_preplan,
    )

    assert plan["primary_intent"] == "product_detail"
    assert plan["answer_type"] == "product_detail"
    assert plan["product_refs"] == []
    assert plan["must_compare_both_products"] is False
    assert plan["must_make_choice"] is False
    assert plan["tasks"] == []


def test_semantic_preplan_rejects_partial_contract_when_another_requested_field_is_unknown():
    """Do not silently drop one customer intent and answer only the other."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "sample product",
            "canonical_fields": ["durability", "usage_instruction"],
            "field_type": "usage_instruction",
            "field_hint": "usage_instruction",
            "evidence_kind": "structured_field",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The request includes durability and boiling-water capability.",
        }
    )

    assert preplan["fallback_reason"] == "unknown_canonical_field_in_multi_intent"


def test_semantic_preplan_prompt_keeps_unrepresented_capabilities_in_product_qa():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="sample product durability and compatibility question",
        deterministic_plan={},
        context={},
    )

    system = messages[0]["content"]
    assert "product_qa" in system
    assert "non-column" in system
    assert "Preserve every independent customer requirement" in system


def test_semantic_preplan_preserves_component_bound_product_qa_scope():
    """Component-to-value binding must stay in same-SKU RAG, not one scalar field."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "entities": ["CW-C95"],
            "subject_text": "CW-C95",
            "canonical_fields": [],
            "field_type": "",
            "field_hint": None,
            "evidence_kind": "product_qa",
            "qa_evidence_query": "煮锅、煎盘和水壶分别多大",
            "qa_evidence_queries": ["煮锅的容量或尺寸", "煎盘的容量或尺寸", "水壶的容量或尺寸"],
            "compound": True,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The request needs component-level same-SKU evidence.",
        },
        customer_question="CW-C95 的煮锅、煎盘和水壶分别多大？",
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["evidence_kind"] == "product_qa"
    assert preplan["canonical_fields"] == []
    assert preplan["qa_evidence_queries"] == [
        "煮锅的容量或尺寸",
        "煎盘的容量或尺寸",
        "水壶的容量或尺寸",
    ]
    assert preplan["compound"] is True


def test_semantic_preplan_repairs_compound_component_field_mirror_into_rag():
    """A contradictory field mirror must not send component facts to the scalar renderer."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "entities": ["CW-C95", "煮锅", "煎盘", "水壶"],
            "subject_text": "CW-C95",
            "canonical_fields": [],
            "field_type": "",
            "field_hint": "dimensions",
            "evidence_kind": "structured_field",
            "compound": True,
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "qa_or_usage_care": True,
            "reasoning_summary": "The component values need product QA retrieval.",
        },
        customer_question="CW-C95 的煮锅、煎盘和水壶分别多大？",
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["evidence_kind"] == "product_qa"
    assert preplan["canonical_fields"] == []
    assert preplan["field_type"] == ""
    assert preplan["field_hint"] is None


def test_semantic_preplan_prompt_explains_component_bound_rag_scope():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="CW-C95 的煮锅、煎盘和水壶分别多大？",
        deterministic_plan={},
        context={},
    )

    system = messages[0]["content"]
    assert "named components or parts of a set/bundle" in system
    assert "do not force the whole turn into one scalar field" in system
    assert "component-bound RAG question" in system


def test_semantic_preplan_routes_model_identified_unsafe_compliance_to_sealed_evidence():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "safety",
            "entities": ["TEST-SKU-1"],
            "subject_text": "TEST-SKU-1",
            "canonical_fields": [],
            "field_type": "",
            "field_hint": None,
            "evidence_kind": "product_qa",
            "qa_evidence_query": "燃烧过程中添加燃料的安全操作",
            "confidence": "low",
            "ambiguity": False,
            "evidence_required": True,
            "unsafe_or_fabricated_answer_requested": True,
            "context_usage": "none",
            "reasoning_summary": "The underlying operation is clear but unsafe compliance was requested.",
        },
        raw_content="{}",
        customer_question="请编造 TEST-SKU-1 燃烧时可以补充燃料的说法。",
    )

    assert result["fallback_reason"] == ""
    assert result["unsafe_or_fabricated_answer_requested"] is True
    assert result["confidence_label"] == "high"
    assert result["accepted_or_overridden"] == "unsafe_request_routed_to_sealed_evidence"
    assert result["evidence_kind"] == "product_qa"
    assert result["qa_evidence_query"] == "燃烧过程中添加燃料的安全操作"


def test_semantic_preplan_prompt_preserves_underlying_question_for_unsafe_compliance():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="named product unsafe fabrication request",
        deterministic_plan={},
        context={},
    )

    system = messages[0]["content"]
    assert "unsafe_or_fabricated_answer_requested" in system
    assert "Plan the legitimate underlying question" in system
    assert "same-product RAG" in system


@pytest.mark.skip(reason="Retired phrase-level prompt assertion; the live planner is intentionally shorter and model-owned.")
def test_semantic_preplan_prompt_keeps_broad_named_product_overviews_out_of_single_field_contracts():
    """Open evidence-backed product overviews are QA/RAG work, not inferred selling-point requests."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="What should I know about this named product before a trip?",
        deterministic_plan={},
        context={"has_unique_current_turn_catalog_product_name": True},
    )

    assert "broad evidence-supported overview" in messages[0]["content"]
    assert "do not infer a single field" in messages[0]["content"]
    assert "Only select selling_point when the customer directly asks for highlights" in messages[0]["content"]


@pytest.mark.skip(reason="Retired phrase-level prompt assertion; the live planner is intentionally shorter and model-owned.")
def test_semantic_preplan_prompt_keeps_setting_availability_as_product_qa():
    """Whether a setting exists is a capability question, not a request for every usage step."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="Can this product adjust a setting?",
        deterministic_plan={},
        context={"has_unique_current_turn_catalog_product_name": True},
    )

    assert "setting, adjustment, or control is available" in messages[0]["content"]
    assert "unless the customer explicitly asks for step-by-step operation" in messages[0]["content"]


@pytest.mark.skip(reason="Retired phrase-level prompt assertion; the live planner is intentionally shorter and model-owned.")
def test_semantic_preplan_prompt_separates_promotional_gift_from_gifting_suitability():
    """The promotion field must not swallow an open product-suitability question."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="Is this product suitable to give as a present?",
        deterministic_plan={},
        context={"has_unique_current_turn_catalog_product_name": True},
    )

    system = messages[0]["content"]
    assert "only when the customer asks whether a purchase includes a promotional gift" in system
    assert "gifting suitability is product_qa, not gift" in system


@pytest.mark.skip(reason="Retired phrase-level prompt assertion; identity is validated by the entity contract, not a prompt string.")
def test_semantic_preplan_prompt_preserves_identity_bearing_version_in_subject_span():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="How do I adjust the length of version 1.1 of this named product?",
        deterministic_plan={},
        context={},
    )

    assert "must preserve every customer-stated identity-bearing version or edition" in messages[0]["content"]


def test_semantic_subject_contract_detects_dropped_explicit_numeric_version():
    assert customer_agent_planner_service._semantic_subject_omits_explicit_numeric_version(
        "1.0版本-行川包包椅怎么调长度？", "行川包包椅"
    )
    assert not customer_agent_planner_service._semantic_subject_omits_explicit_numeric_version(
        "1.1版本-行川包包椅怎么调长度？", "1.1版本-行川包包椅"
    )


def test_category_exclusion_uses_catalogue_scope_not_compatible_appliance_in_name():
    contract = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "只推荐锅具，不要炉具和配件。"
    )
    cookware = {
        "sku": "POT-1",
        "product_name_cn": "酒精炉单锅",
        "category": "锅具",
        "sub_category": "单锅",
    }
    stove = {
        "sku": "STOVE-1",
        "product_name_cn": "便携炉",
        "category": "炉具",
        "sub_category": "酒精炉",
    }

    cookware_result, stove_result = (
        customer_recommendation_verification_contract.verify_recommendation_candidates(
            contract, [cookware, stove]
        )
    )

    assert cookware_result.subject_eligible is True
    assert stove_result.subject_eligible is False
    assert "excluded_category" in stove_result.rejection_reasons


def test_customer_polish_lead_rejects_a_duplicate_of_the_verified_body():
    draft = "It can adjust grind coarseness for different brewing methods."

    assert customer_service_service._is_nonduplicative_customer_lead(
        "I checked the verified information for you.", draft
    )
    assert not customer_service_service._is_nonduplicative_customer_lead(
        "It can adjust grind coarseness for different brewing methods.", draft
    )


def test_semantic_named_formal_field_normalizes_provider_subtype_into_field_contract():
    """A provider subtype cannot erase an otherwise valid formal field plan."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subtype": "single_product_fact",
            "entities": ["sample product"],
            "subject_text": "sample product",
            "canonical_fields": ["series"],
            "field_type": "series",
            "field_hint": "series",
            "evidence_kind": "structured_field",
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "context_usage": "none",
            "reasoning_summary": "The customer requests the named product's series.",
        }
    )

    field_contract = customer_field_contract.resolve_requested_field_contract(
        "CW-C95 belongs to which series?",
        {"semantic_preplan": preplan},
    )

    assert preplan["subtype"] == "known_detail"
    assert field_contract["field_type"] == "series"
    assert field_contract["source"] == "validated_semantic_preplan"


def test_resolved_named_product_contract_uses_unique_canonical_subject_before_full_question():
    product = _product("SKU-CHOP", "便携式户外旅行筷")

    class Query:
        def order_by(self, *_args):
            return self

        def all(self):
            return [product]

    class Db:
        def query(self, _model):
            return Query()

    assert customer_service_service._has_resolved_named_product_contract(
        Db(),
        "便携式户外旅行筷有哪些值得留意的地方？",
    )






def test_semantic_comparison_field_forms_the_same_formal_field_contract():
    field_contract = resolve_requested_field_contract(
        "示例甲和示例乙，哪个更适合多人使用？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "comparison",
                "route_hint": "comparison",
                "question_type": "comparison",
                "subtype": "relation_comparison",
                "entities": ["示例甲", "示例乙"],
                "field_type": "people",
                "field_hint": "people",
                "canonical_fields": ["people"],
                "confidence": 0.9,
            }
        },
    )

    assert field_contract["canonical_fields"] == ["people"]
    assert field_contract["source"] == "validated_semantic_preplan"


def test_semantic_comparison_builds_an_entity_contract_for_each_verbatim_participant():
    products = [
        _product("SKU-A", "示例甲"),
        _product("SKU-B", "示例乙"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["示例甲", "示例乙"],
        "canonical_fields": ["people"],
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "示例甲和示例乙，哪个更适合多人使用？",
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["SKU-A", "SKU-B"]
    assert all(contract.status == "resolved" for contract in contracts)
    assert [contract.field_type for contract in contracts] == ["people", "people"]




def test_semantic_comparison_keeps_each_participant_local_when_only_one_is_sku():
    """One explicit SKU must not overwrite a second named comparison participant."""
    products = [
        _product("CW-C95", "风暴炉pro-两用版"),
        _product("CS-B15S", "围雪炉-酒精版"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["CW-C95", "围雪炉-酒精版"],
        "canonical_fields": [],
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "CW-C95和围雪炉-酒精版分别有什么特点？",
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["CW-C95", "CS-B15S"]


def test_semantic_comparison_can_seal_one_prior_turn_anchor():
    products = [
        _product("SKU-A", "Alpha"),
        _product("SKU-B", "Beta"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["SKU-B", "SKU-A"],
        "canonical_fields": ["weight"],
        "context_usage": "entity_anchor",
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "Compared with SKU-B, which is lighter?",
        preplan,
        products,
        context_anchor_sku="SKU-A",
    )

    assert [contract.resolved_sku for contract in contracts] == ["SKU-B", "SKU-A"]
    assert contracts[1].status_reason == "trusted_context_anchor_exact"


def test_semantic_comparison_rejects_non_current_participant_without_anchor_contract():
    products = [
        _product("SKU-A", "Alpha"),
        _product("SKU-B", "Beta"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["SKU-B", "SKU-A"],
        "canonical_fields": ["weight"],
        "context_usage": "none",
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "Compared with SKU-B, which is lighter?",
        preplan,
        products,
        context_anchor_sku="SKU-A",
    )

    assert contracts == []


def test_semantic_comparison_seals_catalogue_exact_coordinated_ellipsis():
    products = [
        _product("KETTLE-4", "SwanKettle4Black"),
        _product("KETTLE-9", "SwanKettle9Black"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["SwanKettle4Black", "SwanKettle9Black"],
        "canonical_fields": ["capacity", "people"],
        "confidence": 0.95,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "Compare SwanKettle4Black and 9Black by capacity and people.",
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["KETTLE-4", "KETTLE-9"]


def test_semantic_comparison_rejects_unsealed_nonliteral_expansion():
    products = [
        _product("KETTLE-4", "SwanKettle4Black"),
        _product("OTHER-9", "OtherKettle9Black"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["SwanKettle4Black", "OtherKettle9Black"],
        "canonical_fields": ["capacity"],
        "confidence": 0.95,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "Compare SwanKettle4Black and 9Black.",
        preplan,
        products,
    )

    assert contracts == []


def test_literal_kettle_followup_recovers_scope_and_compact_capacity_preference():
    contract = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "通常两三个人喝，壶别太大，你会留哪款？",
        semantic_constraints={"people": {"min": 2, "max": 3}},
    )

    assert contract.subject_kind == "waterware"
    assert contract.subject_subtype == "kettle"
    assert "capacity" in contract.soft_preferences
    assert contract.people_min == 2
    assert contract.people_max == 3


def test_high_confidence_semantic_comparison_replaces_legacy_participant_extraction_with_sealed_contracts():
    products = [
        _product("SKU-A", "示例甲"),
        _product("SKU-B", "示例乙"),
    ]
    plan = {"primary_intent": "product_detail", "answer_type": "product_detail", "product_refs": []}
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["示例甲", "示例乙"],
        "canonical_fields": ["people"],
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._apply_semantic_comparison_plan(
        "示例甲和示例乙，哪个更适合多人使用？",
        plan,
        preplan,
        products,
    )

    assert plan["primary_intent"] == "comparison"
    assert plan["answer_type"] == "comparison"
    assert plan["product_refs"] == ["SKU-A", "SKU-B"]
    assert [contract.resolved_sku for contract in contracts] == ["SKU-A", "SKU-B"]
    assert plan["semantic_comparison_entity_contracts"] == [contract.to_dict() for contract in contracts]


def test_semantic_pairwise_recommendation_uses_the_same_sealed_entity_contracts_as_comparison():
    products = [
        _product("SKU-A", "示例甲"),
        _product("SKU-B", "示例乙"),
    ]
    plan = {"primary_intent": "recommendation", "answer_type": "recommendation", "product_refs": []}
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "entities": ["示例甲", "示例乙"],
        "canonical_fields": [],
        "decision_requested": True,
        "confidence": 0.9,
        "ambiguity": False,
    }

    contracts = customer_service_service._apply_semantic_comparison_plan(
        "示例甲和示例乙，我该买哪个？",
        plan,
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["SKU-A", "SKU-B"]
    assert all(contract.status == "resolved" for contract in contracts)
    assert plan["primary_intent"] == "comparison"
    assert plan["must_make_choice"] is True
    assert plan["semantic_comparison_entity_contracts"] == [contract.to_dict() for contract in contracts]


def test_semantic_pairwise_choice_without_a_requested_field_clarifies_instead_of_legacy_default_selection():
    result = customer_service_service._semantic_pairwise_missing_criterion_result(
        [
            {"sku": "SKU-A", "product_name_cn": "示例甲"},
            {"sku": "SKU-B", "product_name_cn": "示例乙"},
        ],
        [
            {"status": "resolved", "resolved_sku": "SKU-A"},
            {"status": "resolved", "resolved_sku": "SKU-B"},
        ],
    )

    assert result["answer_type"] == "clarification"
    assert result["candidate_skus"] == ["SKU-A", "SKU-B"]
    assert result["result_skus"] == ["SKU-A", "SKU-B"]
    assert result["answer_metadata"]["final_choice_sku"] is None
    assert result["debug"]["agent_mode"] == "semantic_pairwise_missing_criterion_clarification"
    assert "容量、重量、使用场景或预算" in result["answer"]






def test_semantic_comparison_owns_the_decision_request_not_the_legacy_question_parser():
    products = [_product("SKU-A", "示例甲"), _product("SKU-B", "示例乙")]
    plan = {"primary_intent": "comparison", "answer_type": "comparison", "must_make_choice": True}
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["示例甲", "示例乙"],
        "canonical_fields": ["people"],
        "decision_requested": False,
        "confidence": 0.9,
        "ambiguity": False,
    }

    customer_service_service._apply_semantic_comparison_plan(
        "示例甲和示例乙的适用人数有什么不同？",
        plan,
        preplan,
        products,
    )

    assert plan["must_make_choice"] is False


def test_semantic_comparison_adjudication_accepts_only_a_sealed_participant_index_and_evidence_fields():
    decision = customer_service_service._validate_semantic_comparison_adjudication(
        {
            "selected_index": 1,
            "evidence_fields": ["usage_scene", "selling_point"],
            "reasoning_summary": "The sealed evidence for participant 2 better matches the stated scenario.",
        },
        participant_count=2,
        allowed_evidence_fields={"usage_scene", "selling_point"},
    )

    assert decision == {
        "selected_index": 1,
        "evidence_fields": ["usage_scene", "selling_point"],
        "reasoning_summary": "The sealed evidence for participant 2 better matches the stated scenario.",
    }


def test_semantic_comparison_adjudication_rejects_identity_or_unsealed_evidence_claims():
    assert customer_service_service._validate_semantic_comparison_adjudication(
        {
            "selected_index": 1,
            "selected_sku": "SKU-B",
            "evidence_fields": ["usage_scene"],
        },
        participant_count=2,
        allowed_evidence_fields={"usage_scene"},
    ) is None


def test_semantic_comparison_adjudication_accepts_a_safe_no_choice_without_evidence_claims():
    assert customer_service_service._validate_semantic_comparison_adjudication(
        {
            "selected_index": None,
            "evidence_fields": [],
            "reasoning_summary": "The sealed evidence does not support preferring either participant.",
        },
        participant_count=2,
        allowed_evidence_fields={"usage_scene"},
    ) == {
        "selected_index": None,
        "evidence_fields": [],
        "reasoning_summary": "The sealed evidence does not support preferring either participant.",
    }


@pytest.mark.skip(reason="Retired duplicate comparison grounding reviewer; one sealed semantic adjudication is the live path.")
def test_semantic_comparison_adjudication_uses_the_same_constrained_semantic_model_runtime(monkeypatch):
    captured = []

    async def fake_chat_completion(db, messages, **kwargs):
        captured.append({**kwargs, "messages": messages})
        if kwargs.get("purpose") == "semantic_comparison_adjudication_grounding_review":
            return '{"approved":true,"reasoning_summary":"the selected participant is directly supported and has no contrary evidence"}'
        return '{"selected_index":1,"evidence_fields":["usage_scene"],"reasoning_summary":"sealed evidence supports participant 2"}'

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="示例甲和示例乙，哪一个更适合家庭使用？",
            participant_count=2,
            evidence_packet={
                "usage_scene": [
                    {"participant_index": 0, "value": "单人露营"},
                    {"participant_index": 1, "value": "家庭野餐"},
                ],
                "capacity": [
                    {"participant_index": 0, "value": "1L"},
                    {"participant_index": 1, "value": "2L"},
                ],
            },
        )
    )

    assert decision and decision["selected_index"] == 1
    assert [item["purpose"] for item in captured] == [
        "semantic_comparison_adjudication",
        "semantic_comparison_adjudication_grounding_review",
    ]
    assert all(item["api_model_override"] == "deepseek-v4-flash" for item in captured)
    assert all(item["response_format"] == {"type": "json_object"} for item in captured)
    assert all(item["thinking"] == {"type": "disabled"} for item in captured)
    assert "minimal, directly sufficient evidence fields" in captured[0]["messages"][0]["content"]
    assert "a missing participant row means unknown, never positive evidence" in captured[0]["messages"][0]["content"]
    assert "another participant is explicitly contradicted by a stated hard requirement" in captured[0]["messages"][0]["content"]
    assert "Return only JSON: {\"approved\":boolean}. Do not explain." in captured[1]["messages"][0]["content"]
    assert "Do not require an exact requested-value row for the selected participant" in captured[1]["messages"][0]["content"]
    assert "Do not independently re-decide which participant is more suitable" in captured[1]["messages"][0]["content"]
    assert captured[1]["max_tokens"] == 40
    review_payload = json.loads(captured[1]["messages"][1]["content"])
    assert set(review_payload["sealed_evidence"]) == {"usage_scene"}


def test_comparison_adjudication_can_include_partial_fields_without_treating_missing_as_a_value(monkeypatch):
    first = SimpleNamespace(sku="SKU-A")
    second = SimpleNamespace(sku="SKU-B")
    bundles = [(first, None, None, None), (second, None, None, None)]

    def structured(field, **kwargs):
        sku = kwargs["product"].sku
        if field == "people":
            return ("", None) if sku == "SKU-A" else ("1-2人", "business.people")
        if field == "usage_scene":
            return (
                ("家庭露营", "business.usage_scene")
                if sku == "SKU-A"
                else ("单人露营", "business.usage_scene")
            )
        return "", None

    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        structured,
    )

    complete = customer_service_service._comparison_adjudication_evidence(
        db=None,
        bundles=bundles,
    )
    progressive = customer_service_service._comparison_adjudication_evidence(
        db=None,
        bundles=bundles,
        include_partial=True,
    )

    assert "people" not in complete
    assert progressive["people"] == [{
        "participant_index": 1,
        "sku": "SKU-B",
        "value": "1-2人",
        "source": "business.people",
    }]
    assert len(progressive["usage_scene"]) == 2


@pytest.mark.skip(reason="Retired duplicate comparison grounding reviewer; one sealed semantic adjudication is the live path.")
def test_semantic_comparison_adjudication_removes_a_choice_rejected_by_independent_grounding_review(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        if kwargs.get("purpose") == "semantic_comparison_adjudication":
            return '{"selected_index":1,"evidence_fields":["capacity","target_audience"],"reasoning_summary":"participant 2 looks larger"}'
        return '{"approved":false,"reasoning_summary":"the selected participant is marked for 1-2 people, contrary to the four-person request"}'

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat_completion)
    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="四个人露营应该选哪个？",
            participant_count=2,
            evidence_packet={
                "capacity": [
                    {"participant_index": 0, "value": "3.7L+2.3L"},
                    {"participant_index": 1, "value": "3L+1.7L"},
                ],
                "target_audience": [
                    {"participant_index": 0, "value": "家庭露营"},
                    {"participant_index": 1, "value": "1-2人露营者"},
                ],
            },
        )
    )

    assert calls == [
        "semantic_comparison_adjudication",
        "semantic_comparison_adjudication_grounding_review",
    ]
    assert decision["selected_index"] is None
    assert decision["evidence_fields"] == ["capacity", "target_audience"]


def test_semantic_comparison_without_sealed_participants_fails_closed_before_legacy_compare_paths():
    result = customer_service_service._semantic_comparison_fail_closed_result(
        {
            "called": True,
            "route_family": "comparison",
            "entities": ["示例甲", "示例乙"],
            "confidence": 0.9,
        }
    )

    assert result is not None
    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == []
    assert result["needs_clarification"] is True
    assert result["debug"]["agent_mode"] == "semantic_comparison_unsealed_clarification"
    assert "示例甲" not in result["answer"]
    assert customer_service_service._semantic_comparison_fail_closed_result(
        {"called": True, "route_family": "product_bound_qa"}
    ) is None
    assert customer_service_service._validate_semantic_comparison_adjudication(
        {
            "selected_index": 1,
            "evidence_fields": ["unsealed_field"],
        },
        participant_count=2,
        allowed_evidence_fields={"usage_scene"},
    ) is None


def test_semantic_pairwise_realtime_price_comparison_fails_closed_without_unrelated_choice():
    result = customer_service_service._semantic_pairwise_realtime_fields_result(
        [
            {"sku": "SKU-A", "product_name_cn": "示例甲"},
            {"sku": "SKU-B", "product_name_cn": "示例乙"},
        ],
        [{"status": "resolved", "resolved_sku": "SKU-A"}, {"status": "resolved", "resolved_sku": "SKU-B"}],
        ["price"],
    )

    assert result["answer_type"] == "comparison"
    assert result["result_skus"] == ["SKU-A", "SKU-B"]
    assert result["answer_metadata"]["final_choice_sku"] is None
    assert result["answer_metadata"]["contract_field_types"] == ["price"]
    assert result["debug"]["agent_mode"] == "semantic_pairwise_realtime_field_boundary"
    assert "实时价格" in result["answer"]
    assert "不能判断哪款更便宜" in result["answer"]
    assert "容量" not in result["answer"]


def test_single_catalog_recommendation_is_not_misclassified_as_an_unsealed_comparison():
    assert customer_service_service._semantic_comparison_fail_closed_result(
        {
            "called": True,
            "route_family": "recommendation",
            "entities": [],
            "decision_requested": True,
            "confidence": 0.9,
        }
    ) is None


def test_people_evidence_policy_accepts_explicit_headcount_from_same_sku_selling_points():
    policy = customer_field_contract.field_evidence_policy("people")

    assert policy is not None
    assert policy.structured_fields == ("business.target_audience", "business.top_selling_points")


@pytest.mark.skip(reason="Retired exhaustive prompt wording assertion; taxonomy meaning is now supplied through the compact semantic contract.")
def test_semantic_preplan_prompt_distinguishes_category_from_series():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="示例商品算哪类产品？",
        deterministic_plan={},
        context={},
    )
    system = messages[0]["content"]
    assert "category=the product kind, class, merchandise type, or taxonomy bucket" in system
    assert "series=a named product family, collection, or product line" in system
    assert "do not reinterpret a generic classification request as series" in system
    assert "sku=the SKU, item number, product code" in system
    assert "never substitute SKU, item number, product code" in system
    assert "barcode=an EAN, UPC, GTIN, scannable barcode" in system
    assert "never map a SKU, model, item number, product code, or catalogue code to barcode" in system
    assert "rated output or power must use power, not specification" in system
    assert "people=a numeric or bounded group-size fact" in system
    assert "target_audience=the user personas, customer types, or groups" in system
    assert "heat_source=compatible stove types, heating methods, fuel sources" in system
    assert "usage_instruction=operating or usage steps for the product" in system
    assert "dishwasher=only whether the product is explicitly dishwasher-safe" in system
    assert "generic machine-wash or washing-machine compatibility belongs to cleaning" in system
    assert "never translate generic machine-wash wording into dishwasher" in system
    assert "care=maintenance, upkeep, drying before storage" in system
    assert "product_level=the catalogue's grade or tier label" in system
    assert "product_level requires an explicit catalogue grade label" in system
    assert "price_positioning, not product_level" in system
    assert "selling_point=the named product's benefits, highlights, advantages" in system
    assert "emotional_value=the intended feeling, emotional experience, or felt outcome" in system
    assert "do not use selling_point merely because an experience can also be described as a benefit" in system
    assert "technical_advantages=concrete product technologies" in system
    assert "competitor_benchmark=the named product's recorded comparison set" in system
    assert "sales_region=geographic markets, countries, areas, territories, or launch regions" in system
    assert "Asking why one already named product is worth choosing is a product_bound_qa" in system
    assert 'canonical_fields":["series"]' not in messages[1]["content"]


def test_recommendation_preplan_ignores_irrelevant_evidence_kind_variant():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "subtype": "product_selection",
            "entities": [],
            "subject_text": "",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": False,
            "evidence_kind": "recommendation",
            "qa_evidence_query": "",
            "context_usage": "none",
            "decision_requested": False,
            "information_scope": "",
            "reasoning_summary": "customer requests product options",
            "recommendation_constraints": {"subject_kind": "cookware"},
        }
    )

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["evidence_kind"] == "structured_field"


def test_recommendation_preplan_ignores_irrelevant_malformed_structured_query_constraints():
    result = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "recommendation",
            "subtype": "product_selection",
            "entities": [],
            "subject_text": "锅具",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
            "decision_requested": True,
            "reasoning_summary": "Customer requests evidence-backed cookware options.",
            "recommendation_constraints": {"subject_kind": "cookware"},
            "structured_query_constraints": {"field": "heat_source"},
        }
    )

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["recommendation_constraints"]["subject_kind"] == "cookware"
    assert result["structured_query_constraints"] == []


def test_malformed_recommendation_semantic_shape_is_repaired_without_dropping_meaning(monkeypatch):
    responses = iter(
        [
            json.dumps(
                {
                    "route_family": "recommendation",
                    "confidence": "high",
                    "evidence_required": True,
                    "decision_requested": True,
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "heat_sources": ["alcohol_stove"],
                        # Flash understood the phrase but returned it in the
                        # natural-language slot instead of the public enum.
                        "weight_preference": "轻便",
                    },
                    # These are semantic arrays, but the provider serialized
                    # a one-item array as a string and would otherwise lose it.
                    "unrepresented_recommendation_requirements": "适合两人煮面",
                    "recommendation_evidence_requirements": "轻便",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "route_family": "recommendation",
                    "confidence": "high",
                    "evidence_required": True,
                    "decision_requested": True,
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "heat_sources": ["alcohol_stove"],
                        "weight_preference": "lightweight",
                    },
                    "unrepresented_recommendation_requirements": ["适合两人煮面"],
                    "recommendation_evidence_requirements": [],
                    "recommendation_soft_preferences": ["轻便"],
                },
                ensure_ascii=False,
            ),
        ]
    )
    calls = []

    async def fake_chat_completion(_db, _messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        return next(responses)

    monkeypatch.setattr(
        customer_agent_planner_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(
        customer_agent_planner_service,
        "_database_field_value_hints",
        lambda *_args: [],
    )

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "我已经有酒精炉，准备两个人煮面，想买轻便的锅，现有资料里推荐哪款？",
            {},
            context={},
        )
    )

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["fallback_reason"] == ""
    assert result["semantic_repaired"] is True
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "people": {"min": 2, "max": 2},
        "heat_sources": ["alcohol_stove"],
        "weight_preference": "lightweight",
    }
    assert result["unrepresented_recommendation_requirements"] == ["适合两人煮面"]
    assert result["recommendation_soft_preferences"] == ["轻便"]


def test_compact_recommendation_partition_repair_recovers_meaning_after_generic_repair(monkeypatch):
    responses = iter(
        [
            json.dumps(
                {
                    "route_family": "recommendation",
                    "confidence": "high",
                    "evidence_required": True,
                    "decision_requested": True,
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "heat_sources": ["alcohol_stove"],
                        "weight_preference": "轻便",
                    },
                    "unrepresented_recommendation_requirements": "准备两个人煮面",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "route_family": "recommendation",
                    "confidence": "high",
                    "evidence_required": True,
                    "decision_requested": True,
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "heat_sources": ["alcohol_stove"],
                        "weight_preference": "轻便",
                    },
                    "unrepresented_recommendation_requirements": ["准备两个人煮面"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "recommendation_constraints": {
                        "subject_kind": "cookware",
                        "people": {"min": 2, "max": 2},
                        "heat_sources": ["alcohol_stove"],
                        "weight_preference": "lightweight",
                    },
                    "predicate_constraints": [],
                    "unrepresented_recommendation_requirements": ["准备两个人煮面"],
                },
                ensure_ascii=False,
            ),
        ]
    )
    purposes = []

    async def fake_chat_completion(_db, _messages, **kwargs):
        purposes.append(kwargs.get("purpose"))
        return next(responses)

    monkeypatch.setattr(
        customer_agent_planner_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )
    monkeypatch.setattr(
        customer_agent_planner_service,
        "_database_field_value_hints",
        lambda *_args: [],
    )

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "我已经有酒精炉，准备两个人煮面，想买轻便的锅，现有资料里推荐哪款？",
            {},
            context={},
        )
    )

    assert purposes == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_recommendation_constraint_schema_repair",
    ]
    assert result["fallback_reason"] == ""
    assert result["semantic_repaired"] is True
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "people": {"min": 2, "max": 2},
        "heat_sources": ["alcohol_stove"],
        "weight_preference": "lightweight",
    }
    assert result["unrepresented_recommendation_requirements"] == ["准备两个人煮面"]


def test_semantic_preplan_prompt_stays_within_live_provider_budget():
    """Route arbitration needs the contract, not a multi-thousand-token handbook."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="稳稳水袋耐用吗？",
        deterministic_plan={},
        context={},
    )

    assert sum(len(message["content"]) for message in messages) <= 12_000
    assert "can hold a full set of tableware" in messages[0]["content"]


@pytest.mark.skip(reason="Retired exhaustive prompt wording assertion; identity binding is handled by the entity contract and sealed rows.")
def test_semantic_preplan_prompt_exposes_only_unique_catalog_identity_signal():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="便携式户外旅行筷有哪些值得留意的地方？",
        deterministic_plan={},
        context={"has_unique_current_turn_catalog_product_name": True},
    )

    user_packet = json.loads(messages[1]["content"])
    assert user_packet["has_unique_current_turn_catalog_product_name"] is True
    assert "server has independently verified" in messages[0]["content"]
    assert "product_bound_qa" in messages[0]["content"]
    assert "does not provide an SKU, answer, or database value" in messages[0]["content"]


@pytest.mark.skip(reason="Retired route-specific semantic recheck; live planning is one complete-turn parse plus one generic repair.")
def test_unique_catalog_identity_repairs_generic_semantic_route_without_server_route_override(monkeypatch):
    responses = iter(
        [
            json.dumps(
                {
                    "route_family": "generic_query",
                    "route_hint": "query_products",
                    "question_type": "filter",
                    "subtype": "generic_query",
                    "entities": [],
                    "subject_text": "",
                    "canonical_fields": [],
                    "confidence": "high",
                    "ambiguity": False,
                    "evidence_required": False,
                    "evidence_kind": "structured_field",
                    "qa_evidence_query": "",
                    "context_usage": "none",
                    "decision_requested": False,
                    "information_scope": "",
                    "reasoning_summary": "initially treated as a generic catalogue request",
                }
            ),
            json.dumps(
                {
                    "route_family": "product_bound_qa",
                    "route_hint": "product_detail",
                    "question_type": "field",
                    "subtype": "known_detail",
                    "entities": ["便携式户外旅行筷"],
                    "subject_text": "便携式户外旅行筷",
                    "canonical_fields": [],
                    "confidence": "high",
                    "ambiguity": False,
                    "evidence_required": True,
                    "evidence_kind": "product_qa",
                    "qa_evidence_query": "值得留意的产品特点",
                    "context_usage": "none",
                    "decision_requested": False,
                    "information_scope": "",
                    "reasoning_summary": "the customer asks about the uniquely named product",
                }
            ),
        ]
    )
    prompts = []

    async def fake_chat_completion(_db, messages, **_kwargs):
        prompts.append(messages)
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "便携式户外旅行筷有哪些值得留意的地方？",
            {},
            context={"has_unique_current_turn_catalog_product_name": True},
        )
    )

    assert len(prompts) == 2
    assert result["route_family"] == "product_bound_qa"
    assert result["evidence_kind"] == "product_qa"
    assert result["qa_evidence_query"] == "值得留意的产品特点"
    assert "unique catalog product name" in prompts[1][0]["content"]


@pytest.mark.skip(reason="Retired route-specific semantic recheck; live planning is one complete-turn parse plus one generic repair.")
def test_semantic_repair_transport_failure_preserves_valid_recommendation_route(monkeypatch):
    initial = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "subtype": "recommendation",
        "entities": [],
        "subject_text": "",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "decision_requested": True,
        "recommendation_constraints": {
            "subject_kind": "cookware",
            "people": {"min": 3, "max": 3},
            "provider_extra": "malformed optional decoration",
        },
        "recommendation_evidence_requirements": ["non-stick coating"],
        "recommendation_soft_preferences": ["compact storage"],
        "reasoning_summary": "The customer asks for a concrete catalogue recommendation.",
    }

    async def fake_chat_completion(_db, _messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_preplan"
        return json.dumps(initial)

    async def failed_repair(*_args, **_kwargs):
        raise RuntimeError("temporary repair transport failure")

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_repair_semantic_preplan_output", failed_repair)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "Recommend cookware for three campers with non-stick coating.",
            {},
            context={},
        )
    )

    assert result["route_family"] == "recommendation"
    assert result["fallback_reason"] == ""
    assert result["semantic_repair_unavailable"] is True
    assert result["recommendation_constraints"] == {
        "subject_kind": "cookware",
        "people": {"min": 3, "max": 3},
    }
    assert "error" not in result


def test_semantic_preserves_a_complete_product_qa_plan_without_lexical_reclassification(monkeypatch):
    """A complete semantic QA plan remains QA; field meaning stays model-owned."""
    responses = iter(
        [
            json.dumps(
                {
                    "route_family": "product_bound_qa",
                    "route_hint": "product_detail",
                    "question_type": "field",
                    "subtype": "known_detail",
                    "entities": ["Sample product"],
                    "subject_text": "Sample product",
                    "canonical_fields": [],
                    "confidence": "high",
                    "ambiguity": False,
                    "evidence_required": True,
                    "evidence_kind": "product_qa",
                    "qa_evidence_query": "why it is better than comparable products",
                    "context_usage": "none",
                    "decision_requested": False,
                    "information_scope": "",
                    "reasoning_summary": "A product fact without a formal field.",
                }
            ),
        ]
    )
    prompts = []

    async def fake_chat_completion(_db, messages, **_kwargs):
        prompts.append(messages)
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "Why is Sample product better than comparable products?",
            {},
            context={},
        )
    )

    assert len(prompts) == 1
    assert result["canonical_fields"] == []
    assert result["evidence_kind"] == "product_qa"


@pytest.mark.skip(reason="Retired duplicate product-QA reviewer; the initial semantic plan owns intent partitioning.")
def test_semantic_rechecks_compound_product_qa_and_restores_formal_fields(monkeypatch):
    """A broad QA query must not absorb a directly requested recorded field."""
    initial = {
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "subtype": "product_qa",
        "entities": ["Sample stove"],
        "subject_text": "Sample stove",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "product_qa",
        "qa_evidence_query": "supported fuel and maximum power",
        "compound": True,
        "intent_coverage": "full",
        "context_usage": "none",
        "decision_requested": False,
        "information_scope": "",
        "reasoning_summary": "A compound product fact request.",
    }
    repaired = {
        **initial,
        "subtype": "known_detail",
        "canonical_fields": ["heat_source", "power"],
        "field_type": "heat_source",
        "field_hint": "heat_source",
        "evidence_kind": "structured_field",
        "qa_evidence_query": "",
        "reasoning_summary": "Both requested facts map to recorded fields.",
    }
    responses = iter([
        json.dumps(initial),
        json.dumps(repaired),
        '{"capability_query":"","safety_evaluation_requested":false}',
    ])
    purposes = []
    prompts = []

    async def fake_chat_completion(_db, messages, **kwargs):
        prompts.append(messages)
        purposes.append(kwargs.get("purpose"))
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "What fuel does Sample stove support, and what is its maximum power?",
            {},
            context={},
        )
    )

    assert purposes == [
        "semantic_preplan",
        "semantic_preplan_repair",
        "semantic_compound_supplemental_query",
    ]
    assert result["evidence_kind"] == "structured_field"
    assert result["canonical_fields"] == ["heat_source", "power"]
    assert result["supplemental_qa_evidence_query"] == ""
    assert "broad product_qa query must not absorb" in prompts[1][0]["content"]


@pytest.mark.skip(reason="Retired duplicate product-QA reviewer; the initial semantic plan owns intent partitioning.")
def test_semantic_rechecks_a_supplemental_qa_that_is_only_courtesy_scaffolding(monkeypatch):
    """Semantic review removes a non-factual supplement without lexical routing."""
    responses = iter(
        [
            json.dumps(
                {
                    "route_family": "product_bound_qa",
                    "route_hint": "product_detail",
                    "question_type": "field",
                    "subtype": "known_detail",
                    "entities": ["Sample pan"],
                    "subject_text": "Sample pan",
                    "canonical_fields": ["weight"],
                    "field_type": "weight",
                    "field_hint": "weight",
                    "confidence": "high",
                    "ambiguity": False,
                    "evidence_required": True,
                    "evidence_kind": "structured_field",
                    "qa_evidence_query": "",
                    "supplemental_qa_evidence_query": "product introduction",
                    "intent_coverage": "full",
                    "context_usage": "none",
                    "decision_requested": False,
                    "information_scope": "",
                    "reasoning_summary": "Weight plus a generic introduction.",
                }
            ),
            '{"independent":false}',
        ]
    )
    prompts = []

    purposes = []

    async def fake_chat_completion(_db, messages, **kwargs):
        prompts.append(messages)
        purposes.append(kwargs.get("purpose"))
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "Please explain Sample pan's weight for me.",
            {},
            context={},
        )
    )

    # Once semantic review rejects the proposed supplement as courtesy only,
    # the planner must not issue a third supplemental query for this ordinary
    # single-field request.
    assert len(prompts) == 2
    assert purposes == ["semantic_preplan", "semantic_supplemental_intent_review"]
    assert result["canonical_fields"] == ["weight"]
    assert result["supplemental_qa_evidence_query"] == ""
    assert "Courtesy scaffolding" in prompts[1][0]["content"]


@pytest.mark.skip(reason="Retired duplicate product-QA reviewer; the initial semantic plan owns intent partitioning.")
def test_semantic_recheck_preserves_a_real_compound_field_and_capability(monkeypatch):
    """The structural review must not erase a genuinely independent QA intent."""
    compound = {
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "subtype": "known_detail",
        "entities": ["Sample pan"],
        "subject_text": "Sample pan",
        "canonical_fields": ["weight"],
        "field_type": "weight",
        "field_hint": "weight",
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "qa_evidence_query": "",
        "supplemental_qa_evidence_query": "whether it is compatible with gas stoves",
        "intent_coverage": "full",
        "context_usage": "none",
        "decision_requested": False,
        "information_scope": "",
        "reasoning_summary": "Weight plus an independent compatibility fact.",
    }
    responses = iter([
        json.dumps(compound),
        '{"independent":true}',
        '{"capability_query":"whether it is compatible with gas stoves","safety_evaluation_requested":false}',
    ])
    prompts = []

    purposes = []

    async def fake_chat_completion(_db, messages, **kwargs):
        prompts.append(messages)
        purposes.append(kwargs.get("purpose"))
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            None,
            "What is Sample pan's weight and is it compatible with gas stoves?",
            {},
            context={},
        )
    )

    assert len(prompts) == 3
    assert purposes == ["semantic_preplan", "semantic_supplemental_intent_review", "semantic_compound_supplemental_query"]
    assert result["canonical_fields"] == ["weight"]
    assert result["supplemental_qa_evidence_query"] == "whether it is compatible with gas stoves"


@pytest.mark.skip(reason="Retired fixed-phrase prompt assertion; recommendation constraints remain typed but are not phrase-routed.")
def test_semantic_preplan_prompt_exposes_executable_recommendation_constraint_schema():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="recommend a lightweight cookware option for two campers",
        deterministic_plan={},
        context={},
    )

    system = messages[0]["content"]
    assert "recommendation_constraints" in system
    assert "recommendation_evidence_requirements" in system
    assert "recommendation_soft_preferences" in system
    assert "not use a fixed phrase list" in system


@pytest.mark.skip(reason="Retired fixed-phrase prompt assertion; mixed comparison meaning is model-owned.")
def test_semantic_preplan_prompt_preserves_formal_field_in_mixed_comparison():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="Compare the weight and storage of Alpha and Beta.",
        deterministic_plan={},
        context={},
    )

    assert "put only that separate non-column intent in supplemental_qa_evidence_query" in "\n".join(
        str(message.get("content") or "") for message in messages
    )


def test_semantic_preplan_prompt_keeps_current_purchase_availability_out_of_product_qa():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="can I still buy this named product now?",
        deterministic_plan={},
        context={},
    )

    system = messages[0]["content"]
    assert "unknown_realtime" in system
    assert "current commercial information" in system


def test_current_purchase_availability_uses_inventory_safety_contract_not_lifecycle_label():
    contract = customer_field_contract.detect_field_contract("\u6d4b\u8bd5\u4ea7\u54c1\u8fd8\u5728\u552e\u5417\uff1f")

    assert contract is not None
    assert contract.field_type == "inventory"


def test_semantic_unknown_realtime_provider_subtype_normalizes_without_dropping_route():
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "unknown_realtime",
            "route_hint": "unknown_field",
            "question_type": "unknown_field",
            "subtype": "purchasability",
            "subject_text": "AC-Z11",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "product_qa",
        }
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["route_family"] == "unknown_realtime"
    assert preplan["subtype"] == "commercial_realtime"
    assert preplan["evidence_kind"] == "structured_field"


    assert field_contract_metadata("某商品型号是什么") == {
        "contract_field_type": "model",
        "planner_compatible_field_type": "model",
    }


def test_deterministic_semantic_fallback_does_not_conflate_laundry_machine_wash_with_dishwasher():
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(
        "示例收纳包能否放洗衣机机洗？"
    )

    assert semantic is not None
    assert semantic["field_type"] == "cleaning"
    assert semantic["field_type"] != "dishwasher"


def test_deterministic_semantic_fallback_recognizes_rinsing_as_cleaning_action():
    """Semantic outages must not reinterpret a concrete cleaning action as heat compatibility."""
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(
        "刚加热的容器能否立即用冷水冲洗？"
    )

    assert semantic is not None
    assert semantic["field_type"] == "cleaning"
    assert semantic["route_hint"] == "product_detail"


def test_cleaning_qa_evidence_uses_the_same_rinsing_concept_as_the_fallback():
    question = "容器加热后能否用冷水冲洗？"

    assert classify_product_qa_evidence_type(question, '["清洗", "保养"]') == "cleaning"
    assert qa_evidence_matches_field(question, '["清洗", "保养"]', "cleaning")


def test_validated_semantic_cleaning_with_a_concrete_subject_enters_entity_arbitration():
    """A sealed field request must not fall back to generic usage/care routing.

    The semantic layer names only the field and current-turn subject.  Phase 2
    still resolves that subject against the catalogue, so accepting a concrete
    subject here cannot manufacture an SKU or weaken fail-closed identity.
    """
    field_request = {
        "field_type": "cleaning",
        "requested_fields": ["清洁"],
        "canonical_fields": ["cleaning"],
        "subject": "示例收纳箱",
        "source": "validated_semantic_preplan",
    }

    assert customer_service_service._phase2_single_field_arbitration_eligible(
        "示例收纳箱用完如何洗？",
        {"primary_intent": "product_detail"},
        conversation_id=None,
        field_request_override=field_request,
    ) is True
    assert customer_service_service._phase2_single_field_arbitration_eligible(
        "用完如何洗？",
        {"primary_intent": "product_detail"},
        conversation_id=None,
        field_request_override={**field_request, "subject": ""},
    ) is False


def test_high_confidence_semantic_power_outranks_ambiguous_bare_size_fallback():
    question = "示例炉具工作时的额定输出有多大？"
    field_request = resolve_requested_field_contract(
        question,
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subtype": "known_detail",
                "field_type": "power",
                "field_hint": "power",
                "canonical_fields": ["power"],
                "subject_text": "示例炉具",
                "confidence": 0.95,
                "ambiguity": False,
                "evidence_required": True,
                "fallback_reason": "",
            }
        },
    )

    assert field_request["field_type"] == "power"
    assert field_request["canonical_fields"] == ["power"]
    assert field_request["source"] == "validated_semantic_preplan"


def test_high_confidence_semantic_technical_advantages_outranks_overlapping_selling_point_alias():
    """A lexical """ + '"' + "what advantages""" + '"' + " predicate cannot relabel a valid semantic field."""
    question = "它有什么技术优势？"
    field_request = resolve_requested_field_contract(
        question,
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subtype": "known_detail",
                "field_type": "technical_advantages",
                "field_hint": "technical_advantages",
                "canonical_fields": ["technical_advantages"],
                "subject_text": "它",
                "confidence": 0.9,
                "ambiguity": False,
                "evidence_required": True,
                "fallback_reason": "",
            }
        },
    )

    assert field_request["field_type"] == "technical_advantages"
    assert field_request["canonical_fields"] == ["technical_advantages"]
    assert field_request["source"] == "validated_semantic_preplan"


def test_explicit_technical_advantages_predicate_outranks_generic_selling_point_without_semantic_plan():
    """A conservative fallback keeps a specific field inside a generic predicate."""
    phrase_match = customer_field_contract._field_phrase_match("示例收纳箱有哪些技术优势？")

    assert phrase_match is not None
    assert phrase_match[0].field_type == "technical_advantages"


def test_explicit_technical_advantages_label_rejects_semantic_product_qa_route():
    field_request = resolve_requested_field_contract(
        "示例收纳箱技术特点是什么？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "evidence_kind": "product_qa",
                "confidence": 0.9,
                "canonical_fields": [],
                "fallback_reason": "",
            }
        },
    )

    assert field_request["field_type"] == "technical_advantages"
    assert field_request["canonical_fields"] == ["technical_advantages"]
    assert field_request["source"] == "deterministic_alias"








def test_high_confidence_semantic_multi_field_plan_forms_one_compound_contract():
    field_request = resolve_requested_field_contract(
        "SKU-EXAMPLE面向哪些市场，我可以从什么平台购买？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "subtype": "known_detail",
                "field_type": "",
                "field_hint": None,
                "canonical_fields": ["sales_region", "purchase_channel"],
                "subject_text": "SKU-EXAMPLE",
                "confidence": 0.95,
                "ambiguity": False,
                "evidence_required": True,
                "fallback_reason": "",
            }
        },
    )

    assert field_request["field_type"] is None
    assert field_request["canonical_fields"] == ["sales_region", "purchase_channel"]
    assert field_request["requested_fields"] == ["销售区域", "购买渠道"]
    assert field_request["source"] == "validated_semantic_preplan"
    assert field_request["compound"] is True


def test_deterministic_semantic_fallback_classifies_liquid_temperature_capability_as_usage_instruction():
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(
        "这个容器是否能装沸水？"
    )

    assert semantic is not None
    assert semantic["field_type"] == "usage_instruction"
    assert semantic["route_hint"] == "product_detail"


def test_usage_instruction_qa_evidence_accepts_liquid_temperature_capability():
    question = "这个容器能不能装热水？"

    assert classify_product_qa_evidence_type(question, '["装热水", "开水"]') == "usage_instruction"
    assert qa_evidence_matches_field(question, '["装热水", "开水"]', "usage_instruction")


def test_field_contract_separates_recognized_from_supported_detail_fields():
    assert detect_field_contract("某商品价格是多少").field_type == "price"
    assert is_supported_detail_field("price") is False
    assert is_supported_detail_field("gift") is False
    assert is_supported_detail_field("dimensions") is True
    assert is_supported_detail_field("sku") is True
    assert is_supported_detail_field("model") is False


def test_material_component_scopes_remain_distinct_formal_requests():
    contract = resolve_requested_field_contract(
        "炊墨炒锅锅体和锅盖分别是什么材质？",
        subject="炊墨炒锅",
    )

    assert contract["canonical_fields"] == ["material"]
    assert contract["requested_fields"] == ["主体材质", "锅盖材质"]
    assert contract["compound"] is True


def test_component_capability_question_does_not_fabricate_material_or_accessories_contract():
    contract = customer_service_service.resolve_requested_field_contract(
        "2-4人野餐锅10件套的煎盘可以单独用吗，有没有手柄？",
        {},
    )

    assert contract["canonical_fields"] == []
    assert contract["requested_fields"] == []


def test_entity_contract_resolves_unique_canonical_name_with_sku_field():
    product = _product("AA-100", "晨曦Pro水壶")
    result = build_entity_resolution_contract("晨曦Pro水壶的商品编码是什么", [product])
    assert result.status == "resolved"
    assert result.resolved_sku == "AA-100"
    assert result.matched_by == "canonical_name_exact"
    assert result.field_type == "sku"


def test_entity_contract_keeps_version_tokens_distinct_for_exact_variants():
    products = [_product("AA-100", "晨曦Pro水壶"), _product("AA-200", "晨曦Plus水壶")]
    result = build_entity_resolution_contract("晨曦Plus水壶的容量", products)
    assert result.status == "resolved"
    assert result.resolved_sku == "AA-200"


def test_entity_contract_resolves_display_prefix_alias_without_changing_resolver_behavior():
    product = _product("CH-200", "2.0版本-远行折叠椅", "桌椅")
    result = build_entity_resolution_contract("远行折叠椅尺寸是多少", [product])
    assert result.status == "resolved"
    assert result.matched_by == "normalized_alias_exact"
    assert result.field_type == "dimensions"


def test_entity_contract_parses_dimension_state_modifier_as_part_of_field_tail():
    product = _product("CH-201", "1.1版本-远行包包椅", "桌椅")
    result = build_entity_resolution_contract("远行包包椅展开后尺寸是多少", [product])
    assert result.status == "resolved"
    assert result.entity_text == "远行包包椅"
    assert result.resolved_sku == "CH-201"
    assert result.field_type == "dimensions"


def test_entity_contract_resolves_leading_display_label_alias_with_formal_candidate():
    product = _product("CP-201", "（渠道专属）晨光户外杯", "水具")
    result = build_entity_resolution_contract("晨光户外杯的大小是多少", [product], resolver_candidates=[product])
    assert result.status == "resolved"
    assert result.matched_by == "normalized_alias_exact"


def test_entity_contract_resolves_unique_name_with_only_connector_difference():
    products = [
        _product("CS-B15S", "围雪炉-酒精版", "炉具"),
        _product("CS-B15SPRO", "围雪炉-酒精汽炉版", "炉具"),
    ]

    result = build_entity_resolution_contract(
        "围雪炉酒精版熏黑了怎么处理？",
        products,
        entity_text_override="围雪炉酒精版",
    )

    assert result.status == "resolved"
    assert result.resolved_sku == "CS-B15S"
    assert result.matched_by == "normalized_alias_exact"


def test_entity_contract_keeps_family_and_weak_matches_ambiguous():
    products = [_product("KT-1", "远野Max水壶"), _product("KT-2", "远野Pro水壶")]
    result = build_entity_resolution_contract("远野水壶的规格", products)
    assert result.status == "ambiguous"
    assert result.resolved_sku is None
    assert set(result.candidate_skus) == {"KT-1", "KT-2"}


def test_entity_contract_rejects_generic_and_unresolved_inputs():
    generic = build_entity_resolution_contract("水壶容量是多少", [_product("KT-1", "远野水壶")])
    unresolved = build_entity_resolution_contract("不存在名称的型号", [_product("KT-1", "远野水壶")])
    assert generic.status == "generic"
    assert generic.resolved_sku is None
    assert unresolved.status == "unresolved"
    assert unresolved.resolved_sku is None


def test_entity_contract_preserves_explicit_sku_evidence():
    product = _product("AB-123", "晨曦水壶")
    result = build_entity_resolution_contract("AB-123 的型号", [product])
    assert result.status == "resolved"
    assert result.matched_by == "sku_exact"
    assert result.confidence == "high"


def test_entity_contract_keeps_formal_unique_candidate_when_tail_span_is_imperfect():
    product = _product("AA-100", "晨曦Pro水壶")
    result = build_entity_resolution_contract(
        "晨曦Pro水壶，型号怎么查",
        [product],
        resolver_candidates=[product],
    )
    assert result.status != "generic"
    assert result.resolver_candidate_skus == ["AA-100"]
    assert result.candidate_skus == ["AA-100"]


def test_entity_contract_keeps_formal_multiple_candidates_when_tail_contains_how_to_choose():
    products = [_product("AA-100", "晨曦Pro水壶"), _product("AA-200", "晨曦Plus水壶")]
    result = build_entity_resolution_contract(
        "晨曦水壶的规格怎么选",
        products,
        resolver_candidates=products,
    )
    assert result.status == "ambiguous"
    assert result.resolver_candidate_skus == ["AA-100", "AA-200"]
    assert result.diagnostic_candidate_skus == []


def test_entity_contract_separates_diagnostic_family_candidates():
    products = [_product("KT-1", "远野Max水壶"), _product("KT-2", "远野Pro水壶")]
    result = build_entity_resolution_contract("远野水壶的规格", products, resolver_candidates=[])
    assert result.status == "ambiguous"
    assert result.resolver_candidate_skus == []
    assert set(result.diagnostic_candidate_skus) == {"KT-1", "KT-2"}
    assert result.status_reason == "diagnostic_family_overlap"


def test_diagnostic_only_candidate_never_becomes_resolved():
    product = _product("KT-1", "远野Max水壶")
    result = build_entity_resolution_contract("远野水壶的规格", [product], resolver_candidates=[])
    assert result.status == "ambiguous"
    assert result.resolved_sku is None
    assert result.resolver_candidate_skus == []
    assert result.diagnostic_candidate_skus == ["KT-1"]


def test_contract_observation_isolates_contract_exceptions(monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("contract-only failure")

    monkeypatch.setattr(customer_entity_resolution_contract, "build_entity_resolution_contract", boom)
    observation = build_entity_resolution_contract_observation("某商品型号", [])
    assert "entity_resolution_contract" not in observation
    assert observation["entity_resolution_contract_error"].startswith("ValueError:")


def test_contract_is_not_injected_into_semantic_preplan_input_or_global_product_query():
    source = inspect.getsource(customer_service_service.ask_customer_service)
    assert "db.query(Product).all()" not in source
    preplan_call = source.index("_maybe_run_semantic_preplan")
    semantic_executor_call = source.index("_semantic_first_turn_result")
    assert preplan_call < semantic_executor_call
    # The semantic executor owns ordinary read turns.  The historical field
    # arbitration route may still exist as a reusable same-SKU adapter, but
    # the public entry point must not call it as a second interpretation vote.
    assert "_phase2_entity_state_arbitration_result" not in source


def test_semantic_catalogue_listing_subtype_requires_structured_repair():
    """A provider listing label cannot fall through to legacy KB/FAQ routes."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "knowledge_base_meta",
            "subtype": "series_listing",
            "entities": [],
            "subject_text": "Lake Beauty theme series",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
            "reasoning_summary": "List products in one stored series.",
        }
    )

    assert preplan["fallback_reason"] == "unbound_catalogue_browse_requires_structured_query"
    assert preplan["semantic_route_family_hint"] == "structured_query"


@pytest.mark.parametrize("provider_evidence_kind", ["knowledge_base", "knowledge", "knowledge_chunk"])
def test_knowledge_base_source_alias_stays_in_document_rag_contract(provider_evidence_kind):
    """A provider source label must not turn a KB-meta plan into fallback."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "knowledge_base_meta",
            "information_scope": "knowledge_base_meta",
            "subtype": "usage_care",
            "entities": [],
            "subject_text": "",
            "canonical_fields": [],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": False,
            "evidence_kind": provider_evidence_kind,
            "qa_evidence_query": "不粘涂层清洁保养",
            "context_usage": "none",
            "reasoning_summary": "Answer from the supplied knowledge document.",
        },
        raw_content=provider_evidence_kind,
        customer_question="根据知识库，锅具的不粘涂层应该如何清洁和保养？",
    )

    assert preplan["fallback_reason"] == ""
    assert preplan["route_family"] == "knowledge_base_meta"
    assert preplan["information_scope"] == "knowledge_base_meta"
    assert preplan["evidence_kind"] == "product_qa"
    assert preplan["qa_evidence_query"] == "不粘涂层清洁保养"


def test_unanchored_product_bound_shape_requires_semantic_route_repair():
    """A product family list must never collapse into one detail record."""
    preplan = customer_agent_planner_service._validate_semantic_preplan(
        {
            "route_family": "product_bound_qa",
            "subtype": "known_detail",
            "entities": [],
            "subject_text": "围雪炉",
            "canonical_fields": ["product_name_cn", "sku"],
            "confidence": "high",
            "ambiguity": False,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "context_usage": "none",
            "reasoning_summary": "List a named catalogue family.",
        }
    )

    # Shape validation is context-free; the runtime semantic planner applies
    # the entity-anchor consistency gate before execution.
    assert preplan["route_family"] == "product_bound_qa"
    assert preplan["entities"] == []


def test_semantic_unique_typo_recovery_maps_only_one_catalog_owner():
    products = [
        _product("CS-G25", "小青炉", "炉具"),
        _product("CS-B15S", "围雪炉-酒精版", "炉具"),
    ]

    recovered = customer_service_service._semantic_unique_typo_near_catalog_subject(
        "小青点这个炉子",
        products,
    )

    assert recovered == "小青炉"


def test_semantic_unique_typo_recovery_fails_closed_for_two_near_owners():
    products = [
        _product("STOVE-1", "小青炉", "炉具"),
        _product("LAMP-1", "小青灯", "照明"),
    ]

    recovered = customer_service_service._semantic_unique_typo_near_catalog_subject(
        "小青点这个炉子",
        products,
    )

    assert recovered == ""


def test_semantic_comparison_seals_unique_one_character_product_typo():
    products = [
        _product("CS-B15S", "围雪炉-酒精版", "炉具"),
        _product("CS-B15SPRO", "围雪炉-酒精汽炉版", "炉具"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["围雪炉酒精版", "酒精汽油版"],
        "canonical_fields": [],
        "confidence": 0.95,
        "ambiguity": False,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "围雪炉酒精版和酒精汽油版是同一款吗？",
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["CS-B15S", "CS-B15SPRO"]


def test_semantic_comparison_catalogue_sealing_overrides_provider_ambiguity_flag():
    products = [
        _product("CS-B15S", "围雪炉-酒精版", "炉具"),
        _product("CS-B15SPRO", "围雪炉-酒精汽炉版", "炉具"),
    ]
    preplan = {
        "called": True,
        "route_family": "comparison",
        "entities": ["围雪炉酒精版", "酒精汽油版"],
        "canonical_fields": [],
        "confidence": 0.65,
        "ambiguity": True,
    }

    contracts = customer_service_service._semantic_comparison_entity_contracts(
        "围雪炉酒精版和酒精汽油版是同一款吗？",
        preplan,
        products,
    )

    assert [contract.resolved_sku for contract in contracts] == ["CS-B15S", "CS-B15SPRO"]




@pytest.mark.skip(reason="Retired direct narrative validator contract; live final fact-integrity checks cover measurements on selected SKUs.")
def test_semantic_recommendation_rejects_dropped_decimal_measurement():
    common = {
        "candidate_count": 1,
        "verified_fields_by_index": {0: {"specs.capacity"}},
        "verified_evidence_values_by_index": {
            0: {"specs.capacity": "1.4L", "__product_name__": "聚能环水壶"},
        },
    }
    corrupted = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["specs.capacity"]}],
            "answer": "可以看聚能环水壶，资料标注容量为4L。",
        },
        **common,
    )
    literal = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{"candidate_index": 0, "fields": ["specs.capacity"]}],
            "answer": "可以看聚能环水壶，资料标注容量为1.4L。",
        },
        **common,
    )

    assert corrupted is None
    assert literal is not None


@pytest.mark.skip(reason="Retired direct narrative validator contract; live final fact-integrity checks cover same-SKU recommendation prose.")
def test_semantic_recommendation_allows_customer_threshold_in_same_sku_comparison():
    candidate = {
        "product_name": "\u7092\u58a8\u5957\u9505",
        "sku": "CW-C83",
        "identity_aliases": [
            "\u7231\u8def\u5ba2\u7092\u58a8\u7092\u9505\u6237\u5916\u591a\u529f\u80fd\u5957\u9505\u4e0d\u7c98\u9505"
        ],
        "sealed_evidence": {
            "specs.capacity": "\u9505\uff1a3700ML\uff1b\u714e\u76d8\uff1a2300ML",
            "content.surface_finish": "\u786c\u8d28\u6c27\u5316\uff0c\u6c34\u6027\u4e0d\u6cbe",
        },
    }
    answer = (
        "\u63a8\u8350\u7231\u8def\u5ba2\u7092\u58a8\u7092\u9505\uff0c\u5b83\u7684\u5bb9\u91cf\u4e3a3700\u6beb\u5347\uff0c"
        "\u8d85\u8fc71\u5347\uff0c\u91c7\u7528\u6c34\u6027\u4e0d\u7c98\u6d82\u5c42\uff1b\u4f46\u4e09\u4eba\u662f\u5426\u80fd\u5403\u9971\u8fd8\u9700\u7ed3\u5408\u98df\u91cf\u5224\u65ad\u3002"
    )
    tokens = customer_service_service._recommendation_candidate_identity_tokens(candidate)
    result = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{
                "candidate_index": 0,
                "fields": ["specs.capacity", "content.surface_finish"],
            }],
            "answer": answer,
        },
        candidate_count=1,
        verified_fields_by_index={0: set(candidate["sealed_evidence"])},
        candidate_identity_tokens_by_index={0: tokens},
        verified_evidence_values_by_index={
            0: {**candidate["sealed_evidence"], "__product_name__": candidate["product_name"]}
        },
        customer_question=(
            "\u4e09\u4e2a\u4eba\u4e00\u8d77\u9732\u8425\uff0c\u9700\u8981\u5bb9\u91cf\u57281L\u4ee5\u4e0a\u4e14\u6709\u4e0d\u7c98\u6d82\u5c42\u7684\u9505"
        ),
    )

    assert result is not None


@pytest.mark.skip(reason="Retired direct narrative validator contract; live final fact-integrity checks cover selected-SKU measurements.")
def test_semantic_recommendation_rejects_cross_product_measurement_leakage():
    result = customer_service_service._validate_semantic_recommendation_narrative(
        {
            "ranked_candidate_indexes": [0, 1],
            "evidence_usage": [
                {"candidate_index": 0, "fields": ["specs.capacity"]},
                {"candidate_index": 1, "fields": ["specs.capacity"]},
            ],
            "answer": "甲水壶容量为4L；乙水壶容量也为4L。",
        },
        candidate_count=2,
        verified_fields_by_index={0: {"specs.capacity"}, 1: {"specs.capacity"}},
        verified_evidence_values_by_index={
            0: {"specs.capacity": "4L", "__product_name__": "甲水壶"},
            1: {"specs.capacity": "1400ml", "__product_name__": "乙水壶"},
        },
    )

    assert result is None


def test_conflicting_identity_and_capacity_cell_is_not_verified_or_rendered():
    row = {
        "sku": "SAFE-CAPACITY",
        "product_name_cn": "1.7L单锅",
        "category": "锅具",
        "capacity": "7L",
        "gross_weight_g": 310,
    }
    contract = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "想找容量稍微大点的锅",
    )
    contract.soft_preferences.append("capacity")
    verification = customer_recommendation_verification_contract.verify_recommendation_candidates(
        contract,
        [row],
    )[0]
    summary = customer_recommendation_verification_contract._row_customer_summary(row)

    assert verification.evidence_by_constraint["capacity"]["status"] == "unsupported"
    assert "容量7L" not in summary

    content_conflict = {
        "sku": "SAFE-CONTENT-CAPACITY",
        "product_name_cn": "聚能环水壶",
        "category": "水具",
        "capacity": "4L",
        "features": "底部聚能环设计，1.4L 双人容量",
    }
    assert customer_recommendation_verification_contract._capacity_consistent_with_product_identity(
        content_conflict,
    ) is False


def test_decimal_capacity_parser_keeps_leading_integer_and_decimal_point():
    assert customer_recommendation_verification_contract._numeric_values(
        "1.4L野营水壶",
        kind="capacity",
    ) == [1400.0]
    assert customer_service_service._capacity_evidence_is_internally_consistent(
        "4L",
        "1.4L野营水壶",
    ) is False


def test_named_comparison_results_follow_visible_answer_order():
    result = customer_service_service._align_answer_named_result_cards({
        "answer_type": "comparison",
        "answer": "新推荐是小方锅Pro（CW-C99），上一款是小方锅（CW-C69-1）。",
        "results": [
            {"sku": "CW-C69-1", "product_name_cn": "小方锅"},
            {"sku": "CW-C99", "product_name_cn": "小方锅Pro"},
        ],
        "result_skus": ["CW-C69-1", "CW-C99"],
        "candidate_skus": ["CW-C69-1", "CW-C99"],
    })

    assert result["result_skus"] == ["CW-C99", "CW-C69-1"]
    assert [row["sku"] for row in result["results"]] == ["CW-C99", "CW-C69-1"]


def test_named_recommendation_results_follow_product_name_order_without_visible_skus():
    result = customer_service_service._align_answer_named_result_cards({
        "answer_type": "recommendation",
        "answer": "先看乙水壶，再考虑甲水壶。",
        "results": [
            {"sku": "KETTLE-A", "product_name_cn": "甲水壶"},
            {"sku": "KETTLE-B", "product_name_cn": "乙水壶"},
        ],
        "result_skus": ["KETTLE-A", "KETTLE-B"],
        "candidate_skus": ["KETTLE-A", "KETTLE-B"],
    })

    assert result["result_skus"] == ["KETTLE-B", "KETTLE-A"]


def test_compact_easy_wash_phrase_becomes_cleaning_preference():
    contract = customer_recommendation_verification_contract.build_recommendation_request_contract(
        "卡式炉 烤盘 好洗 哪个",
    )

    assert contract.cleaning_required is True
    assert "cleaning" in contract.soft_preferences


def test_safe_missing_product_qa_does_not_echo_unverified_values():
    answer = customer_service_service._safe_missing_product_qa_answer(
        "稳稳水袋",
        "AC-19",
        "AC-19 的防水等级是 IPX6 还是 IPX7？",
    )

    assert "IPX6" not in answer
    assert "IPX7" not in answer


def test_semantic_recommendation_with_natural_purpose_text_stays_catalog_owned():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "fallback_reason": "",
        "ambiguity": False,
        "decision_requested": True,
        "subject_text": "practical gift for a beginner",
        "recommendation_constraints": {},
    }

    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan) is True


def test_empty_semantic_recommendation_plan_does_not_choose_from_catalogue():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "confidence": 0.9,
        "fallback_reason": "",
        "ambiguity": False,
        "recommendation_constraints": {},
    }

    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan) is False


@pytest.mark.skip(reason="Retired deterministic recommendation fallback; current path is semantic writer plus sealed evidence.")
def test_recommendation_fallback_without_soft_preferences_is_safe():
    result = customer_service_service._verified_recommendation_evidence_fallback(
        question="recommend one cookware item",
        rows=[
            {
                "sku": "FALLBACK-02",
                "product_name_cn": "基础单锅",
                "capacity": "1.7L",
                "gross_weight_g": 700,
                "top_selling_points": "轻量便携",
            }
        ],
        soft_preferences=[],
        candidate_indexes=[0],
        single_recommendation_requested=True,
    )

    assert result is not None
    assert "基础单锅" in result["answer"]
    assert "1.7L" in result["answer"]


@pytest.mark.skip(reason="Retired deterministic recommendation fallback; current path is semantic writer plus sealed evidence.")
def test_recommendation_fallback_does_not_dump_long_description_into_customer_answer():
    result = customer_service_service._verified_recommendation_evidence_fallback(
        question="朋友刚开始露营，送什么实用又好收纳？",
        rows=[
            {
                "sku": "FALLBACK-01",
                "product_name_cn": "便携套锅",
                "top_selling_points": "全套收纳便携",
                "long_description_en": "This is a very long marketing description that must not be copied.",
                "capacity": "1.7L",
                "gross_weight_g": 800,
            }
        ],
        soft_preferences=["compact"],
        candidate_indexes=[0],
        single_recommendation_requested=True,
    )

    assert result is not None
    assert "This is a very long marketing description" not in result["answer"]
    assert "便携套锅" in result["answer"]
