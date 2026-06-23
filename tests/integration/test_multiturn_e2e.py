import asyncio
import json
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import Base
from app.models import (
    AgentAction,
    Certification,
    CustomerServiceConversation,
    CustomerServiceMessage,
    Keyword,
    KnowledgeChunk,
    KnowledgeDocument,
    ListingChannel,
    OperationLog,
    Product,
    ProductBusiness,
    ProductCertification,
    ProductContent,
    ProductKeyword,
    ProductListingChannel,
    ProductMedia,
    ProductPrompts,
    ProductQa,
    ProductQaNegative,
    ProductSalesRegion,
    ProductSpecs,
    SalesRegion,
)
from app.services import (
    customer_agent_intent_service,
    customer_agent_runtime_service,
    customer_agent_service,
    customer_agent_tool_service,
    customer_enterprise_guardrail_service,
    customer_llm_service,
    customer_service_service,
)


class MultiturnE2ETest(unittest.TestCase):
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
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self._original_guardrail = customer_enterprise_guardrail_service.evaluate_question
        self._original_runtime = customer_agent_runtime_service.process_agent_request
        self._original_intent = customer_agent_intent_service.process_intent_request
        self._original_legacy = customer_agent_service.process_agent_request
        self._original_chat_completion = customer_llm_service.chat_completion
        self._original_execute_tool_async = customer_agent_tool_service.execute_tool_async
        self._seed_products()

    def tearDown(self):
        customer_enterprise_guardrail_service.evaluate_question = self._original_guardrail
        customer_agent_runtime_service.process_agent_request = self._original_runtime
        customer_agent_intent_service.process_intent_request = self._original_intent
        customer_agent_service.process_agent_request = self._original_legacy
        customer_llm_service.chat_completion = self._original_chat_completion
        customer_agent_tool_service.execute_tool_async = self._original_execute_tool_async
        self.db.close()

    def test_sku_pool_exhaustion(self):
        turns = [
            ["CW-C05-37", "CW-C83"],
            ["CW-C01-37"],
            [],
        ]
        expected_exclusions = [
            [],
            ["CW-C05-37", "CW-C83"],
            ["CW-C05-37", "CW-C83", "CW-C01-37"],
        ]
        calls = []

        async def fake_runtime(db, **kwargs):
            index = len(calls)
            calls.append(kwargs)
            skus = turns[index]
            excluded = set(expected_exclusions[index])
            results = [self._product_row(sku) for sku in skus if sku not in excluded]
            answer = (
                "没有找到其他足够匹配的产品，暂无其他推荐。"
                if not results
                else "推荐：" + "、".join(item["sku"] for item in results)
            )
            return self._agent_result(
                "recommend_products",
                answer,
                results,
                debug={
                    "agent_mode": "llm_tool_calling",
                    "previous_recommended_skus_excluded": expected_exclusions[index],
                },
            )

        self._patch_service_fallbacks(fake_runtime)

        turn1 = self._ask("推荐一款适合2个人露营做饭的锅")
        turn2 = self._ask("换一个推荐，不要刚才那个", turn1["conversation_id"])
        turn3 = self._ask("换一个推荐，不要刚才那个", turn1["conversation_id"])

        self.assertEqual([item["sku"] for item in turn1["results"]], ["CW-C05-37", "CW-C83"])
        self.assertEqual([item["sku"] for item in turn2["results"]], ["CW-C01-37"])
        self.assertEqual(turn3["results"], [])
        self.assertEqual(self._result_skus(turn3), [])
        self.assertTrue(turn3["answer"].strip())
        self.assertTrue("没有找到" in turn3["answer"] or "暂无其他推荐" in turn3["answer"])
        self.assertEqual(
            calls[2]["conversation_history"][-1]["content"],
            turn2["answer"],
        )

    def test_multi_filter_combination(self):
        captured = {}
        candidates = [
            self._candidate("SKU-A", material="titanium", price=280, persons=2),
            self._candidate("SKU-B", material="aluminum", price=250, persons=2),
            self._candidate("SKU-C", material="titanium", price=350, persons=2),
        ]

        async def fake_execute_tool_async(db, *, user_id, name, arguments):
            self.assertEqual(name, "hybrid_search_products")
            captured["arguments"] = arguments
            filters = arguments.get("filters") or {}
            self.assertEqual(filters.get("persons"), 2)
            self.assertEqual(filters.get("material"), "titanium")
            self.assertEqual(filters.get("price_max"), 300)
            rows = [
                item for item in candidates
                if item["body_material"] == filters["material"]
                and item["price"] <= filters["price_max"]
                and item["persons"] == filters["persons"]
            ]
            return {
                "ok": True,
                "tool": "hybrid_search_products",
                "query": arguments.get("semantic_query"),
                "filters": filters,
                "count": len(rows),
                "results": rows,
            }

        async def fake_runtime(db, **kwargs):
            arguments = {
                "semantic_query": kwargs["question"],
                "filters": {"persons": 2, "material": "titanium", "price_max": 300},
                "limit": 20,
            }
            tool_result = await customer_agent_tool_service.execute_tool_async(
                db,
                user_id=kwargs["user_id"],
                name="hybrid_search_products",
                arguments=arguments,
            )
            return self._agent_result(
                "recommend_products",
                "推荐 SKU-A，符合2人、钛合金、300以内。",
                tool_result["results"],
                sources=[{
                    "type": "product_search",
                    "tool": "hybrid_search_products",
                    "filters": arguments["filters"],
                    "candidate_skus": [item["sku"] for item in candidates],
                }],
            )

        self._patch_service_fallbacks(fake_runtime)
        customer_agent_tool_service.execute_tool_async = fake_execute_tool_async

        result = self._ask("推荐2人用、钛合金、预算300以内的锅")

        self.assertEqual(self._result_skus(result), ["SKU-A"])
        self.assertEqual(captured["arguments"]["filters"], {"persons": 2, "material": "titanium", "price_max": 300})
        self.assertEqual(self._previous_recommended_skus_excluded(result["conversation_id"], result["message_id"]), [])

    def test_recommend_compare_re_recommend(self):
        async def fake_runtime(db, **kwargs):
            question = kwargs["question"]
            if "比价" in question:
                context = customer_service_service._latest_recommendation_context_for_sources(
                    db,
                    kwargs["conversation_id"],
                )
                self.assertEqual(context.get("recommended_skus"), ["CW-C05-37", "CW-C83"])
                return self._agent_result(
                    "compare_products",
                    "CW-C05-37 价格定位更高，CW-C83 更轻便。",
                    [self._product_row("CW-C05-37"), self._product_row("CW-C83")],
                )
            if "换" in question:
                context = customer_service_service._latest_recommendation_context_for_sources(
                    db,
                    kwargs["conversation_id"],
                )
                excluded = set(context.get("recommended_skus") or [])
                self.assertEqual(excluded, {"CW-C05-37", "CW-C83"})
                results = [self._product_row("CW-C01-37")]
                return self._agent_result(
                    "recommend_products",
                    "换一个推荐 CW-C01-37。",
                    [item for item in results if item["sku"] not in excluded],
                    debug={
                        "agent_mode": "llm_tool_calling",
                        "recommendation_context_found": True,
                        "previous_recommended_skus_excluded": sorted(excluded),
                    },
                )
            return self._agent_result(
                "recommend_products",
                "推荐 CW-C05-37 和 CW-C83。",
                [self._product_row("CW-C05-37"), self._product_row("CW-C83")],
            )

        self._patch_service_fallbacks(fake_runtime)

        turn1 = self._ask("推荐一款适合2个人露营做饭的锅")
        turn2 = self._ask("这两个帮我比价", turn1["conversation_id"])
        turn3 = self._ask("换一个推荐，不要刚才那个", turn1["conversation_id"])

        turn1_skus = self._result_skus(turn1)
        self.assertEqual(turn1_skus, ["CW-C05-37", "CW-C83"])
        self.assertEqual(turn2["intent"], "compare_products")
        self.assertEqual(self._recommendation_context(turn2["message_id"])["recommended_skus"], turn1_skus)
        self.assertTrue(set(self._result_skus(turn3)).isdisjoint(turn1_skus))
        self.assertTrue(self._recommendation_context_found(turn3))

    def _patch_service_fallbacks(self, fake_runtime):
        customer_enterprise_guardrail_service.evaluate_question = lambda question: None
        customer_agent_runtime_service.process_agent_request = fake_runtime

        async def no_intent(*args, **kwargs):
            return None

        customer_agent_intent_service.process_intent_request = no_intent
        customer_agent_service.process_agent_request = lambda *args, **kwargs: None

        async def fake_chat_completion(*args, **kwargs):
            return json.dumps({"answer": "mocked final answer"}, ensure_ascii=False)

        customer_llm_service.chat_completion = fake_chat_completion

    def _ask(self, question, conversation_id=None):
        return asyncio.run(customer_service_service.ask_customer_service(
            self.db,
            user_id="integration-user",
            question=question,
            conversation_id=conversation_id,
        ))

    def _agent_result(self, intent, answer, results, *, sources=None, debug=None):
        result_skus = [item["sku"] for item in results]
        return {
            "answer": answer,
            "intent": intent,
            "answer_type": "recommendation" if intent == "recommend_products" else "product_detail",
            "confidence": "high",
            "uncertainty": "confirmed" if results or intent != "recommend_products" else "no_result",
            "needs_clarification": False,
            "sources": sources or [],
            "actions": [],
            "results": results,
            "steps": [],
            "warnings": [],
            "evidence": [],
            "debug": {"agent_mode": "llm_tool_calling", **(debug or {})},
            "skip_polish": True,
            "sku": result_skus[0] if len(result_skus) == 1 else None,
            "result_skus": result_skus,
        }

    def _seed_products(self):
        for sku, name, material, price, persons in [
            ("CW-C05-37", "2-4人野餐锅10件套", "硬质氧化铝合金", 420, "2人"),
            ("CW-C83", "炊墨套锅", "硬质氧化铝合金", 390, "2人"),
            ("CW-C01-37", "1-2人野营锅7件套", "硬质氧化铝合金", 260, "2人"),
            ("SKU-A", "钛合金双人锅", "钛合金", 280, "2人"),
            ("SKU-B", "铝合金双人锅", "铝合金", 250, "2人"),
            ("SKU-C", "钛合金高价锅", "钛合金", 350, "2人"),
        ]:
            product = Product(
                id=f"id-{sku}",
                sku=sku,
                barcode=f"barcode-{sku}",
                product_name_cn=name,
                product_name_en=name,
                brand="alocs",
                category="锅具",
                product_level="A类品",
                lifecycle_status="常规品",
                person_in_charge="Test",
            )
            self.db.add(product)
            self.db.add(ProductSpecs(
                id=f"specs-{sku}",
                product_id=product.id,
                capacity="1400ml",
                gross_weight_g=float(price),
                body_material=material,
                heat_source="气炉",
                technical_advantages=f"{persons}露营做饭",
            ))
            self.db.add(ProductBusiness(
                id=f"business-{sku}",
                product_id=product.id,
                top_selling_points=f"{persons}露营做饭",
                target_audience=persons,
                positioning=f"price={price}",
                price_positioning="300以内" if price <= 300 else "300以上",
                usage_scenarios="露营做饭",
            ))
            self.db.add(ProductContent(
                id=f"content-{sku}",
                product_id=product.id,
                title_cn=name,
                long_description_cn=f"{name} {material} {price} {persons}",
            ))
        self.db.commit()

    def _product_row(self, sku):
        product = self.db.query(Product).filter(Product.sku == sku).one()
        specs = self.db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        business = self.db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).one()
        price = int(float(specs.gross_weight_g or 0))
        return {
            "sku": product.sku,
            "product_name_cn": product.product_name_cn,
            "product_name_en": product.product_name_en,
            "category": product.category,
            "capacity": specs.capacity,
            "body_material": specs.body_material,
            "features": specs.technical_advantages,
            "target_audience": business.target_audience,
            "usage_scenarios": business.usage_scenarios,
            "positioning": business.positioning,
            "price_positioning": business.price_positioning,
            "price": price,
            "persons": business.target_audience,
        }

    def _candidate(self, sku, *, material, price, persons):
        row = self._product_row(sku)
        row.update({"body_material": material, "price": price, "persons": persons})
        return row

    def _result_skus(self, result):
        return [item["sku"] for item in result.get("results") or []]

    def _assistant_message(self, message_id):
        return self.db.query(CustomerServiceMessage).filter(
            CustomerServiceMessage.id == message_id,
            CustomerServiceMessage.role == "assistant",
        ).one()

    def _sources(self, message_id):
        return json.loads(self._assistant_message(message_id).sources_json or "[]")

    def _recommendation_context(self, message_id):
        for source in self._sources(message_id):
            if isinstance(source, dict) and source.get("type") == "agent_meta":
                return source.get("recommendation_context") or {}
        return {}

    def _recommendation_context_found(self, result):
        if result.get("intent") == "recommend_products" and self._result_skus(result):
            return True
        return bool(self._recommendation_context(result["message_id"]))

    def _previous_recommended_skus_excluded(self, conversation_id, message_id):
        current = self._assistant_message(message_id)
        messages = (
            self.db.query(CustomerServiceMessage)
            .filter(
                CustomerServiceMessage.conversation_id == conversation_id,
                CustomerServiceMessage.role == "assistant",
                CustomerServiceMessage.created_at < current.created_at,
            )
            .order_by(CustomerServiceMessage.created_at.desc(), CustomerServiceMessage.id.desc())
            .limit(5)
            .all()
        )
        for message in messages:
            sources = json.loads(message.sources_json or "[]")
            for source in sources:
                context = source.get("recommendation_context") if isinstance(source, dict) else None
                if isinstance(context, dict) and context.get("recommended_skus"):
                    return context["recommended_skus"]
        return []


if __name__ == "__main__":
    unittest.main()
