import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services import (
    customer_experience_rag_service,
    customer_service_semantic_rag_v2_service,
    customer_service_workbuddy_agent_service,
    customer_service_workbuddy_rag_service,
    knowledge_service,
)


class CustomerExperienceRagServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_feature_does_not_retrieve(self):
        retrieve = AsyncMock()
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", False),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="值不值得买",
                skus=["CF-PG19"],
            )

        self.assertEqual(rows, [])
        retrieve.assert_not_awaited()

    async def test_only_approved_non_fact_cards_are_returned(self):
        approved_metadata = {
            "source_id": "customer_experience:pilot:CF-PG19:value",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
            "intent": "价格顾虑与选购",
        }
        retrieve = AsyncMock(return_value=[
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "先承接价格顾虑，再用本轮事实解释取舍。",
                "metadata": approved_metadata,
                "score": 0.9,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "未审核卡不能进入运行时。",
                "metadata": {**approved_metadata, "review_status": "needs_review"},
                "score": 0.8,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": "product",
                "sku": "CF-PG19",
                "content": "商品事实不能伪装成经验卡。",
                "metadata": approved_metadata,
                "score": 0.7,
                "_retrieval_signal": "vector",
            },
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CHARS", 1200),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="这个有点贵，值在哪里",
                skus=["cf-pg19"],
            )

        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["fact_authority"])
        self.assertEqual(rows[0]["authority_level"], "candidate_only")
        self.assertIn("case_signal", rows[0])
        self.assertEqual(rows[0]["case_signal"]["signal_strength"], "unknown")
        self.assertTrue(any(
            call.kwargs.get("sku") == "CF-PG19"
            for call in retrieve.await_args_list
        ))
        self.assertTrue(all(
            call.kwargs["source_types"] == [
                knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE
            ]
            and call.kwargs["_include_retrieval_signal"]
            for call in retrieve.await_args_list
        ))

    def test_auto_generated_pilot_card_is_eligible_only_as_non_fact_guidance(self):
        row = {
            "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
            "metadata": {
                "review_status": "auto_generated_pilot",
                "production_use": "experience_guidance_only",
                "authority_level": "candidate_only",
                "fact_authority": False,
            },
        }

        self.assertTrue(customer_experience_rag_service._approved_guidance_row(row))

    async def test_experience_guidance_uses_only_relevant_vector_rows(self):
        metadata = {
            "source_id": "customer_experience:pilot:CF-PG19:value",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
            "intent": "价格顾虑与选购",
        }
        retrieve = AsyncMock(return_value=[
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "低相关向量卡，不应进入回答。",
                "metadata": metadata,
                "score": 0.49,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "高相关向量卡，先承接顾虑再解释取舍。",
                "metadata": metadata,
                "score": 0.82,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "关键词 fallback 即使分数高也不能绕过语义门槛。",
                "metadata": metadata,
                "score": 99,
                "_retrieval_signal": "lexical",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "缺少检索信号的旧格式也不能默认为向量结果。",
                "metadata": metadata,
                "score": 0.95,
            },
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="这个有点贵，值在哪里",
                skus=["CF-PG19"],
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["guidance"], "高相关向量卡，先承接顾虑再解释取舍。")

    async def test_product_bound_query_also_considers_global_guidance(self):
        bound_metadata = {
            "source_id": "customer_experience:pilot:CF-PG19:value",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
            "intent": "value",
        }
        global_metadata = {
            "source_id": "customer_experience:pilot:v2:global:recommendation",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
            "intent": "recommendation",
        }
        retrieve = AsyncMock(side_effect=[
            [{
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "same sku guidance",
                "metadata": bound_metadata,
                "score": 0.70,
                "_retrieval_signal": "vector",
            }],
            [{
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": None,
                "content": "global guidance",
                "metadata": global_metadata,
                "score": 0.80,
                "_retrieval_signal": "vector",
            }, {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "OTHER-SKU",
                "content": "unrelated sku guidance",
                "metadata": bound_metadata,
                "score": 0.99,
                "_retrieval_signal": "vector",
            }],
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CHARS", 1200),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="recommend something",
                skus=["CF-PG19"],
            )

        self.assertEqual([row["guidance"] for row in rows], [
            "same sku guidance",
            "global guidance",
        ])
        self.assertEqual([row["sku"] for row in rows], ["CF-PG19", None])
        self.assertEqual(len(retrieve.await_args_list), 2)
        self.assertIsNone(retrieve.await_args_list[1].kwargs.get("sku"))
        self.assertIsNone(retrieve.await_args_list[1].kwargs.get("skus"))

    async def test_unbound_query_does_not_receive_product_specific_guidance(self):
        metadata = {
            "review_status": "auto_generated_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
        }
        retrieve = AsyncMock(return_value=[
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "OTHER-SKU",
                "content": "具体产品的经验，不应泄漏到无商品问题。",
                "metadata": {**metadata, "source_id": "customer_experience:product:other"},
                "score": 0.99,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": None,
                "content": "跨产品通用经验。",
                "metadata": {**metadata, "source_id": "customer_experience:global:one"},
                "score": 0.70,
                "_retrieval_signal": "vector",
            },
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="客户犹豫值不值得买，怎么沟通",
                skus=[],
            )

        self.assertEqual([row["guidance"] for row in rows], ["跨产品通用经验。"])
        self.assertEqual([row["sku"] for row in rows], [None])

    async def test_semantically_tied_cards_are_not_injected(self):
        metadata = {
            "source_id": "customer_experience:pilot:v2:global:one",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
        }
        retrieve = AsyncMock(return_value=[
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": None,
                "content": "第一张卡",
                "metadata": metadata,
                "score": 0.61,
                "_retrieval_signal": "vector",
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": None,
                "content": "第二张卡",
                "metadata": {
                    **metadata,
                    "source_id": "customer_experience:pilot:v2:global:two",
                },
                "score": 0.59,
                "_retrieval_signal": "vector",
            },
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_MARGIN", 0.03),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 1),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="不确定要怎么回答",
                skus=[],
            )

        self.assertEqual(rows, [])

    async def test_product_bound_card_survives_tied_global_guidance(self):
        metadata = {
            "review_status": "auto_generated_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
        }
        retrieve = AsyncMock(side_effect=[
            [{
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CB253",
                "content": "same sku inferred guidance",
                "metadata": {**metadata, "source_id": "customer_experience:catalog:CB253"},
                "score": 0.61,
                "_retrieval_signal": "vector",
            }],
            [
                {
                    "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                    "sku": None,
                    "content": "global guidance one",
                    "metadata": {**metadata, "source_id": "customer_experience:global:one"},
                    "score": 0.65,
                    "_retrieval_signal": "vector",
                },
                {
                    "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                    "sku": None,
                    "content": "global guidance two",
                    "metadata": {**metadata, "source_id": "customer_experience:global:two"},
                    "score": 0.64,
                    "_retrieval_signal": "vector",
                },
            ],
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_MARGIN", 0.03),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 2),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="这个产品怎么选",
                skus=["cb253"],
            )

        self.assertEqual(len(rows), 2)
        self.assertIn("CB253", [row["sku"] for row in rows])

    async def test_explicit_sku_prefers_observed_topic_card_over_legacy_no_outcome_card(self):
        legacy_metadata = {
            "source_id": "customer_experience:pilot:v1:CB253:scenario",
            "review_status": "approved_pilot",
            "production_use": "experience_guidance_only",
            "authority_level": "candidate_only",
            "fact_authority": False,
        }
        observed_metadata = {
            **legacy_metadata,
            "source_id": "customer_experience:catalog:v2:topic-observed",
            "card_kind": "product_topic",
            "insight_status": "observed_strict",
        }
        retrieve = AsyncMock(side_effect=[
            [
                {
                    "source_type": customer_experience_rag_service.knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                    "sku": "CB253",
                    "content": "旧卡没有结果信号",
                    "metadata": legacy_metadata,
                    "score": 0.90,
                    "_retrieval_signal": "vector",
                },
                {
                    "source_type": customer_experience_rag_service.knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                    "sku": "CB253",
                    "content": "新卡带有严格历史结果信号",
                    "metadata": observed_metadata,
                    "score": 0.72,
                    "_retrieval_signal": "vector",
                },
            ],
            [],
        ])
        with (
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", True),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", 0.50),
            patch.object(settings, "CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", 1),
            patch.object(knowledge_service, "semantic_retrieve", retrieve),
        ):
            rows = await customer_experience_rag_service.retrieve_experience_guidance(
                object(),
                question="这个产品怎么选",
                skus=["CB253"],
            )

        self.assertEqual([row["guidance"] for row in rows], ["新卡带有严格历史结果信号"])

    def test_retrieval_is_not_question_keyword_routed(self):
        self.assertTrue(
            customer_experience_rag_service.should_retrieve_experience_guidance(
                "价格有点高，我还在犹豫值不值得买？"
            )
        )
        self.assertTrue(
            customer_experience_rag_service.should_retrieve_experience_guidance(
                "客户担心安全，客服怎么承接？"
            )
        )
        self.assertTrue(
            customer_experience_rag_service.should_retrieve_experience_guidance(
                "这个水壶的容量、材质和适用热源是什么？"
            )
        )
        self.assertTrue(
            customer_experience_rag_service.should_retrieve_experience_guidance(
                "这个折叠箱的尺寸、容量和承重怎么确认？"
            )
        )

    def test_direct_fact_forms_can_receive_semantic_case_context(self):
        for question in (
            "CS-B14 \u80fd\u5728\u5ba4\u5185\u4f7f\u7528\u5417\uff1f",
            "CB254 \u80fd\u7528\u5361\u5f0f\u7089\u5417\uff1f",
            "CW-C83 \u6709\u6ca1\u6709\u4fdd\u4fee\uff1f",
            "\u6237\u5916\u9152\u7cbe\u7089\u5982\u4f55\u5b89\u5168\u4f7f\u7528\uff1f",
        ):
            self.assertTrue(
                customer_experience_rag_service.should_retrieve_experience_guidance(
                    question
                )
            )

    def test_outcome_signal_packet_keeps_learning_signals_compact(self):
        rows = customer_experience_rag_service.outcome_signal_packet([
            {
                "guidance_id": "case-1",
                "sku": "cw-c94",
                "intent": "选购与推荐",
                "retrieval_score": 0.88,
                "case_signal": {
                    "signal_strength": "observed",
                    "outcome_evidence": {
                        "positive_observations": 8,
                        "confirmed_conversion_observations": 2,
                        "denominator_available": False,
                    },
                },
            },
        ])

        self.assertEqual(rows[0]["sku"], "CW-C94")
        self.assertEqual(rows[0]["signal"]["outcome_evidence"]["positive_observations"], 8)
        self.assertFalse(rows[0]["signal"]["outcome_evidence"]["denominator_available"])

    def test_three_pipelines_keep_guidance_separate_from_fact_evidence(self):
        guidance = [{
            "guidance_id": "customer_experience:pilot:CF-PG19:value",
            "sku": "CF-PG19",
            "guidance": "先承接顾虑，再说明取舍。",
            "authority_level": "candidate_only",
            "fact_authority": False,
        }]
        evidence = [{"evidence_id": "e1", "sku": "CF-PG19", "content": "铝合金"}]

        semantic_payload = customer_service_semantic_rag_v2_service._answer_prompt_payload(
            question="值不值得买",
            plan={},
            page_anchor=None,
            history=[],
            context_candidates=[],
            candidates=[],
            evidence=evidence,
            experience_guidance=guidance,
            identity_ambiguity=False,
        )
        workbuddy_payload = customer_service_workbuddy_rag_service._answer_prompt(
            question="值不值得买",
            history=[],
            previous_turn_memory={},
            context_candidates=[],
            explicit_product_skus=["CF-PG19"],
            anchor_skus=[],
            page_anchor=None,
            candidates=[],
            previous_context_products=[],
            evidence=evidence,
            experience_guidance=guidance,
        )
        agent_message = customer_service_workbuddy_agent_service._experience_guidance_message(
            guidance
        )
        agent_payload = json.loads(agent_message["content"])

        self.assertEqual(semantic_payload["evidence"], evidence)
        self.assertEqual(semantic_payload["experience_guidance"], guidance)
        self.assertEqual(workbuddy_payload["experience_guidance"], guidance)
        self.assertNotIn("experience_guidance", workbuddy_payload["evidence"])
        self.assertEqual(agent_payload["experience_guidance"], guidance)
        self.assertFalse(agent_payload["experience_guidance"][0]["fact_authority"])

    def test_workbuddy_unbound_after_sales_turn_stays_identity_unbound(self):
        payload = customer_service_workbuddy_rag_service._answer_prompt(
            question="收到有问题",
            history=[],
            previous_turn_memory={},
            context_candidates=[],
            explicit_product_skus=[],
            catalogue_subject_skus=[],
            anchor_skus=[],
            page_anchor=None,
            candidates=[{"sku": "CS-B18", "product_name_cn": "候选商品"}],
            previous_context_products=[],
            evidence=[{
                "evidence_id": "candidate-qa",
                "sku": "CS-B18",
                "content": "候选商品的售后资料",
            }],
            experience_guidance=[],
        )

        guidance = payload["turn_identity_contract"]["unbound_turn_guidance"]
        self.assertIn("收货后少件、破损、功能异常或售后处理", guidance)
        self.assertIn("不要从候选商品中挑选或并列引用", guidance)

    async def test_semantic_general_plan_does_not_promote_unanchored_product_rows(self):
        target_skus, candidate_skus = await customer_service_semantic_rag_v2_service._resolve_subject_skus(
            object(),
            question="收到货后发现有问题怎么办",
            plan={
                "request_kind": "general_knowledge",
                "subject_scope": "general",
                "subject_text": "",
                "product_subjects": [],
            },
            page_sku=None,
            explicit_skus=[],
            context_candidates=[],
            retrieved_rows=[{
                "sku": "CS-B18",
                "source_type": "product",
                "content": "候选商品售后资料",
                "score": 0.9,
                "retrieval_rank": 0,
            }],
        )

        self.assertEqual(target_skus, [])
        self.assertEqual(candidate_skus, [])

    async def test_semantic_named_product_resolution_has_candidate_limit(self):
        class EmptyProductDb:
            def query(self, *_args):
                return self

            def all(self):
                return []

        resolved = SimpleNamespace(
            status="resolved",
            resolved_sku="OT-188LY",
            resolver_candidate_skus=[],
            candidate_skus=[],
            diagnostic_candidate_skus=[],
        )
        with patch.object(
            customer_service_semantic_rag_v2_service.customer_entity_resolution_contract,
            "build_entity_resolution_contract",
            return_value=resolved,
        ):
            target_skus, candidate_skus = await customer_service_semantic_rag_v2_service._resolve_subject_skus(
                EmptyProductDb(),
                question="OT-188LY \u9002\u5408\u9732\u8425\u5417\uff1f",
                plan={
                    "request_kind": "recommendation",
                    "subject_scope": "named_product",
                    "product_subjects": ["\u75af\u72c2\u6e38\u4e50\u56ed\u5929\u5e55"],
                },
                page_sku=None,
                explicit_skus=[],
                context_candidates=[],
                retrieved_rows=[],
            )

        self.assertEqual(target_skus, ["OT-188LY"])
        self.assertEqual(candidate_skus, [])

    def test_unbound_semantic_evidence_excludes_sku_rows(self):
        evidence = customer_service_semantic_rag_v2_service._build_evidence(
            [
                {
                    "source_type": "product",
                    "sku": "CS-B18",
                    "source_id": "product:CS-B18:qa:after-sales",
                    "content": "候选商品售后资料",
                    "metadata": {"section": "qa"},
                },
                {
                    "source_type": "knowledge",
                    "sku": None,
                    "source_id": "knowledge:after-sales-intake",
                    "content": "先收集商品身份、订单和具体现象。",
                    "metadata": {},
                },
            ],
            {},
            allowed_skus=set(),
            allow_unbound=True,
        )

        self.assertEqual([item["sku"] for item in evidence], [None])


if __name__ == "__main__":
    unittest.main()
