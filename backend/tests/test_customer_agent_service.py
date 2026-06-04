import contextlib
import io
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    AgentAction, Certification, Keyword, ListingChannel, OperationLog, Product,
    ProductBusiness, ProductCertification, ProductContent, ProductKeyword,
    ProductListingChannel, ProductMedia, ProductPrompts, ProductQa, ProductQaNegative,
    ProductSalesRegion, ProductSpecs, SalesRegion,
)
from app.services import customer_agent_intent_service, customer_agent_runtime_service, customer_agent_service, customer_agent_tool_service, dmxapi_service


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

    def tearDown(self):
        dmxapi_service.chat_completion = self.original_chat_completion
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
        with contextlib.redirect_stdout(stream):
            result = await customer_agent_runtime_service.process_agent_request(
                self.db,
                user_id="user-1",
                question="所有锅的容量给我",
            )

        output = stream.getvalue()
        self.assertIsNotNone(result)
        self.assertEqual(result["answer"], "CW-C93 的容量是 1000ml。")
        self.assertEqual(result["results"][0]["sku"], "CW-C93")
        self.assertEqual(result["results"][0]["field_values"]["容量"], "1000ml")
        self.assertIn("CUSTOMER_AGENT_TOOL_CALL", output)
        self.assertIn("CUSTOMER_AGENT_TOOL_RESULT", output)
        self.assertIn("CUSTOMER_AGENT_FINAL_RESPONSE", output)

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
        self.assertEqual(result["steps"][0]["type"], "clarify")


if __name__ == "__main__":
    unittest.main()
