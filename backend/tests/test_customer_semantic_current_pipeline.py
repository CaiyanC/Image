import asyncio
import json

from app.services import customer_agent_planner_service, customer_service_service


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

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "recommendation"
    assert result["route_hint"] == "recommendation"
    assert result["subject_text"] == "烤盘"
    assert result["recommendation_constraints"] == {}
    assert result["predicate_constraints"][0]["operator"] == "supports"


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

    async def fake_chat_completion(_db, messages, **kwargs):
        assert messages
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


def test_recommendation_group_outcome_allows_bounded_judgement_without_literal_promise():
    rows = [
        {
            "product_name_cn": "炊墨炒锅",
            "sku": "CW-C83-1",
            "capacity": "锅：3700ML",
            "features": "水性不沾，适合户外烹饪",
            "usage_scenarios": "家庭户外野餐",
            "target_audience": "家庭户外野餐群体",
        },
    ]

    bounded = customer_service_service._recommendation_fact_integrity_conflicts(
        "从容量和户外场景看可以作为三人用锅的候选，但实际能否吃饱还要结合食量。",
        "三个人露营想选一口锅。",
        rows,
    )
    unbounded = customer_service_service._recommendation_fact_integrity_conflicts(
        "这口锅能让三个人吃饱。",
        "三个人露营想选一口锅。",
        rows,
    )

    assert bounded["group_outcome"] == []
    assert unbounded["group_outcome"]


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
