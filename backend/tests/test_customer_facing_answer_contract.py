"""Test prompt wiring/protocol, not a substitute for real answer-quality review."""
import asyncio
import json

import pytest

from app.services import (
    customer_llm_service,
    customer_service_semantic_rag_v2_service as formal,
    customer_service_workbuddy_rag_service as rag,
    customer_service_workbuddy_agent_service as agent,
)
from app.services.customer_facing_answer_contract import CUSTOMER_FACING_ANSWER_CONTRACT


@pytest.mark.parametrize('service', [formal, rag])
def test_final_writer_receives_contract_without_extra_call(monkeypatch, service):
    calls = []

    async def fake_chat(_db, **kwargs):
        calls.append(kwargs)
        return json.dumps({'answer': '这款容量是 1.4L。', 'evidence_ids': ['e1']}, ensure_ascii=False)

    monkeypatch.setattr(customer_llm_service, 'chat_completion', fake_chat)
    payload = {'current_question': '容量多少？', 'evidence': [], 'answer_repair_request': 'identity check'}
    result, _ = asyncio.run(service._generate_answer(None, payload=payload))
    assert len(calls) == 1
    prompt = calls[0]['messages'][0]['content']
    assert prompt.endswith(CUSTOMER_FACING_ANSWER_CONTRACT)
    assert prompt.count('【顾客直发回复规范】') == 1
    assert 'canonical_product_record' in prompt
    assert 'SKU' in prompt and 'evidence' in prompt
    assert calls[0]['response_format'] == {'type': 'json_object'}
    assert result['answer'] == '这款容量是 1.4L。'
    assert result['evidence_ids'] == ['e1']


def test_streaming_rag_uses_same_contract_and_preserves_answer(monkeypatch):
    calls, deltas = [], []

    async def fake_stream(_db, **kwargs):
        calls.append(kwargs)
        yield '{"answer":"暂时不能确认是否附送收纳袋。",'
        yield '"evidence_ids":["e1"]}'

    async def capture(delta):
        deltas.append(delta)

    monkeypatch.setattr(customer_llm_service, 'chat_completion_stream', fake_stream)
    result, _ = asyncio.run(rag._generate_answer(None, payload={}, answer_delta_callback=capture))
    assert len(calls) == 1
    assert calls[0]['messages'][0]['content'].endswith(CUSTOMER_FACING_ANSWER_CONTRACT)
    assert ''.join(deltas) == result['answer']


def test_agent_keeps_grounding_and_tool_protocol_with_customer_contract():
    prompt = agent._agent_system_prompt()
    assert prompt.endswith(CUSTOMER_FACING_ANSWER_CONTRACT)
    for term in ['read_product', 'fact_authority', 'response_mode=grounded', 'tool_calls', 'claims']:
        assert term in prompt
    assert '不能承诺稍后主动回复' in prompt
    assert '不删掉影响结论的条件和例外' in prompt
