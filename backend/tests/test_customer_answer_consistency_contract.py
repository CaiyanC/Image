import copy
import asyncio
import json
import pytest
from app.services.customer_answer_consistency_contract import answer_consistency_issues, canonical_products


def packet(heat='明火直烧、卡式炉', instruction='不可直接明火加热（除非产品明确支持）'):
    return {'candidate_products': [{'sku':'TEST-1', 'specs':{'heat_source':heat, 'usage_instruction':instruction}}]}


@pytest.mark.parametrize('answer', ['可以装热饮，但不能直接放在明火上加热。', '不要在明火上加热。', '不可明火直烧。',
    '可盛装热饮不等于可直接加热，使用时不要将杯子直接置于明火上加热。'])
def test_unconditional_denial_loses_supported_exception(answer):
    payload=packet();before=copy.deepcopy(payload)
    assert answer_consistency_issues({'answer':answer}, payload)[0]['code']=='conditional_heat_denial'
    assert payload==before


@pytest.mark.parametrize('answer', ['可以装热饮，避免骤冷骤热。', '不可直接明火加热，除非该产品明确支持。', '禁止干烧。', '不能理解为“不可明火加热”。', '不能在明火上加热手柄。', '不要在密闭帐篷内明火加热。', '不要将空杯放在明火上加热。'])
def test_unrelated_safety_and_exceptions_stay(answer):
    assert not answer_consistency_issues({'answer':answer}, packet())


@pytest.mark.parametrize('payload', [packet('/'),packet('不支持明火'),packet('明火直烧','禁止明火加热'),
    {'candidate_products':packet()['candidate_products']+[{'sku':'TEST-2','specs':{}}]}])
def test_missing_conflicting_or_multiple_product_facts_do_not_grant_permission(payload):
    assert not answer_consistency_issues({'answer':'不可明火加热。'},payload)


def test_agent_canonical_json_is_read_but_candidate_only_is_not():
    record=packet()['candidate_products'][0]
    payload={'evidence':[{'sku':'TEST-1','authority_level':'canonical','fact_authority':True,'content':json.dumps(record)}]}
    assert canonical_products(payload)==[record]
    payload['evidence'][0]['fact_authority']=False
    assert canonical_products(payload)==[]


@pytest.mark.parametrize('pipeline', ['formal', 'rag'])
@pytest.mark.parametrize('repair_ok', [True, False])
def test_answer_writer_retries_only_once_and_rejects_remaining_conflict(monkeypatch, pipeline, repair_ok):
    from app.services import customer_service_semantic_rag_v2_service as formal
    from app.services import customer_service_workbuddy_rag_service as rag
    service = formal if pipeline == 'formal' else rag
    calls=[]
    async def chat(*args, **kwargs):
        calls.append(kwargs)
        answer='可以装热饮。' if len(calls)>1 and repair_ok else '可以装热饮，但不能直接放在明火上加热。'
        return json.dumps({'answer':answer,'selected_skus':['TEST-1']},ensure_ascii=False)
    monkeypatch.setattr(service.customer_llm_service,'chat_completion',chat)
    result,meta=asyncio.run(service._generate_answer(None,payload=packet()))
    assert len(calls)==2
    assert meta['consistency_retry_count']==1
    assert ('冲突' in calls[1]['messages'][0]['content'])
    assert (result is not None) is repair_ok
    if result: assert result['answer']=='可以装热饮。'
    else: assert meta['consistency_rejected']


@pytest.mark.parametrize('repair_ok',[True,False])
def test_agent_buffers_conflict_and_uses_existing_bounded_retry(monkeypatch,repair_ok):
    from app.services import customer_service_workbuddy_agent_service as agent
    calls=[];display=[]
    async def prefetch(*args,**kwargs):
        kwargs['evidence'].append({'evidence_id':'e1','sku':'TEST-1','authority_level':'canonical',
            'fact_authority':True,'content':json.dumps(packet()['candidate_products'][0])})
        return []
    async def guidance(*args,**kwargs): return []
    async def stream(*args,**kwargs):
        calls.append(kwargs)
        answer='可以装热饮。' if len(calls)>1 and repair_ok else '可以装热饮，但不要直接放在明火上加热。'
        yield json.dumps({'answer':answer,'response_mode':'grounded','answer_type':'faq',
            'selected_skus':['TEST-1'],'identity_status':'confirmed',
            'claims':[{'sku':'TEST-1','statement':'支持明火直烧','evidence_ids':['e1']}]},ensure_ascii=False)
    async def delta(text):display.append(text)
    monkeypatch.setattr(agent,'_prefetch_semantic_catalog',prefetch)
    monkeypatch.setattr(agent.customer_experience_rag_service,'retrieve_experience_guidance',guidance)
    monkeypatch.setattr(agent.customer_llm_service,'chat_completion_stream',stream)
    result,*_,meta=asyncio.run(agent._run_agent(None,question='可以装热饮吗？',history=[],page_sku='TEST-1',
        context_skus=[],explicit_skus=['TEST-1'],answer_delta_callback=delta))
    assert len(calls)==2
    assert meta['grounding_retry_counts']['answer_consistency_conflict']==1
    assert ''.join(display)==result['answer']
    assert '不要直接放在明火上加热' not in ''.join(display)
    if repair_ok:assert result['answer']=='可以装热饮。'
    else:assert meta['consistency_rejected'] and result['needs_clarification']
