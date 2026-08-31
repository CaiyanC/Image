from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.services import customer_service_service as service


class _ProductQuery:
    def __init__(self, products):
        self._products = products

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._products)


class _ProductDb:
    def __init__(self, products):
        self._products = products

    def query(self, *_args, **_kwargs):
        return _ProductQuery(self._products)


def _product(
    sku: str,
    name: str,
    *,
    category: str = "锅具",
    lifecycle_status: str = "常规品",
):
    return SimpleNamespace(
        sku=sku,
        product_name_cn=name,
        product_name_en="",
        category=category,
        lifecycle_status=lifecycle_status,
    )


def _recovery(sku: str, name: str, candidates: list[str]):
    return {
        "source": "product_knowledge_rag",
        "resolved_sku": sku,
        "resolved_product_name": name,
        "candidate_skus": candidates,
    }


def test_rag_recovery_receipt_requires_live_candidate_and_canonical_name():
    target = _product("TW-141", "烽宴聚能锅")
    other = _product("CF-PG19", "瓦片烤盘")
    products = [target, other]

    valid = {"semantic_identity_recovery": _recovery("TW-141", "烽宴聚能锅", ["TW-141", "CF-PG19"])}
    assert service._semantic_rag_recovered_product(products, valid) is target

    absent_candidate = {"semantic_identity_recovery": _recovery("TW-141", "烽宴聚能锅", ["CF-PG19"])}
    assert service._semantic_rag_recovered_product(products, absent_candidate) is None

    mismatched_name = {"semantic_identity_recovery": _recovery("TW-141", "瓦片烤盘", ["TW-141"])}
    assert service._semantic_rag_recovered_product(products, mismatched_name) is None


def test_identity_recovery_uses_full_customer_turn_and_ignores_predicate_candidate(monkeypatch):
    target = _product("TW-141", "烽宴聚能锅")
    predicate_product = _product("CF-PG19", "瓦片烤盘")
    db = _ProductDb([target, predicate_product])
    captured = {}

    monkeypatch.setattr(service.customer_agent_service, "_extract_skus", lambda _question: [])
    monkeypatch.setattr(
        service,
        "_products_named_in_question",
        lambda _db, _question: [predicate_product],
    )

    async def fake_retrieve(_db, query, **kwargs):
        captured["retrieval_query"] = query
        captured["retrieval_kwargs"] = kwargs
        return [{
            "sku": "TW-141",
            "content": "问：烽宴方锅的锅盖能当煎盘用吗？答：可以。",
            "score": 0.95,
            "metadata": {"section": "qa", "source_id": "qa:tw-141"},
        }]

    async def fake_chat_completion(_db, messages, **kwargs):
        captured["purpose"] = kwargs["purpose"]
        captured["payload"] = json.loads(messages[-1]["content"])
        return json.dumps({
            "selected_candidate_index": 0,
            "confidence": "high",
            "reasoning_summary": "same product alias",
        })

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "flash", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    question = "烽宴方锅的盖子能不能当煎盘用？"
    result = asyncio.run(service._semantic_recover_product_identity_from_rag(
        db,
        question,
        {
            "route_family": "product_bound_qa",
            "subject_text": "烽宴方锅",
            "context_result_indexes": [],
            "context_usage": "none",
        },
    ))

    assert captured["retrieval_query"] == question
    assert captured["payload"]["customer_question"] == question
    assert captured["payload"]["customer_product_subject"] == "烽宴方锅"
    assert captured["purpose"] == "semantic_product_identity_rag_rerank"
    assert result["subject_text"] == "烽宴聚能锅"
    assert result["semantic_identity_recovery"]["resolved_sku"] == "TW-141"


def test_identity_recovery_refines_evidence_inside_recalled_candidate_skus(monkeypatch):
    target = _product("AC-Z13", "拾野·便携调料瓶套装", category="配件")
    other = _product("TX-38", "坐忘泡茶套装", category="茶具")
    db = _ProductDb([target, other])
    retrieval_calls = []
    captured = {}

    monkeypatch.setattr(service.customer_agent_service, "_extract_skus", lambda _question: [])
    monkeypatch.setattr(service, "_products_named_in_question", lambda _db, _question: [])

    async def fake_retrieve(_db, query, **kwargs):
        retrieval_calls.append({"query": query, **kwargs})
        if kwargs.get("skus"):
            return [{
                "sku": "AC-Z13",
                "content": (
                    "Q: 拾野·便携调料瓶套装的尺寸是多少？\n"
                    "A: 液体瓶约φ4×13.7cm，粉罐约3.8×3.8×9.5cm。"
                ),
                "score": 0.93,
                "metadata": {"section": "qa", "source_id": "qa:ac-z13:size"},
            }]
        return [
            {
                "sku": "AC-Z13",
                "content": "Q: 拾野·便携调料瓶套装怎么辨别正品？答：扫描防伪码。",
                "score": 0.81,
                "metadata": {"section": "qa", "source_id": "qa:ac-z13:auth"},
            },
            {
                "sku": "TX-38",
                "content": "Q: 坐忘泡茶套装怎么清洗？答：温水清洗。",
                "score": 0.73,
                "metadata": {"section": "qa", "source_id": "qa:tx-38:care"},
            },
        ]

    async def fake_chat_completion(_db, messages, **kwargs):
        captured["payload"] = json.loads(messages[-1]["content"])
        return json.dumps({
            "selected_candidate_index": 0,
            "confidence": "high",
            "reasoning_summary": "same-SKU component evidence establishes the shorthand",
        })

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "flash", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    question = "调料套装里的液体瓶和粉罐分别多大？"
    result = asyncio.run(service._semantic_recover_product_identity_from_rag(
        db,
        question,
        {
            "route_family": "product_bound_qa",
            "subject_text": "调料套装",
            "context_result_indexes": [],
            "context_usage": "none",
        },
    ))

    assert len(retrieval_calls) == 2
    assert retrieval_calls[0]["query"] == question
    assert retrieval_calls[1]["skus"] == ["AC-Z13", "TX-38"]
    target_evidence = captured["payload"]["candidates"][0]["retrieved_evidence"]
    assert "液体瓶约φ4×13.7cm" in target_evidence[0]["content"]
    assert result["semantic_identity_recovery"]["resolved_sku"] == "AC-Z13"


def test_identity_recovery_keeps_retired_product_for_support_question(monkeypatch):
    retired = _product(
        "CW-C19T-37",
        "旅伴2-3人野餐锅5件套",
        lifecycle_status="老款无货不补",
    )
    live_distractor = _product("CW-C77", "Where Eat-享野系列套锅-套装1")
    db = _ProductDb([retired, live_distractor])
    captured = {}

    monkeypatch.setattr(service.customer_agent_service, "_extract_skus", lambda _question: [])
    monkeypatch.setattr(service, "_products_named_in_question", lambda _db, _question: [])

    async def fake_retrieve(_db, _query, **kwargs):
        if kwargs.get("skus"):
            captured["scoped_skus"] = list(kwargs["skus"])
        return [
            {
                "sku": "CW-C19T-37",
                "content": (
                    "Q: 旅伴2-3人野餐锅5件套是不是304不锈钢做的？\n"
                    "A: 不是，主体材质是硬质氧化铝合金。"
                ),
                "score": 0.97,
                "metadata": {"section": "qa", "source_id": "qa:cw-c19t-37:material"},
            },
            {
                "sku": "CW-C77",
                "content": "Q: 享野套锅是什么材质？答：硬质氧化铝合金。",
                "score": 0.71,
                "metadata": {"section": "qa", "source_id": "qa:cw-c77:material"},
            },
        ]

    async def fake_chat_completion(_db, messages, **_kwargs):
        candidates = json.loads(messages[-1]["content"])["candidates"]
        captured["candidate_skus"] = [item["sku"] for item in candidates]
        return json.dumps({
            "selected_candidate_index": 0,
            "confidence": "high",
            "reasoning_summary": "approved product QA establishes the retired product shorthand",
        })

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "luna", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    question = "旅伴那套锅是不是304不锈钢做的？"
    result = asyncio.run(service._semantic_recover_product_identity_from_rag(
        db,
        question,
        {
            "route_family": "product_bound_qa",
            "subject_text": "旅伴那套锅",
            "context_result_indexes": [],
            "context_usage": "none",
        },
    ))

    assert captured["scoped_skus"] == ["CW-C19T-37", "CW-C77"]
    assert captured["candidate_skus"] == ["CW-C19T-37", "CW-C77"]
    assert result["semantic_identity_recovery"]["resolved_sku"] == "CW-C19T-37"


def test_entity_guard_keeps_validated_rag_sku_over_predicate_noun(monkeypatch):
    target = _product("TW-141", "烽宴聚能锅")
    predicate_product = _product("CF-PG19", "瓦片烤盘")
    db = _ProductDb([target, predicate_product])
    captured = {}

    monkeypatch.setattr(service, "_semantic_prefers_sealed_product_qa", lambda _plan: True)
    monkeypatch.setattr(
        service,
        "_products_named_in_question",
        lambda _db, _question: [predicate_product],
    )
    monkeypatch.setattr(
        service.customer_entity_resolution_contract,
        "recover_explicit_versioned_subject",
        lambda *_args: "",
    )

    def canonical_subject_must_not_override(*_args, **_kwargs):
        raise AssertionError("validated RAG identity must bypass later local canonical override")

    monkeypatch.setattr(
        service.customer_entity_resolution_contract,
        "unique_canonical_subject_in_question",
        canonical_subject_must_not_override,
    )
    monkeypatch.setattr(service, "_resolve_exact_sku_variant", lambda *_args: None)
    monkeypatch.setattr(service, "_resolve_explicit_question_sku", lambda *_args: None)

    contract = SimpleNamespace(status="resolved", to_dict=lambda: {"status": "resolved"})

    def fake_build(_question, _products, **kwargs):
        captured["resolver_candidates"] = kwargs["resolver_candidates"]
        captured["entity_text_override"] = kwargs["entity_text_override"]
        return contract

    monkeypatch.setattr(
        service.customer_entity_resolution_contract,
        "build_entity_resolution_contract",
        fake_build,
    )
    monkeypatch.setattr(
        service.customer_entity_resolution_contract,
        "can_resolve_single_product",
        lambda *_args: SimpleNamespace(allowed=True, resolved_sku="TW-141"),
    )
    monkeypatch.setattr(
        service,
        "_sealed_product_qa_safe_missing_result",
        lambda product, _answer, **kwargs: {
            "sku": product.sku,
            "debug": kwargs["debug"],
        },
    )

    result = service._sealed_semantic_product_qa_entity_guard(
        db,
        "烽宴方锅的盖子能不能当煎盘用？",
        {
            "semantic_preplan": {
                "route_family": "product_bound_qa",
                "subject_text": "烽宴方锅",
                "semantic_identity_recovery": _recovery(
                    "TW-141",
                    "烽宴聚能锅",
                    ["TW-141", "CF-PG19"],
                ),
            },
        },
    )

    assert captured["resolver_candidates"] == [target]
    assert captured["entity_text_override"] == "烽宴聚能锅"
    assert result["sku"] == "TW-141"
    assert result["debug"]["binding_provenance"] == "semantic_product_knowledge_rag_identity_recovery"


def test_direct_recommendation_uses_bounded_same_sku_rag_answer(monkeypatch):
    adapter = _product("GA01-37", "mountain-to-long-canister adapter", category="accessory")
    unrelated = _product("GA03", "other canister adapter", category="accessory")
    db = _ProductDb([adapter, unrelated])
    retrieval_calls = []
    captured = {}

    async def fake_retrieve(_db, query, **kwargs):
        retrieval_calls.append({"query": query, **kwargs})
        if kwargs.get("skus"):
            return [{
                "sku": "GA01-37",
                "content": (
                    "Q: Which adapter connects a mountain-canister stove to a long canister? "
                    "A: Use the GA01-37 mountain-to-long-canister adapter."
                ),
                "score": 0.97,
                "metadata": {"section": "qa", "source_id": "qa:ga01-37:adapter"},
            }]
        return [
            {
                "sku": "GA01-37",
                "content": "GA01-37 connects a mountain-canister stove to a long canister.",
                "score": 0.95,
                "metadata": {"section": "qa", "source_id": "qa:ga01-37:adapter"},
            },
            {
                "sku": "GA03",
                "content": "GA03 is another canister adapter.",
                "score": 0.71,
                "metadata": {"section": "content", "source_id": "product:ga03"},
            },
        ]

    async def fake_chat_completion(_db, messages, **kwargs):
        captured["purpose"] = kwargs["purpose"]
        captured["review_payload"] = json.loads(messages[-1]["content"])
        return json.dumps({
            "selected_candidate_index": 0,
            "selected_evidence_indexes": [0],
            "direct_answerable": True,
            "coverage": "full",
            "confidence": "high",
            "reasoning_summary": "one same-SKU QA directly covers the interface conversion",
        })

    async def fake_same_sku_answer(_db, question, phase1_plan):
        captured["answer_question"] = question
        captured["qa_preplan"] = phase1_plan["semantic_preplan"]
        return {
            "answer": "Use the GA01-37 mountain-to-long-canister adapter.",
            "result_skus": ["GA01-37"],
            "answer_metadata": {},
            "debug": {"agent_mode": "sealed_same_sku_knowledge"},
        }

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(service, "_try_sealed_same_sku_knowledge_answer", fake_same_sku_answer)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "flash", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    question = "Which adapter lets this mountain-canister stove use a long canister?"
    result = asyncio.run(service._semantic_direct_recommendation_same_sku_rag_answer(
        db,
        question=question,
        semantic_preplan={
            "called": True,
            "route_family": "recommendation",
            "route_hint": "accessory",
            "decision_requested": True,
            "subject_text": "mountain-canister stove to long canister",
            "recommendation_evidence_requirements": ["compatible interface conversion"],
            "recommendation_soft_preferences": [],
            "context_result_indexes": [],
            "context_usage": "none",
            "confidence": 0.91,
            "confidence_label": "high",
        },
        phase1_plan={},
    ))

    assert len(retrieval_calls) == 2
    assert retrieval_calls[1]["skus"] == ["GA01-37", "GA03"]
    assert captured["purpose"] == "semantic_direct_recommendation_same_sku_rag_review"
    assert captured["qa_preplan"]["route_family"] == "product_bound_qa"
    assert captured["qa_preplan"]["semantic_identity_recovery"]["resolved_sku"] == "GA01-37"
    assert captured["qa_preplan"]["semantic_identity_recovery"]["candidate_skus"] == [
        "GA01-37",
        "GA03",
    ]
    assert result["result_skus"] == ["GA01-37"]
    assert result["answer_metadata"]["source"] == "semantic_direct_recommendation_same_sku_rag"
    assert result["debug"]["agent_mode"] == "semantic_direct_recommendation_same_sku_rag"


def test_direct_recommendation_rejects_partial_rag_evidence(monkeypatch):
    adapter = _product("GA01-37", "mountain-to-long-canister adapter", category="accessory")
    db = _ProductDb([adapter])

    async def fake_retrieve(_db, _query, **_kwargs):
        return [{
            "sku": "GA01-37",
            "content": "GA01-37 is a canister adapter.",
            "score": 0.82,
            "metadata": {"section": "content", "source_id": "product:ga01-37"},
        }]

    async def fake_chat_completion(_db, _messages, **_kwargs):
        return json.dumps({
            "selected_candidate_index": None,
            "selected_evidence_indexes": [],
            "direct_answerable": False,
            "coverage": "partial",
            "confidence": "low",
            "reasoning_summary": "the evidence does not state the requested relationship",
        })

    async def same_sku_must_not_run(*_args, **_kwargs):
        raise AssertionError("partial evidence must fall through to the recommendation contract")

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(service, "_try_sealed_same_sku_knowledge_answer", same_sku_must_not_run)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "flash", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    result = asyncio.run(service._semantic_direct_recommendation_same_sku_rag_answer(
        db,
        question="Which adapter is the most stable and cheapest?",
        semantic_preplan={
            "called": True,
            "route_family": "recommendation",
            "decision_requested": True,
            "subject_text": "canister adapter",
            "recommendation_evidence_requirements": ["compatibility", "stability", "price"],
            "recommendation_soft_preferences": [],
            "context_result_indexes": [],
            "context_usage": "none",
            "confidence": 0.9,
            "confidence_label": "high",
        },
    ))

    assert result is None


def test_direct_recommendation_excludes_unavailable_lifecycle_sku(monkeypatch):
    retired = _product(
        "AC-Z09",
        "老款转换接头",
        category="配件",
        lifecycle_status="老款无货不补",
    )
    live = _product(
        "GA01-37",
        "山系转长罐转换接头",
        category="配件",
    )
    db = _ProductDb([retired, live])
    captured = {}

    async def fake_retrieve(_db, _query, **kwargs):
        if kwargs.get("skus"):
            captured["scoped_skus"] = list(kwargs["skus"])
            return [{
                "sku": "GA01-37",
                "content": "GA01-37 可将山系气罐接口转换为长罐接口。",
                "score": 0.96,
                "metadata": {"section": "qa", "source_id": "qa:ga01-37"},
            }]
        return [
            {
                "sku": "AC-Z09",
                "content": "AC-Z09 可用于山系气罐转长罐。",
                "score": 0.99,
                "metadata": {"section": "qa", "source_id": "qa:ac-z09"},
            },
            {
                "sku": "GA01-37",
                "content": "GA01-37 可将山系气罐接口转换为长罐接口。",
                "score": 0.96,
                "metadata": {"section": "qa", "source_id": "qa:ga01-37"},
            },
        ]

    async def fake_chat_completion(_db, messages, **kwargs):
        captured["candidates"] = json.loads(messages[-1]["content"])["candidates"]
        return json.dumps({
            "selected_candidate_index": 0,
            "selected_evidence_indexes": [0],
            "direct_answerable": True,
            "coverage": "full",
            "confidence": "high",
            "reasoning_summary": "live same-SKU evidence directly supports the interface",
        })

    async def fake_same_sku_answer(_db, _question, phase1_plan):
        assert phase1_plan["semantic_preplan"]["semantic_identity_recovery"][
            "resolved_sku"
        ] == "GA01-37"
        return {
            "answer": "推荐山系转长罐转换接头。",
            "result_skus": ["GA01-37"],
            "answer_metadata": {},
            "debug": {"agent_mode": "sealed_same_sku_knowledge"},
        }

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(service.customer_llm_service, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(service, "_try_sealed_same_sku_knowledge_answer", fake_same_sku_answer)
    monkeypatch.setattr(
        service.customer_agent_planner_service,
        "_semantic_preplan_runtime_settings",
        lambda: {"model": "flash", "max_tokens": 180, "response_format": None, "thinking": None},
    )

    result = asyncio.run(service._semantic_direct_recommendation_same_sku_rag_answer(
        db,
        question="哪款接头能把山系气罐转成长罐？",
        semantic_preplan={
            "called": True,
            "route_family": "recommendation",
            "decision_requested": True,
            "subject_text": "山系气罐转长罐接头",
            "recommendation_evidence_requirements": ["接口转换"],
            "recommendation_soft_preferences": [],
            "context_result_indexes": [],
            "context_usage": "none",
            "confidence": 0.91,
            "confidence_label": "high",
        },
        phase1_plan={},
    ))

    assert result["result_skus"] == ["GA01-37"]
    assert captured["scoped_skus"] == ["GA01-37"]
    assert [item["sku"] for item in captured["candidates"]] == ["GA01-37"]


def test_approved_heat_source_qa_can_corroborate_same_sku_structured_sources():
    approved_heat_qa = SimpleNamespace(
        question="蓝翼分体炉高山气罐和卡式气罐都能用吗？",
        answer="高山气罐和卡式气罐都能用。",
        tags=json.dumps(["历史自然问法", "热源"], ensure_ascii=False),
    )
    unrelated_qa = SimpleNamespace(
        question="蓝翼分体炉有多重？",
        answer="高山气罐和卡式气罐都能用。",
        tags=json.dumps(["历史自然问法", "重量"], ensure_ascii=False),
    )

    assert service._approved_heat_source_qa_corroborates_structured_value(
        [approved_heat_qa],
        "高山气罐\n卡式气罐",
    )
    assert not service._approved_heat_source_qa_corroborates_structured_value(
        [unrelated_qa],
        "高山气罐\n卡式气罐",
    )
