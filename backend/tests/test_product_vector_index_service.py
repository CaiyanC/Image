import unittest
import asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.knowledge_base import KnowledgeChunk, KnowledgeDocument
from app.models.product import Product
from app.models.product_specs import ProductSpecs
from app.services import product_vector_index_service
from app.services.product_vector_index_service import build_product_documents, should_create_ivfflat_index
from scripts.apply_product_specs_review_ledger import apply_ledger


class ProductVectorIndexServiceTest(unittest.TestCase):
    def test_should_create_ivfflat_index_only_for_supported_vector_dimensions(self):
        self.assertTrue(should_create_ivfflat_index(1536))
        self.assertTrue(should_create_ivfflat_index(2000))
        self.assertFalse(should_create_ivfflat_index(4096))
        self.assertFalse(should_create_ivfflat_index(None))

    def test_embed_pending_chunks_can_be_scoped_to_one_sku(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add_all([
                KnowledgeDocument(
                    id="doc-a", source_type="product", source_id="product:A:profile",
                    sku="A", title="A", content="A",
                ),
                KnowledgeDocument(
                    id="doc-b", source_type="product", source_id="product:B:profile",
                    sku="B", title="B", content="B",
                ),
                KnowledgeChunk(
                    id="chunk-a", document_id="doc-a", sku="A", source_type="product",
                    chunk_index=0, content="A pending",
                ),
                KnowledgeChunk(
                    id="chunk-b", document_id="doc-b", sku="B", source_type="product",
                    chunk_index=0, content="B pending",
                ),
            ])
            db.commit()

            with patch.object(
                product_vector_index_service.dmxapi_service,
                "create_embedding",
                new=AsyncMock(side_effect=RuntimeError("stop after selection")),
            ) as create_embedding:
                result = asyncio.run(
                    product_vector_index_service.embed_pending_chunks(db, sku="a")
                )

            self.assertEqual(result["total"], 1)
            self.assertEqual(create_embedding.await_count, 1)
            self.assertEqual(create_embedding.await_args.args[1], "A pending")
            self.assertEqual(db.get(KnowledgeChunk, "chunk-a").embedding_status, "failed")
            self.assertIsNone(db.get(KnowledgeChunk, "chunk-b").embedding_error)
            self.assertNotEqual(db.get(KnowledgeChunk, "chunk-b").embedding_status, "failed")
        finally:
            db.close()

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
                "long_description_en": "Lightweight design with effortless clean up.",
                "listing_en": "Easy to clean after outdoor cooking.",
            },
            "qa_items": [
                {"id": "qa-1", "question": "能泡咖啡吗？", "answer": "可以。", "priority": 1, "integrity_status": "approved"}
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
                "product:CS-G25:recommendation",
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
        recommendation = next(
            doc for doc in docs
            if doc["source_id"] == "product:CS-G25:recommendation"
        )
        self.assertIn("商品名称: 小青炉", recommendation["content"])
        self.assertIn("商品类目: 炉具", recommendation["content"])
        self.assertIn("使用场景: 露营泡咖啡", recommendation["content"])
        self.assertIn("英文描述: Lightweight design with effortless clean up.", recommendation["content"])
        self.assertIn("英文 Listing: Easy to clean after outdoor cooking.", recommendation["content"])
        self.assertEqual(
            recommendation["metadata"]["retrieval_role"],
            "recommendation_candidate_recall",
        )
        self.assertFalse(recommendation["metadata"]["fact_authority"])

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

        self.assertEqual(
            [doc["source_id"] for doc in docs],
            ["product:TW-141:recommendation", "product:TW-141:profile"],
        )
        self.assertIn("烽宴多功能聚能套锅", docs[0]["content"])

    def test_build_product_documents_excludes_cross_category_usage_instruction(self):
        detail = {
            "sku": "POT-100",
            "product_name_cn": "Camping moka pot",
            "product_name_en": "Moka pot",
            "category": "coffee equipment",
            "specs": {
                "usage_instruction": "Adjust grind size and clean grinder burrs after use.",
            },
            "business": {},
            "content": {},
            "qa_items": [],
            "qa_negative": None,
        }

        docs = build_product_documents(detail)
        profile = next(
            doc for doc in docs
            if doc["source_id"] == "product:POT-100:profile"
        )

        self.assertNotIn("grind size", profile["content"])
        self.assertNotIn("grinder burrs", profile["content"])

    def test_build_product_documents_keeps_grinder_usage_instruction(self):
        detail = {
            "sku": "GRINDER-100",
            "product_name_cn": "Travel coffee grinder",
            "category": "coffee equipment",
            "specs": {
                "usage_instruction": "Adjust grind size and clean grinder burrs after use.",
            },
            "business": {},
            "content": {},
            "qa_items": [],
            "qa_negative": None,
        }

        docs = build_product_documents(detail)
        profile = next(
            doc for doc in docs
            if doc["source_id"] == "product:GRINDER-100:profile"
        )

        self.assertIn("grind size", profile["content"])
        self.assertIn("grinder burrs", profile["content"])

    def test_index_product_marks_product_as_synced(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add(Product(
                id="product-1",
                sku="CS-G25",
                barcode="barcode-CS-G25",
                product_name_cn="Mini stove",
                brand="alocs",
                sync_flag=False,
            ))
            db.commit()
            detail = {
                "sku": "CS-G25",
                "product_name_cn": "Mini stove",
                "brand": "alocs",
                "specs": {},
                "business": {},
                "content": {},
                "qa_items": [],
                "qa_negative": None,
            }

            with patch("app.services.product_service.get_product_detail", return_value=detail):
                result = product_vector_index_service.index_product(db, "CS-G25")

            db.expire_all()
            product = db.query(Product).filter(Product.sku == "CS-G25").first()
            self.assertEqual(result["chunks"], 2)
            self.assertTrue(product.sync_flag)
        finally:
            db.close()

    def test_index_product_replaces_stale_chunks_and_removed_qa_documents(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add(Product(
                id="product-update-1",
                sku="UPDATE-1",
                barcode="barcode-update-1",
                product_name_cn="更新测试锅",
                brand="alocs",
                sync_flag=False,
            ))
            db.commit()
            original_detail = {
                "sku": "UPDATE-1",
                "product_name_cn": "更新测试锅",
                "brand": "alocs",
                "category": "锅具",
                "specs": {"capacity": "900ML"},
                "business": {"usage_scenarios": ["旧场景"]},
                "content": {"long_description_cn": "旧版商品描述"},
                "qa_items": [{
                    "id": "qa-removed",
                    "question": "旧问题？",
                    "answer": "旧答案。",
                    "priority": 1,
                    "integrity_status": "approved",
                }],
                "qa_negative": None,
            }
            updated_detail = {
                **original_detail,
                "specs": {"capacity": "1400ML"},
                "business": {"usage_scenarios": ["双人露营"]},
                "content": {"long_description_cn": "新版商品描述"},
                "qa_items": [],
            }

            with patch(
                "app.services.product_service.get_product_detail",
                side_effect=[original_detail, updated_detail],
            ):
                product_vector_index_service.index_product(db, "UPDATE-1")
                product_vector_index_service.index_product(db, "UPDATE-1")

            documents = db.query(KnowledgeDocument).filter(
                KnowledgeDocument.sku == "UPDATE-1",
                KnowledgeDocument.source_type == "product",
            ).all()
            chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.sku == "UPDATE-1",
                KnowledgeChunk.source_type == "product",
            ).all()
            combined = "\n".join(chunk.content for chunk in chunks)

            self.assertNotIn("product:UPDATE-1:qa:qa-removed", {doc.source_id for doc in documents})
            self.assertNotIn("旧场景", combined)
            self.assertNotIn("旧版商品描述", combined)
            self.assertNotIn("900ML", combined)
            self.assertIn("双人露营", combined)
            self.assertIn("新版商品描述", combined)
            self.assertIn("1400ML", combined)
            self.assertTrue(chunks)
            self.assertTrue(all(chunk.embedding_status == "pending" for chunk in chunks))
        finally:
            db.close()

    def test_specs_review_ledger_rejects_duplicate_sku(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__, ProductSpecs.__table__])
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            db.add(Product(id="ledger-product", sku="LEDGER-100", barcode="ledger-barcode", product_name_cn="test", brand="alocs"))
            db.add(ProductSpecs(product_id="ledger-product", usage_instruction="original"))
            db.commit()

            with self.assertRaisesRegex(ValueError, "invalid"):
                apply_ledger(db, [
                    {"sku": "LEDGER-100", "field": "usage_instruction", "value": "", "reason": "reviewed"},
                    {"sku": "LEDGER-100", "field": "usage_instruction", "value": "", "reason": "duplicate"},
                ])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
