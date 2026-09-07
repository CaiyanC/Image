import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone

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

    def test_keyword_idf_gives_rare_retrieval_signal_more_weight(self):
        tokens = ["common", "specific operation"]
        contents = [
            "common specific operation",
            "common catalogue text",
            "common catalogue summary",
        ]

        weights = knowledge_service._keyword_token_weights(tokens, contents)

        self.assertGreater(weights["specific operation"], weights["common"])
        self.assertGreater(
            knowledge_service._keyword_score(
                "query",
                tokens,
                contents[0],
                token_weights=weights,
            ),
            knowledge_service._keyword_score(
                "query",
                tokens,
                contents[1],
                token_weights=weights,
            ),
        )

    def test_cjk_ngram_budget_represents_later_semantic_run(self):
        tokens = knowledge_service._query_tokens(
            "顾客明确要求锅具套装 锅具套装 "
            "顾客要求锅具套装具备煮面能力且必须有产品资料依据 煮面能力"
        )

        self.assertIn("锅具套装", tokens)
        self.assertIn("煮面", tokens)

    def test_cjk_ngram_budget_represents_end_of_long_natural_clause(self):
        tokens = knowledge_service._query_tokens(
            "两个人周末露营想煮面，推荐一套有明确资料支持的锅具。 "
            "锅具 产品需有明确资料支持，如规格、材质、适用场景等"
        )

        self.assertIn("两个人", tokens)
        self.assertIn("煮面", tokens)
        self.assertLessEqual(len(tokens), 32)

    def test_retrieval_revision_changes_when_corpus_or_embedding_state_changes(self):
        document = KnowledgeDocument(
            id="doc-revision-1",
            source_type="product",
            source_id="product:REV-1:qa:1",
            sku="REV-1",
            title="revision",
            content="revision content",
        )
        chunk = KnowledgeChunk(
            id="chunk-revision-1",
            document_id=document.id,
            sku="REV-1",
            source_type="product",
            chunk_index=0,
            content="revision content",
            embedding_status="pending",
        )
        self.db.add_all([document, chunk])
        self.db.commit()

        pending_revision = knowledge_service._knowledge_retrieval_revision(self.db)
        chunk.embedding_status = "synced"
        self.db.commit()
        synced_revision = knowledge_service._knowledge_retrieval_revision(self.db)

        self.assertNotEqual(pending_revision, synced_revision)
        self.db.add(KnowledgeChunk(
            id="chunk-revision-2",
            document_id=document.id,
            sku="REV-1",
            source_type="product",
            chunk_index=1,
            content="new revision content",
            embedding_status="pending",
        ))
        self.db.commit()
        expanded_revision = knowledge_service._knowledge_retrieval_revision(self.db)
        self.assertNotEqual(synced_revision, expanded_revision)

    def test_non_fact_experience_source_is_excluded_unless_explicitly_requested(self):
        product_document = KnowledgeDocument(
            id="doc-fact-source",
            source_type="product",
            source_id="product:PILOT-1:qa:1",
            sku="PILOT-1",
            title="fact",
            content="价格顾虑的商品事实",
        )
        experience_document = KnowledgeDocument(
            id="doc-experience-source",
            source_type=knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
            source_id="customer_experience:pilot:PILOT-1:value",
            sku="PILOT-1",
            title="experience",
            content="价格顾虑的沟通策略",
        )
        self.db.add_all([
            product_document,
            experience_document,
            KnowledgeChunk(
                id="chunk-fact-source",
                document_id=product_document.id,
                sku="PILOT-1",
                source_type="product",
                chunk_index=0,
                content=product_document.content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-experience-source",
                document_id=experience_document.id,
                sku="PILOT-1",
                source_type=knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE,
                chunk_index=0,
                content=experience_document.content,
                embedding_status="pending",
            ),
        ])
        self.db.commit()

        normal_rows = knowledge_service.keyword_retrieve(
            self.db,
            "价格顾虑",
            sku="PILOT-1",
            limit=5,
        )
        experience_rows = knowledge_service.keyword_retrieve(
            self.db,
            "价格顾虑",
            sku="PILOT-1",
            limit=5,
            source_types=[knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
        )

        self.assertEqual([row["source_type"] for row in normal_rows], ["product"])
        self.assertEqual(
            [row["source_type"] for row in experience_rows],
            [knowledge_service.CUSTOMER_EXPERIENCE_SOURCE_TYPE],
        )

    def test_keyword_retrieve_merges_token_group_pages_before_idf_ranking(self):
        now = datetime.now(timezone.utc)
        documents = []
        chunks = []
        for index in range(50):
            document = KnowledgeDocument(
                id=f"doc-generic-{index}",
                source_type="product",
                source_id=f"product:GEN-{index}:content",
                sku=f"GEN-{index}",
                title=f"generic {index}",
                content="genericone catalogue text",
            )
            documents.append(document)
            chunks.append(KnowledgeChunk(
                id=f"chunk-generic-{index}",
                document_id=document.id,
                sku=document.sku,
                source_type="product",
                chunk_index=0,
                content=document.content,
                embedding_status="pending",
                updated_at=now + timedelta(seconds=index),
            ))
        direct_document = KnowledgeDocument(
            id="doc-direct-capability",
            source_type="product",
            source_id="product:DIRECT-1:content",
            sku="DIRECT-1",
            title="direct capability",
            content="directcapability is explicitly documented",
        )
        documents.append(direct_document)
        chunks.append(KnowledgeChunk(
            id="chunk-direct-capability",
            document_id=direct_document.id,
            sku="DIRECT-1",
            source_type="product",
            chunk_index=0,
            content=direct_document.content,
            embedding_status="pending",
            updated_at=now - timedelta(days=365),
        ))
        self.db.add_all(documents)
        self.db.add_all(chunks)
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(
            self.db,
            (
                "genericone generic2 generic3 generic4 generic5 "
                "generic6 generic7 generic8 directcapability"
            ),
            limit=5,
        )

        self.assertEqual(rows[0]["sku"], "DIRECT-1")

    def test_keyword_retrieve_keeps_older_multi_token_match_in_candidate_page(self):
        now = datetime.now(timezone.utc)
        documents = []
        chunks = []
        for index in range(80):
            document = KnowledgeDocument(
                id=f"doc-shared-{index}",
                source_type="product",
                source_id=f"product:SHARED-{index}:content",
                sku=f"SHARED-{index}",
                title=f"shared {index}",
                content="sharedterm catalogue text",
            )
            documents.append(document)
            chunks.append(KnowledgeChunk(
                id=f"chunk-shared-{index}",
                document_id=document.id,
                sku=document.sku,
                source_type="product",
                chunk_index=0,
                content=document.content,
                embedding_status="pending",
                updated_at=now + timedelta(seconds=index),
            ))

        direct_document = KnowledgeDocument(
            id="doc-multi-token-direct",
            source_type="product",
            source_id="product:DIRECT-MULTI:content",
            sku="DIRECT-MULTI",
            title="multi-token capability",
            content="sharedterm rareterm exact capability",
        )
        documents.append(direct_document)
        chunks.append(KnowledgeChunk(
            id="chunk-multi-token-direct",
            document_id=direct_document.id,
            sku=direct_document.sku,
            source_type="product",
            chunk_index=0,
            content=direct_document.content,
            embedding_status="pending",
            updated_at=now - timedelta(days=365),
        ))
        self.db.add_all(documents)
        self.db.add_all(chunks)
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(
            self.db,
            "sharedterm rareterm",
            limit=5,
        )

        assert rows[0]["sku"] == "DIRECT-MULTI"

    def test_merge_retrieval_rows_keeps_product_keyword_evidence_when_vectors_exist(self):
        vector_rows = [{
            "source_type": "file",
            "sku": None,
            "content": "generic outdoor guidance",
            "metadata": {"source_id": "file:1"},
            "score": 0.99,
        }]
        keyword_rows = [{
            "source_type": "product",
            "sku": "CW-C83",
            "content": "CW-C83 表面工艺：水性不沾",
            "metadata": {"source_id": "product:CW-C83:profile"},
            "score": 4.0,
        }]

        rows = knowledge_service.merge_retrieval_rows(
            vector_rows,
            keyword_rows,
            limit=2,
            prefer_product_sources=True,
        )

        self.assertEqual([row["sku"] for row in rows], ["CW-C83", None])

    def test_merge_product_retrieval_surfaces_distinct_skus_before_duplicate_chunks(self):
        vector_rows = [
            {
                "source_type": "product",
                "sku": "SKU-A",
                "content": f"SKU-A chunk {index}",
                "metadata": {"source_id": f"product:SKU-A:{index}"},
                "score": 0.9 - index / 100,
            }
            for index in range(4)
        ]
        keyword_rows = [{
            "source_type": "product",
            "sku": "SKU-B",
            "content": "SKU-B exact lexical evidence",
            "metadata": {"source_id": "product:SKU-B:content"},
            "score": 4.0,
        }]

        rows = knowledge_service.merge_retrieval_rows(
            vector_rows,
            keyword_rows,
            limit=3,
            prefer_product_sources=True,
        )

        self.assertEqual([row["sku"] for row in rows[:2]], ["SKU-A", "SKU-B"])

    def test_merge_retrieval_rows_fuses_generic_vector_and_lexical_signals(self):
        vector_rows = [{
            "source_type": "file",
            "sku": None,
            "content": "unrelated stove sales paragraph",
            "metadata": {"source_id": "file:stove"},
            "score": 0.99,
        }]
        keyword_rows = [{
            "source_type": "product",
            "sku": "CW-C73",
            "content": "Q: 如何清洗保养？ A: 使用温水和软刷清洗，擦干后存放。",
            "metadata": {"source_id": "product:CW-C73:qa:1", "section": "qa:1"},
            "score": 9.0,
        }]

        rows = knowledge_service.merge_retrieval_rows(
            vector_rows,
            keyword_rows,
            limit=2,
            prefer_product_sources=False,
        )

        self.assertEqual([row["sku"] for row in rows], ["CW-C73", None])

    def test_merge_generic_retrieval_preserves_distinct_sku_coverage(self):
        vector_rows = [
            {
                "source_type": "product",
                "sku": "SKU-A",
                "content": f"SKU-A vector chunk {index}",
                "metadata": {"source_id": f"product:SKU-A:vector:{index}"},
            }
            for index in range(8)
        ]
        vector_rows.extend(
            {
                "source_type": "product",
                "sku": "SKU-B",
                "content": f"SKU-B vector chunk {index}",
                "metadata": {"source_id": f"product:SKU-B:vector:{index}"},
            }
            for index in range(8)
        )
        lexical_rows = [
            {
                "source_type": "product",
                "sku": "SKU-NOISE",
                "content": f"noise lexical chunk {index}",
                "metadata": {"source_id": f"product:SKU-NOISE:lexical:{index}"},
            }
            for index in range(14)
        ]
        lexical_rows.append({
            "source_type": "product",
            "sku": "SKU-TARGET",
            "content": "the independently relevant lexical product row",
            "metadata": {"source_id": "product:SKU-TARGET:lexical"},
        })

        rows = knowledge_service.merge_retrieval_rows(
            vector_rows,
            lexical_rows,
            limit=16,
            prefer_product_sources=False,
        )

        self.assertIn("SKU-TARGET", [row["sku"] for row in rows])

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
        self.assertEqual(result["results"][0]["metadata"]["source_id"], "manual:1")

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

    def test_keyword_retrieve_can_limit_results_to_recommendation_documents(self):
        recommendation = KnowledgeDocument(
            id="doc-recommendation",
            source_type="product",
            source_id="product:CUP-1:recommendation",
            sku="CUP-1",
            title="CUP-1 recommendation",
            content="small outdoor drinking cup",
        )
        profile = KnowledgeDocument(
            id="doc-profile",
            source_type="product",
            source_id="product:POT-1:profile",
            sku="POT-1",
            title="POT-1 profile",
            content="small outdoor drinking cup mentioned in a pot profile",
        )
        self.db.add_all([recommendation, profile])
        self.db.add_all([
            KnowledgeChunk(
                id="chunk-recommendation",
                document_id=recommendation.id,
                sku="CUP-1",
                source_type="product",
                chunk_index=0,
                content=recommendation.content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-profile",
                document_id=profile.id,
                sku="POT-1",
                source_type="product",
                chunk_index=0,
                content=profile.content,
                embedding_status="pending",
            ),
        ])
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(
            self.db,
            "outdoor drinking cup",
            limit=5,
            sections=["recommendation"],
        )

        self.assertEqual([row["sku"] for row in rows], ["CUP-1"])

    def test_keyword_retrieve_matches_nested_product_qa_section_ids(self):
        qa_document = KnowledgeDocument(
            id="doc-qa-nested",
            source_type="product",
            source_id="product:CW-K31:qa:qa-2",
            sku="CW-K31",
            title="CW-K31 QA",
            content="研磨粗细可调，适用于手冲和法压壶",
        )
        qa_negative_document = KnowledgeDocument(
            id="doc-qa-negative",
            source_type="product",
            source_id="product:CW-K31:qa_negative",
            sku="CW-K31",
            title="CW-K31 negative",
            content="negative feedback",
        )
        self.db.add_all([qa_document, qa_negative_document])
        self.db.add_all([
            KnowledgeChunk(
                id="chunk-qa-nested",
                document_id=qa_document.id,
                sku="CW-K31",
                source_type="product",
                chunk_index=0,
                content=qa_document.content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-qa-negative",
                document_id=qa_negative_document.id,
                sku="CW-K31",
                source_type="product",
                chunk_index=0,
                content=qa_negative_document.content,
                embedding_status="pending",
            ),
        ])
        self.db.commit()

        rows = knowledge_service.keyword_retrieve(
            self.db,
            "手冲 法压",
            limit=5,
            sections=["qa"],
        )

        self.assertEqual([row["metadata"]["source_id"] for row in rows], [qa_document.source_id])

    def test_keyword_retrieve_uses_generic_cjk_ngrams_for_natural_product_questions(self):
        documents = [
            KnowledgeDocument(
                id="doc-bag-29l",
                source_type="product",
                source_id="product:AC-Z07:recommendation",
                sku="AC-Z07",
                title="29L outdoor storage bag",
                content="户外收纳包，含厨具餐具包，支持分类收纳和多隔层整理。",
            ),
            KnowledgeDocument(
                id="doc-bag-17l",
                source_type="product",
                source_id="product:AC-Z09:recommendation",
                sku="AC-Z09",
                title="17L outdoor storage pouch",
                content="户外收纳袋，适合收纳餐具包，可分类整理户外用品。",
            ),
            KnowledgeDocument(
                id="doc-cup-tw502",
                source_type="product",
                source_id="product:TW-502:recommendation",
                sku="TW-502",
                title="small outdoor cup",
                content="户外水杯，小杯子，便于随身携带和饮水。",
            ),
            KnowledgeDocument(
                id="doc-cup-t13",
                source_type="product",
                source_id="product:CT-T13:recommendation",
                sku="CT-T13",
                title="compact drinking cup",
                content="便携水杯，适合户外饮水，占用空间较小。",
            ),
        ]
        self.db.add_all(documents)
        self.db.add_all([
            KnowledgeChunk(
                id="chunk-bag-29l",
                document_id="doc-bag-29l",
                sku="AC-Z07",
                source_type="product",
                chunk_index=0,
                content=documents[0].content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-bag-17l",
                document_id="doc-bag-17l",
                sku="AC-Z09",
                source_type="product",
                chunk_index=0,
                content=documents[1].content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-cup-tw502",
                document_id="doc-cup-tw502",
                sku="TW-502",
                source_type="product",
                chunk_index=0,
                content=documents[2].content,
                embedding_status="pending",
            ),
            KnowledgeChunk(
                id="chunk-cup-t13",
                document_id="doc-cup-t13",
                sku="CT-T13",
                source_type="product",
                chunk_index=0,
                content=documents[3].content,
                embedding_status="pending",
            ),
        ])
        self.db.commit()

        bag_rows = knowledge_service.keyword_retrieve(
            self.db,
            "户外餐具收纳包有推荐吗？我想要能把一套餐具收在一起的。",
            limit=5,
        )
        cup_rows = knowledge_service.keyword_retrieve(
            self.db,
            "户外喝水用的小杯子，有没有不占地方的？",
            limit=5,
        )

        self.assertTrue({"AC-Z07", "AC-Z09"}.issubset({row["sku"] for row in bag_rows}))
        self.assertTrue({"TW-502", "CT-T13"}.issubset({row["sku"] for row in cup_rows}))


if __name__ == "__main__":
    unittest.main()
