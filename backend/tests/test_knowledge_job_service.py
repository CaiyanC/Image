import json
import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.operation_logs import OperationLog
from app.models.user import User
from app.services import knowledge_job_service


class KnowledgeJobServiceTest(unittest.TestCase):
    def setUp(self):
        self.runtime_dir = tempfile.TemporaryDirectory()
        self.old_runtime_dir = knowledge_job_service._RUNTIME_DIR
        self.old_job_store_path = knowledge_job_service._JOB_STORE_PATH
        knowledge_job_service._RUNTIME_DIR = self.runtime_dir.name
        knowledge_job_service._JOB_STORE_PATH = os.path.join(self.runtime_dir.name, "knowledge_jobs.json")
        knowledge_job_service._LOADED = False
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine, tables=[
            User.__table__,
            OperationLog.__table__,
        ])
        self.Session = sessionmaker(bind=engine)
        knowledge_job_service._JOBS.clear()

    def tearDown(self):
        knowledge_job_service._JOBS.clear()
        knowledge_job_service._LOADED = False
        knowledge_job_service._RUNTIME_DIR = self.old_runtime_dir
        knowledge_job_service._JOB_STORE_PATH = self.old_job_store_path
        self.runtime_dir.cleanup()

    def test_reindex_job_runs_in_background_registry(self):
        def submit_now(fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch.object(knowledge_job_service._EXECUTOR, "submit", side_effect=submit_now),
            patch("app.services.product_vector_index_service.index_all_products", return_value={"products": 2, "documents": 4, "chunks": 4}),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", return_value={"total": 4, "embedded": 4, "failed": 0}),
            patch("app.services.knowledge_service.health_report", return_value={"grade": "healthy"}),
        ):
            created = knowledge_job_service.create_reindex_job(
                created_by="user-1",
                mode="full",
                embed=True,
            )

        job = knowledge_job_service.get_job(created["id"])

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["stage"], "completed")
        self.assertEqual(job["result"]["indexed"]["products"], 2)
        self.assertEqual(job["result"]["embedding"]["embedded"], 4)

    def test_embedding_retry_job_records_failure(self):
        def submit_now(fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch.object(knowledge_job_service._EXECUTOR, "submit", side_effect=submit_now),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", side_effect=RuntimeError("provider down")),
        ):
            created = knowledge_job_service.create_embedding_retry_job(created_by="user-1", limit=3)

        job = knowledge_job_service.get_job(created["id"])

        self.assertEqual(job["status"], "failed")
        self.assertIn("provider down", job["error"])

    def test_jobs_are_persisted_and_reloaded(self):
        def submit_now(fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch.object(knowledge_job_service._EXECUTOR, "submit", side_effect=submit_now),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", return_value={"total": 1, "embedded": 1, "failed": 0}),
            patch("app.services.knowledge_service.health_report", return_value={"grade": "healthy"}),
        ):
            created = knowledge_job_service.create_embedding_retry_job(created_by="user-1", limit=1)

        knowledge_job_service._JOBS.clear()
        knowledge_job_service._LOADED = False
        restored = knowledge_job_service.get_job(created["id"])

        self.assertEqual(restored["status"], "succeeded")
        self.assertEqual(restored["result"]["embedding"]["embedded"], 1)

    def test_loaded_active_job_is_marked_interrupted_after_restart(self):
        interrupted_id = "job-interrupted"
        os.makedirs(self.runtime_dir.name, exist_ok=True)
        with open(knowledge_job_service._JOB_STORE_PATH, "w", encoding="utf-8") as file:
            json.dump([
                {
                    "id": interrupted_id,
                    "kind": "embedding_retry",
                    "status": "running",
                    "stage": "embedding_retry",
                    "created_by": "user-1",
                    "payload": {"limit": 1},
                    "result": None,
                    "error": None,
                    "created_at": "2026-06-13T00:00:00+00:00",
                    "updated_at": "2026-06-13T00:00:01+00:00",
                    "started_at": "2026-06-13T00:00:01+00:00",
                    "finished_at": None,
                }
            ], file)

        restored = knowledge_job_service.get_job(interrupted_id)

        self.assertEqual(restored["status"], "failed")
        self.assertEqual(restored["stage"], "interrupted")
        self.assertIn("restarted", restored["error"])

    def test_duplicate_active_jobs_return_existing_job(self):
        def do_not_run(*_args, **_kwargs):
            return None

        with patch.object(knowledge_job_service._EXECUTOR, "submit", side_effect=do_not_run):
            first = knowledge_job_service.create_embedding_retry_job(created_by="user-1", limit=1)
            second = knowledge_job_service.create_reindex_job(created_by="user-1", mode="full")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "queued")


if __name__ == "__main__":
    unittest.main()
