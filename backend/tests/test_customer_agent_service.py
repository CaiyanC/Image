import contextlib
import io
import json
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    AgentAction, Certification, Keyword, ListingChannel, OperationLog, Product,
    ProductBusiness, ProductCertification, ProductContent, ProductKeyword,
    ProductListingChannel, ProductMedia, ProductPrompts, ProductQa, ProductQaNegative,
    ProductSalesRegion, ProductSpecs, SalesRegion, CustomerServiceConversation,
    CustomerServiceMessage, KnowledgeChunk, KnowledgeDocument,
)
from app.services import agent_trace_service, customer_agent_intent_service, customer_agent_runtime_service, customer_agent_service, customer_agent_tool_service, customer_service_service, dmxapi_service, knowledge_service


class CustomerAgentServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            ProductSpecs.__table__,
            ProductBusiness.__table__,
            ProductContent.__table__,
            ProductMedia.__table__,
            ProductPrompts.__table__,
            ProductQa.__table__,
            ProductQaNegative.__table__,
            ListingChannel.__table__,
            ProductListingChannel.__table__,
            SalesRegion.__table__,
            ProductSalesRegion.__table__,
            Certification.__table__,
            ProductCertification.__table__,
            Keyword.__table__,
            ProductKeyword.__table__,
            AgentAction.__table__,
            OperationLog.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self._add_product("CS-G25", "小青炉", "炉具", "不锈钢", "防滑条设计")
        self._add_product("CW-C93", "行山单锅", "锅具", "铝合金", "聚能结构")
        self._add_product("TW-141", "野营套锅", "锅具", "铝合金", "")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_product(self, sku, name, category, material, advantages):
        product = Product(
            id=f"id-{sku}",
            sku=sku,
            barcode="6959291009022" if sku == "CW-C93" else f"barcode-{sku}",
            product_name_cn=name,
            product_name_en=name,
            brand="alocs爱路客",
            category=category,
            product_level="A类品",
            lifecycle_status="常规品" if sku == "TW-141" else "新品",
            person_in_charge="Max",
        )
        self.db.add(product)
        self.db.add(ProductSpecs(
            id=f"specs-{sku}",
            product_id=product.id,
            capacity='{"label": "1000ml"}' if sku == "CW-C93" else ("300ml" if sku == "CS-G25" else ""),
            body_material=material,
            color="银色",
            surface_finish="硬质氧化",
            heat_source="燃气炉",
            technical_advantages=advantages,
        ))

    def test_process_update_request_creates_pending_actions_without_writing(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="把 CS-G25、CW-C93 的生命周期都改成常规品",
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual({item["sku"] for item in result["actions"]}, {"CS-G25", "CW-C93"})
        self.assertEqual({item["status"] for item in result["actions"]}, {"pending"})
        products = {item.sku: item.lifecycle_status for item in self.db.query(Product).all()}
        self.assertEqual(products["CS-G25"], "新品")
        self.assertEqual(products["CW-C93"], "新品")

    def test_process_search_request_returns_product_results(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="哪些产品支持防滑条",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["results"][0]["sku"], "CS-G25")
        self.assertIn("找到", result["answer"])

    def test_process_lifecycle_query_returns_matching_products(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="把生命周期为新品给我，我想改一些为常规品",
        )

        self.assertIsNotNone(result)
        self.assertEqual({item["sku"] for item in result["results"]}, {"CS-G25", "CW-C93"})
        self.assertIn("生命周期", result["answer"])
        self.assertEqual(result["actions"], [])

    def test_process_category_query_for_pot_products_returns_features(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="哪些产品为锅，这些产品分别有什么特色",
        )

        self.assertIsNotNone(result)
        self.assertEqual([item["sku"] for item in result["results"]], ["CW-C93", "TW-141"])
        self.assertIn("聚能结构", result["answer"])

    def test_capacity_answer_formats_list_values_for_humans(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="CW-C93 的容量是多少",
        )

        self.assertIsNotNone(result)
        self.assertIn("1000ml", result["answer"])
        self.assertNotIn("{'label'", result["answer"])

    def test_capacity_formatter_keeps_label_and_value(self):
        text = customer_agent_service._stringify([{"label": "锅", "value": "1000ML"}])

        self.assertEqual(text, "锅 1000ML")
        self.assertNotEqual(text, "锅")

    def test_exact_product_name_search_does_not_expand_to_series(self):
        self._add_product("CW-C83-2", "炊墨煎锅", "锅具", "硬质氧化铝合金", "")
        self._add_product("CW-C83-1", "炊墨炒锅", "锅具", "硬质氧化铝合金", "")
        self._add_product("CW-C83", "炊墨套锅", "锅具", "硬质氧化铝合金", "")
        self.db.commit()

        rows = customer_agent_service.search_products(self.db, "炊墨炒锅")

        self.assertEqual([item["sku"] for item in rows], ["CW-C83-1"])

    def test_intent_capacity_answer_uses_capacity_value(self):
        self._add_product("CW-C83-1", "炊墨炒锅", "锅具", "硬质氧化铝合金", "")
        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "id-CW-C83-1").first()
        specs.capacity = '[{"label": "锅", "value": "3700ML"}]'
        self.db.commit()

        original_chat_completion = dmxapi_service.chat_completion

        async def fail_chat_completion(*args, **kwargs):
            raise RuntimeError("skip llm")

        dmxapi_service.chat_completion = fail_chat_completion
        try:
            result = self._run_async(customer_agent_intent_service.process_intent_request(
                self.db,
                user_id="user-1",
                question="炊墨炒锅的容量是多少",
            ))
        finally:
            dmxapi_service.chat_completion = original_chat_completion

        self.assertIsNotNone(result)
        self.assertEqual([item["sku"] for item in result["results"]], ["CW-C83-1"])
        self.assertIn("3700ML", result["answer"])
        self.assertNotIn("容量：锅\n", result["answer"])
        self.assertNotIn("异常提示", result["answer"])
        self.assertEqual(result["answer_type"], "product_detail")
        self.assertEqual(result["uncertainty"], "confirmed")
        self.assertTrue(result["evidence"])
        self.assertIn("debug", result)

    def test_unknown_attribute_followup_gives_useful_answer(self):
        self._add_product("CW-C83", "炊墨套锅", "锅具", "硬质氧化铝合金、白蜡木", "轻量便携")
        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == "id-CW-C83").first()
        specs.surface_finish = "水性涂层"
        specs.usage_instruction = "使用后请擦干收纳"
        self.db.commit()

        original_chat_completion = dmxapi_service.chat_completion

        async def fail_chat_completion(*args, **kwargs):
            raise RuntimeError("skip llm")

        dmxapi_service.chat_completion = fail_chat_completion
        try:
            result = self._run_async(customer_agent_intent_service.process_intent_request(
                self.db,
                user_id="user-1",
                question="他防水吗",
                previous_result_skus=["CW-C83"],
            ))
        finally:
            dmxapi_service.chat_completion = original_chat_completion

        self.assertIsNotNone(result)
        self.assertIn("没有标注", result["answer"])
        self.assertIn("不能直接确认", result["answer"])
        self.assertIn("材质", result["answer"])
        self.assertNotIn("我还没识别到你要查的字段", result["answer"])
        self.assertEqual(result["uncertainty"], "not_recorded")
        self.assertNotIn("Agent 执行过程", result["answer"])

    def test_followup_for_uncommittable_field_is_contextual(self):
        self._add_product("CW-C83", "炊墨套锅", "锅具", "硬质氧化铝合金、白蜡木", "轻量便携")
        self.db.commit()

        original_chat_completion = dmxapi_service.chat_completion

        async def fail_chat_completion(*args, **kwargs):
            raise RuntimeError("skip llm")

        dmxapi_service.chat_completion = fail_chat_completion
        try:
            result = self._run_async(customer_agent_intent_service.process_intent_request(
                self.db,
                user_id="user-1",
                question="它防水吗",
                previous_result_skus=["CW-C83"],
            ))
        finally:
            dmxapi_service.chat_completion = original_chat_completion

        self.assertIsNotNone(result)
        self.assertIn("防水/防泼水参数", result["suggested_followups"][0])

    def test_all_pots_capacity_query_returns_capacity_list(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="所有锅的容量给我",
        )

        self.assertIsNotNone(result)
        self.assertEqual([item["sku"] for item in result["results"]], ["CW-C93", "TW-141"])
        self.assertIn("CW-C93", result["answer"])
        self.assertIn("1000ml", result["answer"])
        self.assertIn("TW-141", result["answer"])
        self.assertIn("暂无", result["answer"])

    def test_barcode_query_returns_matching_product(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="条形码是6959291009022的产品是什么",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["sku"], "CW-C93")
        self.assertEqual(result["results"][0]["sku"], "CW-C93")
        self.assertIn("6959291009022", result["answer"])
        self.assertIn("CW-C93", result["answer"])

    def test_person_in_charge_filter_returns_matching_products(self):
        result = customer_agent_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="负责人为Max的产品有哪些",
        )

        self.assertIsNotNone(result)
        self.assertEqual({item["sku"] for item in result["results"]}, {"CS-G25", "CW-C93", "TW-141"})
        self.assertIn("负责人", result["answer"])

    def test_full_text_search_includes_status_note(self):
        product = self.db.query(Product).filter(Product.sku == "TW-141").first()
        product.status_note = "春季主推"
        self.db.commit()

        rows = customer_agent_service.search_products(self.db, "春季主推")

        self.assertEqual([item["sku"] for item in rows], ["TW-141"])

    def test_structured_filters_can_combine_person_and_category(self):
        rows = customer_agent_service.search_products(
            self.db,
            "",
            filters={"负责人": "Max", "类目": "锅"},
        )

        self.assertEqual([item["sku"] for item in rows], ["CW-C93", "TW-141"])

    def test_tool_search_products_accepts_structured_filters_and_fields(self):
        result = customer_agent_tool_service.execute_tool(
            self.db,
            user_id="user-1",
            name="search_products",
            arguments={"filters": {"负责人": "Max", "类目": "锅"}, "fields": ["容量"]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual([item["sku"] for item in result["results"]], ["CW-C93", "TW-141"])

    def _run_async(self, awaitable):
        import asyncio

        return asyncio.run(awaitable)
        self.assertEqual(result["results"][0]["field_values"]["容量"], "1000ml")

    def test_hybrid_search_products_combines_structured_filters(self):
        result = customer_agent_tool_service.execute_tool(
            self.db,
            user_id="user-1",
            name="hybrid_search_products",
            arguments={"filters": {"负责人": "Max", "类目": "锅"}, "fields": ["容量"]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual([item["sku"] for item in result["results"]], ["CW-C93", "TW-141"])

    def test_get_product_detail_accepts_multiple_skus(self):
        result = customer_agent_tool_service.execute_tool(
            self.db,
            user_id="user-1",
            name="get_product_detail",
            arguments={"skus": ["CW-C93", "TW-141"]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)
        self.assertEqual([item["sku"] for item in result["details"]], ["CW-C93", "TW-141"])

    def test_get_product_detail_returns_requested_context_fields(self):
        channel = ListingChannel(id="channel-1", channel_name="淘宝", channel_code="taobao")
        region = SalesRegion(id="region-1", region_name="中国", region_code="CN")
        keyword = Keyword(id="keyword-1", keyword="轻量徒步", keyword_level="core")
        self.db.add_all([
            channel,
            region,
            keyword,
            ProductListingChannel(product_id="id-CW-C93", channel_id=channel.id),
            ProductSalesRegion(product_id="id-CW-C93", region_id=region.id),
            ProductKeyword(product_id="id-CW-C93", keyword_id=keyword.id),
        ])
        self.db.commit()

        result = customer_agent_tool_service.execute_tool(
            self.db,
            user_id="user-1",
            name="get_product_detail",
            arguments={"sku": "CW-C93", "fields": ["条形码", "上架平台", "售卖地区", "关键词库"]},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["detail"]["field_values"]["条形码"], "6959291009022")
        self.assertIn("淘宝", result["detail"]["field_values"]["上架平台"])
        self.assertIn("中国", result["detail"]["field_values"]["售卖地区"])
        self.assertIn("轻量徒步", result["detail"]["field_values"]["关键词库"])

    def test_keyword_retrieve_tokenizes_fuzzy_scene_query(self):
        doc = KnowledgeDocument(
            id="doc-1",
            source_type="manual",
            title="送礼场景",
            content="年轻人送礼更看重颜值、便携和使用场景。",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            document_id="doc-1",
            source_type="manual",
            content="年轻人送礼更看重颜值、便携和使用场景。",
            embedding_status="pending",
        )
        self.db.add(doc)
        self.db.add(chunk)
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(self.db, "三个年轻人哪种适合送礼", limit=3)

        self.assertEqual(len(rows), 1)
        self.assertIn("送礼", rows[0]["content"])


    def test_semantic_tool_enriches_product_fields(self):
        original_keyword_retrieve = knowledge_service.keyword_retrieve

        def fake_keyword_retrieve(db, query, sku=None, limit=8):
            return [{"sku": "CW-C93", "content": "适合露营泡咖啡"}]

        knowledge_service.keyword_retrieve = fake_keyword_retrieve
        try:
            result = customer_agent_tool_service.execute_tool(
                self.db,
                user_id="user-1",
                name="semantic_search_knowledge",
                arguments={"query": "适合泡咖啡的小锅"},
            )
        finally:
            knowledge_service.keyword_retrieve = original_keyword_retrieve

        row = result["results"][0]
        self.assertEqual(row["sku"], "CW-C93")
        self.assertTrue(row["product_name_cn"])
        self.assertIn("capacity", row)


class CustomerAgentRuntimeServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            ProductSpecs.__table__,
            ProductBusiness.__table__,
            ProductContent.__table__,
            ProductMedia.__table__,
            ProductPrompts.__table__,
            ProductQa.__table__,
            ProductQaNegative.__table__,
            ListingChannel.__table__,
            ProductListingChannel.__table__,
            SalesRegion.__table__,
            ProductSalesRegion.__table__,
            Certification.__table__,
            ProductCertification.__table__,
            Keyword.__table__,
            ProductKeyword.__table__,
            AgentAction.__table__,
            OperationLog.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        product = Product(
            id="id-CW-C93",
            sku="CW-C93",
            barcode="barcode-CW-C93",
            product_name_cn="行山单锅",
            product_name_en="Trail Pot",
            brand="alocs爱路客",
            category="锅具",
            person_in_charge="Max",
        )
        self.db.add(product)
        self.db.add(ProductSpecs(
            id="specs-CW-C93",
            product_id=product.id,
            capacity='{"label": "1000ml"}',
            body_material="铝合金",
        ))
        self.db.commit()
        self.original_chat_completion = dmxapi_service.chat_completion
        self.original_execute_tool_async = customer_agent_tool_service.execute_tool_async

    def tearDown(self):
        dmxapi_service.chat_completion = self.original_chat_completion
        customer_agent_tool_service.execute_tool_async = self.original_execute_tool_async
        self.db.close()

    async def test_model_tool_call_executes_safe_tool_and_prints_trace(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"search_products","arguments":{"term":"锅","fields":["容量"]}}]}'
            return '{"answer":"CW-C93 的容量是 1000ml。"}'

        dmxapi_service.chat_completion = fake_chat_completion
        stream = io.StringIO()
        original_trace_stdout = agent_trace_service.TRACE_STDOUT
        try:
            agent_trace_service.TRACE_STDOUT = True
            with contextlib.redirect_stdout(stream):
                result = await customer_agent_runtime_service.process_agent_request(
                    self.db,
                    user_id="user-1",
                question="所有锅的容量给我",
            )

        finally:
            agent_trace_service.TRACE_STDOUT = original_trace_stdout

        output = stream.getvalue()
        self.assertIsNotNone(result)
        self.assertEqual(result["answer"], "CW-C93 的容量是 1000ml。")
        self.assertEqual(result["intent"], "query_products")
        self.assertEqual(result["answer_type"], "product_query")
        self.assertEqual(result["debug"]["agent_mode"], "llm_tool_calling")
        self.assertTrue(result["skip_polish"])
        self.assertEqual(result["results"][0]["sku"], "CW-C93")
        self.assertEqual(result["results"][0]["field_values"]["容量"], "1000ml")
        self.assertIn("CUSTOMER_AGENT_TOOL_CALL", output)
        self.assertIn("CUSTOMER_AGENT_TOOL_RESULT", output)
        self.assertIn("CUSTOMER_AGENT_FINAL_RESPONSE", output)

    async def test_runtime_strips_markdown_from_customer_answer(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"search_products","arguments":{"term":"锅","fields":["容量"]}}]}'
            return '{"answer":"**首选：CW-C93**\\n### 依据\\n容量是 `1000ml`。"}'

        dmxapi_service.chat_completion = fake_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="三个年轻人适合哪个锅",
        )

        self.assertNotIn("**", result["answer"])
        self.assertNotIn("###", result["answer"])
        self.assertNotIn("`", result["answer"])

    async def test_model_can_search_then_create_batch_actions_in_multiple_rounds(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"search_products","arguments":{"term":"","filters":{"负责人":"Max","类目":"锅"}}}]}'
            if len(calls) == 2:
                return '{"tool_calls":[{"name":"propose_update_product_field","arguments":{"skus":"$last_search_skus","field":"生命周期","new_value":"常规品"}}]}'
            return '{"answer":"已为查询到的产品生成待确认动作。"}'

        dmxapi_service.chat_completion = fake_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="把负责人为Max的锅生命周期改成常规品",
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["sku"], "CW-C93")
        self.assertEqual(result["intent"], "propose_update")
        self.assertEqual(result["actions"][0]["field_label"], "生命周期")

    async def test_model_can_use_previous_result_skus_for_these(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"propose_update_product_field","arguments":{"skus":"$previous_result_skus","field":"生命周期","new_value":"常规品"}}]}'
            return '{"answer":"已基于上一轮结果生成待确认动作。"}'

        dmxapi_service.chat_completion = fake_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="把这些生命周期改成常规品",
            previous_result_skus=["CW-C93"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["sku"], "CW-C93")

    async def test_model_receives_conversation_history_for_followup(self):
        calls = []
        history = [
            {"role": "user", "content": "查一下锅具"},
            {"role": "assistant", "content": "找到 CW-C93。"},
        ]

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                payload = json.loads(messages[-1]["content"])
                self.assertEqual(payload["conversation_history"], history)
                return '{"tool_calls":[{"name":"get_product_detail","arguments":{"sku":"CW-C93"}}]}'
            return '{"answer":"结合上一轮结果，CW-C93 更适合继续查看容量和材质。"}'

        dmxapi_service.chat_completion = fake_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="哪种适合送礼",
            previous_result_skus=["CW-C93"],
            conversation_history=history,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["debug"]["history_turns"], 2)
        self.assertEqual(result["results"][0]["sku"], "CW-C93")

    async def test_context_reference_without_previous_results_clarifies(self):
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="把这些生命周期改成常规品",
            previous_result_skus=[],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["actions"], [])
        self.assertIn("没有可引用的上一轮产品结果", result["answer"])

    def test_budget_followup_builds_conversation_context(self):
        context = customer_agent_runtime_service._conversation_context_for_question(
            "预算不高",
            [
                {"role": "user", "content": "三个年轻人露营，适合带什么产品？"},
                {"role": "assistant", "content": "首选 CW-C83-2，炊墨煎锅。"},
            ],
        )

        self.assertEqual(context["mode"], "budget_followup")
        self.assertIn("三个年轻人露营", context["previous_user_need"])
        self.assertIn("预算不高", context["combined_user_need"])
        self.assertEqual(context["slots"]["budget"], "low")
        self.assertIn("预算=low", context["summary"])

    def test_complete_new_need_uses_current_question_context(self):
        context = customer_agent_runtime_service._conversation_context_for_question(
            "适合四个人做饭的锅有哪些？",
            [
                {"role": "user", "content": "适合泡咖啡的小锅有吗？"},
                {"role": "assistant", "content": "首选 CW-C93。"},
            ],
        )

        self.assertEqual(context["mode"], "current_question")
        self.assertEqual(context["previous_user_need"], "")
        self.assertEqual(context["slots"]["quantity"], "四人")
        self.assertEqual(context["slots"]["scene"], "做饭")

    def test_tool_selection_payload_includes_dialogue_state(self):
        messages = customer_agent_runtime_service._build_tool_selection_messages(
            "预算不高",
            None,
            ["CW-C93"],
            [{"role": "user", "content": "三个年轻人露营，适合什么锅？"}],
            [],
        )

        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["dialogue_state"]["mode"], "budget_followup")
        self.assertEqual(payload["dialogue_state"]["budget"], "low")
        self.assertEqual(payload["conversation_context"]["slots"]["budget"], "low")

    def test_fallback_intent_prompt_keeps_readable_chinese_rules(self):
        prompt = customer_agent_intent_service._build_intent_llm_prompt(None, ["CW-C93"])

        self.assertIn("这些/这款/刚才那些", prompt)
        self.assertIn("负责人/person_in_charge", prompt)
        self.assertIn("容量/capacity", prompt)
        self.assertNotIn("???", prompt)

    def test_empty_product_results_discard_hallucinated_recommendation(self):
        result = customer_agent_runtime_service._build_result(
            "三个人去旅行，推荐一下产品",
            None,
            [{"ok": True, "tool": "hybrid_search_products", "query": "三个人去旅行，推荐一下产品", "count": 0, "results": []}],
            "推荐 CW-C83，炊墨套锅适合三个人旅行。",
            [],
        )

        self.assertEqual(result["results"], [])
        self.assertNotIn("CW-C83", result["answer"])
        self.assertIn("没有找到", result["answer"])

    def test_stale_semantic_sku_is_not_returned_as_product(self):
        rows = customer_agent_tool_service._enrich_semantic_rows(
            self.db,
            [{"sku": "CW-C83", "content": "炊墨套锅适合三人旅行"}],
        )

        self.assertEqual(rows, [])

    async def test_context_field_followup_uses_previous_sku_without_llm(self):
        async def fail_chat_completion(*args, **kwargs):
            raise RuntimeError("LLM should not be called for deterministic field followup")

        dmxapi_service.chat_completion = fail_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="条形码是多少？",
            previous_result_skus=["CW-C93"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "product_detail")
        self.assertEqual(result["results"][0]["field_values"]["条形码"], "barcode-CW-C93")
        self.assertIn("条形码", result["answer"])
        self.assertIn("barcode-CW-C93", result["answer"])

    async def test_confirmation_reuses_field_from_previous_clarification(self):
        region = SalesRegion(id="region-runtime-1", region_name="日本", region_code="JP")
        self.db.add(region)
        self.db.add(ProductSalesRegion(product_id="id-CW-C93", region_id=region.id))
        self.db.commit()

        async def fail_chat_completion(*args, **kwargs):
            raise RuntimeError("LLM should not be called for confirmation field followup")

        dmxapi_service.chat_completion = fail_chat_completion
        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="是的",
            previous_result_skus=["CW-C93"],
            conversation_history=[
                {"role": "assistant", "content": "你是想查行山单锅的售卖地区吗？如果是，我可以继续查。"},
            ],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["results"][0]["field_values"]["售卖地区"], "日本")
        self.assertIn("售卖地区", result["answer"])
        self.assertIn("日本", result["answer"])

    def test_negative_recommendation_excludes_unwanted_series(self):
        result = customer_agent_runtime_service._build_result(
            "不要炊墨系列的，换一个推荐",
            None,
            [{
                "ok": True,
                "tool": "hybrid_search_products",
                "results": [
                    {"sku": "CW-C83", "product_name_cn": "炊墨套锅", "series": "炊墨", "features": "多人露营"},
                    {"sku": "CW-C93", "product_name_cn": "行山单锅", "features": "轻量徒步"},
                ],
            }],
            "首选 CW-C83，炊墨套锅。",
            [],
        )

        self.assertEqual(result["results"][0]["sku"], "CW-C93")
        self.assertNotIn("CW-C83", result["answer"])

    def test_missing_field_value_replaces_hallucinated_answer(self):
        result = customer_agent_runtime_service._build_result(
            "小圆炉的尺寸是多少？",
            None,
            [{
                "ok": True,
                "tool": "get_product_detail",
                "detail": {
                    "sku": "CS-G35",
                    "product_name_cn": "小圆炉",
                    "field_values": {"尺寸规格": "暂无"},
                },
            }],
            "小圆炉尺寸很小巧，可以轻松放入口袋。",
            [],
        )

        self.assertIn("暂无", result["answer"])
        self.assertIn("未记录", result["answer"])
        self.assertNotIn("放入口袋", result["answer"])


    async def test_write_request_without_action_falls_back_to_intent_parser(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"search_products","arguments":{"term":"","filters":{"负责人":"Yao"}}}]}'
            return '{"answer":"当前没有找到负责人为 Yao 的产品。"}'

        dmxapi_service.chat_completion = fake_chat_completion

        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="修改他的负责人为kang",
            previous_result_skus=["CS-G25"],
        )

        self.assertIsNone(result)

    async def test_product_lookup_direct_answer_is_regrounded_on_current_question(self):
        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            return '{"answer":"根据您适合泡咖啡的小锅需求，推荐 CW-C93。"}'

        async def fake_execute_tool_async(db, *, user_id, name, arguments):
            self.assertEqual(name, "hybrid_search_products")
            self.assertEqual(arguments["semantic_query"], "适合四个人做饭的锅有哪些")
            return {
                "ok": True,
                "tool": name,
                "query": arguments["semantic_query"],
                "count": 1,
                "results": [{
                    "sku": "CW-C83",
                    "product_name_cn": "炊墨套锅",
                    "category": "锅具",
                    "capacity": "锅 3700ML，煎盘 2300ML",
                    "features": "一锅多用，适合营地做饭",
                    "usage_scenarios": "家庭露营，户外营地大餐",
                    "target_audience": "家庭户外野餐群体，多人露营",
                }],
            }

        dmxapi_service.chat_completion = fake_chat_completion
        customer_agent_tool_service.execute_tool_async = fake_execute_tool_async

        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="适合四个人做饭的锅有哪些",
            conversation_history=[
                {"role": "user", "content": "适合泡咖啡的小锅有吗？"},
                {"role": "assistant", "content": "首选 CW-C93。"},
            ],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["results"][0]["sku"], "CW-C83")
        self.assertNotIn("泡咖啡", result["answer"])

    async def test_tool_grounded_answer_replaces_stale_previous_need(self):
        calls = []

        async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200):
            calls.append(messages)
            if len(calls) == 1:
                return '{"tool_calls":[{"name":"hybrid_search_products","arguments":{"semantic_query":"适合四个人做饭的锅有哪些","limit":5}}]}'
            return '{"answer":"根据您适合泡咖啡的小锅需求，推荐 CW-C93。"}'

        async def fake_execute_tool_async(db, *, user_id, name, arguments):
            self.assertEqual(name, "hybrid_search_products")
            return {
                "ok": True,
                "tool": name,
                "query": arguments["semantic_query"],
                "count": 1,
                "results": [{
                    "sku": "CW-C83",
                    "product_name_cn": "炊墨套锅",
                    "category": "锅具",
                    "capacity": "锅 3700ML，煎盘 2300ML",
                    "features": "一锅多用，适合营地做饭",
                    "usage_scenarios": "家庭露营，户外营地大餐",
                    "target_audience": "家庭户外野餐群体，多人露营",
                }],
            }

        dmxapi_service.chat_completion = fake_chat_completion
        customer_agent_tool_service.execute_tool_async = fake_execute_tool_async

        result = await customer_agent_runtime_service.process_agent_request(
            self.db,
            user_id="user-1",
            question="适合四个人做饭的锅有哪些",
            conversation_history=[
                {"role": "user", "content": "适合泡咖啡的小锅有吗？"},
                {"role": "assistant", "content": "首选 CW-C93。"},
            ],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["results"][0]["sku"], "CW-C83")
        self.assertIn("CW-C83", result["answer"])
        self.assertNotIn("CW-C93", result["answer"])
        self.assertNotIn("泡咖啡", result["answer"])


class CustomerServiceServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            ProductSpecs.__table__,
            ProductBusiness.__table__,
            ProductContent.__table__,
            ProductMedia.__table__,
            ProductPrompts.__table__,
            ProductQa.__table__,
            ProductQaNegative.__table__,
            ListingChannel.__table__,
            ProductListingChannel.__table__,
            SalesRegion.__table__,
            ProductSalesRegion.__table__,
            Certification.__table__,
            ProductCertification.__table__,
            Keyword.__table__,
            ProductKeyword.__table__,
            AgentAction.__table__,
            OperationLog.__table__,
            CustomerServiceConversation.__table__,
            CustomerServiceMessage.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.original_runtime = customer_agent_runtime_service.process_agent_request
        self.original_intent = customer_agent_intent_service.process_intent_request
        self.original_polish = customer_service_service._polish_customer_answer

    def tearDown(self):
        customer_agent_runtime_service.process_agent_request = self.original_runtime
        customer_agent_intent_service.process_intent_request = self.original_intent
        customer_service_service._polish_customer_answer = self.original_polish
        self.db.close()

    async def test_ask_customer_service_uses_llm_runtime_before_intent_parser(self):
        calls = []

        async def fake_runtime(db, **kwargs):
            calls.append(("runtime", kwargs["question"]))
            return {
                "answer": "Agent 已经自主查询并回答。",
                "intent": "query_products",
                "answer_type": "product_query",
                "confidence": "high",
                "uncertainty": "confirmed",
                "sources": [],
                "actions": [],
                "results": [{"id": uuid.uuid4(), "sku": "CW-C93"}],
                "steps": [],
                "warnings": [],
                "evidence": [],
                "debug": {"agent_mode": "llm_tool_calling"},
                "skip_polish": True,
                "sku": "CS-G25",
            }

        async def fake_intent(*args, **kwargs):
            calls.append(("intent", kwargs["question"]))
            return None

        async def fake_polish(*args, **kwargs):
            calls.append(("polish", "unexpected"))
            return "不应该润色"

        customer_agent_runtime_service.process_agent_request = fake_runtime
        customer_agent_intent_service.process_intent_request = fake_intent
        customer_service_service._polish_customer_answer = fake_polish

        result = await customer_service_service.ask_customer_service(
            self.db,
            user_id="user-1",
            question="三个年轻人适合哪个锅",
        )

        self.assertEqual(result["answer"], "Agent 已经自主查询并回答。")
        self.assertEqual([item[0] for item in calls], ["runtime"])
        self.assertEqual(result["debug"]["agent_mode"], "llm_tool_calling")

    async def test_ask_customer_service_passes_negative_feedback_lessons(self):
        conversation = CustomerServiceConversation(id="conv-1", user_id="user-1", title="旧会话")
        self.db.add(conversation)
        self.db.add(CustomerServiceMessage(
            id="user-msg-1",
            conversation_id="conv-1",
            role="user",
            content="哪种适合送礼",
        ))
        self.db.add(CustomerServiceMessage(
            id="assistant-msg-1",
            conversation_id="conv-1",
            role="assistant",
            content="随便选一个就行。",
            sources_json=json.dumps([{
                "type": "agent_meta",
                "feedback": {"rating": "incorrect", "reason": "too_casual", "comment": "没有依据"},
            }], ensure_ascii=False),
        ))
        self.db.commit()

        async def fake_runtime(db, **kwargs):
            self.assertEqual(kwargs["feedback_lessons"][0]["question"], "哪种适合送礼")
            self.assertEqual(kwargs["feedback_lessons"][0]["rating"], "incorrect")
            return {
                "answer": "这次会基于资料给推荐理由。",
                "intent": "recommend_products",
                "answer_type": "recommendation",
                "confidence": "high",
                "uncertainty": "confirmed",
                "sources": [],
                "actions": [],
                "results": [{"sku": "CW-C93"}],
                "steps": [],
                "warnings": [],
                "evidence": [],
                "debug": {"agent_mode": "llm_tool_calling"},
                "skip_polish": True,
                "sku": "CS-G25",
            }

        customer_agent_runtime_service.process_agent_request = fake_runtime

        result = await customer_service_service.ask_customer_service(
            self.db,
            user_id="user-1",
            question="给三个年轻人送礼选哪个",
        )

        self.assertEqual(result["intent"], "recommend_products")

    async def test_ask_customer_service_never_locks_frontend_selected_sku(self):
        captured = {}

        async def fake_runtime(db, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "我会根据问题和上下文判断，不使用前端选中的 SKU。",
                "intent": "query_products",
                "answer_type": "product_query",
                "confidence": "high",
                "uncertainty": "confirmed",
                "sources": [],
                "actions": [],
                "results": [{"sku": "CS-G25"}],
                "steps": [],
                "warnings": [],
                "evidence": [],
                "debug": {"agent_mode": "llm_tool_calling"},
                "skip_polish": True,
                "sku": "CS-G25",
            }

        customer_agent_runtime_service.process_agent_request = fake_runtime

        result = await customer_service_service.ask_customer_service(
            self.db,
            user_id="user-1",
            question="这个适合露营吗",
            sku="CW-C83",
        )

        self.assertIsNone(captured["sku"])
        self.assertEqual(result["sku"], "CS-G25")

    async def test_standalone_followup_does_not_pass_previous_result_skus(self):
        conversation = CustomerServiceConversation(id="conv-context", user_id="user-1", title="旧会话")
        self.db.add(conversation)
        self.db.add(CustomerServiceMessage(
            conversation_id="conv-context",
            role="assistant",
            content="首选 CW-C93。",
            sources_json=json.dumps([
                {"type": "agent_context", "result_skus": ["CW-C93", "CW-C83-1"]}
            ], ensure_ascii=False),
        ))
        self.db.commit()
        captured = {}

        async def fake_runtime(db, **kwargs):
            captured.update(kwargs)
            return {
                "answer": "已按四个人做饭重新检索。",
                "intent": "recommend_products",
                "answer_type": "recommendation",
                "confidence": "high",
                "uncertainty": "confirmed",
                "sources": [],
                "actions": [],
                "results": [{"sku": "CW-C83"}],
                "steps": [],
                "warnings": [],
                "evidence": [],
                "debug": {"agent_mode": "llm_tool_calling"},
                "skip_polish": True,
                "sku": None,
            }

        customer_agent_runtime_service.process_agent_request = fake_runtime

        await customer_service_service.ask_customer_service(
            self.db,
            user_id="user-1",
            question="适合四个人做饭的锅有哪些？",
            conversation_id="conv-context",
        )

        self.assertEqual(captured["previous_result_skus"], [])
        self.assertEqual(len(captured["conversation_history"]), 1)
        self.assertEqual(captured["conversation_history"][0]["role"], "assistant")
        self.assertIn("CW-C93", captured["conversation_history"][0]["content"])

    async def test_pronoun_update_uses_previous_result_sku(self):
        product = Product(
            id="product-cs-g25",
            sku="CS-G25",
            barcode="barcode-cs-g25",
            product_name_cn="小青炉",
            product_name_en="Mini Stove",
            brand="alocs爱路客",
            category="炉具",
            person_in_charge="Max",
        )
        self.db.add(product)
        conversation = CustomerServiceConversation(id="conv-pronoun", user_id="user-1", title="小青炉")
        self.db.add(conversation)
        self.db.add(CustomerServiceMessage(
            conversation_id="conv-pronoun",
            role="assistant",
            content="已查到小青炉。",
            sources_json=json.dumps([
                {"type": "agent_context", "result_skus": ["CS-G25"]}
            ], ensure_ascii=False),
        ))
        self.db.commit()

        async def fake_runtime(db, **kwargs):
            return None

        customer_agent_runtime_service.process_agent_request = fake_runtime

        result = await customer_service_service.ask_customer_service(
            self.db,
            user_id="user-1",
            question="修改他的负责人为kang",
            conversation_id="conv-pronoun",
        )

        self.assertEqual(result["intent"], "propose_update")
        self.assertEqual(result["actions"][0]["sku"], "CS-G25")
        self.assertEqual(result["actions"][0]["field_path"], "product.person_in_charge")
        self.assertEqual(result["actions"][0]["proposed_value"], "kang")

    def test_recommendation_answer_filters_oversized_pans_for_coffee(self):
        tool_results = [{
            "ok": True,
            "tool": "search_products",
            "query": "适合泡咖啡的小锅",
            "count": 3,
            "results": [
                {
                    "sku": "CW-C83-1",
                    "product_name_cn": "炊墨炒锅",
                    "category": "锅具",
                    "capacity": "锅 3700ML",
                    "features": "一锅N用",
                    "usage_scenarios": "家庭精致露营",
                },
                {
                    "sku": "CW-C83-2",
                    "product_name_cn": "炊墨煎锅",
                    "category": "锅具",
                    "capacity": "煎盘 2300ML",
                    "features": "健康不沾",
                    "usage_scenarios": "家庭精致露营",
                },
                {
                    "sku": "CW-C93",
                    "product_name_cn": "行山单锅",
                    "category": "锅具",
                    "capacity": "锅 1000ML",
                    "features": "聚能结构 95秒速沸",
                    "usage_scenarios": "单人野宿，露营泡咖啡",
                },
            ],
        }]

        result = customer_agent_runtime_service._build_result(
            "适合泡咖啡的小锅有吗？",
            None,
            tool_results,
            "为您找到了以下适合泡咖啡的小锅推荐：\n1. 炊墨炒锅\n2. 炊墨煎锅\n3. 行山单锅",
            [],
        )

        self.assertEqual(result["intent"], "recommend_products")
        self.assertEqual(result["results"][0]["sku"], "CW-C93")
        self.assertIn("CW-C93", result["answer"])
        self.assertIn("不作为优先推荐", result["answer"])

    def test_recommendation_answer_prefers_three_person_camping_capacity(self):
        tool_results = [{
            "ok": True,
            "tool": "search_products",
            "query": "三个年轻人露营",
            "count": 2,
            "results": [
                {
                    "sku": "CW-C93",
                    "product_name_cn": "行山单锅",
                    "category": "锅具",
                    "capacity": "锅 1000ML",
                    "features": "极限轻量",
                    "target_audience": "单人背包客",
                    "usage_scenarios": "单人野宿",
                },
                {
                    "sku": "CW-C83",
                    "product_name_cn": "炊墨套锅",
                    "category": "锅具",
                    "capacity": "锅 3700ML，煎盘 2300ML",
                    "features": "轻量便携 健康不沾 一锅N用",
                    "target_audience": "家庭户外野餐群体",
                    "usage_scenarios": "家庭精致露营，户外营地大餐",
                },
            ],
        }]

        result = customer_agent_runtime_service._build_result(
            "三个年轻人露营，适合带什么产品",
            None,
            tool_results,
            None,
            [],
        )

        self.assertEqual(result["results"][0]["sku"], "CW-C83")
        self.assertIn("CW-C83", result["answer"])
        self.assertNotIn("找到 2 条产品资料", result["answer"])

    def test_budget_followup_uses_context_and_avoids_high_end_first_choice(self):
        tool_results = [{
            "ok": True,
            "tool": "hybrid_search_products",
            "query": "预算不高，推荐一下",
            "count": 2,
            "results": [
                {
                    "sku": "CW-C93",
                    "product_name_cn": "行山单锅",
                    "category": "锅具",
                    "capacity": "锅 1000ML",
                    "features": "聚能结构 95秒速沸，极限轻量",
                    "target_audience": "单人背包客，极限轻量徒步者",
                    "usage_scenarios": "高海拔徒步，单人野宿",
                    "price_positioning": "高端价格带",
                },
                {
                    "sku": "CW-C83-1",
                    "product_name_cn": "炊墨炒锅",
                    "category": "锅具",
                    "capacity": "锅 3700ML",
                    "features": "轻量化设计，可拆卸手柄，水性不沾，易清洁",
                    "target_audience": "家庭户外野餐群体，多人露营",
                    "usage_scenarios": "家庭精致露营，户外营地大餐",
                    "price_positioning": "常规价格带，性价比款",
                },
            ],
        }]

        result = customer_agent_runtime_service._build_result(
            "预算不高，推荐一下",
            None,
            tool_results,
            "预算不高的话，我推荐行山单锅，它很轻，性价比很高。",
            [],
            conversation_history=[
                {"role": "user", "content": "三个年轻人露营，适合带什么产品？"},
                {"role": "assistant", "content": "首选 CW-C83-1，炊墨炒锅。"},
            ],
        )

        self.assertEqual(result["intent"], "recommend_products")
        self.assertEqual(result["results"][0]["sku"], "CW-C83-1")
        self.assertIn("CW-C83-1", result["answer"])
        self.assertIn("价格定位", result["answer"])
        self.assertNotIn("推荐行山单锅", result["answer"])


if __name__ == "__main__":
    unittest.main()
