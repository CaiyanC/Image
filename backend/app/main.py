import logging
import os
from logging.handlers import TimedRotatingFileHandler

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .core.config import settings
from .core.database import init_db, SessionLocal
from .core.permission_constants import MANAGEMENT_GROUP_NAME
from .core.security import get_password_hash
from .models.user import User
from .api import auth, users, generation, history, admin, products, groups, categories, drafts, customer_service, knowledge_base
from .services import knowledge_service

def _configure_error_logging() -> None:
    logs_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "logs"))
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

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.IMAGE_UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.GENERATED_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(generation.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(drafts.router)
app.include_router(products.router)
app.include_router(groups.router)
app.include_router(categories.router)
app.include_router(customer_service.router)
app.include_router(knowledge_base.router)


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
    if not settings.DEFAULT_ADMIN_PASSWORD:
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

            # Assign admin to 管理员 group (primary) and 管理层 group
            from .models.group import Group as GroupModel
            from .models.user_group import UserGroup
            management = db.query(GroupModel).filter(GroupModel.group_name == MANAGEMENT_GROUP_NAME).first()
            product_manager = db.query(GroupModel).filter(GroupModel.group_name == "产品经理").first()
            if management:
                db.add(UserGroup(user_id=admin.id, group_id=management.id, group_role="admin"))
            if product_manager:
                db.add(UserGroup(user_id=admin.id, group_id=product_manager.id, group_role="admin"))
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
def startup():
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not set. Please configure it in backend/.env")
    init_db()
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


@app.get("/api/health")
def health_check():
    return _live_payload()


@app.get("/api/health/live")
def live_check():
    return _live_payload()


@app.get("/api/health/ready")
def ready_check():
    return _ready_payload()
