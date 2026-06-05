import unittest

from app.services.product_service import _normalize_size_info


class ProductServiceSizeInfoTest(unittest.TestCase):
    def test_extracts_unit_from_single_unit_dimensions(self):
        result = _normalize_size_info([
            {"unit": "", "label": "展开尺寸(带手柄)", "value": "36.5*28.6*6cm"},
            {"unit": "", "label": "煎锅", "value": "φ28.6*6cm"},
            {"unit": "", "label": "展开尺寸", "value": "15.2×11.7cm"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "36.5*28.6*6")
        self.assertEqual(result[1]["unit"], "cm")
        self.assertEqual(result[1]["value"], "φ28.6*6")
        self.assertEqual(result[2]["unit"], "cm")
        self.assertEqual(result[2]["value"], "15.2×11.7")

    def test_keeps_mixed_unit_dimensions_in_value(self):
        raw_value = "9.5x6.7mm（炉体）+12×13.4cm（炉架）"

        result = _normalize_size_info([
            {"unit": "", "label": "收纳尺寸", "value": raw_value},
        ])

        self.assertEqual(result[0]["unit"], "")
        self.assertEqual(result[0]["value"], raw_value)

    def test_preserves_existing_unit(self):
        result = _normalize_size_info([
            {"unit": "cm", "label": "展开尺寸", "value": "36.5*28.6*6"},
        ])

        self.assertEqual(result[0]["unit"], "cm")
        self.assertEqual(result[0]["value"], "36.5*28.6*6")


if __name__ == "__main__":
    unittest.main()
