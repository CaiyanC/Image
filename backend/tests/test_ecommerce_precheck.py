import unittest


class EcommercePrecheckContractTest(unittest.TestCase):
    def test_ecommerce_requires_its_original_target_and_source_roles(self):
        from app.services.ecommerce_precheck_service import build_precheck

        result = build_precheck("ecommerce", {"sales_theme_analysis"})

        self.assertFalse(result["can_run"])
        self.assertIn("w27_target", result["missing_required_roles"])
        self.assertNotIn("product_archive", result["missing_required_roles"])
        self.assertIn("product_archive", result["missing_optional_roles"])

    def test_amazon_precheck_passes_only_when_all_original_three_roles_are_present(self):
        from app.services.ecommerce_precheck_service import build_precheck

        result = build_precheck(
            "amazon",
            {"amazon_inventory_target", "amazon_inventory_weekly", "fba_inventory"},
        )

        self.assertTrue(result["can_run"])
        self.assertEqual(result["missing_required_roles"], [])


if __name__ == "__main__":
    unittest.main()
