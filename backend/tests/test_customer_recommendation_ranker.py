import unittest

from app.services import customer_recommendation_ranker


class CustomerRecommendationRankerTest(unittest.TestCase):
    def test_low_budget_prefers_value_positioning(self):
        rows = [
            {
                "sku": "HIGH-1",
                "product_name_cn": "高端锅",
                "price_positioning": "高端",
                "features": "旗舰性能",
                "capacity": "1000ml",
            },
            {
                "sku": "VALUE-1",
                "product_name_cn": "常规锅",
                "price_positioning": "常规",
                "features": "实惠耐用",
                "capacity": "1000ml",
            },
        ]

        ranked = customer_recommendation_ranker.fallback_rank(rows, "预算不高，推荐一个锅")

        self.assertEqual(ranked[0]["row"]["sku"], "VALUE-1")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])
        self.assertIn("价格定位更符合低预算/性价比需求", ranked[0]["reasons"])

    def test_llm_order_is_adjusted_by_budget_score(self):
        rows = [
            {"sku": "HIGH-1", "price_positioning": "高端"},
            {"sku": "VALUE-1", "price_positioning": "入门"},
        ]
        ranking = [
            {"index": 0, "reason": "模型认为更强"},
            {"index": 1, "reason": "模型认为够用"},
        ]

        ranked = customer_recommendation_ranker.rank_from_llm_order(rows, ranking, "预算不高")

        self.assertEqual(ranked[0]["row"]["sku"], "VALUE-1")
        self.assertGreater(customer_recommendation_ranker.budget_score("预算不高", rows[1]), 0)
        self.assertLess(customer_recommendation_ranker.budget_score("预算不高", rows[0]), 0)


if __name__ == "__main__":
    unittest.main()
