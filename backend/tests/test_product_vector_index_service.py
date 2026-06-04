import unittest

from app.services.product_vector_index_service import build_product_documents, should_create_ivfflat_index


class ProductVectorIndexServiceTest(unittest.TestCase):
    def test_should_create_ivfflat_index_only_for_supported_vector_dimensions(self):
        self.assertTrue(should_create_ivfflat_index(1536))
        self.assertTrue(should_create_ivfflat_index(2000))
        self.assertFalse(should_create_ivfflat_index(4096))
        self.assertFalse(should_create_ivfflat_index(None))

    def test_build_product_documents_includes_core_sections_and_stable_source_ids(self):
        detail = {
            "sku": "CS-G25",
            "product_name_cn": "小青炉",
            "product_name_en": "Mini Stove",
            "brand": "alocs爱路客",
            "category": "炉具",
            "sub_category": "便携炉",
            "specs": {
                "capacity": "300ml",
                "body_material": "不锈钢",
                "technical_advantages": ["防滑条", "聚能"],
            },
            "business": {
                "top_selling_points": ["轻量", "适合露营"],
                "usage_scenarios": ["露营泡咖啡"],
            },
            "content": {
                "title_cn": "户外炉具",
                "search_keywords": ["露营炉", "咖啡"],
            },
            "qa_items": [
                {"id": "qa-1", "question": "能泡咖啡吗？", "answer": "可以。", "priority": 1}
            ],
            "qa_negative": {
                "id": "neg-1",
                "high_freq_negative_words": "不好清洗",
                "response_tone": "耐心解释",
            },
            "keywords": [{"keyword": "露营"}, {"keyword": "咖啡"}],
            "channels": [{"channel_name": "Amazon"}],
            "regions": [{"region_name": "北美"}],
            "certifications": [{"certification_name": "FDA"}],
        }

        docs = build_product_documents(detail)

        source_ids = {doc["source_id"] for doc in docs}
        self.assertEqual(
            source_ids,
            {
                "product:CS-G25:profile",
                "product:CS-G25:content",
                "product:CS-G25:qa:qa-1",
                "product:CS-G25:qa_negative:neg-1",
            },
        )
        combined = "\n".join(doc["content"] for doc in docs)
        self.assertIn("SKU: CS-G25", combined)
        self.assertIn("容量: 300ml", combined)
        self.assertIn("技术优势: 防滑条, 聚能", combined)
        self.assertIn("使用场景: 露营泡咖啡", combined)
        self.assertIn("关键词: 露营, 咖啡", combined)
        self.assertIn("Q: 能泡咖啡吗？", combined)

    def test_build_product_documents_skips_empty_optional_documents(self):
        detail = {
            "sku": "TW-141",
            "product_name_cn": "烽宴多功能聚能套锅",
            "product_name_en": "",
            "brand": "alocs爱路客",
            "specs": {},
            "business": {},
            "content": {},
            "qa_items": [],
            "qa_negative": None,
        }

        docs = build_product_documents(detail)

        self.assertEqual([doc["source_id"] for doc in docs], ["product:TW-141:profile"])
        self.assertIn("烽宴多功能聚能套锅", docs[0]["content"])


if __name__ == "__main__":
    unittest.main()
