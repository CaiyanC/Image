from app.services import customer_service_service
from app.services import customer_agent_planner_service




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




def test_semantically_complete_parent_answer_is_not_marked_missing_by_literal_child_matching():
    queries = [
        "稳稳水袋平常耐不耐用",
        "刚煮开的水能直接灌进去吗",
    ]
    answer = (
        "正常使用非常耐用，但刚煮开的水温度超过140°F（60°C），"
        "不建议直接灌入。"
    )

    assert customer_service_service._uncovered_compound_queries_for_output(
        answer,
        queries,
        {"semantic_answer_coverage_complete": True},
    ) == []
