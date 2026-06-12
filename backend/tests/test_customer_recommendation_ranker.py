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

    def test_four_person_cooking_prefers_mid_capacity(self):
        rows = [
            {
                "sku": "SMALL-1",
                "product_name_cn": "行山单锅",
                "capacity": "1000ml",
                "features": "单人轻量徒步",
                "target_audience": "单人",
            },
            {
                "sku": "MID-1",
                "product_name_cn": "营地套锅",
                "capacity": "3700ML",
                "features": "适合露营做饭",
                "target_audience": "多人露营",
            },
        ]

        ranked = customer_recommendation_ranker.fallback_rank(rows, "适合四个人做饭的锅")

        self.assertEqual(ranked[0]["row"]["sku"], "MID-1")
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score("适合四个人做饭的锅", rows[1]),
            customer_recommendation_ranker.recommendation_score("适合四个人做饭的锅", rows[0]),
        )

    def test_low_budget_penalty_overrides_scene_fit_for_high_end(self):
        rows = [
            {
                "sku": "HIGH-FIT",
                "product_name_cn": "高端家庭套锅",
                "capacity": "3700ML",
                "features": "多人露营做饭",
                "target_audience": "家庭多人",
                "price_positioning": "高端价格带",
            },
            {
                "sku": "VALUE-OK",
                "product_name_cn": "常规单锅",
                "capacity": "1400ML",
                "features": "实惠耐用",
                "target_audience": "双人",
                "price_positioning": "常规价格带，性价比款",
            },
        ]

        ranked = customer_recommendation_ranker.fallback_rank(rows, "适合四个人做饭的锅；追加条件：预算不高")

        self.assertEqual(ranked[0]["row"]["sku"], "VALUE-OK")
        self.assertLess(customer_recommendation_ranker.budget_score("预算不高", rows[0]), -50)

    def test_pot_query_penalizes_stove_candidate(self):
        pot = {"sku": "POT-1", "product_name_cn": "行山单锅", "category": "锅具", "features": "适合泡咖啡"}
        stove = {"sku": "STOVE-1", "product_name_cn": "旋焰酒精炉", "category": "炉具", "features": "适合冲泡咖啡"}
        cup = {"sku": "CUP-1", "product_name_cn": "悦享杯套装", "category": "杯具", "features": "适合泡咖啡"}
        bag = {"sku": "BAG-1", "product_name_cn": "悦行包", "category": "收纳包", "features": "适合露营"}

        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("适合泡咖啡的小锅", stove))
        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("适合泡咖啡的小锅", cup))
        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("适合泡咖啡的小锅", bag))
        self.assertFalse(customer_recommendation_ranker.is_obvious_product_type_mismatch("适合泡咖啡的小锅", pot))
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score("适合泡咖啡的小锅", pot),
            customer_recommendation_ranker.recommendation_score("适合泡咖啡的小锅", stove),
        )

    def test_stove_query_penalizes_pot_candidate(self):
        stove = {"sku": "STOVE-1", "product_name_cn": "酒精炉套装", "category": "酒精炉", "price_positioning": "入门款"}
        pot = {"sku": "POT-1", "product_name_cn": "激川单锅", "category": "锅具", "price_positioning": "中端"}

        self.assertFalse(customer_recommendation_ranker.is_obvious_product_type_mismatch("预算不高的炉具推荐一下", stove))
        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("预算不高的炉具推荐一下", pot))
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score("预算不高的炉具推荐一下", stove),
            customer_recommendation_ranker.recommendation_score("预算不高的炉具推荐一下", pot),
        )


if __name__ == "__main__":
    unittest.main()
