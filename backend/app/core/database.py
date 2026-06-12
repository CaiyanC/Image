import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)

logger = logging.getLogger("uvicorn")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and seed default data if not present."""
    # Import all models so Base.metadata knows about them
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _ensure_products_compat_columns()
    _init_vector_storage()

    db = SessionLocal()
    try:
        _seed_default_groups(db)
        _seed_default_permissions(db)
    finally:
        db.close()


def _init_vector_storage():
    """Prepare optional pgvector support without blocking normal startup."""
    if not settings.DATABASE_URL.startswith("postgresql"):
        return

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                "ALTER TABLE knowledge_chunks "
                "ADD COLUMN IF NOT EXISTS embedding vector"
            ))
            dimensions = conn.execute(text(
                "SELECT vector_dims(embedding) "
                "FROM knowledge_chunks "
                "WHERE embedding IS NOT NULL "
                "LIMIT 1"
            )).scalar()
            if dimensions and dimensions <= 2000:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding "
                    "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) "
                    "WITH (lists = 100)"
                ))
    except Exception as exc:
        logger.warning("pgvector is not available yet: %s", exc)


def _ensure_products_compat_columns():
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("products")}
        if "quality_note" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE products ADD COLUMN quality_note TEXT"))
    except Exception as exc:
        logger.warning("failed to ensure product compatibility columns: %s", exc)


def _seed_default_groups(db):
    from ..models.group import Group

    default_groups = [
        ("产品团队", "产品管理部门，负责产品元数据录入与维护"),
        ("设计团队", "设计部门，负责产品视觉素材与 AI 生成"),
        ("电商运营", "电商运营岗位"),
        ("海外营销", "海外市场营销"),
        ("AI内容岗", "AI 内容生成岗位"),
        ("客服团队", "客户服务"),
        ("管理层", "管理决策层"),
        ("AI工程师", "AI 技术团队"),
        ("经销商", "外部经销商"),
        ("外部达人", "外部 KOL/达人"),
        ("广告代理商", "广告代理商"),
    ]
    existing = {g.group_name: g for g in db.query(Group).all()}
    changed = False
    for name, desc in default_groups:
        group = existing.get(name)
        if group:
            if not group.description:
                group.description = desc
                changed = True
        else:
            db.add(Group(group_name=name, description=desc))
            changed = True
    if changed:
        db.commit()


def _seed_default_permissions(db):
    from ..models.group import Group
    from ..models.permissions import Permission, GroupPermission
    from ..models.routes import Route, PermissionRoute

    permission_defs = [
        ("history.view", "查看历史记录", "page"),
        ("profile.view", "查看个人资料", "page"),
        ("category.read", "查看产品品类", "api"),
        ("product.read", "查看产品", "page"),
        ("product.create", "创建产品", "button"),
        ("product.edit", "编辑产品", "button"),
        ("product.delete", "删除产品", "button"),
        ("product.review", "审核产品", "button"),
        ("media.upload", "上传素材", "button"),
        ("media.review", "审核素材", "button"),
        ("media.download", "下载素材", "button"),
        ("tag.edit", "编辑标签", "button"),
        ("ai.call", "AI 调用", "api"),
        ("ai.generate", "AI 生图", "api"),
        ("ai.customer_service", "智能客服", "api"),
        ("ai.authorize", "AI 调用授权", "button"),
        ("competitor.view", "查看竞品图", "page"),
        ("new_product.view", "查看新品图", "page"),
        ("export.approved", "导出审批", "button"),
    ]
    permissions = {p.permission_key: p for p in db.query(Permission).all()}
    changed = False
    for key, name, permission_type in permission_defs:
        permission = permissions.get(key)
        if not permission:
            permission = Permission(permission_key=key, permission_name=name, permission_type=permission_type)
            db.add(permission)
            permissions[key] = permission
            changed = True
        else:
            if permission.permission_name != name:
                permission.permission_name = name
                changed = True
            if permission.permission_type != permission_type:
                permission.permission_type = permission_type
                changed = True
    if changed:
        db.commit()

    route_defs = [
        ("/customer-service", "智能客服", "page"),
        ("/", "工作区", "page"),
        ("/history", "历史记录", "page"),
        ("/profile", "个人资料", "page"),
        ("/products", "产品管理", "page"),
        ("/products/create", "新增产品", "page"),
        ("/products/drafts", "草稿箱", "page"),
        ("/admin/users", "用户管理", "page"),
        ("/admin/groups", "用户组管理", "page"),
        ("/admin/settings", "系统设置", "page"),
    ]
    routes = {r.route_path: r for r in db.query(Route).all()}
    changed = False
    for path, name, route_type in route_defs:
        route = routes.get(path)
        if not route:
            route = Route(route_path=path, route_name=name, route_type=route_type)
            db.add(route)
            routes[path] = route
            changed = True
        else:
            if route.route_name != name:
                route.route_name = name
                changed = True
            if route.route_type != route_type:
                route.route_type = route_type
                changed = True
    if changed:
        db.commit()

    group_permission_map = {
        "管理层": [key for key, _, _ in permission_defs],
        "产品团队": [
            "product.read", "product.create", "product.edit", "product.review",
            "media.download", "tag.edit", "ai.call", "ai.generate", "ai.customer_service", "competitor.view", "new_product.view",
        ],
        "设计团队": [
            "product.read", "product.edit", "media.upload", "media.review",
            "media.download", "ai.call", "ai.generate", "ai.customer_service", "new_product.view",
        ],
        "AI工程师": ["ai.call", "ai.generate", "ai.customer_service", "ai.authorize", "media.download", "new_product.view"],
        "AI内容岗": ["product.read", "media.download", "ai.call", "ai.generate", "ai.customer_service", "competitor.view", "new_product.view"],
        "电商运营": ["product.read", "product.edit", "media.download", "ai.call", "ai.generate", "ai.customer_service", "new_product.view"],
        "海外营销": ["product.read", "media.download", "ai.call", "ai.generate", "ai.customer_service", "competitor.view", "new_product.view"],
        "客服团队": ["product.read", "ai.call", "ai.customer_service"],
        "经销商": ["product.read", "media.download"],
        "外部达人": ["product.read", "media.download"],
        "广告代理商": ["product.read", "media.download"],
    }
    for permission_keys in group_permission_map.values():
        permission_keys.extend(["history.view", "profile.view"])
        if "product.read" in permission_keys:
            permission_keys.append("category.read")
    groups = {g.group_name: g for g in db.query(Group).all()}
    permissions = {p.permission_key: p for p in db.query(Permission).all()}
    existing_pairs = {
        (str(gp.group_id), str(gp.permission_id))
        for gp in db.query(GroupPermission).all()
    }
    changed = False
    for group_name, permission_keys in group_permission_map.items():
        group = groups.get(group_name)
        if not group:
            continue
        for permission_key in permission_keys:
            permission = permissions.get(permission_key)
            if not permission:
                continue
            pair = (str(group.id), str(permission.id))
            if pair not in existing_pairs:
                db.add(GroupPermission(group_id=group.id, permission_id=permission.id))
                existing_pairs.add(pair)
                changed = True
    if changed:
        db.commit()

    permission_route_map = {
        "ai.generate": ["/"],
        "ai.customer_service": ["/customer-service"],
        "history.view": ["/history"],
        "profile.view": ["/profile"],
        "product.read": ["/products", "/products/drafts"],
        "product.create": ["/products/create"],
        "product.edit": ["/products/create", "/products/drafts"],
        "product.delete": ["/products"],
    }
    routes = {r.route_path: r for r in db.query(Route).all()}
    existing_pairs = {
        (str(pr.permission_id), str(pr.route_id))
        for pr in db.query(PermissionRoute).all()
    }
    changed = False
    for permission_key, route_paths in permission_route_map.items():
        permission = permissions.get(permission_key)
        if not permission:
            continue
        for route_path in route_paths:
            route = routes.get(route_path)
            if not route:
                continue
            pair = (str(permission.id), str(route.id))
            if pair not in existing_pairs:
                db.add(PermissionRoute(permission_id=permission.id, route_id=route.id))
                existing_pairs.add(pair)
                changed = True
    if changed:
        db.commit()
