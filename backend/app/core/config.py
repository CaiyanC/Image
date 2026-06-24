import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")


def _resolve_env_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def _load_runtime_env() -> str:
    """Load the intended backend env file regardless of the current cwd.

    Batch launchers still set env vars explicitly. This fallback mainly protects
    Python scripts run from the project root, where python-dotenv would otherwise
    miss backend/.env.dev and silently fall back to sqlite defaults.
    """
    explicit = (os.getenv("CAIYAN_ENV_FILE") or os.getenv("ENV_FILE") or "").strip()
    if explicit:
        resolved = _resolve_env_path(explicit)
        load_dotenv(resolved, override=False)
        return resolved

    app_env = os.getenv("APP_ENV", "").strip().lower()
    if app_env == "prod":
        candidates = [os.path.join(BACKEND_ROOT, ".env")]
    elif app_env == "dev":
        candidates = [os.path.join(BACKEND_ROOT, ".env.dev")]
    else:
        candidates = [
            os.path.join(BACKEND_ROOT, ".env.dev"),
            os.path.join(BACKEND_ROOT, ".env"),
        ]

    for candidate in candidates:
        if os.path.exists(candidate):
            load_dotenv(candidate, override=False)
            return candidate
    load_dotenv(override=False)
    return ""


LOADED_ENV_FILE = _load_runtime_env()


class Settings:
    APP_NAME: str = "AI Image & Video Generation Platform"
    APP_ENV: str = os.getenv("APP_ENV", "").strip().lower()
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
    CELERY_QUEUE: str = os.getenv("CELERY_QUEUE", "").strip()
    CELERY_WORKER_NAME: str = os.getenv("CELERY_WORKER_NAME", "").strip()
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ENABLE_PUBLIC_REGISTRATION: bool = os.getenv("ENABLE_PUBLIC_REGISTRATION", "false").lower() == "true"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    AI_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30"))
    AI_REQUEST_QUEUE_TIMEOUT_SECONDS: float = float(os.getenv("AI_REQUEST_QUEUE_TIMEOUT_SECONDS", "8"))
    EMBEDDING_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("EMBEDDING_REQUEST_TIMEOUT_SECONDS", "8"))
    AI_MAX_CONCURRENT_REQUESTS: int = int(os.getenv("AI_MAX_CONCURRENT_REQUESTS", "10"))

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./app.db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "uploads"),
    )
    IMAGE_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "images")
    VIDEO_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "videos")
    GENERATED_DIR: str = os.path.join(UPLOAD_DIR, "generated")

    DMXAPI_BASE_URL: str = os.getenv("DMXAPI_BASE_URL", "https://www.dmxapi.cn")
    DMXAPI_API_KEY: str = os.getenv("DMXAPI_API_KEY", "")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

    DMXAPI_TXT2IMG_TIMEOUT: int = int(os.getenv("DMXAPI_TXT2IMG_TIMEOUT", "300"))
    DMXAPI_IMG2IMG_READ_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_READ_TIMEOUT", "1200"))
    DMXAPI_IMG2IMG_CONNECT_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_CONNECT_TIMEOUT", "60"))

    DEFAULT_ADMIN_USERNAME: str = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

    CORS_ORIGINS: list = [
        "http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.3.216:3000",
        "http://localhost:3001", "http://127.0.0.1:3001",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://192.168.3.109:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
        "http://192.168.3.109:5175",
        "http://localhost:5275", "http://127.0.0.1:5275",
        "http://192.168.3.109:5275",
        "http://localhost:5176", "http://127.0.0.1:5176",
        "http://192.168.3.109:5176",
    ]


def resolve_project_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def database_name_from_url(database_url: str) -> str:
    try:
        return make_url(database_url).database or ""
    except Exception:
        return ""


def _upload_dir_name(upload_dir: str) -> str:
    normalized = os.path.normpath(upload_dir)
    return os.path.basename(normalized).lower()


def validate_runtime_isolation(current_settings: Settings) -> None:
    app_env = current_settings.APP_ENV
    if app_env not in {"prod", "dev"}:
        raise RuntimeError("APP_ENV must be prod or dev")

    database_name = database_name_from_url(current_settings.DATABASE_URL)
    upload_name = _upload_dir_name(current_settings.UPLOAD_DIR)

    if app_env == "dev" and database_name == "product_knowledge":
        raise RuntimeError("Refusing to start dev environment with production database product_knowledge")
    if app_env == "prod" and database_name == "product_knowledge_dev":
        raise RuntimeError("Refusing to start prod environment with development database product_knowledge_dev")
    if app_env == "dev" and upload_name == "uploads":
        raise RuntimeError("Refusing to start dev environment with production UPLOAD_DIR=uploads")
    if app_env == "prod" and upload_name == "uploads_dev":
        raise RuntimeError("Refusing to start prod environment with development UPLOAD_DIR=uploads_dev")

    expected_celery_queue = {"prod": "celery_prod", "dev": "celery_dev"}[app_env]
    expected_worker_name = {"prod": "worker_prod", "dev": "worker_dev"}[app_env]

    if not current_settings.CELERY_QUEUE:
        raise RuntimeError("CELERY_QUEUE must be explicitly configured")
    if current_settings.CELERY_QUEUE != expected_celery_queue:
        raise RuntimeError(
            f"Refusing to start {app_env} environment with CELERY_QUEUE={current_settings.CELERY_QUEUE}; "
            f"expected {expected_celery_queue}"
        )
    if not current_settings.CELERY_WORKER_NAME:
        raise RuntimeError("CELERY_WORKER_NAME must be explicitly configured")
    if current_settings.CELERY_WORKER_NAME != expected_worker_name:
        raise RuntimeError(
            f"Refusing to start {app_env} environment with CELERY_WORKER_NAME={current_settings.CELERY_WORKER_NAME}; "
            f"expected {expected_worker_name}"
        )


def runtime_summary(current_settings: Settings) -> dict:
    return {
        "app_env": current_settings.APP_ENV,
        "database": database_name_from_url(current_settings.DATABASE_URL),
        "upload_dir": current_settings.UPLOAD_DIR,
        "backend_port": current_settings.BACKEND_PORT,
        "redis_url": current_settings.REDIS_URL,
        "celery_queue": current_settings.CELERY_QUEUE,
        "celery_worker_name": current_settings.CELERY_WORKER_NAME,
        "log_dir": current_settings.LOG_DIR,
    }


settings = Settings()
