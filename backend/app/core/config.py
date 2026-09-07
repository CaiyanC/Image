import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")


def resolve_backend_path(path: str) -> str:
    """Resolve runtime data paths independently from the process cwd.

    Backend env files intentionally use short values such as ``uploads_dev``.
    Those values must always mean ``backend/uploads_dev`` whether Uvicorn was
    launched from the project root, the backend directory, or a test runner.
    """
    if os.path.isabs(path):
        return os.path.abspath(path)
    normalized = os.path.normpath(path)
    if normalized.split(os.sep, 1)[0].lower() == "backend":
        return os.path.abspath(os.path.join(PROJECT_ROOT, normalized))
    return os.path.abspath(os.path.join(BACKEND_ROOT, normalized))


def _resolve_env_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    # CLI tools are commonly launched from ``backend`` with a short value
    # such as ``.env.dev``.  Prefer an explicitly existing path relative to
    # the caller's working directory, then fall back to the project root for
    # launchers that run from the repository root.  This keeps environment
    # selection deterministic without silently loading a default config.
    cwd_candidate = os.path.abspath(path)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
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


def _csv_setting(name: str, default: str) -> list[str]:
    return [item.strip().rstrip("/") for item in os.getenv(name, default).split(",") if item.strip()]


_RUNTIME_APP_ENV = os.getenv("APP_ENV", "").strip().lower()
_DEFAULT_LEGACY_KNOWLEDGE_FILE_DIR = (
    os.path.join(
        os.path.dirname(PROJECT_ROOT),
        "data",
        f"caiyan-{_RUNTIME_APP_ENV}",
        "knowledge-files",
    )
    if _RUNTIME_APP_ENV in {"dev", "prod"}
    else ""
)


def _cors_origins(default: str) -> list[str]:
    origins = _csv_setting("CORS_ORIGINS", default)
    if "*" in origins:
        raise ValueError("CORS_ORIGINS cannot contain '*' when credentials are enabled")
    return origins


class Settings:
    APP_NAME: str = "AI Image & Video Generation Platform"
    APP_ENV: str = os.getenv("APP_ENV", "").strip().lower()
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
    CELERY_QUEUE: str = os.getenv("CELERY_QUEUE", "").strip()
    CELERY_WORKER_NAME: str = os.getenv("CELERY_WORKER_NAME", "").strip()
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    MODEL_CREDENTIAL_ENCRYPTION_KEY: str = os.getenv("MODEL_CREDENTIAL_ENCRYPTION_KEY", "").strip()
    ALLOW_PRIVATE_MODEL_ENDPOINTS: bool = os.getenv("ALLOW_PRIVATE_MODEL_ENDPOINTS", "false").lower() == "true"
    ALLOW_INSECURE_MODEL_ENDPOINTS: bool = os.getenv("ALLOW_INSECURE_MODEL_ENDPOINTS", "false").lower() == "true"
    ALGORITHM: str = "HS256"
    ENABLE_PUBLIC_REGISTRATION: bool = os.getenv("ENABLE_PUBLIC_REGISTRATION", "false").lower() == "true"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    AUTH_TOKEN_ISSUER: str = os.getenv(
        "AUTH_TOKEN_ISSUER", f"caiyan-auth-{APP_ENV or 'unknown'}"
    ).strip()
    AUTH_TOKEN_AUDIENCE: str = os.getenv(
        "AUTH_TOKEN_AUDIENCE", f"caiyan-api-{APP_ENV or 'unknown'}"
    ).strip()
    AUTH_COOKIE_NAME: str = os.getenv(
        "AUTH_COOKIE_NAME", f"caiyan_session_{APP_ENV or 'unknown'}"
    ).strip()
    AUTH_COOKIE_SECURE: bool = os.getenv(
        "AUTH_COOKIE_SECURE", "true" if APP_ENV == "prod" else "false"
    ).lower() == "true"
    AUTH_COOKIE_SAMESITE: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    ALLOW_INSECURE_LOCAL_PROD: bool = os.getenv("ALLOW_INSECURE_LOCAL_PROD", "false").lower() == "true"
    ALLOW_ADMIN_BOOTSTRAP: bool = os.getenv("ALLOW_ADMIN_BOOTSTRAP", "false").lower() == "true"
    # Flash preplanning and the bounded answer writer can occasionally need
    # more than the old 30-second transport window. A premature timeout is
    # more damaging here than a modestly slower answer because it activates
    # the outage compatibility layer and can discard the semantic result.
    # Keep the value environment-overridable for deployments with a different
    # latency SLO.
    AI_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "45"))
    AI_REQUEST_QUEUE_TIMEOUT_SECONDS: float = float(os.getenv("AI_REQUEST_QUEUE_TIMEOUT_SECONDS", "8"))
    EMBEDDING_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("EMBEDDING_REQUEST_TIMEOUT_SECONDS", "8"))
    AI_MAX_CONCURRENT_REQUESTS: int = int(os.getenv("AI_MAX_CONCURRENT_REQUESTS", "10"))
    KNOWLEDGE_JOB_STALE_MINUTES: int = int(os.getenv("KNOWLEDGE_JOB_STALE_MINUTES", "120"))
    SEMANTIC_PREPLAN_MODEL: str = os.getenv("SEMANTIC_PREPLAN_MODEL", "deepseek-v4-flash").strip()
    # The semantic contract contains route, entity, field, provenance, and
    # recommendation dimensions.  256 tokens can truncate valid JSON into a
    # bare label, which must then fail closed; reserve enough room for the
    # complete structured contract instead of dropping its constraints.
    SEMANTIC_PREPLAN_MAX_TOKENS: int = int(os.getenv("SEMANTIC_PREPLAN_MAX_TOKENS", "768"))
    SEMANTIC_PREPLAN_TEMPERATURE: float = float(os.getenv("SEMANTIC_PREPLAN_TEMPERATURE", "0"))
    SEMANTIC_PREPLAN_JSON_MODE: bool = os.getenv("SEMANTIC_PREPLAN_JSON_MODE", "true").lower() == "true"
    SEMANTIC_PREPLAN_THINKING_DISABLED: bool = os.getenv("SEMANTIC_PREPLAN_THINKING_DISABLED", "true").lower() == "true"
    # Customer-service pipeline selection is an operational switch.  Development
    # must exercise the established semantic-RAG baseline by default; production
    # keeps the legacy value until an explicit release changes its configuration.
    # This is an environment default, not a question router.
    CUSTOMER_SERVICE_PIPELINE: str = os.getenv(
        "CUSTOMER_SERVICE_PIPELINE",
        "semantic_rag_v2" if APP_ENV == "dev" else "legacy",
    ).strip().lower()
    CUSTOMER_SERVICE_PIPELINE_OVERRIDE_ENABLED: bool = os.getenv(
        "CUSTOMER_SERVICE_PIPELINE_OVERRIDE_ENABLED",
        "true" if APP_ENV == "dev" else "false",
    ).lower() == "true"
    CUSTOMER_SERVICE_V2_MAX_HISTORY_MESSAGES: int = int(
        os.getenv("CUSTOMER_SERVICE_V2_MAX_HISTORY_MESSAGES", "12")
    )
    CUSTOMER_SERVICE_V2_MAX_RETRIEVAL_ROWS: int = int(
        os.getenv("CUSTOMER_SERVICE_V2_MAX_RETRIEVAL_ROWS", "8")
    )
    # WorkBuddy keeps a wider candidate recall page than the existing semantic
    # baseline.  The answer prompt remains bounded separately, so this
    # improves catalogue recall without adding another model call.
    CUSTOMER_SERVICE_WORKBUDDY_MAX_RETRIEVAL_ROWS: int = int(
        os.getenv("CUSTOMER_SERVICE_WORKBUDDY_MAX_RETRIEVAL_ROWS", "16")
    )
    CUSTOMER_SERVICE_WORKBUDDY_MAX_ANSWER_TOKENS: int = int(
        os.getenv("CUSTOMER_SERVICE_WORKBUDDY_MAX_ANSWER_TOKENS", "320")
    )
    CUSTOMER_SERVICE_WORKBUDDY_REASONING_EFFORT: str = os.getenv(
        "CUSTOMER_SERVICE_WORKBUDDY_REASONING_EFFORT", "none"
    ).strip().lower()
    # Optional non-factual RAG guidance for conversational strategy. Product
    # facts remain exclusively in the existing evidence packet, and the
    # feature can be disabled without changing any of the three pipelines.
    CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED: bool = os.getenv(
        "CUSTOMER_SERVICE_EXPERIENCE_RAG_ENABLED", "false"
    ).lower() == "true"
    CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS: int = int(
        os.getenv("CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CARDS", "1")
    )
    CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CHARS: int = int(
        os.getenv("CUSTOMER_SERVICE_EXPERIENCE_RAG_MAX_CHARS", "1200")
    )
    # Experience guidance is optional conversational context, not product
    # evidence. Require a real vector-retrieval score before it can enter a
    # prompt so lexical fallback rows cannot bypass the relevance boundary.
    CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE: float = float(
        os.getenv("CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_SCORE", "0.50")
    )
    CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_MARGIN: float = float(
        os.getenv("CUSTOMER_SERVICE_EXPERIENCE_RAG_MIN_MARGIN", "0.02")
    )

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./app.db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    UPLOAD_DIR: str = resolve_backend_path(os.getenv("UPLOAD_DIR", "uploads"))
    IMAGE_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "images")
    VIDEO_UPLOAD_DIR: str = os.path.join(UPLOAD_DIR, "videos")
    GENERATED_DIR: str = os.path.join(UPLOAD_DIR, "generated")
    # Keep knowledge-base source files outside disposable app/worktree folders.
    # Deployments can override this independently from image/video uploads.
    KNOWLEDGE_FILE_DIR: str = resolve_backend_path(os.getenv(
        "KNOWLEDGE_FILE_DIR",
        os.path.join(UPLOAD_DIR, "knowledge-files"),
    ))
    # Knowledge files may have been uploaded by an older runtime into the
    # per-environment data directory.  Keep the compatibility roots explicit
    # and bounded; never allow an arbitrary filesystem path from the database
    # to become downloadable.
    KNOWLEDGE_FILE_LEGACY_DIRS: list[str] = [
        resolve_backend_path(item)
        for item in _csv_setting(
            "KNOWLEDGE_FILE_LEGACY_DIRS",
            _DEFAULT_LEGACY_KNOWLEDGE_FILE_DIR,
        )
    ]

    DMXAPI_BASE_URL: str = os.getenv("DMXAPI_BASE_URL", "https://www.dmxapi.cn")
    DMXAPI_API_KEY: str = os.getenv("DMXAPI_API_KEY", "")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

    DMXAPI_TXT2IMG_TIMEOUT: int = int(os.getenv("DMXAPI_TXT2IMG_TIMEOUT", "300"))
    DMXAPI_IMG2IMG_READ_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_READ_TIMEOUT", "1200"))
    DMXAPI_IMG2IMG_CONNECT_TIMEOUT: int = int(os.getenv("DMXAPI_IMG2IMG_CONNECT_TIMEOUT", "60"))

    DEFAULT_ADMIN_USERNAME: str = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")

    CORS_ORIGINS_EXPLICIT: bool = bool(os.getenv("CORS_ORIGINS", "").strip())
    CORS_ORIGINS: list[str] = _cors_origins(
        ",".join((
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:3001", "http://127.0.0.1:3001",
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5174", "http://127.0.0.1:5174",
            "http://localhost:5175", "http://127.0.0.1:5175",
            "http://localhost:5176", "http://127.0.0.1:5176",
            "http://localhost:5275", "http://127.0.0.1:5275",
            "http://localhost:5276", "http://127.0.0.1:5276",
        )),
    )


def resolve_project_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


def database_name_from_url(database_url: str) -> str:
    try:
        return make_url(database_url).database or ""
    except Exception:
        return ""


def redis_database_from_url(redis_url: str) -> int:
    """Return the Redis logical database, treating an omitted DB as 0.

    Redis is shared by the local deployment, so the logical DB is part of the
    dev/prod isolation contract just like the PostgreSQL database and Celery
    queue.  Fail closed for malformed or non-integer database components
    rather than allowing a process to start against an ambiguous namespace.
    """
    try:
        parsed = make_url(redis_url)
    except Exception as exc:
        raise RuntimeError("REDIS_URL is invalid") from exc
    database = parsed.database
    if database in (None, ""):
        return 0
    try:
        return int(database)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("REDIS_URL database must be an integer") from exc


def safe_runtime_url(url: str) -> str:
    """Render a runtime URL without credentials for logs and diagnostics."""
    try:
        parsed = make_url(url)
        host = parsed.host or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        database = f"/{parsed.database}" if parsed.database not in (None, "") else ""
        return f"{parsed.drivername}://{host}{database}"
    except Exception:
        return "<invalid>"


def _upload_dir_name(upload_dir: str) -> str:
    normalized = os.path.normpath(upload_dir)
    return os.path.basename(normalized).lower()


def validate_runtime_isolation(current_settings: Settings) -> None:
    app_env = current_settings.APP_ENV
    if app_env not in {"prod", "dev", "preview"}:
        raise RuntimeError("APP_ENV must be prod, dev, or preview")

    database_name = database_name_from_url(current_settings.DATABASE_URL)
    upload_name = _upload_dir_name(current_settings.UPLOAD_DIR)
    redis_database = redis_database_from_url(current_settings.REDIS_URL)

    if app_env == "dev" and database_name == "product_knowledge":
        raise RuntimeError("Refusing to start dev environment with production database product_knowledge")
    if app_env == "prod" and database_name == "product_knowledge_dev":
        raise RuntimeError("Refusing to start prod environment with development database product_knowledge_dev")
    if app_env == "dev" and upload_name == "uploads":
        raise RuntimeError("Refusing to start dev environment with production UPLOAD_DIR=uploads")
    if app_env == "prod" and upload_name == "uploads_dev":
        raise RuntimeError("Refusing to start prod environment with development UPLOAD_DIR=uploads_dev")
    if app_env == "preview" and (database_name in {"product_knowledge", "product_knowledge_dev"} or upload_name in {"uploads", "uploads_dev"}):
        raise RuntimeError("Preview must use an isolated database and upload directory")

    expected_redis_database = {"prod": 0, "dev": 1, "preview": 2}[app_env]
    if redis_database != expected_redis_database:
        raise RuntimeError(
            f"Refusing to start {app_env} environment with Redis database {redis_database}; "
            f"expected {expected_redis_database}"
        )

    expected_celery_queue = {"prod": "celery_prod", "dev": "celery_dev", "preview": "celery_toolpreview"}[app_env]
    expected_worker_name = {"prod": "worker_prod", "dev": "worker_dev", "preview": "worker_toolpreview"}[app_env]

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


def validate_security_settings(current_settings: Settings) -> None:
    secret = current_settings.SECRET_KEY.strip()
    weak_values = {"", "change-me", "changeme", "secret", "your-secret-key"}
    if len(secret) < 32 or secret.lower() in weak_values:
        raise RuntimeError("SECRET_KEY must be a non-placeholder secret of at least 32 characters")
    if not 5 <= current_settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 480:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 480")
    if current_settings.AUTH_COOKIE_SAMESITE not in {"lax", "strict"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax or strict")
    for name, value in (
        ("AUTH_TOKEN_ISSUER", current_settings.AUTH_TOKEN_ISSUER),
        ("AUTH_TOKEN_AUDIENCE", current_settings.AUTH_TOKEN_AUDIENCE),
        ("AUTH_COOKIE_NAME", current_settings.AUTH_COOKIE_NAME),
    ):
        if not value:
            raise RuntimeError(f"{name} must not be empty")

    if current_settings.APP_ENV != "prod":
        return
    if not current_settings.MODEL_CREDENTIAL_ENCRYPTION_KEY:
        raise RuntimeError("MODEL_CREDENTIAL_ENCRYPTION_KEY must be configured in production")
    if not current_settings.CORS_ORIGINS_EXPLICIT:
        raise RuntimeError("CORS_ORIGINS must be explicitly configured in production")
    if current_settings.DEFAULT_ADMIN_PASSWORD and not current_settings.ALLOW_ADMIN_BOOTSTRAP:
        raise RuntimeError(
            "DEFAULT_ADMIN_PASSWORD must be removed after bootstrap, or ALLOW_ADMIN_BOOTSTRAP explicitly enabled"
        )
    if not current_settings.AUTH_COOKIE_SECURE and not current_settings.ALLOW_INSECURE_LOCAL_PROD:
        raise RuntimeError(
            "Production auth cookies must be Secure unless ALLOW_INSECURE_LOCAL_PROD is explicitly enabled"
        )


def runtime_summary(current_settings: Settings) -> dict:
    return {
        "app_env": current_settings.APP_ENV,
        "database": database_name_from_url(current_settings.DATABASE_URL),
        "upload_dir": current_settings.UPLOAD_DIR,
        "backend_port": current_settings.BACKEND_PORT,
        "redis_url": safe_runtime_url(current_settings.REDIS_URL),
        "redis_database": redis_database_from_url(current_settings.REDIS_URL),
        "celery_queue": current_settings.CELERY_QUEUE,
        "celery_worker_name": current_settings.CELERY_WORKER_NAME,
        "log_dir": current_settings.LOG_DIR,
    }


settings = Settings()
