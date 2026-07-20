import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.knowledge_base import KnowledgeJob
from app.models.operation_logs import OperationLog
from app.models.user import User
from app.services import knowledge_job_service


class KnowledgeJobServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine, tables=[User.__table__, OperationLog.__table__, KnowledgeJob.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.db.add(User(id="user-1", username="tester", email="tester@example.com", password_hash="hash"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_create_job_persists_then_dispatches_celery_task(self):
        with patch("app.tasks.knowledge_tasks.run_knowledge_job.delay") as delay:
            created = knowledge_job_service.create_embedding_retry_job(self.db, created_by="user-1", limit=3)

        stored = self.db.query(KnowledgeJob).filter(KnowledgeJob.id == created["id"]).one()
        self.assertEqual(stored.status, "queued")
        self.assertEqual(created["payload"], {"limit": 3})
        delay.assert_called_once_with(created["id"])

    def test_duplicate_active_job_returns_existing_database_record(self):
        with patch("app.tasks.knowledge_tasks.run_knowledge_job.delay"):
            first = knowledge_job_service.create_embedding_retry_job(self.db, created_by="user-1", limit=1)
            second = knowledge_job_service.create_reindex_job(self.db, created_by="user-1", mode="full")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.query(KnowledgeJob).count(), 1)

    def test_worker_marks_job_succeeded_after_running_reindex(self):
        with patch("app.tasks.knowledge_tasks.run_knowledge_job.delay"):
            created = knowledge_job_service.create_reindex_job(self.db, created_by="user-1", mode="full", embed=True)
        with (
            patch.object(knowledge_job_service, "SessionLocal", self.Session),
            patch("app.services.product_vector_index_service.index_all_products", return_value={"products": 2}),
            patch("app.services.product_vector_index_service.run_embed_pending_chunks", return_value={"embedded": 2}),
            patch("app.services.knowledge_service.health_report", return_value={"grade": "healthy"}),
        ):
            result = knowledge_job_service.run_job(created["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(knowledge_job_service.get_job(self.db, created["id"])["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
