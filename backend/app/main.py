import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .core.config import settings
from .core.database import init_db, SessionLocal
from .core.security import get_password_hash
from .models.user import User
from .api import auth, users, generation, history, admin, products, groups, categories, drafts, customer_service, knowledge_base

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
            management = db.query(GroupModel).filter(GroupModel.group_name == "管理层").first()
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


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
