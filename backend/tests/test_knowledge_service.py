import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.knowledge_base import KnowledgeChunk, KnowledgeDocument
from app.models.product import Product
from app.services import knowledge_service


class KnowledgeServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[
            Product.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def test_health_report_surfaces_enterprise_readiness(self):
        self.db.add(Product(
            id="product-1",
            sku="CS-G25",
            barcode="barcode-CS-G25",
            product_name_cn="Mini stove",
            brand="alocs",
            sync_flag=False,
        ))
        self.db.add(Product(
            id="product-2",
            sku="CW-C93",
            barcode="barcode-CW-C93",
            product_name_cn="Solo pot",
            brand="alocs",
            sync_flag=True,
        ))
        doc = KnowledgeDocument(
            id="doc-1",
            source_type="product",
            source_id="product:CS-G25:profile",
            sku="CS-G25",
            title="CS-G25 profile",
            content="CS-G25 camping coffee stove",
        )
        self.db.add(doc)
        self.db.add(KnowledgeChunk(
            id="chunk-1",
            document_id="doc-1",
            sku="CS-G25",
            source_type="product",
            chunk_index=0,
            content="CS-G25 camping coffee stove",
            metadata_json='{"title":"CS-G25 profile"}',
            embedding_status="failed",
            embedding_error="provider error",
        ))
        self.db.commit()

        report = knowledge_service.health_report(self.db)

        self.assertEqual(report["grade"], "critical")
        self.assertEqual(report["totals"]["products"], 2)
        self.assertEqual(report["totals"]["indexed_product_skus"], 1)
        self.assertEqual(report["totals"]["pending_products"], 1)
        self.assertEqual(report["embedding_status_counts"]["failed"], 1)
        self.assertTrue(report["recommendations"])
        self.assertEqual(report["samples"]["failed_chunks"][0]["sku"], "CS-G25")

    def test_search_preview_falls_back_to_keyword_and_preserves_metadata(self):
        doc = KnowledgeDocument(
            id="doc-1",
            source_type="manual",
            source_id="manual:1",
            title="Coffee use",
            content="Camping coffee knowledge",
        )
        self.db.add(doc)
        self.db.add(KnowledgeChunk(
            id="chunk-1",
            document_id="doc-1",
            sku=None,
            source_type="manual",
            chunk_index=0,
            content="Camping coffee knowledge for lightweight outdoor kits",
            metadata_json='{"title":"Coffee use","owner":"qa"}',
            embedding_status="pending",
        ))
        self.db.commit()

        result = asyncio.run(knowledge_service.search_preview(self.db, "coffee", limit=3))

        self.assertEqual(result["mode"], "keyword")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["metadata"]["owner"], "qa")


if __name__ == "__main__":
    unittest.main()
