import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.knowledge_job import KnowledgeJob
from app.models.operation_logs import OperationLog
from app.models.user import User
from app.services import knowledge_job_service


class KnowledgeJobServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine, tables=[
            User.__table__,
            OperationLog.__table__,
            KnowledgeJob.__table__,
        ])
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _run_immediately(self, *, args, task_id):
        self.assertEqual(args, [task_id])
        return knowledge_job_service.run_job(task_id)

    def test_reindex_job_runs_through_persistent_worker_record(self):
        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch(
                "app.tasks.knowledge_jobs.run_knowledge_job.apply_async",
                side_effect=self._run_immediately,
            ),
            patch("app.services.product_vector_index_service.index_all_products", return_value={"products": 2, "documents": 4, "chunks": 4}),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", return_value={"total": 4, "embedded": 4, "failed": 0}),
            patch("app.services.knowledge_service.health_report", return_value={"grade": "healthy"}),
        ):
            created = knowledge_job_service.create_reindex_job(
                self.db,
                created_by="user-1",
                mode="full",
                embed=True,
            )

        self.db.expire_all()
        job = knowledge_job_service.get_job(self.db, created["id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["stage"], "completed")
        self.assertEqual(job["result"]["indexed"]["products"], 2)
        self.assertEqual(job["result"]["embedding"]["embedded"], 4)

    def test_embedding_retry_job_records_failure(self):
        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch(
                "app.tasks.knowledge_jobs.run_knowledge_job.apply_async",
                side_effect=self._run_immediately,
            ),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", side_effect=RuntimeError("provider down")),
        ):
            created = knowledge_job_service.create_embedding_retry_job(
                self.db, created_by="user-1", limit=3
            )

        self.db.expire_all()
        job = knowledge_job_service.get_job(self.db, created["id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("provider down", job["error"])
        self.assertIsNone(self.db.get(KnowledgeJob, created["id"]).active_slot)

    def test_enqueue_failure_is_compensated_and_reported(self):
        with patch(
            "app.tasks.knowledge_jobs.run_knowledge_job.apply_async",
            side_effect=ConnectionError("redis down"),
        ):
            with self.assertRaises(knowledge_job_service.KnowledgeJobEnqueueError) as raised:
                knowledge_job_service.create_embedding_retry_job(
                    self.db, created_by="user-1", limit=1
                )

        self.db.expire_all()
        job = self.db.get(KnowledgeJob, raised.exception.job_id)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.stage, "enqueue_failed")
        self.assertNotIn("redis down", job.error)
        self.assertIsNone(job.active_slot)

    def test_duplicate_active_jobs_return_existing_database_job(self):
        with patch("app.tasks.knowledge_jobs.run_knowledge_job.apply_async"):
            first = knowledge_job_service.create_embedding_retry_job(
                self.db, created_by="user-1", limit=1
            )
            second = knowledge_job_service.create_reindex_job(
                self.db, created_by="user-1", mode="full"
            )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["status"], "queued")
        self.assertEqual(self.db.query(KnowledgeJob).count(), 1)

    def test_stale_active_job_is_recovered_after_restart_timeout(self):
        old = datetime.now(timezone.utc) - timedelta(hours=3)
        job = KnowledgeJob(
            kind="embedding_retry",
            status="running",
            stage="embedding_retry",
            created_by="user-1",
            payload={"limit": 1},
            active_slot=knowledge_job_service.ACTIVE_SLOT,
            created_at=old,
            updated_at=old,
            started_at=old,
        )
        self.db.add(job)
        self.db.commit()

        recovered = knowledge_job_service.recover_stale_jobs(self.db, stale_minutes=120)

        self.assertEqual(recovered, 1)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.stage, "interrupted")
        self.assertIsNone(job.active_slot)

    def test_jobs_are_listed_from_database_after_a_new_session(self):
        with patch("app.tasks.knowledge_jobs.run_knowledge_job.apply_async"):
            created = knowledge_job_service.create_embedding_retry_job(
                self.db, created_by="user-1", limit=1
            )
        self.db.close()
        self.db = self.Session()

        restored = knowledge_job_service.get_job(self.db, created["id"])
        listing = knowledge_job_service.list_jobs(self.db)

        self.assertEqual(restored["status"], "queued")
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["id"], created["id"])


if __name__ == "__main__":
    unittest.main()
