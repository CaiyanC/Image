import importlib
import os
import unittest
from unittest.mock import patch

from app.core import config


class SettingsConfigTest(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)

    def _runtime_settings(self, app_env: str):
        settings = config.Settings()
        settings.APP_ENV = app_env
        if app_env == "prod":
            settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge"
            settings.UPLOAD_DIR = "uploads"
            settings.CELERY_QUEUE = "celery_prod"
            settings.CELERY_WORKER_NAME = "worker_prod"
        else:
            settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge_dev"
            settings.UPLOAD_DIR = "uploads_dev"
            settings.CELERY_QUEUE = "celery_dev"
            settings.CELERY_WORKER_NAME = "worker_dev"
        return settings

    def test_upload_dir_can_be_configured_from_env(self):
        custom_upload_dir = os.path.normpath("backend/uploads_dev")
        with patch.dict(os.environ, {"UPLOAD_DIR": custom_upload_dir}):
            reloaded = importlib.reload(config)

        self.assertEqual(os.path.normpath(reloaded.settings.UPLOAD_DIR), custom_upload_dir)
        self.assertEqual(
            os.path.normpath(reloaded.settings.IMAGE_UPLOAD_DIR),
            os.path.join(custom_upload_dir, "images"),
        )
        self.assertEqual(
            os.path.normpath(reloaded.settings.VIDEO_UPLOAD_DIR),
            os.path.join(custom_upload_dir, "videos"),
        )
        self.assertEqual(
            os.path.normpath(reloaded.settings.GENERATED_DIR),
            os.path.join(custom_upload_dir, "generated"),
        )

    def test_runtime_isolation_settings_are_loaded_from_env(self):
        env = {
            "APP_ENV": "dev",
            "BACKEND_PORT": "8001",
            "CELERY_QUEUE": "celery_dev",
            "CELERY_WORKER_NAME": "worker_dev",
            "LOG_DIR": "logs/dev",
            "UPLOAD_DIR": "uploads_dev",
        }
        with patch.dict(os.environ, env):
            reloaded = importlib.reload(config)
            settings = reloaded.Settings()

        self.assertEqual(settings.APP_ENV, "dev")
        self.assertEqual(settings.BACKEND_PORT, 8001)
        self.assertEqual(settings.CELERY_QUEUE, "celery_dev")
        self.assertEqual(settings.CELERY_WORKER_NAME, "worker_dev")
        self.assertEqual(os.path.normpath(settings.LOG_DIR), os.path.normpath("logs/dev"))
        self.assertEqual(os.path.normpath(settings.UPLOAD_DIR), os.path.normpath("uploads_dev"))

    def test_environment_validation_rejects_dev_database_in_prod(self):
        settings = config.Settings()
        settings.APP_ENV = "prod"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge_dev"
        settings.UPLOAD_DIR = "uploads"

        with self.assertRaisesRegex(RuntimeError, "product_knowledge_dev"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_prod_database_in_dev(self):
        settings = config.Settings()
        settings.APP_ENV = "dev"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge"
        settings.UPLOAD_DIR = "uploads_dev"

        with self.assertRaisesRegex(RuntimeError, "product_knowledge"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_crossed_upload_dirs(self):
        settings = config.Settings()
        settings.APP_ENV = "dev"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge_dev"
        settings.UPLOAD_DIR = "uploads"

        with self.assertRaisesRegex(RuntimeError, "UPLOAD_DIR"):
            config.validate_runtime_isolation(settings)

        settings.APP_ENV = "prod"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge"
        settings.UPLOAD_DIR = "uploads_dev"

        with self.assertRaisesRegex(RuntimeError, "UPLOAD_DIR"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_unknown_app_env(self):
        settings = config.Settings()
        settings.APP_ENV = "local"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge"
        settings.UPLOAD_DIR = "uploads"

        with self.assertRaisesRegex(RuntimeError, "APP_ENV"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_missing_celery_queue(self):
        settings = self._runtime_settings("prod")
        settings.CELERY_QUEUE = ""

        with self.assertRaisesRegex(RuntimeError, "CELERY_QUEUE"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_missing_celery_worker_name(self):
        settings = self._runtime_settings("dev")
        settings.CELERY_WORKER_NAME = ""

        with self.assertRaisesRegex(RuntimeError, "CELERY_WORKER_NAME"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_crossed_celery_queues(self):
        settings = self._runtime_settings("prod")
        settings.CELERY_QUEUE = "celery_dev"

        with self.assertRaisesRegex(RuntimeError, "CELERY_QUEUE"):
            config.validate_runtime_isolation(settings)

        settings = self._runtime_settings("dev")
        settings.CELERY_QUEUE = "celery_prod"

        with self.assertRaisesRegex(RuntimeError, "CELERY_QUEUE"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_default_celery_queue(self):
        settings = self._runtime_settings("prod")
        settings.CELERY_QUEUE = "celery"

        with self.assertRaisesRegex(RuntimeError, "CELERY_QUEUE"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_rejects_crossed_or_default_worker_names(self):
        settings = self._runtime_settings("prod")
        settings.CELERY_WORKER_NAME = "worker_dev"

        with self.assertRaisesRegex(RuntimeError, "CELERY_WORKER_NAME"):
            config.validate_runtime_isolation(settings)

        settings = self._runtime_settings("dev")
        settings.CELERY_WORKER_NAME = "worker"

        with self.assertRaisesRegex(RuntimeError, "CELERY_WORKER_NAME"):
            config.validate_runtime_isolation(settings)

    def test_environment_validation_accepts_correct_prod_and_dev_celery_isolation(self):
        config.validate_runtime_isolation(self._runtime_settings("prod"))
        config.validate_runtime_isolation(self._runtime_settings("dev"))

    def test_runtime_summary_does_not_expose_database_password(self):
        settings = config.Settings()
        settings.APP_ENV = "prod"
        settings.DATABASE_URL = "postgresql+psycopg2://user:secret@localhost:5432/product_knowledge"
        settings.REDIS_URL = "redis://localhost:6379/0"
        settings.UPLOAD_DIR = "uploads"
        settings.BACKEND_PORT = 8000
        settings.CELERY_QUEUE = "celery_prod"
        settings.CELERY_WORKER_NAME = "worker_prod"
        settings.LOG_DIR = "logs/prod"

        summary = config.runtime_summary(settings)

        self.assertEqual(summary["database"], "product_knowledge")
        self.assertNotIn("secret", str(summary))
