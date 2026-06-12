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

    def test_generic_recommendation_answer_is_flagged(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "推荐一个适合露营的锅",
            answer="找到 2 条产品资料：CW-C83，CW-C93。",
            intent="recommend_products",
            results=[{"sku": "CW-C83"}, {"sku": "CW-C93"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertIn("generic_recommendation_answer", quality["risks"])
        self.assertFalse(quality["passed"])

    def test_low_budget_high_end_first_choice_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "预算不高，推荐一下",
            answer="首选 CW-C83，价格定位高端。",
            intent="recommend_products",
            results=[{"sku": "CW-C83", "price_positioning": "高端价格带"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("low_budget_high_end_first_choice", quality["risks"])

    def test_pot_query_non_pot_first_choice_is_blocked(self):
        quality = customer_agent_quality_service.evaluate_agent_response(
            "适合泡咖啡的小锅有吗？",
            answer="首选 CB-003 悦行包。",
            intent="recommend_products",
            results=[{"sku": "CB-003", "product_name_cn": "悦行包", "category": "收纳包"}],
            sources=[{"type": "product_search"}],
            actions=[],
            warnings=[],
        )

        self.assertEqual(quality["level"], "low")
        self.assertFalse(quality["passed"])
        self.assertIn("product_type_mismatch_first_choice", quality["risks"])


if __name__ == "__main__":
    unittest.main()
