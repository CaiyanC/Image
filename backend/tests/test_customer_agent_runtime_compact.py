from app.services import customer_agent_runtime_service
from app.services import customer_service_service


def test_build_result_prefers_final_answer_metadata_override():
    result = customer_agent_runtime_service._build_result(
        "question",
        "CW-C93",
        [{"tool": "get_product_detail", "detail": {"sku": "CW-C93", "product_name_cn": "X"}}],
        "insufficient",
        preserve_llm_answer=True,
        answer_metadata_override={
            "evidence_insufficient": True,
            "answer_policy": "insufficient_evidence",
        },
    )

    assert result["answer_metadata"] == {
        "evidence_insufficient": True,
        "answer_policy": "insufficient_evidence",
    }


def test_polish_customer_answer_skips_when_answer_metadata_marks_insufficient_evidence():
    called = []

    async def fail_chat_completion(*args, **kwargs):
        called.append("chat")
        raise AssertionError("chat_completion should not be called")

    original = customer_service_service.customer_llm_service.chat_completion
    customer_service_service.customer_llm_service.chat_completion = fail_chat_completion
    try:
        import asyncio

        answer = asyncio.run(customer_service_service._polish_customer_answer(
            None,
            "行山单锅有哪些不能承诺的宣传内容？",
            {
                "answer": "当前知识库没有专门维护行山单锅不可承诺或禁用的宣传内容，无法给出对应的禁用话术清单。",
                "answer_metadata": {
                    "evidence_insufficient": True,
                    "answer_policy": "insufficient_evidence",
                },
                "answer_type": "product_detail",
                "uncertainty": "not_recorded",
                "evidence": [],
                "followups": [],
                "suggested_followups": [],
            },
        ))
    finally:
        customer_service_service.customer_llm_service.chat_completion = original

    assert answer == "当前知识库没有专门维护行山单锅不可承诺或禁用的宣传内容，无法给出对应的禁用话术清单。"
    assert called == []


def test_polish_grounding_uses_the_structured_semantic_runtime():
    calls = []

    async def fake_chat_completion(*args, **kwargs):
        calls.append(kwargs)
        return '{"grounded": true}'

    original = customer_service_service.customer_llm_service.chat_completion
    customer_service_service.customer_llm_service.chat_completion = fake_chat_completion
    try:
        import asyncio

        grounded = asyncio.run(customer_service_service._polished_answer_is_evidence_grounded(
            None,
            "稳稳水袋耐用吗？",
            "采用耐用材质制造。",
            "这款水袋采用耐用材质制造。",
            [{"sku": "AC-19", "value": "采用耐用材质制造。"}],
        ))
    finally:
        customer_service_service.customer_llm_service.chat_completion = original

    runtime = customer_service_service.customer_agent_planner_service._semantic_preplan_runtime_settings()
    assert grounded is True
    assert calls[0]["api_model_override"] == runtime["model"]
    assert calls[0]["response_format"] == runtime["response_format"]
    assert calls[0]["thinking"] == runtime["thinking"]


def test_polish_prompt_forbids_summarising_grounded_product_facts():
    calls = []

    async def fake_chat_completion(*args, **kwargs):
        calls.append(kwargs)
        return "采用方形设计，支持中式煎炒。" if len(calls) == 1 else '{"grounded": true}'

    original = customer_service_service.customer_llm_service.chat_completion
    customer_service_service.customer_llm_service.chat_completion = fake_chat_completion
    try:
        import asyncio

        asyncio.run(customer_service_service._polish_customer_answer(
            None,
            "资料如何帮助理解这件装备？",
            {
                "answer": "方形设计增加烹饪空间，支持中式煎炒，轻量便携易收纳。",
                "answer_type": "product_detail",
                "uncertainty": "confirmed",
                "evidence": [{"sku": "CW-C69-1", "value": "方形设计增加烹饪空间，支持中式煎炒，轻量便携易收纳。"}],
            },
        ))
    finally:
        customer_service_service.customer_llm_service.chat_completion = original

    system_prompt = calls[0]["messages"][0]["content"]
    assert "不要改写、总结、复述或截取 draft_answer" in system_prompt


def test_polish_keeps_the_verified_draft_after_a_model_written_friendly_lead():
    async def fake_chat_completion(*args, **kwargs):
        return "给您说明一下：" if kwargs["purpose"] == "evidence_bounded_customer_polish" else '{"grounded": true}'

    original = customer_service_service.customer_llm_service.chat_completion
    customer_service_service.customer_llm_service.chat_completion = fake_chat_completion
    try:
        import asyncio

        answer = asyncio.run(customer_service_service._polish_customer_answer(
            None,
            "资料如何帮助理解这件装备？",
            {
                "answer": "方形设计增加烹饪空间，支持中式煎炒，轻量便携易收纳。",
                "answer_type": "product_detail",
                "uncertainty": "confirmed",
                "evidence": [{"sku": "CW-C69-1", "value": "方形设计增加烹饪空间，支持中式煎炒，轻量便携易收纳。"}],
            },
        ))
    finally:
        customer_service_service.customer_llm_service.chat_completion = original

    assert answer == "给您说明一下：\n方形设计增加烹饪空间，支持中式煎炒，轻量便携易收纳。"


def test_compact_retrieved_product_ignores_string_content_without_crashing():
    product = {
        "sku": "CS-B14",
        "product_name_cn": "旋焰酒精炉",
        "content": "酒精炉安全使用说明",
    }

    compact = customer_agent_runtime_service._compact_retrieved_product_for_prompt(product)

    assert compact["sku"] == "CS-B14"
    assert compact["product_name_cn"] == "旋焰酒精炉"


def test_compact_retrieved_product_ignores_string_specs_without_crashing():
    product = {
        "sku": "CS-B14",
        "product_name_cn": "旋焰酒精炉",
        "specs": "酒精炉规格说明",
    }

    compact = customer_agent_runtime_service._compact_retrieved_product_for_prompt(product)

    assert compact["sku"] == "CS-B14"
    assert compact["product_name_cn"] == "旋焰酒精炉"


def test_compact_retrieved_product_preserves_capacity_value_when_label_is_blank():
    product = {
        "sku": "CW-C93",
        "product_name_cn": "行山单锅",
        "specs": {
            "capacity": [
                {
                    "label": "",
                    "value": "锅：1000ML",
                    "unit": "",
                }
            ]
        },
    }

    compact = customer_agent_runtime_service._compact_retrieved_product_for_prompt(product)

    assert compact["capacity"] == "锅：1000ML"


def test_clean_customer_answer_replaces_br_and_strips_html_tags():
    answer = "第一行<br>第二行<br/>第三行<br />第四行<p>段落</p><b>重点</b>"

    cleaned = customer_agent_runtime_service._clean_customer_answer(answer)

    assert cleaned == "第一行\n第二行\n第三行\n第四行段落重点"
