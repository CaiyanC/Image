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


def test_semantic_predicate_keeps_headcount_and_volume_units_distinct():
    malformed = customer_agent_planner_service._validated_structured_query_constraints(
        [{
            "field": "capacity",
            "operator": ">=",
            "value": 2,
            "unit": "people",
            "evidence_span": "两个人",
        }]
    )
    valid = customer_agent_planner_service._validated_structured_query_constraints(
        [{
            "field": "people",
            "operator": ">=",
            "value": 2,
            "unit": "people",
            "evidence_span": "两个人",
        }]
    )

    assert malformed is None
    assert valid == [{
        "field": "people",
        "operator": ">=",
        "value": 2,
        "unit": "people",
        "evidence_span": "两个人",
    }]


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


def test_semantic_preplan_normalizes_catalogue_category_scope_transport():
    provider_shape = {
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "contents_accessories",
        "entities": [],
        "subject_text": "\u9644\u4ef6",
        "entity_scope": "catalogue_category",
        "canonical_fields": ["accessories"],
        "confidence": "high",
        "ambiguity": False,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "decision_requested": False,
        "predicate_constraints": [],
        "structured_query_constraints": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
        customer_question="\u9644\u4ef6\u6709\u54ea\u4e9b\u53ef\u9009\uff1f",
    )

    assert result["fallback_reason"] == ""
    assert result["entity_scope"] == "category_scope"
    assert result["canonical_fields"] == ["category"]


def test_unanchored_accessory_browse_is_recovered_by_flash_and_live_category(monkeypatch):
    calls = []

    async def fake_chat(_db, _messages, **kwargs):
        calls.append(kwargs.get("purpose"))
        assert "有哪些配件可选" in _messages[0]["content"]
        assert "category browse" in _messages[0]["content"]
        return json.dumps(
            {
                "route_family": "structured_query",
                "set_field": "category",
                "subject_text": "\u914d\u4ef6",
                "subject_kind": "",
                "unrepresented_requirements": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda _db, _ref: [{"category": "\u914d\u4ef6"}],
    )
    monkeypatch.setattr(
        customer_service_service,
        "_database_category_scope_ref",
        lambda _rows, subject: "\u914d\u4ef6" if subject == "\u914d\u4ef6" else "",
    )

    result = asyncio.run(
        customer_service_service._semantic_unanchored_catalogue_category_recovery(
            object(),
            "\u914d\u4ef6\u6709\u54ea\u4e9b\u53ef\u9009\uff1f",
            {
                "called": True,
                "route_family": "clarification",
                "route_hint": "clarification",
                "question_type": "contents_accessories",
                "subtype": "contents_accessories",
                "entities": [],
                "subject_text": "",
                "canonical_fields": ["accessories"],
                "field_type": "accessories",
                "field_hint": "accessories",
                "context_usage": "none",
                "context_result_indexes": [],
                "llm_call_count": 1,
                "llm_call_count_delta": 1,
            },
        )
    )

    assert result is not None
    assert result["route_family"] == "structured_query"
    assert result["canonical_fields"] == ["category"]
    assert result["subject_text"] == "\u914d\u4ef6"
    assert result["catalogue_category_ref"] == "\u914d\u4ef6"
    assert result["semantic_adapter_source"] == (
        "semantic_unanchored_catalogue_category_recovery"
    )
    assert result["llm_call_count"] == 2
    assert calls == ["semantic_unanchored_catalogue_scope_recovery"]


def test_unanchored_accessory_scope_does_not_bypass_identity_safety(monkeypatch):
    async def fake_chat(_db, _messages, **kwargs):
        assert kwargs.get("purpose") == "semantic_unanchored_catalogue_scope_recovery"
        return json.dumps(
            {
                "route_family": "clarification",
                "set_field": "",
                "subject_text": "",
                "subject_kind": "",
                "unrepresented_requirements": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat,
    )
    result = asyncio.run(
        customer_service_service._semantic_unanchored_catalogue_category_recovery(
            object(),
            "\u8fd9\u4e2a\u4ea7\u54c1\u6709\u54ea\u4e9b\u914d\u4ef6\uff1f",
            {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "accessory",
                "question_type": "contents_accessories",
                "subtype": "contents_accessories",
                "entities": [],
                "subject_text": "",
                "canonical_fields": ["accessories"],
                "field_type": "accessories",
                "field_hint": "accessories",
                "context_usage": "none",
                "context_result_indexes": [],
            },
        )
    )

    assert result is None


def test_unresolved_factor_cannot_authorize_an_adjacent_writer_field():
    violations = customer_service_service._semantic_recommendation_unresolved_factor_evidence_fields(
        {
            "ranked_candidate_indexes": [0],
            "evidence_usage": [{
                "candidate_index": 0,
                "fields": [
                    "identity.product_form",
                    "specs.capacity",
                    "content.features",
                ],
            }],
        },
        candidates=[{
            "candidate_index": 0,
            "sealed_evidence": {
                "identity.product_form": "cookware_set",
                "specs.capacity": "3L",
                "content.features": "全套收纳",
            },
        }],
        coverage={
            "decision_factors": [
                {
                    "factor": "cookware set",
                    "supported_candidate_indexes": [0],
                    "evidence_usage": [{
                        "candidate_index": 0,
                        "evidence": [{"field": "identity.product_form"}],
                    }],
                },
                {
                    "factor": "large capacity",
                    "supported_candidate_indexes": [0],
                    "evidence_usage": [{
                        "candidate_index": 0,
                        "evidence": [{"field": "specs.capacity"}],
                    }],
                },
                {
                    "factor": "easy to store",
                    "unverified_candidate_indexes": [0],
                    "evidence_usage": [{
                        "candidate_index": 0,
                        "evidence": [{"field": "content.features"}],
                    }],
                },
            ],
        },
    )

    assert violations == [{
        "candidate_index": 0,
        "field": "content.features",
        "unresolved_factors": ["easy to store"],
        "reason": "writer field is also attached to an unverified factor for this candidate",
    }]


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


def test_natural_category_browse_uses_live_catalogue_scope(monkeypatch):
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
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subject_text": "\u9505\u5177",
            "entities": ["\u9505\u5177"],
            "canonical_fields": [],
            "structured_query_constraints": [],
            "predicate_constraints": [],
            "recommendation_constraints": {},
            "decision_requested": False,
        },
        None,
        question="\u6211\u60f3\u770b\u9505\u5177\uff0c\u6709\u54ea\u4e9b\u53ef\u9009\uff1f",
    )

    assert normalized["route_family"] == "structured_query"
    assert normalized["route_hint"] == "query_products"
    assert normalized["canonical_fields"] == ["category"]
    assert normalized["catalogue_category_ref"] == "\u9505\u5177"
    assert normalized["accepted_or_overridden"] == "catalogue_category_continuation"


def test_structured_category_scope_survives_flash_scope_shape_in_predicate_slot():
    provider_shape = {
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "entities": ["\u9505\u5177"],
        "subject_text": "\u9505\u5177",
        "canonical_fields": ["category"],
        "confidence": 0.9,
        "ambiguity": False,
        "evidence_required": False,
        "evidence_kind": "structured_field",
        "decision_requested": False,
        "recommendation_constraints": {"subject_kinds": ["cookware"]},
        "structured_query_constraints": {"subject_kinds": ["cookware"]},
        "recommendation_evidence_requirements": [],
        "recommendation_soft_preferences": [],
        "unrepresented_recommendation_requirements": [],
    }

    result = customer_agent_planner_service._validate_semantic_preplan(
        provider_shape,
        raw_content=json.dumps(provider_shape, ensure_ascii=False),
        customer_question="\u6211\u60f3\u770b\u9505\u5177\uff0c\u6709\u54ea\u4e9b\u53ef\u9009\uff1f",
    )

    assert result["fallback_reason"] == ""
    assert result["route_family"] == "structured_query"
    assert result["subject_text"] == "\u9505\u5177"
    assert result["canonical_fields"] == ["category"]
    assert result["structured_query_constraints"] == []
    assert result["semantic_category_scope_salvaged"] is True


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


def test_semantic_repair_salvages_ambiguous_recommendation_scope_without_inventing_kind():
    initial_plan = {
        "route_family": "recommendation",
        "route_hint": "recommendation",
        "question_type": "recommendation",
        "subtype": "recommendation",
        "entities": [],
        "subject_text": "露营用品",
        "entity_scope": "category",
        "canonical_fields": [],
        "confidence": "high",
        "ambiguity": True,
        "evidence_required": True,
        "evidence_kind": "structured_field",
        "context_usage": "none",
        "decision_requested": True,
        "recommendation_constraints": {
            "subject_kinds": ["camping_gear"],
            "scenarios": ["camping"],
        },
        "recommendation_evidence_requirements": ["适合露营新手"],
        "recommendation_soft_preferences": ["实用"],
        "unrepresented_recommendation_requirements": ["不容易选错"],
        "reasoning_summary": "The customer wants a camping gift recommendation.",
    }

    preserved = customer_agent_planner_service._preserve_semantic_route_after_repair_failure(
        initial_plan,
        raw_content=json.dumps(initial_plan, ensure_ascii=False),
        failure_reason="invalid_recommendation_constraints",
        error=ValueError("schema repair returned an invalid optional scope"),
    )

    assert preserved is not None
    assert preserved["route_family"] == "recommendation"
    assert preserved["subject_text"] == "露营用品"
    assert preserved["recommendation_constraints"] == {"scenarios": ["camping"]}
    assert preserved["recommendation_evidence_requirements"] == ["适合露营新手"]
    assert preserved["recommendation_soft_preferences"] == ["实用"]
    assert preserved["unrepresented_recommendation_requirements"] == ["不容易选错"]


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


def test_unresolved_generic_product_safety_uses_knowledge_rag_shape(monkeypatch):
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

    assert normalized["route_family"] == "knowledge_base_meta"
    assert normalized["entities"] == []
    assert normalized["evidence_required"] is True
    assert normalized["information_scope"] == "knowledge_base_meta"
    assert normalized["semantic_adapter_source"] == (
        "semantic_unanchored_product_qa_to_knowledge_base_rag"
    )
    assert normalized["semantic_original_product_qa_scope"]["question_type"] == "usage"


def test_unanchored_product_qa_with_independent_semantic_query_uses_knowledge_rag():
    normalized = customer_service_service._normalize_unanchored_product_qa_to_general_chat(
        None,
        "\u4e0d\u7c98\u9505\u6d82\u5c42\u80fd\u7528\u94a2\u4e1d\u7403\u6e05\u6d17\u5417\uff1f",
        {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "usage_care",
            "question_type": "usage",
            "subject_text": "\u4e0d\u7c98\u9505",
            "qa_or_usage_care": True,
            "evidence_required": True,
            "evidence_kind": "structured_field",
            "semantic_product_field_supplemental_review": {
                "independent": True,
                "supplemental_query": "\u4e0d\u7c98\u6d82\u5c42\u662f\u5426\u80fd\u7528\u94a2\u4e1d\u7403\u6e05\u6d17",
            },
        },
    )

    assert normalized["route_family"] == "knowledge_base_meta"
    assert normalized["evidence_kind"] == "product_qa"
    assert normalized["qa_evidence_query"] == (
        "\u4e0d\u7c98\u6d82\u5c42\u662f\u5426\u80fd\u7528\u94a2\u4e1d\u7403\u6e05\u6d17"
    )
    assert normalized["semantic_adapter_source"] == (
        "semantic_unanchored_product_qa_to_knowledge_base_rag"
    )


def test_product_bound_missing_recovery_does_not_authorize_adjacent_care_procedure(monkeypatch):
    captured = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        return json.dumps({"answer": "这个使用条件目前没有直接确认记录。"}, ensure_ascii=False)

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )
    result = asyncio.run(
        customer_service_service._semantic_owned_missing_result_with_llm(
            object(),
            "得用防风打火机吧？",
            {
                "route_family": "product_bound_qa",
                "question_type": "usage",
                "subject_text": "",
                "entities": [],
            },
            reason="product_qa_evidence_missing",
        )
    )

    assert result["answer"] == "这个使用条件目前没有直接确认记录。"
    assert "no resolved identity or selected same-SKU evidence" in captured["system"]
    assert "Do not add an adjacent procedure" in captured["system"]


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
    assert "selected_participant or conditional_choice_participant is the same participant identified by reasoning_summary" in captured["system"]
    assert "must never be summed or described as a total capacity" in captured["system"]
    assert "cannot justify selecting the other participant or reverse a measured relation" in captured["system"]


def test_comparison_choice_packet_excludes_supplemental_rag_prose():
    packet = customer_service_service._semantic_comparison_choice_evidence_packet(
        {
            "capacity": [
                {"participant_index": 0, "value": "1.7L"},
                {"participant_index": 1, "value": "3.0L"},
            ],
            "comparison_qa": [
                {"participant_index": 0, "value": "方形设计增加烹饪空间"},
                {"participant_index": 1, "value": "适合背包旅行"},
            ],
        }
    )

    assert list(packet) == ["capacity"]
    assert packet["capacity"][1]["value"] == "3.0L"


def test_comparison_choice_packet_can_follow_semantic_field_contract():
    packet = customer_service_service._semantic_comparison_choice_evidence_packet(
        {
            "capacity": [{"participant_index": 0, "value": "1.7L"}],
            "target_audience": [{"participant_index": 0, "value": "1-2人"}],
        },
        preferred_fields={"capacity"},
    )

    assert list(packet) == ["capacity"]


def test_comparison_adjudication_maps_semantic_participant_labels():
    decision = customer_service_service._validate_semantic_comparison_adjudication(
        {
            "selected_participant": None,
            "conditional_choice_participant": "B",
            "evidence_fields": ["capacity"],
            "reasoning_summary": "B has the larger recorded capacity",
        },
        participant_count=2,
        allowed_evidence_fields={"capacity"},
    )

    assert decision["selected_index"] is None
    assert decision["conditional_choice_index"] == 1


def test_comparison_adjudication_accepts_conditional_choice_without_group_fit(monkeypatch):
    async def fake_chat_completion(_db, messages, **kwargs):
        assert messages
        return json.dumps({
            "selected_index": None,
            "conditional_choice_index": 1,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 1 has the directly larger recorded pot capacity",
        })

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="哪款更适合两个人露营？",
            evidence_packet={
                "capacity": [
                    {"participant_index": 0, "value": "1.7L"},
                    {"participant_index": 1, "value": "3.0L"},
                ],
            },
            participant_count=2,
        )
    )

    assert decision["selected_index"] is None
    assert decision["conditional_choice_index"] == 1
    assert decision["evidence_fields"] == ["capacity"]


def test_comparison_adjudication_receives_sealed_product_forms_for_component_semantics(monkeypatch):
    captured = {}

    async def fake_chat_completion(_db, messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        captured["payload"] = json.loads(messages[1]["content"])
        return json.dumps({
            "selected_participant": "B",
            "conditional_choice_participant": None,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "B's single pot is 3L, larger than A's labelled 1.7L pot.",
        })

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(customer_service_service._semantic_comparison_adjudication(
        None,
        question="Which pot has the larger capacity?",
        evidence_packet={
            "capacity": [
                {"participant_index": 0, "value": "kettle 1.0L, large pot 1.7L"},
                {"participant_index": 1, "value": "3L"},
            ],
        },
        participant_count=2,
        choice_requested=True,
        participant_forms=["cookware_set", "single_cookware"],
    ))

    assert decision["selected_index"] == 1
    assert captured["payload"]["participant_forms"] == {
        "A": "cookware_set",
        "B": "single_cookware",
    }
    assert "sealed catalogue identity context" in captured["system"]
    assert "must never be summed" in captured["system"]


def test_comparison_adjudication_retries_empty_choice_on_same_packet(monkeypatch):
    calls = []
    responses = iter([
        json.dumps({
            "selected_index": None,
            "conditional_choice_index": None,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "the group-fit outcome is not directly recorded",
        }),
        json.dumps({
            "selected_index": None,
            "conditional_choice_index": 1,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 1 has the directly larger recorded capacity",
        }),
    ])

    async def fake_chat_completion(*_args, **kwargs):
        calls.append(kwargs["purpose"])
        return next(responses)

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="哪款更适合两个人露营？",
            evidence_packet={
                "capacity": [
                    {"participant_index": 0, "value": "1.7L"},
                    {"participant_index": 1, "value": "3.0L"},
                ],
            },
            participant_count=2,
            choice_requested=True,
        )
    )

    assert decision["conditional_choice_index"] == 1
    assert calls == [
        "semantic_comparison_adjudication",
        "semantic_comparison_adjudication_retry",
    ]


def test_comparison_adjudication_keeps_noncolumn_choice_conditional(monkeypatch):
    calls = []
    responses = iter([
        json.dumps({
            "selected_index": 0,
            "conditional_choice_index": None,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 0 appears more suitable from the mixed packet",
        }),
        json.dumps({
            "selected_index": None,
            "conditional_choice_index": 1,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 1 has the directly larger recorded capacity",
        }),
    ])

    async def fake_chat_completion(*_args, **kwargs):
        calls.append(kwargs["purpose"])
        return next(responses)

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="哪款更适合两个人露营？",
            evidence_packet={
                "capacity": [
                    {"participant_index": 0, "value": "1.7L"},
                    {"participant_index": 1, "value": "3.0L"},
                ],
                "comparison_qa": [
                    {"participant_index": 0, "value": "方形设计"},
                    {"participant_index": 1, "value": "适合背包旅行"},
                ],
            },
            participant_count=2,
            choice_requested=True,
            allow_unconditional_choice=False,
        )
    )

    assert decision["selected_index"] is None
    assert decision["conditional_choice_index"] == 1
    assert calls == [
        "semantic_comparison_adjudication",
        "semantic_comparison_adjudication_retry",
    ]


def test_comparison_adjudication_rechecks_conditional_index_identity(monkeypatch):
    calls = []
    responses = iter([
        json.dumps({
            "selected_index": None,
            "conditional_choice_index": 0,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 1 has the larger recorded capacity",
        }),
        json.dumps({
            "selected_index": None,
            "conditional_choice_index": 1,
            "evidence_fields": ["capacity"],
            "reasoning_summary": "participant 1 has the larger recorded capacity",
        }),
    ])

    async def fake_chat_completion(*_args, **kwargs):
        calls.append(kwargs["purpose"])
        return next(responses)

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )

    decision = asyncio.run(
        customer_service_service._semantic_comparison_adjudication(
            None,
            question="哪款更适合两个人露营？",
            evidence_packet={
                "capacity": [
                    {"participant_index": 0, "value": "1.7L"},
                    {"participant_index": 1, "value": "3.0L"},
                ],
            },
            participant_count=2,
            choice_requested=True,
            allow_unconditional_choice=False,
        )
    )

    assert decision["selected_index"] is None
    assert decision["conditional_choice_index"] == 1
    assert calls == [
        "semantic_comparison_adjudication",
        "semantic_comparison_adjudication_retry",
    ]


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
    retrieval_kwargs = []

    async def fake_retrieve(_db, _query, **_kwargs):
        retrieval_kwargs.append(dict(_kwargs))
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
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        payload = json.loads(messages[-1]["content"])
        if purpose == "semantic_knowledge_evidence_relevance_audit":
            assert payload["excerpts"][0]["sku"] == "CW-C73"
            return json.dumps({
                "relevant_source_indexes": [0],
                "scope": "common_category",
                "reason": "The excerpt directly records the requested care operation.",
            }, ensure_ascii=False)
        assert purpose == "semantic_knowledge_base_answer"
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
    assert retrieval_kwargs[0]["sections"] == ["qa"]
    assert calls == [
        "semantic_knowledge_evidence_relevance_audit",
        "semantic_knowledge_base_answer",
    ]


def test_knowledge_rag_missing_closes_without_generic_care_writer():
    result = customer_service_service._semantic_knowledge_base_meta_missing_result(
        "不粘锅涂层能用钢丝球清洗吗？",
        {
            "route_family": "knowledge_base_meta",
            "information_scope": "knowledge_base_meta",
        },
        reason="knowledge_base_meta_executor_no_result",
    )

    assert result["answer"] == "当前知识库没有直接匹配的资料，暂时无法确认这个问题；请以该产品说明书或官方指引为准。"
    assert result["answer_metadata"]["source"] == "semantic_knowledge_base_rag_missing"
    assert result["answer_metadata"]["llm_allowed"] is False
    assert result["debug"]["agent_mode"] == "semantic_knowledge_base_rag_missing"


def test_product_qa_rag_drops_semantically_adjacent_evidence_before_writing(monkeypatch):
    calls = []

    async def fake_retrieve(_db, _query, **_kwargs):
        return [{
            "source_type": "product",
            "sku": "CF-PG19",
            "content": "Q: 瓦片烤盘有什么禁止操作？ A: 严禁骤冷骤热，严禁长时间浸泡水中。",
            "metadata": {
                "source_id": "product:CF-PG19:qa:care",
                "section": "qa:care",
                "title": "CF-PG19 QA 禁止操作",
                "sku": "CF-PG19",
            },
            "score": 9.0,
        }]

    async def fake_chat(_db, messages, **kwargs):
        purpose = kwargs.get("purpose")
        calls.append(purpose)
        assert purpose == "semantic_knowledge_evidence_relevance_audit"
        payload = json.loads(messages[-1]["content"])
        assert payload["question"] == "铝合金锅可以直接放在明火上烧吗？"
        return json.dumps({
            "relevant_source_indexes": [],
            "scope": "none",
            "reason": "The excerpt concerns cleaning care, not heat-source compatibility.",
        }, ensure_ascii=False)

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_chat)

    result = asyncio.run(
        customer_service_service._semantic_knowledge_base_meta_result(
            object(),
            "铝合金锅可以直接放在明火上烧吗？",
            {"qa_evidence_query": "明火兼容性", "route_family": "general_chat"},
            allow_product_qa=True,
        )
    )

    assert result is None
    assert calls == ["semantic_knowledge_evidence_relevance_audit"]


def test_semantic_coverage_preserves_typed_assignment_role_for_rag_reranking(monkeypatch):
    captured = {}

    async def fake_chat_completion(*_args, **kwargs):
        captured["system"] = kwargs["messages"][0]["content"]
        return json.dumps({
            "decision_factors": [{
                "factor": "gift suitability",
                "customer_basis": "the item is requested as a gift",
                "dimension": "",
                "factor_type": "practical_fit",
                "decision_kind": "subjective_outcome",
                "importance": "preferred",
                "supported_candidate_indexes": [0],
                "bounded_candidate_indexes": [],
                "partial_candidate_indexes": [],
                "unverified_candidate_indexes": [],
                "evidence_usage": [{
                    "candidate_index": 0,
                    "evidence": [{
                        "field": "identity.product_form",
                        "excerpt": "cookware_set",
                    }],
                }],
            }],
            "coverage": [],
            "candidate_usability": [{"candidate_index": 0, "status": "usable"}],
            "request_fit": [{"candidate_index": 0, "status": "supported"}],
            "ranked_candidate_indexes": [0],
        }, ensure_ascii=False)

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_chat_completion,
    )
    coverage = asyncio.run(
        customer_service_service._semantic_recommendation_requirement_coverage(
            object(),
            question="我想送朋友一件不容易选错的露营礼物",
            candidates=[{
                "candidate_index": 0,
                "sku": "CW-C78",
                "product_name": "享野套锅",
                "product_form": "cookware_set",
                "sealed_evidence": {
                    "identity.product_name": "享野套锅",
                    "identity.product_form": "cookware_set",
                },
            }],
            semantic_requirements=[],
            decision_factor_contract=[{
                "factor": "gift suitability",
                "customer_basis": "the item is requested as a gift",
                "dimension": "",
                "factor_type": "practical_fit",
                "decision_kind": "subjective_outcome",
                "importance": "preferred",
                "requested_role_factor": True,
            }],
        )
    )

    assert coverage is not None
    assert coverage["decision_factors"][0]["requested_role_factor"] is True
    assert "requested_role_factor=true" in captured["system"]


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
