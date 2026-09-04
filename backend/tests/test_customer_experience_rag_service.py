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
            },
            {
                "source_type": knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                "sku": "CF-PG19",
                "content": "未审核卡不能进入运行时。",
                "metadata": {**approved_metadata, "review_status": "needs_review"},
                "score": 0.8,
            },
            {
                "source_type": "product",
                "sku": "CF-PG19",
                "content": "商品事实不能伪装成经验卡。",
                "metadata": approved_metadata,
                "score": 0.7,
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
        kwargs = retrieve.await_args.kwargs
        self.assertEqual(kwargs["sku"], "CF-PG19")
        self.assertEqual(
            kwargs["source_types"],
            [knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
        )

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


if __name__ == "__main__":
    unittest.main()
