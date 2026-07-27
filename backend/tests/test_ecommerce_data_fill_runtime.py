import unittest


class EcommerceDataFillRuntimeContractTest(unittest.TestCase):
    def test_runner_exposes_the_three_v1035_workflows(self):
        from app.tool_runtimes.ecommerce_data_fill import runner

        self.assertEqual(set(runner.SUPPORTED_MODES), {"ecommerce", "kepule", "amazon"})


if __name__ == "__main__":
    unittest.main()
