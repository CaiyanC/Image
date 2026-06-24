import asyncio
import json
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

    def test_keyword_retrieve_keeps_keyword_or_conditions_inside_sku_scope(self):
        docs = [
            KnowledgeDocument(id="doc-c95", source_type="product", sku="CW-C95", title="CW-C95 QA", content="CW-C95 QA"),
            KnowledgeDocument(id="doc-ws", source_type="product", sku="WS-B20", title="WS-B20 QA", content="WS-B20 QA"),
            KnowledgeDocument(id="doc-tx", source_type="product", sku="TX-38", title="TX-38 QA", content="TX-38 QA"),
        ]
        self.db.add_all(docs)
        self.db.add_all([
            KnowledgeChunk(
                id="chunk-c95",
                document_id="doc-c95",
                sku="CW-C95",
                source_type="product",
                chunk_index=0,
                content="Q: 风暴炉pro-汽炉版如何清洗保养？\nA: 使用后趁热用温水+软刷清洗。",
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-ws",
                document_id="doc-ws",
                sku="WS-B20",
                source_type="product",
                chunk_index=0,
                content="Q: 畅享水杯如何清洗保养？\nA: 使用后趁热用温水+软刷清洗。",
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-tx",
                document_id="doc-tx",
                sku="TX-38",
                source_type="product",
                chunk_index=0,
                content="Q: 坐忘泡茶套装如何清洗保养？\nA: 使用后趁热用温水+软刷清洗。",
                embedding_status="pending",
            ),
        ])
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(self.db, "他该如何清洗保养", sku="CW-C95", limit=5)

        self.assertEqual({row["sku"] for row in rows}, {"CW-C95"})

    def test_keyword_retrieve_matches_file_chunk_by_related_skus_metadata(self):
        doc = KnowledgeDocument(
            id="doc-file-multisku",
            source_type="file",
            source_id="file:multisku",
            sku="CW-C93",
            title="multi sku file",
            content="CW-C93 and CS-B14 shared file knowledge",
            related_skus_json=json.dumps(["CW-C93", "CS-B14"], ensure_ascii=False),
        )
        self.db.add(doc)
        self.db.add(KnowledgeChunk(
            id="chunk-file-multisku",
            document_id=doc.id,
            sku="CW-C93",
            source_type="file",
            chunk_index=1,
            content="This file covers CW-C93 and CS-B14 shared product knowledge.",
            metadata_json=json.dumps(
                {
                    "document_id": doc.id,
                    "chunk_id": "chunk-file-multisku",
                    "related_skus": ["CW-C93", "CS-B14"],
                },
                ensure_ascii=False,
            ),
            embedding_status="pending",
        ))
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(self.db, "shared product knowledge", sku="CS-B14", limit=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metadata"]["related_skus"], ["CW-C93", "CS-B14"])
        self.assertEqual(rows[0]["metadata"]["document_id"], doc.id)


if __name__ == "__main__":
    unittest.main()
