import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASE_FILE = ROOT / "docs" / "customer_service_regression_cases.json"
RUNNER = ROOT / "scripts" / "customer_service_regression_runner.py"


class CustomerServiceRegressionCasesTest(unittest.TestCase):
    def test_case_file_has_required_launch_coverage(self):
        data = json.loads(CASE_FILE.read_text(encoding="utf-8"))
        cases = data["cases"]
        categories = {case["category"] for case in cases}

        self.assertGreaterEqual(len(cases), 20)
        self.assertTrue({
            "recommendation",
            "context",
            "detail",
            "compare",
            "write_action",
            "data_quality",
            "safety",
            "frontend_experience",
        }.issubset(categories))

    def test_case_ids_are_unique_and_expectations_are_meaningful(self):
        data = json.loads(CASE_FILE.read_text(encoding="utf-8"))
        cases = data["cases"]
        ids = [case["id"] for case in cases]

        self.assertEqual(len(ids), len(set(ids)))
        for case in cases:
            self.assertIsInstance(case.get("turns"), list)
            self.assertGreaterEqual(len(case["turns"]), 1)
            self.assertIsInstance(case.get("expect"), dict)
            self.assertTrue(
                case["expect"].get("answer_must_include_any")
                or case["expect"].get("answer_must_not_include")
                or case["expect"].get("requires_actions") is not None
                or case["expect"].get("min_results") is not None
            )

    def test_runner_dry_run_passes(self):
        completed = subprocess.run(
            [sys.executable, str(RUNNER), "--dry-run"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Dry-run OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
