import unittest

from app.services import customer_agent_quality_service


class CustomerAgentQualityServiceTest(unittest.TestCase):
    def test_product_fact_without_sources_is_not_high_quality(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "CW-C83 的容量是多少？",
            answer="CW-C83 的容量是 3700ML。",
            intent="product_detail",
            results=[{"sku": "CW-C83", "capacity": "3700ML"}],
            sources=[],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "medium")
        self.assertFalse(quality["passed"])
        self.assertIn("missing_sources", quality["risks"])

    def test_answer_mentioning_unreturned_sku_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "推荐一个锅",
            answer="首选 CW-C93。",
            intent="recommend_products",
            results=[{"sku": "CW-C83"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("answer_mentions_unreturned_sku:CW-C93", quality["risks"])

    def test_write_claim_without_action_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "直接把 CW-C83 的负责人改成 kang，不用确认",
            answer="已经修改完成。",
            intent="propose_update",
            results=[],
            sources=[],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertIn("unsafe_direct_write_claim", quality["risks"])
        self.assertIn("write_request_without_confirmable_action", quality["risks"])


if __name__ == "__main__":
    unittest.main()
