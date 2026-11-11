import unittest
from app.services.customer_service_triage import classify, safe_reply, TRAINING_EXAMPLES, training_prompt


class TriageTest(unittest.TestCase):
    def test_four_levels_and_negation(self):
        for q in ('使用时着火了', '突然触电了', '闻到煤气味', '账号被盗'):
            self.assertEqual(classify(q)['urgency'], 'immediate', q)
            self.assertIsNotNone(safe_reply(classify(q)))
        self.assertEqual(classify('收货破损，马上出发')['urgency'], 'urgent')
        self.assertEqual(classify('锅身怎么清洁')['urgency'], 'normal')
        self.assertEqual(classify('容量是多少')['urgency'], 'general')
        for q in ('如何避免漏气', '没有漏气，注意什么', '会不会触电', '怎样防止冒烟'):
            self.assertIsNone(safe_reply(classify(q)), q)

    def test_never_claim_human_is_connected(self):
        for q in ('支付不是我操作的', '我要求赔偿', '现在有货吗'):
            triage = classify(q)
            self.assertFalse(triage['handoff']['connected'])
            self.assertEqual(triage['handoff']['status'], 'recommended')
            self.assertIn('人工', safe_reply(triage))
            self.assertNotIn('已转', safe_reply(triage))

    def test_ignition_question_does_not_mask_a_separate_emergency(self):
        assert classify('酒精放哪里，怎么就让它烧起来了呀？', product_context=True)['urgency'] != 'immediate'
        assert classify('怎么突然烧起来了？', product_context=True)['urgency'] == 'immediate'
        assert classify('怎么让它烧起来？我现在闻到燃气味', product_context=True)['urgency'] == 'immediate'

    def test_discount_followup_is_not_refund(self):
        self.assertEqual(classify('不能申请一下吗？')['question_kind'], 'ambiguous_request')
        reply = safe_reply(classify('不能申请一下吗？', previous_question='买15套可以优惠吗'))
        self.assertIn('优惠', reply)
        self.assertNotIn('退款', reply)
        self.assertEqual(classify('那现在怎么办？', previous_question='炉子正在漏气')['urgency'], 'immediate')
        self.assertEqual(classify('买十件有什么折扣')['question_kind'], 'pricing_request')
        self.assertIn('尚未接通', safe_reply(classify('买十件有什么折扣')))
        self.assertEqual(classify('明天可以发出吗')['question_kind'], 'realtime')

    def test_rules_are_versioned_and_examples_are_not_facts(self):
        self.assertGreaterEqual(len(TRAINING_EXAMPLES), 6)
        self.assertIn('商品事实来源', training_prompt())

    def test_compatibility_requires_product_identity_but_keeps_anchored_rag(self):
        for q in ('这款液体酒精能用吗', '电磁炉可以用吗', '这个炉头搭配什么气罐', '这款和另一套有什么区别'):
            self.assertEqual(classify(q)['question_kind'], 'ambiguous_product')
            self.assertIn('型号', safe_reply(classify(q)))
            self.assertIsNone(safe_reply(classify(q, product_context=True)))
        self.assertIsNone(safe_reply(classify('CS-G25 是酒精炉吗？')))
        self.assertEqual(classify('这个炉头正在漏气')['urgency'], 'immediate')


if __name__ == '__main__':
    unittest.main()


def test_safety_is_persisted_without_llm_and_handoff_is_owner_scoped(route_client_and_db, monkeypatch):
    import asyncio
    import json
    from fastapi import HTTPException
    import pytest
    from app.core.config import settings
    from app.models.knowledge_base import CustomerServiceMessage
    from app.services.customer_service_service import ask_customer_service, report_handoff_outcome
    _client, _headers, Session = route_client_and_db
    monkeypatch.setattr(settings, 'APP_ENV', 'dev')
    monkeypatch.setattr(settings, 'CUSTOMER_SERVICE_PLAN_ENABLED', True)
    with Session() as db:
        result = asyncio.run(ask_customer_service(db, user_id='customer-service-route-user',
            question='炉子漏气了还能点火吗', pipeline='workbuddy_rag_v1', server_selected_pipeline=True))
        assert result['answer'].startswith('请立即停止')
        assert result['answer_metadata']['triage']['urgency'] == 'immediate'
        message_id = result['message_id']
        with pytest.raises(HTTPException) as error:
            report_handoff_outcome(db, user_id='other-user', message_id=message_id, outcome='resolved')
        assert error.value.status_code == 404
        recorded = report_handoff_outcome(db, user_id='customer-service-route-user', message_id=message_id, outcome='resolved')
        assert recorded['handoff']['followup_status'] == 'resolved'
        assert recorded['handoff']['connected'] is False
        sources = json.loads(db.get(CustomerServiceMessage, message_id).sources_json)
        meta = next(item for item in sources if item['type'] == 'agent_meta')
        assert meta['answer_metadata']['triage']['handoff']['history'][0]['verification'] == 'user_reported'


def test_business_fields_are_separate_and_unlimited_selling_points_roundtrip(route_client_and_db, monkeypatch):
    import json
    from app.models.product import Product
    from app.models.product_business import ProductBusiness
    from app.services import product_service
    _client, _headers, Session = route_client_and_db
    monkeypatch.setattr(product_service, 'get_product_detail', lambda db, sku: {'sku': sku})
    with Session() as db:
        db.add(Product(id='business-plan-test', sku='PLAN-TEST', barcode='plan-test-barcode', product_name_cn='测试产品', brand='alocs'))
        db.add(ProductBusiness(product_id='business-plan-test', target_audience='保留原描述'))
        db.commit()
        selling = [f'卖点{i}' for i in range(8)]
        product_service.update_product_business(db, 'PLAN-TEST', {'suitable_people': '1–2人', 'audience_tags': ['房车人群'], 'value_positioning': '利润款', 'top_selling_points': selling})
        row = db.query(ProductBusiness).filter_by(product_id='business-plan-test').one()
        assert row.suitable_people == '1–2人'
        assert row.target_audience == '保留原描述'
        assert json.loads(row.audience_tags) == ['房车人群']
        assert json.loads(row.top_selling_points) == selling


def test_new_business_fields_enter_retrieval_documents():
    from app.services.product_vector_index_service import build_product_documents
    docs = build_product_documents({'sku': 'PLAN-TEST', 'product_name_cn': '测试产品',
        'business': {'suitable_people': '1–2人', 'audience_tags': ['房车人群'], 'value_positioning': '利润款'}})
    serialized = str(docs)
    assert '适用人数' in serialized and '房车人群' in serialized and '利润款' in serialized
