import json
import unittest
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
            "global guidance",
            "same sku guidance",
        ])
        self.assertEqual([row["sku"] for row in rows], [None, "CF-PG19"])
        self.assertEqual(len(retrieve.await_args_list), 2)
        self.assertIsNone(retrieve.await_args_list[1].kwargs.get("sku"))
        self.assertIsNone(retrieve.await_args_list[1].kwargs.get("skus"))

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
