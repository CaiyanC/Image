from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "dev_large_business_probe.py"
SPEC = importlib.util.spec_from_file_location("dev_large_business_probe", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DevLargeBusinessProbeTest(unittest.TestCase):
    def _sample_inventory(self) -> dict:
        categories = [
            "套锅", "单锅", "水壶", "烤盘", "炉具",
            "餐具", "杯具", "收纳", "配件", "咖啡器具",
        ]
        products = []
        for index in range(60):
            category = categories[index % len(categories)]
            sku = f"CW-T{index:03d}" if category != "配件" else f"AC-T{index:03d}"
            name = f"{category}样品{index}"
            if category == "水壶":
                name = f"水壶样品{index}"
            products.append(
                {
                    "sku": sku,
                    "name": name,
                    "category": category,
                    "sub_category": "",
                    "capacity": "1L",
                    "material": "铝合金",
                    "weight_g": 500.0,
                    "heat_source": "明火、卡式炉",
                    "size_info": "20cm",
                    "usage_instruction": "可装冷水和饮用水；适合营地烧水",
                    "usage_scenarios": "露营、野餐",
                }
            )
        return {
            "total_products": len(products),
            "products": products,
            "categories": [{"category": category, "count": 6} for category in categories],
        }

    def test_request_with_rate_limit_retry_retries_429_until_success(self):
        calls = []
        sleeps = []
        responses = [
            {"status": 429, "judgement": "blocking", "attribution": "HTTP error"},
            {"status": 429, "judgement": "blocking", "attribution": "HTTP error"},
            {"status": 200, "judgement": "pass", "attribution": "ok"},
        ]

        def send_request():
            calls.append(len(calls))
            return responses[len(calls) - 1]

        result = MODULE.request_with_rate_limit_retry(
            send_request,
            max_retries=2,
            backoff_seconds=1.0,
            sleep_fn=sleeps.append,
        )

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["rate_limit_retries"], 2)
        self.assertFalse(result["rate_limit_exhausted"])
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_request_with_rate_limit_retry_recovers_from_connection_reset(self):
        calls = []
        sleeps = []

        def send_request():
            calls.append(len(calls))
            if len(calls) == 1:
                raise ConnectionResetError("worker restarted")
            return {"status": 200, "judgement": "pass", "attribution": "ok"}

        result = MODULE.request_with_rate_limit_retry(
            send_request,
            max_retries=2,
            backoff_seconds=1.0,
            sleep_fn=sleeps.append,
        )

        self.assertEqual(result["status"], 200)
        self.assertEqual(result["transport_retries"], 1)
        self.assertEqual(result["rate_limit_retries"], 0)
        self.assertEqual(sleeps, [1.0])

    def test_request_with_rate_limit_retry_returns_auditable_transport_error_after_exhaustion(self):
        result = MODULE.request_with_rate_limit_retry(
            lambda: (_ for _ in ()).throw(ConnectionResetError("worker restarted")),
            max_retries=1,
            backoff_seconds=0,
            sleep_fn=lambda _delay: None,
        )

        self.assertEqual(result["status"], 599)
        self.assertEqual(result["transport_retries"], 1)
        self.assertTrue(result["transport_exhausted"])
        self.assertIn("transport_error", result["warnings"])

    def test_request_with_rate_limit_retry_marks_exhausted_after_final_429(self):
        sleeps = []

        result = MODULE.request_with_rate_limit_retry(
            lambda: {"status": 429, "judgement": "blocking", "attribution": "HTTP error"},
            max_retries=2,
            backoff_seconds=0.5,
            sleep_fn=sleeps.append,
        )

        self.assertEqual(result["status"], 429)
        self.assertTrue(result["rate_limit_exhausted"])
        self.assertEqual(result["rate_limit_retries"], 2)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_apply_audited_verdict_reclassifies_429_as_rate_limit_warning(self):
        audited = MODULE.apply_audited_verdict({
            "status": 429,
            "judgement": "blocking",
            "attribution": "HTTP error",
        })

        self.assertEqual(audited["audited_judgement"], "warning")
        self.assertEqual(audited["audited_attribution"], "rate_limit")
        self.assertTrue(audited["runtime_noise"])
        self.assertFalse(audited["business_blocking"])

    def test_summarize_records_keeps_raw_and_audited_counts_separate(self):
        summary = MODULE.summarize_records([
            {"status": 429, "judgement": "blocking", "attribution": "HTTP error"},
            {"status": 200, "judgement": "pass", "attribution": "ok"},
        ])

        self.assertEqual(summary["raw_summary"]["blocking_fail"], 1)
        self.assertEqual(summary["audited_summary"]["rate_limit"], 1)
        self.assertEqual(summary["audited_summary"]["business_blocking"], 0)
        self.assertEqual(summary["audited_summary"]["warning"], 1)

    def test_run_batched_cases_sleeps_between_batches(self):
        sleeps = []
        seen = []
        cases = [{"id": f"case-{index}"} for index in range(5)]

        def runner(case):
            seen.append(case["id"])
            return {"status": 200, "judgement": "pass", "attribution": "ok", "id": case["id"]}

        records = MODULE.run_batched_cases(
            cases,
            runner=runner,
            batch_size=2,
            batch_sleep_seconds=1.5,
            sleep_fn=sleeps.append,
        )

        self.assertEqual([item["id"] for item in records], [case["id"] for case in cases])
        self.assertEqual(seen, [case["id"] for case in cases])
        self.assertEqual(sleeps, [1.5, 1.5])

    def test_large_probe_case_plan_rebuilds_386_case_schedule(self):
        plan = MODULE.build_large_probe_case_plan(self._sample_inventory())

        self.assertEqual(len(plan["cases"]), 386)
        self.assertEqual(plan["coverage"]["total_requests"], 386)
        self.assertEqual(plan["coverage"]["sku_covered"], 50)
        self.assertEqual(plan["coverage"]["category_covered"], 10)
        group_counts = MODULE.Counter(case.group for case in plan["cases"])
        self.assertEqual(group_counts["baseline36"], 36)
        self.assertEqual(group_counts["sku_fields"], 150)
        self.assertEqual(group_counts["categories"], 50)
        self.assertEqual(group_counts["scenarios"], 60)
        self.assertEqual(group_counts["compare"], 30)
        self.assertEqual(group_counts["multiturn"], 50)
        self.assertEqual(group_counts["faq"], 10)

    def test_select_parity_cases_keeps_multiturn_context_complete(self):
        plan = MODULE.build_large_probe_case_plan(self._sample_inventory())
        selected = MODULE.select_parity_cases(plan["cases"], limit=30)
        selected_ids = {case.case_id for case in selected}

        self.assertIn("q15_t1", selected_ids)
        self.assertIn("q15_t2", selected_ids)
        self.assertIn("q15_t3", selected_ids)
        self.assertIn("q16_t1", selected_ids)
        self.assertIn("q16_t2", selected_ids)
        self.assertIn("q16_t3", selected_ids)
        for case in selected:
            if case.expected.get("requires_context"):
                previous = f"{case.sequence_id}_t{case.expected['turn_index'] - 1}"
                self.assertIn(previous, selected_ids)

    def test_multiturn_classification_requires_same_conversation_id(self):
        case = MODULE.ProbeCase(
            case_id="mt_001_t2",
            group="multiturn",
            sequence_id="mt_001",
            question="它能不能用酒精炉？",
            tags=("multiturn",),
            expected={"turn_index": 2, "total_turns": 3, "requires_context": True},
        )
        record = {
            "status": 200,
            "answer": "可以继续看上一轮推荐。",
            "answer_type": "product_detail",
            "question": case.question,
            "result_skus": ["CW-C01-37"],
            "sent_conversation_id": "conv-1",
            "conversation_id": "conv-2",
            "timing": {},
            "elapsed_ms_client": 1200,
        }

        judgement, attribution, issues, _data_issue = MODULE.classify_case(case, record, {})

        self.assertEqual(judgement, "fail")
        self.assertEqual(attribution, "real_business")
        self.assertIn("conversation_id_not_reused", issues)

    def test_apply_audited_verdict_keeps_rate_limit_out_of_business_blocking(self):
        record = MODULE.apply_audited_verdict({
            "status": 429,
            "judgement": "blocking",
            "attribution": "HTTP error",
        })

        self.assertEqual(record["audited_attribution"], "rate_limit")
        self.assertEqual(record["audited_judgement"], "warning")
        self.assertFalse(record["business_blocking"])

    def test_category_list_query_products_is_valid_pass(self):
        case = MODULE.ProbeCase(
            case_id="cat_1_list",
            group="categories",
            sequence_id="cat_1_list",
            question="有哪些锅具产品？",
            tags=("category", "catalog"),
            expected={"category": "锅具", "type": "list", "sample_skus": ["CW-C06PRO"]},
        )
        record = {
            "status": 200,
            "answer": "当前匹配到【锅具】类产品共有 37 款。先列前 10 款：CW-C06PRO 轻途套锅。",
            "answer_type": "query_products",
            "result_skus": ["CW-C06PRO", "CW-C78"],
            "timing": {},
            "elapsed_ms_client": 1200,
        }

        judgement, attribution, issues, _data_issue = MODULE.classify_case(case, record, {})

        self.assertEqual(judgement, "pass")
        self.assertEqual(attribution, "ok")
        self.assertEqual(issues, [])

    def test_category_list_kb_answer_still_stays_warning(self):
        case = MODULE.ProbeCase(
            case_id="cat_7_list",
            group="categories",
            sequence_id="cat_7_list",
            question="有哪些天幕、地垫、帐篷产品？",
            tags=("category", "catalog"),
            expected={"category": "天幕、地垫、帐篷", "type": "list", "sample_skus": ["OT-187HM"]},
        )
        record = {
            "status": 200,
            "answer": "当然可以。",
            "answer_type": "knowledge_base_answer",
            "result_skus": [],
            "timing": {},
            "elapsed_ms_client": 1200,
        }

        judgement, attribution, issues, _data_issue = MODULE.classify_case(case, record, {})

        self.assertEqual(judgement, "warning")
        self.assertEqual(attribution, "real_business")
        self.assertEqual(issues, ["category_catalog_weak"])


if __name__ == "__main__":
    unittest.main()
