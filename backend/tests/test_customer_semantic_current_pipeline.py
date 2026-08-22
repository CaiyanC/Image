import asyncio
import json

from app.services import customer_agent_planner_service, customer_service_service


def test_prior_recommendation_scope_exposes_only_catalogue_context():
    result = customer_service_service._semantic_prior_recommendation_scope(
        {
            "source": "recommendation",
            "answer_type": "recommendation",
            "product_scope": "锅具",
            "recommended_skus": ["CW-C93"],
            "effective_recommendation_contract": {
                "recommendation_constraints": {"subject_kind": "cookware"},
            },
        },
        {},
    )

    assert result == {
        "source": "persisted_recommendation_catalogue_scope",
        "category_or_scope": "锅具",
        "subject_kind": "cookware",
    }
    assert "CW-C93" not in json.dumps(result, ensure_ascii=False)


def test_semantic_preplan_normalizes_scalar_people_transport_shape():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "entities": [],
        "subject_text": "\u9505\u5177",
        "entity_scope": "category_scope",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "decision_requested": True,
        "recommendation_constraints": {
            "subject_kinds": ["cookware"],
            "people": 3,
            "scenarios": ["camping"],
            "storage_preference": "compact_storage",
        },
        "predicate_constraints": [],
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": ["\u5bb9\u91cf\u5927\u4e00\u4e9b"],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    assert result["fallback_reason"] == ""
    assert result["recommendation_constraints"]["people"] == {
        "min": 3,
        "max": 3,
    }


def test_semantic_preplan_lifts_malformed_storage_enum_to_soft_context():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "entities": [],
        "subject_text": "\u9505\u5177",
        "entity_scope": "category_scope",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "decision_requested": True,
        "recommendation_constraints": {
            "subject_kind": "cookware",
            "storage_preference": "easy_to_store",
        },
        "predicate_constraints": [],
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": ["\u5b9e\u7528"],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    assert result["fallback_reason"] == ""
    assert result["recommendation_constraints"] == {"subject_kind": "cookware"}
    assert result["recommendation_soft_preferences"] == [
        "\u5b9e\u7528",
        "easy_to_store",
    ]


def test_category_subject_preserves_prior_recommendation_context(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda *_args: [{"category": "锅具"}],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_database_category_scope_ref",
        lambda _rows, _subject: "锅具",
    )

    normalized = customer_service_service._normalize_semantic_catalogue_continuation(
        object(),
        {
            "route_family": "recommendation",
            "route_hint": "recommendation",
            "question_type": "recommendation",
            "subject_text": "锅具",
            "entity_scope": "category",
            "entities": [],
            "canonical_fields": [],
            "predicate_constraints": [],
            "recommendation_constraints": {"subject_kind": "accessories"},
            "recommendation_soft_preferences": ["作为礼物"],
            "decision_requested": True,
            "context_usage": "none",
            "context_result_indexes": [1],
        },
        {"recommended_skus": ["CW-C78"], "product_scope": "锅具"},
    )

    assert normalized["route_family"] == "recommendation"
    assert normalized["context_usage"] == "recommendation_context"
    assert normalized["context_result_indexes"] == []
    assert normalized["recommendation_constraints"]["subject_kind"] == "cookware"
    assert normalized["decision_requested"] is True
    assert normalized["recommendation_soft_preferences"] == ["作为礼物"]


def test_bare_category_context_marks_copied_soft_preferences_as_scope_only(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda *_args: [{"category": "\u9505\u5177"}],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_database_category_scope_ref",
        lambda _rows, _subject: "\u9505\u5177",
    )

    normalized = customer_service_service._normalize_semantic_catalogue_continuation(
        object(),
        {
            "route_family": "recommendation",
            "subject_text": "\u9505\u5177",
            "entities": [],
            "canonical_fields": [],
            "predicate_constraints": [],
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "scenarios": ["camping"],
            },
            "recommendation_evidence_requirements": [],
            "recommendation_soft_preferences": ["\u5b9e\u7528", "\u597d\u6536\u7eb3"],
            "unrepresented_recommendation_requirements": [],
            "decision_requested": True,
        },
        {"recommended_skus": ["CW-OLD-1"], "product_scope": "\u9505\u5177"},
    )

    assert normalized["context_usage"] == "recommendation_context"
    assert normalized["semantic_catalogue_scope_only_continuation"] is True


def test_bare_category_context_clears_copied_current_turn_requirements(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda *_args: [{"category": "\u9505\u5177"}],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_database_category_scope_ref",
        lambda _rows, _subject: "\u9505\u5177",
    )

    normalized = customer_service_service._normalize_semantic_catalogue_continuation(
        object(),
        {
            "route_family": "recommendation",
            "subject_text": "\u9505\u5177",
            "entities": [],
            "canonical_fields": [],
            "predicate_constraints": [
                {"field": "capacity", "operator": ">=", "value": 1000}
            ],
            "recommendation_constraints": {
                "subject_kind": "cookware",
                "scenarios": ["camping"],
            },
            "recommendation_evidence_requirements": ["\u9002\u5408\u9732\u8425\u65b0\u624b"],
            "recommendation_soft_preferences": ["\u5b9e\u7528"],
            "unrepresented_recommendation_requirements": ["\u4e0d\u5bb9\u6613\u9009\u9519"],
            "decision_requested": True,
        },
        {"recommended_skus": ["CW-OLD-1"], "product_scope": "\u9505\u5177"},
        question="\u9505\u5177",
    )

    assert normalized["semantic_catalogue_scope_only_continuation"] is True
    assert normalized["predicate_constraints"] == []
    assert normalized["recommendation_evidence_requirements"] == []
    assert normalized["recommendation_soft_preferences"] == []
    assert normalized["unrepresented_recommendation_requirements"] == []


def test_semantic_preplan_prompt_receives_prior_scope_as_discourse_context():
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="如果我用酒精炉呢？",
        deterministic_plan={},
        context={
            "prior_recommendation_scope": {
                "source": "persisted_recommendation_catalogue_scope",
                "category_or_scope": "锅具",
                "subject_kind": "cookware",
            },
        },
    )

    payload = json.loads(messages[1]["content"])
    assert payload["prior_recommendation_scope"]["subject_kind"] == "cookware"
    assert "prior_recommendation_scope" in messages[0]["content"]
    assert "heat source" in messages[0]["content"]


def test_semantic_recommendation_route_survives_failed_constraint_schema_repair(monkeypatch):
    initial_plan = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "subtype": "recommendation",
        "entities": [],
        "subject_text": "camping gear",
        "entity_scope": "category",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "product_evidence",
        "context_usage": "none",
        "decision_requested": True,
        "recommendation_constraints": {"subject_kinds": ["camping_gear"]},
        "recommendation_evidence_requirements": ["beginner camping gift"],
        "recommendation_soft_preferences": ["low choice risk"],
        "unrepresented_recommendation_requirements": [],
        "reasoning_summary": "The customer wants a beginner camping gift recommendation.",
    }
    partition_plan = {
        "recommendation_constraints": {"subject_kinds": ["camping_gear"]},
        "predicate_constraints": [],
        "recommendation_evidence_requirements": ["beginner camping gift"],
        "recommendation_soft_preferences": ["low choice risk"],
        "unrepresented_recommendation_requirements": [],
    }
    responses = iter([
        json.dumps(initial_plan),
        json.dumps(initial_plan),
        json.dumps(partition_plan),
        json.dumps(partition_plan),
    ])

    async def fake_chat_completion(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        "beginner camping gift",
        {},
        context={},
    ))

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["subject_text"] == "camping gear"
    assert result["recommendation_constraints"] == {}
    assert result["recommendation_evidence_requirements"] == ["beginner camping gift"]
    assert result["recommendation_soft_preferences"] == ["low choice risk"]
    assert result["semantic_schema_repair_salvaged"] is True


def test_semantic_preplan_keeps_meaning_when_provider_uses_descriptive_transport_shapes():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation with a compatibility constraint and a soft preference",
        "question_type": "recommendation",
        "entities": ["卡式炉", "烤盘"],
        "subject_text": "烤盘",
        "entity_scope": "category",
        "canonical_fields": ["heat_source", "cleaning"],
        "field_type": "product_qa",
        "field_hint": "compatibility and cleaning",
        "subtype": "compatibility",
        "confidence": "high",
        "evidence_required": True,
        "evidence_kind": "product_evidence",
        "decision_requested": True,
        "recommendation_constraints": [{"subject_kind": "烤盘"}],
        "predicate_constraints": [{
            "field": "heat_source",
            "operator": "contains",
            "value": "卡式炉",
            "evidence_span": "支持卡式炉",
            "importance": "required",
        }],
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    # A descriptive transport value is not silently converted into an
    # executable broad scope.  The semantic planner keeps the recommendation
    # ownership as provenance and gives Flash a repair pass; it must not fall
    # through to a lexical/category route.
    assert result["fallback_reason"] == "invalid_recommendation_constraints"
    assert result["semantic_route_family_hint"] == "recommendation"


def test_semantic_preplan_preserves_compound_product_form_scope():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "entities": [],
        "subject_text": "锅和水壶",
        "entity_scope": "category_scope",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "",
        "decision_requested": True,
        "recommendation_constraints": {
            "subject_kinds": ["cookware", "waterware"],
            "people": {"min": 3, "max": 3},
        },
        "predicate_constraints": [],
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    assert result["fallback_reason"] == ""
    assert result["recommendation_constraints"]["subject_kinds"] == [
        "cookware",
        "waterware",
    ]
    assert "subject_kind" not in result["recommendation_constraints"]


def test_semantic_preplan_normalizes_single_context_phrase_without_repair():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "entities": [],
        "subject_text": "cookware",
        "entity_scope": "category_scope",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "decision_requested": True,
        "recommendation_constraints": {"subject_kind": "cookware"},
        "predicate_constraints": [],
        "recommendation_evidence_requirements": "supports alcohol stove",
        "recommendation_soft_preferences": "prefer either fuel option",
        "unrepresented_recommendation_requirements": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    assert result["fallback_reason"] == ""
    assert result["recommendation_evidence_requirements"] == [
        "supports alcohol stove"
    ]
    assert result["recommendation_soft_preferences"] == [
        "prefer either fuel option"
    ]


def test_complete_semantic_field_plan_skips_redundant_completeness_review():
    plan = {
        "route_family": "product_bound_qa",
        "question_type": "field",
        "evidence_kind": "structured_field",
        "canonical_fields": ["capacity"],
        "supplemental_qa_evidence_query": "",
        "compound": False,
        "intent_coverage": "full",
        "ambiguity": False,
        "qa_or_usage_care": False,
        "fallback_reason": "",
    }

    assert not customer_agent_planner_service._semantic_structured_field_recheck_needed(plan)


def test_complete_category_care_plan_skips_generic_recheck():
    plan = {
        "route_family": "product_bound_qa",
        "question_type": "usage",
        "evidence_kind": "structured_field",
        "canonical_fields": ["cleaning", "care"],
        "entity_scope": "category",
        "qa_evidence_query": "锅具不粘涂层清洁保养步骤",
        "supplemental_qa_evidence_query": "",
        "compound": True,
        "intent_coverage": "full",
        "ambiguity": False,
        "qa_or_usage_care": True,
    }

    assert not customer_agent_planner_service._semantic_structured_field_recheck_needed(plan)


def test_resolved_gifting_scope_skips_second_product_qa_recheck(monkeypatch):
    primary_plan = {
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "entities": ["饭盒"],
        "subject_text": "饭盒",
        "entity_scope": "single",
        "canonical_fields": ["gift"],
        "confidence": "high",
        "ambiguity": True,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "qa_evidence_query": "",
        "supplemental_qa_evidence_query": "",
        "compound": False,
        "intent_coverage": "full",
        "context_usage": "none",
        "context_result_indexes": [],
        "decision_requested": False,
        "recommendation_constraints": {},
        "predicate_constraints": [],
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": [],
        "recommendation_followup_action": "",
        "reasoning_summary": "The customer asks whether the named lunchbox is suitable as a present.",
        "qa_or_usage_care": False,
    }
    calls = []

    async def fake_chat_completion(*_args, **kwargs):
        calls.append(kwargs["purpose"])
        if kwargs["purpose"] == "semantic_preplan":
            return json.dumps(primary_plan, ensure_ascii=False)
        if kwargs["purpose"] == "semantic_gift_field_scope_review":
            return json.dumps({
                "promotional_gift_requested": False,
                "product_qa_query": "饭盒适合作为礼物送人吗？",
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected semantic call: {kwargs['purpose']}")

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(customer_agent_planner_service, "_database_field_value_hints", lambda *_args: [])

    result = asyncio.run(customer_agent_planner_service.plan_customer_question_semantic(
        None,
        "饭盒适合送人吗？",
        {},
        context={},
    ))

    assert result["evidence_kind"] == "product_qa"
    assert result["canonical_fields"] == []
    assert calls == ["semantic_preplan", "semantic_gift_field_scope_review"]


def test_semantic_field_completeness_review_remains_for_open_semantic_shape():
    plan = {
        "route_family": "product_bound_qa",
        "question_type": "usage",
        "evidence_kind": "structured_field",
        "canonical_fields": ["capacity"],
        "supplemental_qa_evidence_query": "",
        "compound": True,
        "intent_coverage": "full",
        "ambiguity": False,
        "qa_or_usage_care": False,
        "fallback_reason": "",
    }

    assert customer_agent_planner_service._semantic_structured_field_recheck_needed(plan)


def test_recommendation_ambiguity_diagnostic_does_not_bypass_semantic_rag():
    preplan = {
        "called": True,
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "subject_text": "锅",
        "confidence": 0.9,
        "ambiguity": True,
        "fallback_reason": "",
        "decision_requested": True,
        "recommendation_constraints": {},
        "recommendation_evidence_requirements": ["适合两个人煮面"],
        "recommendation_soft_preferences": ["轻便"],
    }

    assert customer_service_service._semantic_first_turn_is_owned(preplan)
    assert customer_service_service._should_execute_semantic_catalog_recommendation(preplan)

    non_recommendation = dict(preplan, route_family="product_bound_qa")
    assert not customer_service_service._semantic_first_turn_is_owned(non_recommendation)


def test_comparison_ambiguity_reaches_entity_sealing_before_clarification():
    preplan = {
        "called": True,
        "route_family": "comparison",
        "route_hint": "comparison",
        "question_type": "comparison",
        "entities": ["CW-C83", "CW-C06PRO"],
        "canonical_fields": ["weight", "capacity"],
        "confidence": 0.9,
        "confidence_label": "high",
        "ambiguity": True,
        "fallback_reason": "",
    }

    assert customer_service_service._semantic_first_turn_is_owned(preplan)


def test_structured_query_ambiguity_with_typed_work_reaches_executor():
    preplan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subject_text": "水壶",
        "canonical_fields": ["capacity"],
        "field_type": "capacity",
        "predicate_constraints": [{"field": "capacity", "operator": ">=", "value": "1L"}],
        "confidence": 0.9,
        "confidence_label": "high",
        "ambiguity": True,
        "fallback_reason": "",
    }

    assert customer_service_service._semantic_first_turn_is_owned(preplan)


def test_semantic_prior_result_scope_survives_transport_validation():
    provider_shape = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "entities": [],
        "subject_text": "",
        "entity_scope": "prior_context",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": False,
        "evidence_kind": "",
        "decision_requested": True,
        "context_usage": "none",
        "context_result_indexes": [],
        "recommendation_constraints": {},
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
    )

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["entity_scope"] == "prior_results"
    assert result["decision_requested"] is True


def test_semantic_prior_result_scope_binds_only_server_owned_positions():
    normalized = customer_service_service._normalize_semantic_prior_result_context(
        {
            "called": True,
            "route_family": "recommendation",
            "entity_scope": "prior_results",
            "decision_requested": True,
            "context_result_indexes": [],
        },
        ordered_result_skus=["SKU-A", "SKU-B"],
        prior_result_context_semantics={
            "prior_answer_kind": "comparison",
            "prior_result_count": 2,
            "prior_has_recorded_choice": True,
            "prior_recorded_choice_index": 1,
        },
    )

    assert normalized["context_usage"] == "result_context"
    assert normalized["context_result_indexes"] == [1, 2]
    assert normalized["entity_scope"] == "prior_results"
    assert "SKU-A" not in json.dumps(normalized, ensure_ascii=False)
    assert "SKU-B" not in json.dumps(normalized, ensure_ascii=False)


def test_product_qa_prior_scope_uses_recorded_comparison_choice():
    normalized = customer_service_service._normalize_semantic_prior_result_context(
        {
            "called": True,
            "route_family": "product_bound_qa",
            "entity_scope": "prior_results",
            "context_usage": "result_context",
            "decision_requested": False,
            "context_result_indexes": [1, 2],
        },
        ordered_result_skus=["SKU-A", "SKU-B"],
        prior_result_context_semantics={
            "prior_answer_kind": "comparison",
            "prior_result_count": 2,
            "prior_has_recorded_choice": True,
            "prior_recorded_choice_index": 2,
        },
    )

    assert normalized["context_result_indexes"] == [2]
    assert normalized["context_usage"] == "result_context"
    assert "SKU-A" not in json.dumps(normalized, ensure_ascii=False)
    assert "SKU-B" not in json.dumps(normalized, ensure_ascii=False)


def test_unresolved_generic_product_safety_uses_general_guidance_shape(monkeypatch):
    monkeypatch.setattr(
        customer_service_service,
        "_explicit_product_from_question",
        lambda _db, _question: None,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_products_named_in_question",
        lambda _db, _question: [],
    )

    normalized = customer_service_service._normalize_unanchored_product_qa_to_general_chat(
        object(),
        "液体酒精炉能在封闭帐篷里用吗？请直接告诉我风险和安全做法。",
        {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "usage",
            "entities": ["液体酒精炉", "封闭帐篷"],
            "qa_or_usage_care": True,
            "evidence_required": True,
            "evidence_kind": "product_qa",
            "context_usage": "none",
            "context_result_indexes": [],
        },
    )

    assert normalized["route_family"] == "general_chat"
    assert normalized["entities"] == []
    assert normalized["evidence_required"] is False


def test_unbound_environmental_gas_stove_safety_is_not_downgraded_to_gap():
    result = customer_service_service._apply_environmental_fuel_safety_boundary(
        "燃气炉可以在帐篷里使用吗？",
        {"answer": "当前资料没有明确记录，无法确认。", "results": [], "result_skus": []},
    )

    assert result["answer_type"] == "knowledge_base_answer"
    assert result["result_skus"] == []
    assert "不要在帐篷" in result["answer"]
    assert "一氧化碳" in result["answer"]
    assert result["debug"]["semantic_safety_boundary"] is True


def test_semantic_alternative_reopens_prior_recommendation_scope():
    normalized = customer_service_service._apply_semantic_recommendation_followup_action(
        {
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "subject_text": "anchored product",
            "entity_scope": "prior_results",
            "canonical_fields": ["weight"],
            "context_usage": "result_context",
            "context_result_indexes": [1],
            "decision_requested": False,
            "recommendation_soft_preferences": [],
        },
        {
            "product_scope": "cookware",
            "previous_result_skus": ["SKU-A"],
        },
        {
            "recommendation_followup_action": "alternative",
            "relative_fields": ["weight"],
        },
    )

    assert normalized["route_family"] == "recommendation"
    assert normalized["context_usage"] == "recommendation_context"
    assert normalized["context_result_indexes"] == []
    assert normalized["subject_text"] == "cookware"
    assert normalized["canonical_fields"] == []
    assert normalized["decision_requested"] is True
    assert normalized["recommendation_followup_action"] == "alternative"
    assert "lighter than the prior recommendation" in normalized["recommendation_soft_preferences"]


def test_semantic_alternative_is_allowed_to_leave_single_product_anchor():
    agent_result = {
        "answer": "A lighter replacement.",
        "result_skus": ["SKU-B"],
        "debug": {},
    }

    guarded = customer_service_service._apply_sealed_context_anchor_cross_sku_guard(
        None,
        user_id="user-1",
        question="Is there a lighter one?",
        conversation_id=None,
        agent_result=agent_result,
        semantic_preplan={
            "route_family": "recommendation",
            "recommendation_followup_action": "alternative",
        },
    )

    assert guarded is agent_result


def test_product_bound_ambiguity_with_formal_work_reaches_rag_executor():
    preplan = {
        "called": True,
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "subject_text": "刚才那款",
        "canonical_fields": ["weight"],
        "confidence": 0.9,
        "confidence_label": "high",
        "ambiguity": True,
        "fallback_reason": "",
    }

    assert customer_service_service._semantic_first_turn_is_owned(preplan)


def test_comparison_adjudication_uses_one_semantic_decision_over_duplicate_review(monkeypatch):
    calls = []
    captured = {}

    async def fake_chat_completion(_db, messages, **kwargs):
        assert messages
        captured["system"] = messages[0]["content"]
        calls.append(kwargs.get("purpose"))
        return json.dumps({
            "selected_index": 0,
            "evidence_fields": ["weight"],
            "reasoning_summary": "participant 0 has the directly supported lower weight",
        })

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="两款商品哪个更轻？",
            evidence_packet={
                "weight": [
                    {"participant_index": 0, "value": "300g"},
                    {"participant_index": 1, "value": "500g"},
                ],
            },
            participant_count=2,
        )
    )

    assert decision["selected_index"] == 0
    assert decision["evidence_fields"] == ["weight"]
    assert calls == ["semantic_comparison_adjudication"]
    assert "lower recorded weight is directly the lighter participant" in captured["system"]
    assert "does not by itself prove carrying comfort" in captured["system"]
    assert "selected_index is the same participant identified by reasoning_summary" in captured["system"]


def test_comparison_decision_review_recovers_omitted_winner_request(monkeypatch):
    calls = []

    async def fake_chat_completion(_db, messages, **kwargs):
        assert messages
        calls.append(kwargs.get("purpose"))
        return json.dumps({"decision_requested": True})

    monkeypatch.setattr(
        customer_agent_planner_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    review = asyncio.run(
        customer_agent_planner_service.classify_semantic_comparison_decision(
            None,
            question="Which one is more suitable for a two-person hike? Compare weight and capacity.",
            semantic_preplan={
                "route_family": "comparison",
                "canonical_fields": ["weight", "capacity"],
                "decision_requested": False,
            },
        )
    )

    assert review["decision_requested"] is True
    assert review["fallback_reason"] == ""
    assert calls == ["semantic_comparison_decision_review"]


def test_recommendation_fact_integrity_keeps_measurements_bound_to_each_selected_sku():
    rows = [
        {"product_name_cn": "甲锅", "sku": "SKU-A", "capacity": "4L"},
        {"product_name_cn": "乙锅", "sku": "SKU-B", "capacity": "1.4L"},
    ]

    leaked = customer_service_service._recommendation_fact_integrity_conflicts(
        "甲锅容量4L，乙锅容量4L。",
        "比较两款锅的容量。",
        rows,
    )
    correct = customer_service_service._recommendation_fact_integrity_conflicts(
        "甲锅容量4L，乙锅容量1.4L。",
        "比较两款锅的容量。",
        rows,
    )

    assert leaked["cross_sku_measurements"]
    assert correct["cross_sku_measurements"] == []


def test_knowledge_base_meta_uses_document_rag_without_product_candidates(monkeypatch):
    calls = []

    async def fake_retrieve(_db, _query, **_kwargs):
        return [
            {
                "source_type": "manual",
                "sku": None,
                "content": "清洁后应擦干并保持通风，长期存放前确认表面干燥。",
                "metadata": {"source_id": "manual:care", "title": "清洁保养说明"},
                "score": 0.9,
            },
            {
                "source_type": "product",
                "sku": "CW-IGNORE",
                "content": "这条商品资料不应进入通用知识库回答。",
                "metadata": {"source_id": "product:CW-IGNORE"},
                "score": 0.99,
            },
        ]

    async def fake_chat(_db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        payload = json.loads(messages[-1]["content"])
        assert len(payload["excerpts"]) == 1
        assert "CW-IGNORE" not in json.dumps(payload, ensure_ascii=False)
        return json.dumps({
            "answer": "资料建议清洁后擦干并保持通风，长期存放前确认表面干燥。",
            "used_sources": [0],
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat)

    result = asyncio.run(
        customer_service_service._semantic_knowledge_base_meta_result(
            object(),
            "知识库里怎么说明清洁保养？",
            {
                "qa_evidence_query": "清洁保养",
                "route_family": "knowledge_base_meta",
            },
        )
    )

    assert result["answer_type"] == "knowledge_base_answer"
    assert result["result_skus"] == []
    assert result["debug"]["agent_mode"] == "semantic_knowledge_base_rag"
    assert result["evidence"][0]["source_id"] == "manual:care"
    assert calls == ["semantic_knowledge_base_answer"]


def test_knowledge_meta_retrieval_keeps_original_question_with_flash_hint(monkeypatch):
    queries = []

    async def fake_retrieve(_db, query, **_kwargs):
        queries.append(query)
        return [{
            "source_type": "manual",
            "sku": None,
            "content": "care procedure",
            "metadata": {"source_id": "manual:care"},
            "score": 1.0,
        }]

    async def fake_chat(_db, messages, **_kwargs):
        assert messages
        return json.dumps({"answer": "Use the recorded care procedure.", "used_sources": [0]})

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat)

    result = asyncio.run(
        customer_service_service._semantic_knowledge_base_meta_result(
            object(),
            "original care question",
            {"qa_evidence_query": "semantic care hint", "route_family": "knowledge_base_meta"},
        )
    )

    assert result is not None
    assert queries == ["original care question semantic care hint"]


def test_care_knowledge_can_use_sku_scoped_product_qa_without_product_candidates(monkeypatch):
    calls = []

    async def fake_retrieve(_db, _query, **_kwargs):
        return [
            {
                "source_type": "product",
                "sku": "CW-C73",
                "content": "Q: 如何清洗保养？ A: 使用后用温水和软刷清洗，彻底擦干，避免钢丝球刮擦。",
                "metadata": {
                    "source_id": "product:CW-C73:qa:care",
                    "section": "qa:care",
                    "title": "CW-C73 QA 清洗保养",
                    "sku": "CW-C73",
                },
                "score": 9.0,
            },
            {
                "source_type": "file",
                "sku": None,
                "content": "炉头功率与收纳袋信息。",
                "metadata": {"source_id": "file:unrelated", "title": "炉具资料"},
                "score": 0.2,
            },
        ]

    async def fake_chat(_db, messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        payload = json.loads(messages[-1]["content"])
        assert payload["excerpts"][0]["sku"] == "CW-C73"
        return json.dumps({
            "answer": "资料中记录使用温水和软刷清洗，洗后彻底擦干，并避免钢丝球刮擦。",
            "used_sources": [0],
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat)

    result = asyncio.run(
        customer_service_service._semantic_knowledge_base_meta_result(
            object(),
            "锅具如何清洗保养？",
            {"qa_evidence_query": "锅具清洗保养", "route_family": "general_chat"},
            allow_product_qa=True,
        )
    )

    assert result["answer_type"] == "knowledge_base_answer"
    assert result["result_skus"] == []
    assert result["evidence"][0]["sku"] == "CW-C73"
    assert calls == ["semantic_knowledge_base_answer"]


def test_answer_shaper_does_not_reapply_catalogue_cleanup(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("catalogue cleanup belongs to the central save boundary")

    monkeypatch.setattr(
        customer_service_service,
        "_clear_unrelated_catalogue_cards",
        fail_if_called,
    )

    result = customer_service_service._shape_answer_for_output({
        "intent": "recommendation",
        "answer_type": "recommendation",
        "answer": "Demo（SKU-A）",
        "results": [{"sku": "SKU-A", "product_name_cn": "Demo"}],
        "result_skus": ["SKU-A"],
        "candidate_skus": ["SKU-A"],
        "evidence": [],
        "answer_metadata": {},
        "debug": {"plan": {"raw_question": "please recommend"}},
    })

    assert result["answer"] == "Demo（SKU-A）"
