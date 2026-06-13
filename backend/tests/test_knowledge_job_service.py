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


if __name__ == "__main__":
    unittest.main()
