import asyncio
import json

import pytest
from app.services.customer_purchase_urgency import analyze_purchase, purchase_turn_context
from app.services.customer_service_triage import classify, safe_reply
from app.services.customer_answer_prompt import build_customer_answer_prompt


@pytest.mark.parametrize('q', ['明天麻烦务必发出，我要得比较着急', '明天就要出发，能赶上吗', '周五前需要收到', '今天必须用到', '急用，哪个型号合适'])
def test_explicit_urgency(q):
    assert analyze_purchase(q)['level'] == 'urgent'


@pytest.mark.parametrize('q', ['今天能发么', '什么时候发货', '这个有收纳袋吗', '啥样的能看看吗', '两套分别多重'])
def test_do_not_invent_urgency_or_low_intent(q):
    assert analyze_purchase(q)['level'] == 'unknown'


@pytest.mark.parametrize('q', ['不急，先了解一下', '我只是来问问', '随便看看，暂时不买'])
def test_explicit_browsing(q):
    assert analyze_purchase(q)['level'] == 'browsing'


def test_multi_turn_inheritance_update_and_reset():
    state = analyze_purchase('这套我需要15套，还可以优惠吗？')
    assert state['level'] == 'planned' and state['stage'] == 'intending'
    state = analyze_purchase('明天麻烦务必发出，我要的比较着急', state)
    assert state['level'] == 'urgent' and '明天' in state['deadline_expression']
    state = analyze_purchase('我应该是已经支付了', state)
    assert state['level'] == 'urgent' and state['stage'] == 'ordered' and state['inherited']
    state = analyze_purchase('不能申请一下吗', state)
    assert state['level'] == 'urgent' and state['deadline_expression']
    assert analyze_purchase('不急了，先了解一下', state)['level'] == 'browsing'
    assert analyze_purchase('换个话题，容量多少', state)['level'] == 'unknown'
    assert analyze_purchase('另一笔订单什么时候发货', state)['deadline_expression'] == ''


def test_safety_priority_and_compound_goal_preserved():
    t = classify('明天要用，炉子正在漏气，我不急着买了')
    assert t['urgency'] == 'immediate' and t['question_kind'] == 'safety'
    assert safe_reply(t).startswith('请立即停止使用')
    q = '好吧，能有什么赠品呢？明天麻烦务必发出我要的比较着急'
    t = classify(q)
    assert t['purchase']['level'] == 'urgent'
    reply = safe_reply(t, question=q)
    assert '赠品' in reply and '不能保证' in reply and '查不到' in reply
    assert classify('今天能发么')['question_kind'] == 'realtime'
    assert classify('什么时候发货')['question_kind'] == 'realtime'


def test_request_scoped_prompt_and_no_context_leak(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'CUSTOMER_SERVICE_PLAN_ENABLED', True)
    state = analyze_purchase('急用，明天就要出发')
    token = purchase_turn_context.set(state)
    try:
        assert '紧迫程度=urgent' in build_customer_answer_prompt()
    finally:
        purchase_turn_context.reset(token)
    assert '紧迫程度=urgent' not in build_customer_answer_prompt()
    assert purchase_turn_context.get() is None


def test_purchase_metadata_persists_across_turns_and_prompt_context_resets(route_client_and_db, monkeypatch):
    from app.core.config import settings
    from app.services.customer_service_service import ask_customer_service
    from app.services import customer_service_service as service
    from app.services.customer_service_workbuddy_rag_service import _persist_result
    _client, _headers, Session = route_client_and_db
    monkeypatch.setattr(settings, 'CUSTOMER_SERVICE_PLAN_ENABLED', True)
    seen = []
    async def fake_dispatch(db, **kwargs):
        seen.append(purchase_turn_context.get())
        return await _persist_result(db, user_id=kwargs['user_id'], question=kwargs['question'],
            conversation_id=kwargs['conversation_id'], pipeline_version=kwargs['pipeline'], answer_delta_callback=None,
            agent_result={'answer': '订单状态需要向购买平台核实。', 'answer_type': 'faq',
                          'result_skus': [], 'answer_metadata': {}, 'sources': []})
    monkeypatch.setattr(service, '_dispatch_customer_service', fake_dispatch)
    with Session() as db:
        first = asyncio.run(ask_customer_service(db, user_id='customer-service-route-user',
            question='明天麻烦务必发出，比较着急', pipeline='workbuddy_rag_v1', server_selected_pipeline=True))
        second = asyncio.run(ask_customer_service(db, user_id='customer-service-route-user',
            question='我应该是已经支付了', conversation_id=first['conversation_id'],
            pipeline='workbuddy_rag_v1', server_selected_pipeline=True))
        state = second['answer_metadata']['triage']['purchase']
        assert state['level'] == 'urgent' and state['stage'] == 'ordered' and state['inherited']
        assert seen[0]['level'] == 'urgent' and purchase_turn_context.get() is None
