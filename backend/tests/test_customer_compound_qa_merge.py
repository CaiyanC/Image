from app.services import customer_service_service
from app.services import customer_agent_planner_service


def test_semantic_compound_children_may_share_one_verified_evidence_receipt():
    answers = []
    answered_requests = []
    candidate = {
        "answer": "\u8bb0\u5f55\u7684\u8010\u6e29\u4e0a\u9650\u4e3a140\u00b0F\uff0c\u6cb8\u6c34\u8d85\u51fa\u8be5\u8303\u56f4\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u704c\u88c5\u3002",
        "answer_metadata": {
            "evidence_ids": ["knowledge:temperature-boundary"],
            "evidence_source": "same_sku_knowledge",
        },
    }

    assert customer_service_service._record_semantic_compound_child(
        query="\u8010\u9ad8\u6e29",
        candidate=candidate,
        compound_answers=answers,
        answered_requests=answered_requests,
    )
    assert customer_service_service._record_semantic_compound_child(
        query="\u5f00\u6c34\u76f4\u63a5\u704c\u88c5",
        candidate=candidate,
        compound_answers=answers,
        answered_requests=answered_requests,
    )

    assert len(answers) == 2
    assert answered_requests == [
        ("\u8010\u9ad8\u6e29", "knowledge:temperature-boundary"),
        ("\u5f00\u6c34\u76f4\u63a5\u704c\u88c5", "knowledge:temperature-boundary"),
    ]


def test_semantic_compound_split_does_not_promote_intermediate_evidence_concepts(monkeypatch):
    async def fake_completion(_db, *, messages, **_kwargs):
        instruction = messages[0]["content"]
        assert "one-to-one to an explicit customer clause" in instruction
        assert "intermediate concept" in instruction
        assert "source_span must be the exact uninterrupted customer words" in instruction
        return (
            '{"items":['
            '{"query":"\u8010\u7528\u6027","source_span":"\u8010\u4e0d\u8010\u7528"},'
            '{"query":"\u8010\u9ad8\u6e29\u6027\u80fd","source_span":"\u521a\u716e\u5f00\u7684\u6c34\u80fd\u76f4\u63a5\u704c\u8fdb\u53bb\u5417"}'
            ']}'
        )

    monkeypatch.setattr(
        customer_agent_planner_service.customer_llm_service,
        "chat_completion",
        fake_completion,
    )

    import asyncio

    result = asyncio.run(
        customer_agent_planner_service._semantic_compound_product_qa_queries(
            None,
            question="\u7a33\u7a33\u6c34\u888b\u8010\u4e0d\u8010\u7528\uff0c\u521a\u716e\u5f00\u7684\u6c34\u80fd\u76f4\u63a5\u704c\u8fdb\u53bb\u5417\uff1f",
            runtime_settings={
                "max_tokens": 500,
                "model": "test-model",
                "response_format": {"type": "json_object"},
                "thinking": False,
            },
        )
    )

    assert result == [
        "\u8010\u4e0d\u8010\u7528",
        "\u521a\u716e\u5f00\u7684\u6c34\u80fd\u76f4\u63a5\u704c\u8fdb\u53bb\u5417",
    ]


def test_compound_child_retries_same_sku_rag_after_a_transient_semantic_rejection(monkeypatch):
    rag_calls = 0

    async def qa_miss(*_args, **_kwargs):
        return None

    async def rag_then_hit(*_args, **_kwargs):
        nonlocal rag_calls
        rag_calls += 1
        if rag_calls == 1:
            return None
        return {
            "answer": "\u8bb0\u5f55\u8010\u6e29\u4e0a\u9650\u4e3a140\u00b0F\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u704c\u6cb8\u6c34\u3002",
            "answer_metadata": {"evidence_ids": ["knowledge:temperature-boundary"]},
        }

    monkeypatch.setattr(
        customer_service_service,
        "_try_product_qa_shortcut_with_semantic_selection",
        qa_miss,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_try_sealed_same_sku_knowledge_answer",
        rag_then_hit,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_semantic_compound_child_answer(
            None,
            "\u521a\u716e\u5f00\u7684\u6c34\u80fd\u76f4\u63a5\u704c\u8fdb\u53bb\u5417",
            {"semantic_preplan": {"qa_evidence_query": "\u521a\u716e\u5f00\u7684\u6c34\u80fd\u76f4\u63a5\u704c\u8fdb\u53bb\u5417"}},
        )
    )

    assert rag_calls == 2
    assert result is not None
    assert "140\u00b0F" in result["answer"]
