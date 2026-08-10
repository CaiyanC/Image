from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "full_regression_runner.py"
SPEC = importlib.util.spec_from_file_location("full_regression_runner", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

def _multiturn_issue(sequence: dict, records: list[dict], _sku_lookup: dict) -> tuple[str, str]:
    """Small, versioned oracle for the supplemental follow-up regression cases."""
    if not records or any(record.get("status") != 200 for record in records):
        return "fail", "request_error"
    kind = str(sequence.get("kind") or "")
    first_skus = list(records[0].get("result_skus") or [])
    if kind == "single_followup":
        if len(records) < 2 or not first_skus or first_skus[0] not in (records[1].get("result_skus") or []):
            return "fail", "pronoun_error"
    if kind == "ordinal_followup":
        if len(records) < 2 or not first_skus or first_skus[0] not in (records[1].get("result_skus") or []):
            return "fail", "ordinal_error"
    return "pass", "ok"


class FullRegressionRunnerTest(unittest.TestCase):
    def _sample_inventory(self) -> dict:
        products = []
        categories = [
            "锅具",
            "配件",
            "炉具",
            "餐具",
            "水具",
            "水壶",
            "天幕/地垫/帐篷",
            "桌椅",
            "咖啡器具",
            "茶具",
        ]
        special_skus = [
            "CW-C83",
            "CW-C06PRO",
            "CW-C78",
            "CW-C19T-37",
            "CW-C69-1",
            "CW-C93",
            "CW-C76",
            "CS-G25",
            "CS-G18-28",
            "TW-422-蓝",
            "TW-422-绿",
            "TW-422-粉",
            "KW-K31-白",
            "KW-K31-黑",
            "KW-K32-白",
            "KW-K32-黑",
            "CT-T04(BM)",
            "CW-C65-4",
            "GX14-230G",
            "GX15-450G",
            "TW-139",
            "TW-503",
            "CW-C97",
            "AC-Z07",
            "CS-B14",
            "CS-B14（LX）",
            "CB254",
            "CF-PG19",
            "CF-PG11-42",
            "CW-C65-3",
            "CW-C65-5",
            "CW-C70",
            "CW-C71",
            "CW-C99",
            "CW-C85-A",
            "TW-141",
            "CS-G25-B",
        ]
        for index, sku in enumerate(special_skus):
            category = categories[index % len(categories)]
            products.append(
                {
                    "sku": sku,
                    "name": f"{category}样品{index}",
                    "category": category,
                    "sub_category": "",
                    "capacity": "1L",
                    "material": "铝合金",
                    "weight_g": 500.0 + index,
                    "heat_source": "明火 卡式炉 酒精炉" if "CW-C" in sku else "明火 卡式炉",
                    "size_info": "20cm",
                    "usage_instruction": "可装冷水 适合烧水 随身补水",
                    "usage_scenarios": "露营 野餐 徒步 自驾",
                }
            )
        for index in range(80):
            category = categories[index % len(categories)]
            products.append(
                {
                    "sku": f"EX-{index:03d}",
                    "name": f"{category}扩展样品{index}",
                    "category": category,
                    "sub_category": "",
                    "capacity": "900ml",
                    "material": "不锈钢",
                    "weight_g": 300.0 + index,
                    "heat_source": "明火 卡式炉",
                    "size_info": "18cm",
                    "usage_instruction": "可装冷水",
                    "usage_scenarios": "露营 野餐",
                }
            )
        return {"total_products": len(products), "products": products}

    def test_build_medium_plan_matches_requested_scale(self):
        plan = MODULE.build_medium_plan(self._sample_inventory())

        self.assertEqual(plan["coverage"]["single_turn"], 200)
        self.assertEqual(plan["coverage"]["multiturn_sequences"], 20)
        self.assertEqual(plan["coverage"]["endpoint_parity"], 30)
        self.assertEqual(plan["coverage"]["explicit_sku_field_matrix"], 30)
        self.assertGreaterEqual(plan["coverage"]["total_requests"], 290)
        self.assertEqual(len(plan["explicit_matrix_skus"]), 30)
        self.assertNotIn("q07", {case["case_id"] for case in plan["single_turn_cases"]})
        self.assertIn("cat_1_list", {case["case_id"] for case in plan["single_turn_cases"]})
        matrix_cases = [case for case in plan["single_turn_cases"] if case["group"] == "explicit_sku_field_matrix"]
        self.assertEqual(len(matrix_cases), 90)

    def test_build_large_plan_matches_requested_scale_and_keeps_unicode_safe_q07(self):
        plan = MODULE.build_large_plan(self._sample_inventory())

        self.assertGreaterEqual(plan["coverage"]["single_turn"], 500)
        self.assertGreaterEqual(plan["coverage"]["multiturn_sequences"], 50)
        self.assertGreaterEqual(plan["coverage"]["endpoint_parity"], 50)
        self.assertGreaterEqual(plan["coverage"]["explicit_sku_field_matrix"], 50)
        self.assertGreaterEqual(plan["coverage"]["total_requests"], 700)
        self.assertIn("CS-B14（LX）", plan["explicit_matrix_skus"])

        q07 = next(case for case in plan["special_cases"] if case["case_id"] == "q07")
        self.assertEqual(q07["question"], "CW-C83 能不能用酒精炉？如果不能就别推荐错了。")
        self.assertNotIn("?", q07["question"])
        self.assertEqual(q07["expected"]["explicit_sku"], "CW-C83")
        self.assertEqual(q07["expected"]["requested_field"], "heat_source")

    def test_water_bag_matrix_question_uses_water_usage_semantics(self):
        item = MODULE.BASE.InventoryItem(
            sku="AC-19",
            name="\u7a33\u7a33\u6c34\u888b",
            category="\u914d\u4ef6",
            sub_category="",
            capacity="8L",
            material="",
            weight_g=150.0,
            heat_source="/",
            size_info="",
            usage_instruction="",
            usage_scenarios="\u9732\u8425\u50a8\u6c34",
        )

        question, requested_field = MODULE._field_question(item, 2)

        self.assertEqual(requested_field, "water_usage")
        self.assertIn("\u70e7\u6c34", question)

    def test_parity_starts_stream_context_before_ask_context(self):
        calls = []
        case = {
            "case_id": "parity_case",
            "question": "parity question",
        }

        def fake_ask(_token, _question, conversation_id, **kwargs):
            calls.append(("ask", conversation_id, kwargs.get("parity_isolation")))
            return {
                "status": 200,
                "conversation_id": "ask-conversation",
                "answer": "same answer",
                "answer_type": "recommendation",
                "intent": "recommendation",
                "result_skus": ["SKU-ASK"],
            }

        def fake_stream(_token, _question, conversation_id, **kwargs):
            calls.append(("stream", conversation_id, kwargs.get("parity_isolation")))
            return {
                "status": 200,
                "conversation_id": "stream-conversation",
                "answer": "same answer",
                "answer_type": "recommendation",
                "intent": "recommendation",
                "result_skus": ["SKU-STREAM"],
            }

        with patch.object(MODULE.BASE, "ask", side_effect=fake_ask), patch.object(
            MODULE.BASE, "ask_stream", side_effect=fake_stream
        ):
            report = MODULE._run_parity_case("token", case)

        self.assertEqual(calls[:2], [("stream", None, True), ("ask", None, True)])
        self.assertNotEqual(report["ask"]["conversation_id"], report["stream"]["conversation_id"])

    def test_breakfast_griddle_scenario_expects_cookware_domain(self):
        case = next(item for item in MODULE.SCENARIO_CASES if item[0] == "scene_007")

        self.assertEqual(case[2], "\u9505\u5177")

    def test_transport_exhaustion_is_runtime_warning_not_business_failure(self):
        case = {
            "case_id": "transport_case",
            "group": "scenario_recommendation",
            "question": "transport question",
            "expected": {"expected_domain": "\u9505\u5177"},
        }
        record = {
            "case_id": case["case_id"],
            "question": case["question"],
            "status": 599,
            "answer": "",
            "answer_type": "",
            "result_skus": [],
            "transport_exhausted": True,
            "warnings": ["transport_error"],
        }

        classified = MODULE._classify_single_turn(case, record, {})

        self.assertEqual(classified["judgement"], "warning")
        self.assertEqual(classified["audited_attribution"], "runtime_noise")
        self.assertIn("transport_error", classified["issues"])

    def test_summarize_timing_stats_computes_percentiles_and_slow_buckets(self):
        stats = MODULE.summarize_timing_stats(
            [
                {"case_id": "a", "duration_ms": 1000, "answer_type": "product_detail", "llm_call_count": 0},
                {"case_id": "b", "duration_ms": 25000, "answer_type": "recommendation", "llm_call_count": 0},
                {"case_id": "c", "duration_ms": 35000, "answer_type": "recommendation", "llm_call_count": 1},
                {"case_id": "d", "duration_ms": 65000, "answer_type": "query_products", "llm_call_count": 0},
            ]
        )

        self.assertEqual(stats["slow_20s_count"], 3)
        self.assertEqual(stats["slow_30s_count"], 2)
        self.assertEqual(stats["slow_60s_count"], 1)
        self.assertEqual(stats["max"], 65000)
        self.assertEqual(stats["llm_call_count_distribution"]["0"], 3)
        self.assertEqual(stats["llm_call_count_distribution"]["1"], 1)
        self.assertEqual(stats["top_10_slowest"][0]["case_id"], "d")

    def test_summarize_explicit_matrix_counts_fail_modes(self):
        summary = MODULE.summarize_explicit_matrix(
            [
                {"judgement": "pass", "mismatch": False, "kb_fallback": False, "empty_answer": False, "field_wrong": False, "slow": False},
                {"judgement": "warning", "mismatch": False, "kb_fallback": True, "empty_answer": False, "field_wrong": False, "slow": False},
                {"judgement": "fail", "mismatch": True, "kb_fallback": False, "empty_answer": False, "field_wrong": True, "slow": True, "case_id": "sku_bad"},
            ]
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["pass"], 1)
        self.assertEqual(summary["warning"], 1)
        self.assertEqual(summary["fail"], 1)
        self.assertEqual(summary["mismatch"], 1)
        self.assertEqual(summary["kb_fallback"], 1)
        self.assertEqual(summary["field_wrong"], 1)
        self.assertEqual(summary["slow"], 1)
        self.assertEqual(summary["top_failures"][0]["case_id"], "sku_bad")

    def test_field_alias_normalization_accepts_cn_and_en_equivalents(self):
        self.assertEqual(MODULE.normalize_field_label("material"), "material")
        self.assertEqual(MODULE.normalize_field_label("材质"), "material")
        self.assertEqual(MODULE.normalize_field_label("热源"), "heat_source")
        self.assertEqual(MODULE.normalize_field_label("酒精炉"), "alcohol_stove")
        self.assertEqual(MODULE.normalize_field_label("随身补水"), "hydration")

    def test_compound_field_judgement_does_not_fail_when_answer_covers_expected_semantics(self):
        case = {
            "case_id": "matrix_CW-C83_1",
            "group": "explicit_sku_field_matrix",
            "question": "CW-C83 是什么材质？容量多大？",
            "expected": {
                "explicit_sku": "CW-C83",
                "requested_field": "material_capacity",
            },
        }
        record = {
            "case_id": "matrix_CW-C83_1",
            "question": case["question"],
            "conversation_id": "conv-1",
            "answer_type": "product_detail",
            "intent": "product_detail",
            "result_skus": ["CW-C83"],
            "answer": "炊墨套锅（CW-C83）的材质是硬质氧化铝合金，容量约 2L。",
            "warnings": [],
            "debug_plan": {"product_ref": "CW-C83", "requested_field": "材质"},
            "debug_trace": {},
            "duration_ms": 12.0,
            "llm_call_count": 0,
            "status": 200,
        }

        classified = MODULE._classify_explicit_matrix(case, record)

        self.assertEqual(classified["judgement"], "pass")
        self.assertFalse(classified["field_wrong"])
        self.assertFalse(classified["field_alias_mismatch"])
        self.assertFalse(classified["compound_field_overstrict"])

    def test_alias_mismatch_only_warns_when_answer_semantics_are_present(self):
        case = {
            "case_id": "matrix_CW-C83_3",
            "group": "explicit_sku_field_matrix",
            "question": "CW-C83 适合什么场景？能不能用酒精炉？",
            "expected": {
                "explicit_sku": "CW-C83",
                "requested_field": "scene_alcohol_stove",
            },
        }
        record = {
            "case_id": "matrix_CW-C83_3",
            "question": case["question"],
            "conversation_id": "conv-1",
            "answer_type": "product_detail",
            "intent": "product_detail",
            "result_skus": ["CW-C83"],
            "answer": "当前资料未显示支持酒精炉，适用热源为明火直烧、燃气炉、卡式炉、电磁炉。",
            "warnings": [],
            "debug_plan": {"product_ref": "CW-C83", "requested_field": "heat_source"},
            "debug_trace": {},
            "duration_ms": 18.0,
            "llm_call_count": 0,
            "status": 200,
        }

        classified = MODULE._classify_explicit_matrix(case, record)

        self.assertEqual(classified["judgement"], "warning")
        self.assertTrue(classified["field_alias_mismatch"])
        self.assertFalse(classified["field_wrong"])


    def test_missing_requested_field_with_semantic_answer_downgrades_to_runner_noise_warning(self):
        case = {
            "case_id": "matrix_CW-C83_missing_field",
            "group": "explicit_sku_field_matrix",
            "question": "CW-C83 \u5bb9\u91cf\u591a\u5927\uff1f",
            "expected": {
                "explicit_sku": "CW-C83",
                "requested_field": "capacity",
            },
        }
        record = {
            "case_id": "matrix_CW-C83_missing_field",
            "question": case["question"],
            "conversation_id": "conv-1",
            "answer_type": "product_detail",
            "intent": "product_detail",
            "result_skus": ["CW-C83"],
            "answer": "CW-C83 \u5bb9\u91cf\u7ea62L\u3002",
            "warnings": [],
            "debug_plan": {"product_ref": "CW-C83", "requested_field": ""},
            "debug_trace": {},
            "duration_ms": 9.0,
            "llm_call_count": 0,
            "status": 200,
        }

        classified = MODULE._classify_explicit_matrix(case, record)

        self.assertEqual(classified["judgement"], "warning")
        self.assertEqual(classified["audited_attribution"], "runner_noise")
        self.assertIn("missing_requested_field_warning", classified["issues"])
        self.assertFalse(classified["field_wrong"])

    def test_missing_requested_field_without_semantic_answer_is_true_field_wrong(self):
        case = {
            "case_id": "matrix_CW-C83_missing_wrong",
            "group": "explicit_sku_field_matrix",
            "question": "CW-C83 \u5bb9\u91cf\u591a\u5927\uff1f",
            "expected": {
                "explicit_sku": "CW-C83",
                "requested_field": "capacity",
            },
        }
        record = {
            "case_id": "matrix_CW-C83_missing_wrong",
            "question": case["question"],
            "conversation_id": "conv-1",
            "answer_type": "product_detail",
            "intent": "product_detail",
            "result_skus": ["CW-C83"],
            "answer": "CW-C83 \u91c7\u7528\u786c\u8d28\u6c27\u5316\u94dd\u5408\u91d1\u3002",
            "warnings": [],
            "debug_plan": {"product_ref": "CW-C83", "requested_field": ""},
            "debug_trace": {},
            "duration_ms": 9.0,
            "llm_call_count": 0,
            "status": 200,
        }

        classified = MODULE._classify_explicit_matrix(case, record)

        self.assertEqual(classified["judgement"], "fail")
        self.assertEqual(classified["audited_attribution"], "real_business")
        self.assertIn("field_wrong", classified["issues"])
        self.assertTrue(classified["field_wrong"])

    def test_explicit_matrix_supports_legacy_field_key(self):
        case = {
            "case_id": "matrix_CW-C83_legacy_field",
            "group": "explicit_sku_field_matrix",
            "question": "CW-C83 \u6750\u8d28\u662f\u4ec0\u4e48\uff1f",
            "expected": {
                "explicit_sku": "CW-C83",
                "field": "material",
            },
        }
        record = {
            "case_id": "matrix_CW-C83_legacy_field",
            "question": case["question"],
            "conversation_id": "conv-1",
            "answer_type": "product_detail",
            "intent": "product_detail",
            "result_skus": ["CW-C83"],
            "answer": "CW-C83 \u6750\u8d28\u662f\u786c\u8d28\u6c27\u5316\u94dd\u5408\u91d1\u3002",
            "warnings": [],
            "debug_plan": {"product_ref": "CW-C83", "requested_field": ""},
            "debug_trace": {},
            "duration_ms": 8.0,
            "llm_call_count": 0,
            "status": 200,
        }

        classified = MODULE._classify_explicit_matrix(case, record)

        self.assertEqual(classified["judgement"], "warning")
        self.assertIn("missing_requested_field_warning", classified["issues"])
        self.assertEqual(classified["expected_field"], "material")

    def test_stove_expected_domain_is_downgraded_for_pot_question_shape(self):
        sku_lookup = {
            "CW-C06PRO": type(
                "Item",
                (),
                {"sku": "CW-C06PRO", "name": "\u8f7b\u9014\u5957\u9505", "category": "\u9505\u5177", "sub_category": ""},
            )()
        }
        case = {
            "case_id": "scene_x048",
            "group": "scenario_recommendation",
            "question": "\u5973\u751f\u4e00\u4e2a\u4eba\u5468\u672b\u51fa\u6e38\uff0c\u60f3\u9009\u4e2a\u80fd\u70e7\u6c34\u7684\u8f7b\u91cf\u9505\u3002",
            "expected": {"expected_domain": "\u7089\u5177"},
        }
        record = {
            "case_id": "scene_x048",
            "question": case["question"],
            "answer_type": "recommendation",
            "result_skus": ["CW-C06PRO"],
            "answer": "\u9996\u9009\u8f7b\u91cf\u9505\u5177 CW-C06PRO\u3002",
            "duration_ms": 120.0,
        }

        classified = MODULE._classify_single_turn(case, record, sku_lookup)

        self.assertEqual(classified["judgement"], "warning")
        self.assertEqual(classified["audited_attribution"], "runner_noise")
        self.assertIn("scenario_expected_domain_overstrict", classified["issues"])

    def test_true_stove_question_still_fails_when_top_sku_drifts_to_water_domain(self):
        sku_lookup = {
            "CB253": type(
                "Item",
                (),
                {"sku": "CB253", "name": "\u805a\u80fd\u73af\u6c34\u58f6", "category": "\u6c34\u5177", "sub_category": ""},
            )()
        }
        case = {
            "case_id": "scene_x023",
            "group": "scenario_recommendation",
            "question": "\u4e24\u4e2a\u4eba\u6d77\u8fb9\u9732\u8425\uff0c\u98ce\u5927\u4e00\u70b9\uff0c\u7089\u5177\u8be5\u600e\u4e48\u9009\uff1f",
            "expected": {"expected_domain": "\u7089\u5177"},
        }
        record = {
            "case_id": "scene_x023",
            "question": case["question"],
            "answer_type": "recommendation",
            "result_skus": ["CB253"],
            "answer": "\u9996\u9009\u805a\u80fd\u73af\u6c34\u58f6 CB253\u3002",
            "duration_ms": 120.0,
        }

        classified = MODULE._classify_single_turn(case, record, sku_lookup)

        self.assertEqual(classified["judgement"], "fail")
        self.assertEqual(classified["audited_attribution"], "real_business")
        self.assertIn("recommendation_wrong_domain", classified["issues"])

    def test_supplemental_constraint_followup_passes_for_negative_alternative_same_domain(self):
        sequence = {"sequence_id": "mt_var_09", "kind": "constraint_followup"}
        records = [
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t1",
                "answer_type": "recommendation",
                "question": "双人露营想买套轻便锅具。",
                "result_skus": ["CW-C01-37", "TW-141"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t2",
                "answer_type": "recommendation",
                "question": "不要刚才那个，换一个更轻的。",
                "result_skus": ["TW-141", "CW-C19T-37"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t3",
                "answer_type": "recommendation",
                "question": "再给我一个稍微便宜点的。",
                "result_skus": ["CW-C19T-37", "CW-C73"],
            },
        ]
        sku_lookup = {
            "CW-C01-37": {"category": "锅具"},
            "TW-141": {"category": "锅具"},
            "CW-C19T-37": {"category": "锅具"},
            "CW-C73": {"category": "锅具"},
        }

        judgement, reason = _multiturn_issue(sequence, records, sku_lookup)

        self.assertEqual((judgement, reason), ("pass", "ok"))

    def test_supplemental_single_followup_still_requires_same_top_sku(self):
        sequence = {"sequence_id": "q15_like", "kind": "single_followup"}
        records = [
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t1",
                "answer_type": "recommendation",
                "question": "我一个人徒步，推荐个轻便锅。",
                "result_skus": ["CW-C06PRO", "CW-C65-2"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t2",
                "answer_type": "product_detail",
                "question": "这个可以配酒精炉吗？",
                "result_skus": ["CW-C65-2"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t3",
                "answer_type": "recommendation",
                "question": "不能的话有没有更合适的？",
                "result_skus": ["CW-C65-2"],
            },
        ]

        judgement, reason = _multiturn_issue(sequence, records, {})

        self.assertEqual((judgement, reason), ("fail", "pronoun_error"))

    def test_supplemental_ordinal_followup_still_requires_ordered_skus(self):
        sequence = {"sequence_id": "ordinal_like", "kind": "ordinal_followup"}
        records = [
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t1",
                "answer_type": "recommendation",
                "question": "推荐几款适合家庭露营的锅具。",
                "result_skus": ["CW-C01-37", "TW-141", "CW-C19T-37"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t2",
                "answer_type": "product_detail",
                "question": "第一个能不能用酒精炉？",
                "result_skus": ["TW-141"],
            },
            {
                "status": 200,
                "is_kb_fallback": False,
                "answer": "t3",
                "answer_type": "product_detail",
                "question": "第二个容量多大？",
                "result_skus": ["CW-C19T-37"],
            },
        ]

        judgement, reason = _multiturn_issue(sequence, records, {})

        self.assertEqual((judgement, reason), ("fail", "ordinal_error"))


if __name__ == "__main__":
    unittest.main()
