import asyncio
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.api import knowledge_base as kb_api
from app.core.database import Base, get_db
from app.core.security import get_current_super_admin
from app.main import app
from app.models.knowledge_base import KnowledgeChunk, KnowledgeDocument, KnowledgeParseTask
from app.services.file_ingestion_service import ingest_file, recover_stuck_processing_documents
from app.services import knowledge_service
from app.tasks import parse_tasks


class FileIngestionStabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)
        self.db_path = self.temp_dir_path / "test.db"
        self.upload_dir = self.temp_dir_path / "knowledge-files"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite+pysqlite:///{self.db_path}", future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        KnowledgeDocument.__table__.create(bind=self.engine)
        KnowledgeChunk.__table__.create(bind=self.engine)
        KnowledgeParseTask.__table__.create(bind=self.engine)
        self.db = self.SessionLocal()

        self.original_upload_dir = kb_api.KNOWLEDGE_FILE_DIR
        self.original_session_local = kb_api.SessionLocal
        self.original_task_session_local = parse_tasks.SessionLocal
        self.original_startup_handlers = list(app.router.on_startup)
        self.original_shutdown_handlers = list(app.router.on_shutdown)
        kb_api.KNOWLEDGE_FILE_DIR = str(self.upload_dir)
        kb_api.SessionLocal = self.SessionLocal
        parse_tasks.SessionLocal = self.SessionLocal
        self.dispatched_parse_tasks = []
        self.parse_delay_patcher = patch.object(
            kb_api.parse_document,
            "delay",
            side_effect=lambda document_id, task_id: self.dispatched_parse_tasks.append((document_id, task_id)),
        )
        self.parse_delay_patcher.start()
        app.router.on_startup.clear()
        app.router.on_shutdown.clear()

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_super_admin, None)
        app.router.on_startup[:] = self.original_startup_handlers
        app.router.on_shutdown[:] = self.original_shutdown_handlers
        kb_api.KNOWLEDGE_FILE_DIR = self.original_upload_dir
        kb_api.SessionLocal = self.original_session_local
        parse_tasks.SessionLocal = self.original_task_session_local
        self.parse_delay_patcher.stop()
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_single_upload_and_rerun_do_not_duplicate_chunks(self):
        file_path = self._write_txt("rerun.txt", "P0 稳定版测试文本。\n" * 20)
        doc = asyncio.run(
            ingest_file(
                self.db,
                file_path=str(file_path),
                file_name=file_path.name,
                related_skus=["SKU-001"],
            )
        )
        first_chunks = self._load_chunks(doc.id)
        self.assertEqual(doc.parse_status, "done")
        self.assertGreater(len(first_chunks), 0)
        self.assertEqual(self._chunk_indexes(first_chunks), list(range(1, len(first_chunks) + 1)))

        rerun = asyncio.run(
            ingest_file(
                self.db,
                file_path=str(file_path),
                file_name=file_path.name,
                related_skus=["SKU-001"],
                document=doc,
            )
        )
        rerun_chunks = self._load_chunks(rerun.id)
        self.assertEqual(rerun.parse_status, "done")
        self.assertEqual(len(rerun_chunks), len(first_chunks))
        self.assertEqual(self._chunk_indexes(rerun_chunks), list(range(1, len(rerun_chunks) + 1)))

    def test_duplicate_upload_reuses_existing_document_and_merges_related_skus(self):
        file_path = self._write_txt("duplicate.txt", "重复文件测试内容。\n" * 20)
        first = self._upload_via_api(file_path, "duplicate.txt", "text/plain", ["SKU-A"])
        self.assertEqual(first.status_code, 200, first.text)
        first_item = first.json()["items"][0]
        self.assertFalse(first_item["duplicate"])
        self.assertTrue(first_item["task_id"])
        self.assertEqual(self.dispatched_parse_tasks[-1], (first_item["document_id"], first_item["task_id"]))
        first_document_id = first_item["document_id"]
        self._run_dispatched_parse_tasks()
        self.db.expire_all()
        first_chunk_count = self._count_chunks(first_document_id)
        self.assertGreater(first_chunk_count, 0)

        second = self._upload_via_api(file_path, "duplicate.txt", "text/plain", ["SKU-B"])
        self.assertEqual(second.status_code, 200, second.text)
        second_item = second.json()["items"][0]
        self.assertTrue(second_item["duplicate"])
        self.assertEqual(second_item["reused_document_id"], first_document_id)
        self.assertEqual(second_item["parse_status"], "done")
        self.assertEqual(second_item["chunk_count"], first_chunk_count)

        refreshed = self._get_document(first_document_id)
        self.assertEqual(set(json.loads(refreshed.related_skus_json or "[]")), {"SKU-A", "SKU-B"})
        self.assertEqual(self._count_chunks(first_document_id), first_chunk_count)

    def test_unique_constraint_conflict_is_reused_not_500(self):
        file_path = self._write_txt("conflict.txt", "并发冲突测试内容。\n" * 20)
        first = self._upload_via_api(file_path, "conflict.txt", "text/plain", ["SKU-CONFLICT"])
        self.assertEqual(first.status_code, 200, first.text)
        first_item = first.json()["items"][0]
        self._run_dispatched_parse_tasks()
        self.db.expire_all()
        existing_doc = self._get_document(first_item["document_id"])

        with patch.object(kb_api, "_find_existing_file_document", side_effect=[None, existing_doc]):
            second = self._upload_via_api(file_path, "conflict.txt", "text/plain", ["SKU-CONFLICT-2"])

        self.assertEqual(second.status_code, 200, second.text)
        second_item = second.json()["items"][0]
        self.assertTrue(second_item["duplicate"])
        self.assertEqual(second_item["reused_document_id"], existing_doc.id)
        self.assertEqual(second_item["parse_status"], "done")

    def test_upload_returns_task_id_and_task_status_can_be_polled(self):
        file_path = self._write_txt("task.txt", "task status test content\n" * 20)
        response = self._upload_via_api(file_path, "task.txt", "text/plain", ["SKU-TASK"])
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertFalse(item["duplicate"])
        self.assertTrue(item["task_id"])
        self.assertEqual(item["task_status"], "pending")
        self.assertEqual(self.dispatched_parse_tasks[-1], (item["document_id"], item["task_id"]))

        task_response = self._get_task_via_api(item["task_id"])
        self.assertEqual(task_response.status_code, 200, task_response.text)
        task_payload = task_response.json()
        self.assertEqual(task_payload["status"], "pending")

        self._run_dispatched_parse_tasks()
        task_response = self._get_task_via_api(item["task_id"])
        self.assertEqual(task_response.status_code, 200, task_response.text)
        task_payload = task_response.json()
        self.assertEqual(task_payload["task_id"], item["task_id"])
        self.assertEqual(task_payload["document_id"], item["document_id"])
        self.assertEqual(task_payload["status"], "done")

    def test_failed_background_parse_marks_task_error(self):
        file_path = self._write_txt("task-error.txt", "   \n\t  ")
        response = self._upload_via_api(file_path, "task-error.txt", "text/plain", ["SKU-TASK-ERR"])
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertTrue(item["task_id"])

        self._run_dispatched_parse_tasks()
        task_response = self._get_task_via_api(item["task_id"])
        self.assertEqual(task_response.status_code, 200, task_response.text)
        task_payload = task_response.json()
        self.assertEqual(task_payload["status"], "error")
        self.assertTrue(task_payload["error_message"])

    def test_duplicate_processing_upload_returns_existing_task_id(self):
        file_path = self._write_txt("processing-duplicate.txt", "processing duplicate content\n" * 20)
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        document = KnowledgeDocument(
            id="doc-existing-processing",
            source_type="file",
            source_id=file_hash,
            sku="SKU-PROC",
            title="processing duplicate",
            content="",
            file_name="processing-duplicate.txt",
            file_path=str(file_path),
            file_type="txt",
            file_hash=file_hash,
            page_count=0,
            parse_status="processing",
            parse_error=None,
            related_skus_json='["SKU-PROC"]',
            metadata_json="{}",
        )
        self.db.add(document)
        self.db.commit()
        task = KnowledgeParseTask(document_id=document.id, status="pending")
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        response = self._upload_via_api(file_path, "processing-duplicate.txt", "text/plain", ["SKU-PROC-2"])
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]
        self.assertTrue(item["duplicate"])
        self.assertEqual(item["reused_document_id"], document.id)
        self.assertEqual(item["parse_status"], "processing")
        self.assertEqual(item["task_id"], task.id)

    def test_parse_failure_marks_error_and_clears_chunks(self):
        file_path = self._write_txt("empty.txt", "   \n\t  ")
        document = asyncio.run(
            ingest_file(
                self.db,
                file_path=str(file_path),
                file_name=file_path.name,
                related_skus=["SKU-ERR"],
            )
        )
        self.db.expire_all()
        refreshed = self._get_document(document.id)
        self.assertEqual(refreshed.parse_status, "error")
        self.assertTrue(refreshed.parse_error)
        self.assertEqual(self._count_chunks(document.id), 0)

    def test_recover_stuck_processing_documents_marks_old_processing_as_error(self):
        doc = KnowledgeDocument(
            id="doc-processing",
            source_type="file",
            source_id="hash-processing",
            sku="SKU-OLD",
            title="stuck",
            content="",
            file_name="stuck.txt",
            file_path="/tmp/stuck.txt",
            file_type="txt",
            file_hash="hash-processing",
            page_count=0,
            parse_status="processing",
            parse_error=None,
            related_skus_json='["SKU-OLD"]',
            metadata_json="{}",
        )
        self.db.add(doc)
        self.db.commit()

        old_time = datetime.now(timezone.utc) - timedelta(minutes=90)
        with self.engine.begin() as conn:
            conn.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc.id)
                .values(updated_at=old_time)
            )

        self.db.expire_all()
        result = recover_stuck_processing_documents(self.db, timeout_minutes=30)
        self.assertEqual(result["recovered_count"], 1)
        refreshed = self._get_document(doc.id)
        self.assertEqual(refreshed.parse_status, "error")
        self.assertIn("处理超时", refreshed.parse_error or "")

    def test_recover_stuck_files_api_supports_dry_run_and_apply(self):
        doc = KnowledgeDocument(
            id="doc-api-processing",
            source_type="file",
            source_id="hash-api-processing",
            sku="SKU-OLD",
            title="stuck api",
            content="",
            file_name="stuck-api.txt",
            file_path="/tmp/stuck-api.txt",
            file_type="txt",
            file_hash="hash-api-processing",
            page_count=0,
            parse_status="processing",
            parse_error=None,
            related_skus_json='["SKU-OLD"]',
            metadata_json="{}",
        )
        self.db.add(doc)
        self.db.commit()

        old_time = datetime.now(timezone.utc) - timedelta(minutes=90)
        with self.engine.begin() as conn:
            conn.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc.id)
                .values(updated_at=old_time)
            )

        app.dependency_overrides[get_current_super_admin] = lambda: SimpleNamespace(id="super-admin")

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as client:
                dry_run = client.post(
                    "/api/knowledge-base/files/recover-stuck",
                    json={"timeout_minutes": 30, "dry_run": True},
                )
                self.assertEqual(dry_run.status_code, 200, dry_run.text)
                dry_run_payload = dry_run.json()
                self.assertEqual(dry_run_payload["recovered_count"], 0)
                self.assertEqual(dry_run_payload["candidates_count"], 1)
                self.assertEqual(dry_run_payload["documents"][0]["id"], doc.id)
                self.db.expire_all()
                self.assertEqual(self._get_document(doc.id).parse_status, "processing")

                applied = client.post(
                    "/api/knowledge-base/files/recover-stuck",
                    json={"timeout_minutes": 30, "dry_run": False},
                )
                self.assertEqual(applied.status_code, 200, applied.text)
                applied_payload = applied.json()
                self.assertEqual(applied_payload["recovered_count"], 1)
                self.assertEqual(applied_payload["candidates_count"], 1)
                self.assertEqual(applied_payload["documents"][0]["parse_status"], "error")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_super_admin, None)

        self.db.expire_all()
        refreshed = self._get_document(doc.id)
        self.assertEqual(refreshed.parse_status, "error")

    def test_search_preview_smoke_test_still_works(self):
        doc = KnowledgeDocument(
            id="doc-search",
            source_type="manual",
            source_id="manual:search",
            title="Coffee use",
            content="Camping coffee knowledge",
            parse_status="done",
            metadata_json="{}",
        )
        self.db.add(doc)
        self.db.add(
            KnowledgeChunk(
                id="chunk-search",
                document_id=doc.id,
                sku=None,
                source_type="manual",
                chunk_index=0,
                content="Camping coffee knowledge for lightweight outdoor kits",
                metadata_json='{"title":"Coffee use","owner":"qa"}',
                embedding_status="pending",
            )
        )
        self.db.commit()

        result = asyncio.run(knowledge_service.search_preview(self.db, "coffee", limit=3))
        self.assertEqual(result["mode"], "keyword")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["metadata"]["owner"], "qa")

    def _upload_via_api(self, file_path: Path, filename: str, content_type: str, related_skus: list[str]):
        app.dependency_overrides[get_current_super_admin] = lambda: SimpleNamespace(id="super-admin")

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as client:
                return client.post(
                    "/api/knowledge-base/files/upload",
                    data={"related_skus": json.dumps(related_skus)},
                    files=[
                        (
                            "files",
                            (
                                filename,
                                file_path.read_bytes(),
                                content_type,
                            ),
                        )
                    ],
                )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_super_admin, None)

    def _get_task_via_api(self, task_id: str):
        app.dependency_overrides[get_current_super_admin] = lambda: SimpleNamespace(id="super-admin")

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app) as client:
                return client.get(f"/api/knowledge-base/tasks/{task_id}")
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_super_admin, None)

    def _run_dispatched_parse_tasks(self):
        pending = list(self.dispatched_parse_tasks)
        self.dispatched_parse_tasks.clear()
        for document_id, task_id in pending:
            parse_tasks.parse_document(document_id, task_id)

    def _write_txt(self, filename: str, content: str) -> Path:
        file_path = self.temp_dir_path / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _get_document(self, document_id: str) -> KnowledgeDocument:
        return self.db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)).scalar_one()

    def _load_chunks(self, document_id: str) -> list[KnowledgeChunk]:
        return self.db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)).scalars().all()

    def _count_chunks(self, document_id: str) -> int:
        return self.db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).count()

    def _chunk_indexes(self, chunks: list[KnowledgeChunk]) -> list[int]:
        return [chunk.chunk_index for chunk in chunks]


if __name__ == "__main__":
    unittest.main()
