import unittest

from app.services import customer_dialogue_state
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

    def test_not_too_expensive_is_treated_as_low_budget(self):
        rows = [
            {"sku": "HIGH-1", "price_positioning": "高端价格带"},
            {"sku": "VALUE-1", "price_positioning": "常规价格带，性价比款"},
        ]

        self.assertTrue(customer_dialogue_state.is_low_budget_query("不是很贵的锅推荐一下"))
        self.assertGreater(
            customer_recommendation_ranker.budget_score("不是很贵的锅推荐一下", rows[1]),
            customer_recommendation_ranker.budget_score("不是很贵的锅推荐一下", rows[0]),
        )

    def test_high_end_query_prefers_high_price_candidate(self):
        rows = [
            {"sku": "VALUE-1", "product_name_cn": "常规单锅", "price_positioning": "常规价格带"},
            {"sku": "HIGH-1", "product_name_cn": "高端套锅", "price_positioning": "高端价格带"},
        ]

        ranked = customer_recommendation_ranker.fallback_rank(rows, "推荐高端一点的锅")

        self.assertEqual(ranked[0]["row"]["sku"], "HIGH-1")
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score("推荐高端一点的锅", rows[1]),
            customer_recommendation_ranker.recommendation_score("推荐高端一点的锅", rows[0]),
        )

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
        self.assertTrue(any("容量适合3-4人" in item for item in ranked[0]["matched"]))
        self.assertTrue(any("做饭" in item or "煎炒煮" in item for item in ranked[0]["matched"]))
        self.assertIn("score_reason", ranked[0])
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

    def test_lightweight_one_two_person_pot_prefers_compact_over_family_cookset(self):
        compact = {
            "sku": "CW-C01-37",
            "product_name_cn": "1-2人野营锅7件套",
            "category": "锅具",
            "capacity": "锅 900ML，碗 450ML",
            "features": "轻量化套娃收纳，全包围防风",
            "target_audience": "1-2人露营者，轻量徒步用户",
            "usage_scenarios": "轻量徒步，双人露营，极简野炊",
        }
        family = {
            "sku": "CW-C83",
            "product_name_cn": "炊墨套锅",
            "category": "锅具",
            "capacity": "锅 3700ML，煎盘 2300ML",
            "features": "家庭精致露营，可拆卸手柄",
            "target_audience": "家庭户外野餐群体，多人露营",
            "usage_scenarios": "家庭精致露营，房车自驾旅行，户外营地大餐",
        }

        ranked = customer_recommendation_ranker.fallback_rank(
            [family, compact],
            "推荐一款适合1-2人轻量徒步的锅具",
        )

        self.assertEqual(ranked[0]["row"]["sku"], "CW-C01-37")
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score("推荐一款适合1-2人轻量徒步的锅具", compact),
            customer_recommendation_ranker.recommendation_score("推荐一款适合1-2人轻量徒步的锅具", family),
        )

    def test_two_person_high_end_cooking_prefers_dual_capacity_over_single_ultralight(self):
        single = {
            "sku": "CW-C93",
            "product_name_cn": "行山单锅",
            "category": "锅具",
            "capacity": "锅 1000ML",
            "features": "适配多种炉头，聚能结构，95秒速沸",
            "target_audience": "单人背包客，极限轻量徒步者，速穿玩家",
            "usage_scenarios": "高海拔徒步，极限轻量游，单人野宿",
            "price_positioning": "高端",
        }
        dual = {
            "sku": "CW-S10-A",
            "product_name_cn": "激川单锅",
            "category": "锅具",
            "capacity": "锅 1400ML",
            "features": "1.4L大容量满足双人需求，食品级陶瓷不沾，高效集热",
            "target_audience": "1-2人露营者，轻量徒步爱好者",
            "usage_scenarios": "轻量徒步，双人露营，户外小份烹饪",
            "price_positioning": "高端",
        }

        query = "两个人旅行，要能煎炒煮；追加条件：推荐高端一点的锅"
        ranked = customer_recommendation_ranker.fallback_rank([single, dual], query)

        self.assertEqual(ranked[0]["row"]["sku"], "CW-S10-A")
        self.assertGreater(
            customer_recommendation_ranker.recommendation_score(query, dual),
            customer_recommendation_ranker.recommendation_score(query, single),
        )

    def test_water_gear_request_penalizes_stove_and_pot_candidates(self):
        kettle = {"sku": "CW-K03-37", "product_name_cn": "1.4升户外水壶", "category": "水壶", "capacity": "水壶 1400ml", "features": "轻量便携，户外补水，山野煮茶"}
        stove = {"sku": "CS-B02-37", "product_name_cn": "酒精炉套装", "category": "酒精炉", "features": "户外加热"}
        pot = {"sku": "CW-C93", "product_name_cn": "行山单锅", "category": "锅具", "capacity": "锅 1000ML", "features": "轻量徒步"}

        ranked = customer_recommendation_ranker.fallback_rank(
            [stove, pot, kettle],
            "预算低一点，有没有水壶推荐？",
        )

        self.assertEqual(ranked[0]["row"]["sku"], "CW-K03-37")
        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("推荐轻便水具", stove))
        self.assertTrue(customer_recommendation_ranker.is_obvious_product_type_mismatch("推荐轻便水具", pot))
        self.assertFalse(customer_recommendation_ranker.is_obvious_product_type_mismatch("推荐轻便水具", kettle))

    def test_negated_pot_request_with_water_target_prefers_water_gear(self):
        cup = {"sku": "TW-502", "product_name_cn": "悦享杯套装", "category": "水具", "capacity": "350ml", "features": "轻量徒步，露营饮水"}
        pot = {"sku": "CW-C93", "product_name_cn": "行山单锅", "category": "锅具", "capacity": "锅 1000ML", "features": "轻量徒步"}

        ranked = customer_recommendation_ranker.fallback_rank(
            [pot, cup],
            "不要锅，推荐轻便水具",
        )

        self.assertEqual(ranked[0]["row"]["sku"], "TW-502")


if __name__ == "__main__":
    unittest.main()
