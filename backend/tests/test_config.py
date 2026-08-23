import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from app.core import config


class SettingsConfigTest(unittest.TestCase):
    def _settings_from_clean_process(self, env_updates: dict[str, str]) -> dict:
        env = os.environ.copy()
        env.update(env_updates)
        code = (
            "import json;"
            "from app.core.config import settings;"
            "print(json.dumps({"
            "'APP_ENV': settings.APP_ENV, 'BACKEND_PORT': settings.BACKEND_PORT,"
            "'CELERY_QUEUE': settings.CELERY_QUEUE, 'CELERY_WORKER_NAME': settings.CELERY_WORKER_NAME,"
            "'LOG_DIR': settings.LOG_DIR, 'UPLOAD_DIR': settings.UPLOAD_DIR,"
            "'IMAGE_UPLOAD_DIR': settings.IMAGE_UPLOAD_DIR, 'VIDEO_UPLOAD_DIR': settings.VIDEO_UPLOAD_DIR,"
            "'GENERATED_DIR': settings.GENERATED_DIR, 'BACKEND_ROOT': __import__('app.core.config', fromlist=['BACKEND_ROOT']).BACKEND_ROOT"
            "}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])

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
        loaded = self._settings_from_clean_process({"UPLOAD_DIR": custom_upload_dir})

        resolved_upload_dir = os.path.join(config.PROJECT_ROOT, custom_upload_dir)
        self.assertEqual(os.path.normpath(loaded["UPLOAD_DIR"]), os.path.normpath(resolved_upload_dir))
        self.assertEqual(
            os.path.normpath(loaded["IMAGE_UPLOAD_DIR"]),
            os.path.join(resolved_upload_dir, "images"),
        )
        self.assertEqual(
            os.path.normpath(loaded["VIDEO_UPLOAD_DIR"]),
            os.path.join(resolved_upload_dir, "videos"),
        )
        self.assertEqual(
            os.path.normpath(loaded["GENERATED_DIR"]),
            os.path.join(resolved_upload_dir, "generated"),
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
        loaded = self._settings_from_clean_process(env)

        self.assertEqual(loaded["APP_ENV"], "dev")
        self.assertEqual(loaded["BACKEND_PORT"], 8001)
        self.assertEqual(loaded["CELERY_QUEUE"], "celery_dev")
        self.assertEqual(loaded["CELERY_WORKER_NAME"], "worker_dev")
        self.assertEqual(os.path.normpath(loaded["LOG_DIR"]), os.path.normpath("logs/dev"))
        self.assertEqual(
            os.path.normpath(loaded["UPLOAD_DIR"]),
            os.path.normpath(os.path.join(loaded["BACKEND_ROOT"], "uploads_dev")),
        )

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

    def test_project_root_script_import_loads_dev_env_instead_of_sqlite_default(self):
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        for key in (
            "APP_ENV",
            "DATABASE_URL",
            "BACKEND_PORT",
            "REDIS_URL",
            "CELERY_QUEUE",
            "CELERY_WORKER_NAME",
            "UPLOAD_DIR",
            "LOG_DIR",
            "CAIYAN_ENV_FILE",
            "ENV_FILE",
        ):
            env.pop(key, None)
        code = (
            "import sys;"
            "sys.path.insert(0, 'backend');"
            "from app.core.config import settings;"
            "print(settings.APP_ENV);"
            "print(settings.BACKEND_PORT);"
            "print(settings.DATABASE_URL)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "dev")
        self.assertEqual(lines[1], "8001")
        self.assertIn("product_knowledge_dev", lines[2])
        self.assertNotIn("sqlite", lines[2].lower())
