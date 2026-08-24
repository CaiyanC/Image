import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from .core.config import (
    BACKEND_ROOT,
    PROJECT_ROOT,
    resolve_project_path,
    runtime_summary,
    settings,
    validate_runtime_isolation,
    validate_security_settings,
)
from .core.database import init_db, SessionLocal
from .core.permission_constants import MANAGEMENT_GROUP_NAME, PRODUCT_TEAM_GROUP_NAME
from .core.security import get_current_super_admin, get_password_hash
from .models.user import User
from .api import auth, users, generation, history, admin, products, groups, categories, drafts, customer_service, knowledge_base, files, assets, asset_search, tools, admin_tools, model_governance
from .services import knowledge_service

def _configure_error_logging() -> None:
    logs_dir = resolve_project_path(settings.LOG_DIR)
    os.makedirs(logs_dir, exist_ok=True)
    handler = TimedRotatingFileHandler(
        os.path.join(logs_dir, "error.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for logger_name in ("uvicorn.error", "uvicorn", "app"):
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


_configure_error_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.APP_ENV == "prod" else "/docs",
    redoc_url=None if settings.APP_ENV == "prod" else "/redoc",
    openapi_url=None if settings.APP_ENV == "prod" else "/openapi.json",
)
STARTED_AT = datetime.now(timezone.utc).isoformat()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_cookie_origin(request: Request, call_next):
    if (
        request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        and request.cookies.get(settings.AUTH_COOKIE_NAME)
        and not request.headers.get("authorization", "").lower().startswith("bearer ")
    ):
        origin = (request.headers.get("origin") or "").rstrip("/")
        if origin not in settings.CORS_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Invalid request origin"})
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.APP_ENV == "prod":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if settings.AUTH_COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith(("/api/auth", "/api/admin")) or request.url.path == "/api/health/version":
        response.headers["Cache-Control"] = "no-store"
    return response

os.makedirs(settings.IMAGE_UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.GENERATED_DIR, exist_ok=True)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(generation.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(drafts.router)
app.include_router(products.router)
app.include_router(assets.router)
app.include_router(asset_search.router)
app.include_router(groups.router)
app.include_router(categories.router)
app.include_router(customer_service.router)
app.include_router(knowledge_base.router)
app.include_router(files.router)
app.include_router(tools.router)
app.include_router(admin_tools.router)
app.include_router(model_governance.router)
app.include_router(model_governance.admin_router)


def _redact_api_key_value(value):
    if isinstance(value, dict):
        return {key: "***" if key == "api_key" else _redact_api_key_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_api_key_value(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        sanitized = dict(error)
        if "input" in sanitized:
            sanitized["input"] = (
                "***" if "api_key" in sanitized.get("loc", ())
                else _redact_api_key_value(sanitized["input"])
            )
        errors.append(sanitized)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger("app").exception("Unhandled request error: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "系统暂时繁忙，请稍后再试。如持续出现，请联系管理员。"},
    )


def seed_default_categories():
    from .models.product_category import ProductCategory
    defaults = [
        "待分类", "餐具", "茶具", "炊具", "锅具",
        "酒具", "炉具", "水具", "咖啡器具", "户外家具",
        "收纳包具", "登山杖", "电商专供", "经销商专供", "配件",
    ]
    db = SessionLocal()
    try:
        if not db.query(ProductCategory).first():
            for name in defaults:
                db.add(ProductCategory(category_name=name))
            db.commit()
    finally:
        db.close()


def seed_default_admin():
    if not settings.DEFAULT_ADMIN_PASSWORD or not settings.ALLOW_ADMIN_BOOTSTRAP:
        return
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.DEFAULT_ADMIN_USERNAME).first()
        if not existing:
            admin = User(
                username=settings.DEFAULT_ADMIN_USERNAME,
                email=settings.DEFAULT_ADMIN_EMAIL,
                password_hash=get_password_hash(settings.DEFAULT_ADMIN_PASSWORD),
                user_type="human",
                display_name="系统管理员",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)

            # Assign the bootstrap admin to the executive office and product department.
            from .models.group import Group as GroupModel
            from .models.user_group import UserGroup
            management = db.query(GroupModel).filter(GroupModel.group_name == MANAGEMENT_GROUP_NAME).first()
            product_manager = db.query(GroupModel).filter(GroupModel.group_name == PRODUCT_TEAM_GROUP_NAME).first()
            if management:
                db.add(UserGroup(user_id=admin.id, group_id=management.id, group_role="admin"))
            if product_manager:
                db.add(UserGroup(user_id=admin.id, group_id=product_manager.id, group_role="admin"))
            db.commit()
    finally:
        db.close()


def startup():
    validate_security_settings(settings)
    validate_runtime_isolation(settings)
    summary = runtime_summary(settings)
    runtime_message = (
        "Runtime config: "
        f"APP_ENV={summary['app_env']} "
        f"database={summary['database']} "
        f"UPLOAD_DIR={summary['upload_dir']} "
        f"BACKEND_PORT={summary['backend_port']} "
        f"REDIS_URL={summary['redis_url']} "
        f"CELERY_QUEUE={summary['celery_queue']} "
        f"CELERY_WORKER_NAME={summary['celery_worker_name']} "
        f"LOG_DIR={summary['log_dir']}"
    )
    print(runtime_message, flush=True)
    logging.getLogger("app").info(runtime_message)
    _log_version_check()
    init_db()
    from .services import dmxapi_service
    from .services import knowledge_job_service
    from .services import model_governance_service
    db = SessionLocal()
    try:
        legacy_migration = dmxapi_service.migrate_legacy_model_credentials(db)
        credential_migration = model_governance_service.migrate_provider_credential_encryption(db)
        if legacy_migration["failed"] or credential_migration["failed"]:
            raise RuntimeError("One or more legacy model credentials could not be encrypted")
        migrated_count = legacy_migration["migrated"] + credential_migration["migrated"]
        if migrated_count:
            logging.getLogger("app").info(
                "Encrypted or rewrapped %s model credential(s)", migrated_count
            )
        recovered_jobs = knowledge_job_service.recover_stale_jobs(db)
        if recovered_jobs:
            logging.getLogger("app").warning(
                "Marked %s stale knowledge job(s) as interrupted", recovered_jobs
            )
    finally:
        db.close()
    seed_default_categories()
    seed_default_admin()


def _live_payload() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}


def _ready_payload() -> dict:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        vector = knowledge_service.vector_status(db)
        return {
            "status": "ok" if vector.get("available") else "degraded",
            "app": settings.APP_NAME,
            "database": "ok",
            "vector": vector,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "app": settings.APP_NAME,
                "database": "error",
                "error": str(exc),
            },
        ) from exc
    finally:
        db.close()


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return "unknown"
    return (result.stdout or "").strip() or "unknown"


def _get_current_git_head() -> str:
    return (
        os.getenv("APP_COMMIT")
        or os.getenv("GIT_COMMIT")
        or _run_git(["rev-parse", "HEAD"])
    ) or "unknown"


def _get_current_git_branch() -> str:
    return (
        os.getenv("APP_BRANCH")
        or os.getenv("GIT_BRANCH")
        or _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    ) or "unknown"


def _build_startup_runtime_info() -> dict:
    return {
        "version": app.version,
        "startup_commit": _get_current_git_head(),
        "startup_branch": _get_current_git_branch(),
        "code_root": BACKEND_ROOT,
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "pid": os.getpid(),
        "started_at": STARTED_AT,
        "env": settings.APP_ENV,
        "backend_port": settings.BACKEND_PORT,
    }


STARTUP_RUNTIME_INFO = _build_startup_runtime_info()


def _runtime_version_payload() -> dict:
    current_git_head = _get_current_git_head()
    current_git_branch = _get_current_git_branch()
    startup_commit = STARTUP_RUNTIME_INFO.get("startup_commit") or "unknown"
    startup_branch = STARTUP_RUNTIME_INFO.get("startup_branch") or "unknown"
    return {
        "version": STARTUP_RUNTIME_INFO.get("version") or app.version,
        "startup_commit": startup_commit,
        "current_git_head": current_git_head or "unknown",
        "commit": startup_commit,
        "commit_source": "startup_commit",
        "branch": startup_branch,
        "current_git_branch": current_git_branch or "unknown",
        "code_root": STARTUP_RUNTIME_INFO.get("code_root") or BACKEND_ROOT,
        "cwd": STARTUP_RUNTIME_INFO.get("cwd") or os.getcwd(),
        "python_executable": STARTUP_RUNTIME_INFO.get("python_executable") or sys.executable,
        "pid": STARTUP_RUNTIME_INFO.get("pid") or os.getpid(),
        "started_at": STARTUP_RUNTIME_INFO.get("started_at") or STARTED_AT,
        "env": STARTUP_RUNTIME_INFO.get("env") or settings.APP_ENV,
        "backend_port": STARTUP_RUNTIME_INFO.get("backend_port") or settings.BACKEND_PORT,
    }


def _public_version_payload() -> dict:
    return {
        "version": STARTUP_RUNTIME_INFO.get("version") or app.version,
        "commit": STARTUP_RUNTIME_INFO.get("startup_commit") or "unknown",
        "env": STARTUP_RUNTIME_INFO.get("env") or settings.APP_ENV,
    }


def _log_version_check() -> None:
    payload = _runtime_version_payload()
    message = (
        "RUNNING VERSION CHECK "
        f"commit={payload['commit']} "
        f"branch={payload['branch']} "
        f"current_git_head={payload['current_git_head']} "
        f"current_git_branch={payload['current_git_branch']} "
        f"commit_source={payload['commit_source']} "
        f"code_root={payload['code_root']} "
        f"cwd={payload['cwd']} "
        f"pid={payload['pid']} "
        f"python={payload['python_executable']} "
        f"env={payload['env']} "
        f"port={payload['backend_port']}"
    )
    logging.getLogger("app").info(message)
    log_dir = resolve_project_path(settings.LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "backend_version.log"), "a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


@app.get("/api/health")
def health_check():
    return _live_payload()


@app.get("/api/health/live")
def live_check():
    return _live_payload()


@app.get("/api/health/ready")
def ready_check():
    return _ready_payload()


@app.get("/api/health/version")
def version_check():
    return _public_version_payload()


@app.get("/api/admin/runtime/version")
def admin_version_check(_: User = Depends(get_current_super_admin)):
    return _runtime_version_payload()
