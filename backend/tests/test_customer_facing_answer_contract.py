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


@pytest.mark.parametrize('service', [formal, rag])
def test_final_writer_receives_contract_without_extra_call(monkeypatch, service):
    calls = []

    async def fake_chat(_db, **kwargs):
        calls.append(kwargs)
        return json.dumps({'answer': '这款容量是 1.4L。', 'evidence_ids': ['e1']}, ensure_ascii=False)

    monkeypatch.setattr(customer_llm_service, 'chat_completion', fake_chat)
    payload = {
        'current_question': '容量多少？',
        'evidence': [{'evidence_id': 'e1', 'sku': 'SKU-A', 'content': '1.4L', 'fact_authority': True}],
        'answer_repair_request': 'identity check',
    }
    result, _ = asyncio.run(service._generate_answer(None, payload=payload))
    assert len(calls) == 1
    prompt = calls[0]['messages'][0]['content']
    assert '当前 evidence' in prompt
    assert '主产品记录' in prompt
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
    result, _ = asyncio.run(rag._generate_answer(None, payload={
        'evidence': [{'evidence_id': 'e1', 'content': '当前证据', 'fact_authority': True}],
    }, answer_delta_callback=capture))
    assert len(calls) == 1
    assert '当前 evidence' in calls[0]['messages'][0]['content']
    assert ''.join(deltas) == result['answer']


def test_agent_keeps_grounding_and_tool_protocol_with_customer_contract():
    prompt = agent._agent_system_prompt()
    for term in ['read_product', 'fact_authority', 'response_mode=grounded', 'tool_calls', 'claims']:
        assert term in prompt
    assert '完整需求' in prompt
    assert '当前证据' in prompt
    assert '固定问题树' in prompt
