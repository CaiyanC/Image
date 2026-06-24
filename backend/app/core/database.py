import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from .config import settings
from .permission_constants import (
    COMMON_PERMISSION_KEYS,
    DEFAULT_GROUPS,
    GROUP_PERMISSION_KEYS,
    PERMISSION_DEFS,
    PERMISSION_ROUTE_MAP,
    ROUTE_DEFS,
)

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    hide_parameters=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=30,
)

logger = logging.getLogger("uvicorn")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def release_session_connection(db: Session) -> None:
    """Return the current DB connection to the pool while keeping the Session reusable."""
    try:
        db.close()
    except Exception as exc:
        logger.warning("failed to release database session connection: %s", exc)


def init_db():
    """Create all tables and seed default data if not present."""
    lock_conn = _acquire_init_lock()
    try:
        # Import all models so Base.metadata knows about them
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        _ensure_products_compat_columns()
        _ensure_product_assets_compat()
        _init_vector_storage()

        db = SessionLocal()
        try:
            _seed_default_groups(db)
            _seed_default_permissions(db)
        finally:
            db.close()
    finally:
        _release_init_lock(lock_conn)


def _acquire_init_lock():
    if not settings.DATABASE_URL.startswith("postgresql"):
        return None
    conn = engine.connect()
    conn.execute(text("SELECT pg_advisory_lock(2026061301)"))
    return conn


def _release_init_lock(conn) -> None:
    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(2026061301)"))
    finally:
        conn.close()


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


def _ensure_product_assets_compat():
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if "product_assets" not in table_names:
            return
        existing_columns = {column["name"] for column in inspector.get_columns("product_assets")}
        expected_columns = {
            "id": "VARCHAR(36) PRIMARY KEY",
            "sku": "VARCHAR(64) NOT NULL",
            "category_code": "VARCHAR(2) NOT NULL",
            "category_name": "VARCHAR(64) NOT NULL",
            "sub_category": "VARCHAR(64)",
            "asset_type": "VARCHAR(10) DEFAULT 'image'",
            "url": "TEXT",
            "thumbnail_url": "TEXT",
            "brand": "VARCHAR(64) DEFAULT 'alocs'",
            "material_type": "VARCHAR(64)",
            "angle_scene": "VARCHAR(128)",
            "channel": "VARCHAR(64)",
            "language_tag": "VARCHAR(32)",
            "version_tag": "VARCHAR(32)",
            "date_tag": "VARCHAR(16)",
            "status_tag": "VARCHAR(32)",
            "seq": "INTEGER DEFAULT 0",
            "sort_order": "INTEGER DEFAULT 0",
            "tags": "TEXT DEFAULT '{}'",
            "notes": "TEXT",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
        }
        with engine.begin() as conn:
            for name, definition in expected_columns.items():
                if name not in existing_columns and name != "id":
                    conn.execute(text(f"ALTER TABLE product_assets ADD COLUMN {name} {definition}"))
            if settings.DATABASE_URL.startswith("postgresql"):
                orphan_count = conn.execute(text(
                    "SELECT COUNT(*) FROM product_assets pa "
                    "LEFT JOIN products p ON p.sku = pa.sku "
                    "WHERE p.sku IS NULL"
                )).scalar_one()
                if orphan_count:
                    raise RuntimeError(f"product_assets contains {orphan_count} orphan sku rows")
                conn.execute(text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS ("
                    "SELECT 1 FROM pg_constraint WHERE conname = 'fk_product_assets_sku_products_sku'"
                    ") THEN "
                    "ALTER TABLE product_assets "
                    "ADD CONSTRAINT fk_product_assets_sku_products_sku "
                    "FOREIGN KEY (sku) REFERENCES products (sku) ON DELETE RESTRICT; "
                    "END IF; "
                    "END $$;"
                ))
            if settings.DATABASE_URL.startswith("postgresql"):
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_product_assets_sku ON product_assets (sku)"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_product_assets_sku_category "
                    "ON product_assets (sku, category_code)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_product_assets_seq_group "
                    "ON product_assets (sku, category_code, sub_category, material_type)"
                ))
            else:
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_product_assets_sku ON product_assets (sku)"))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_product_assets_sku_category "
                    "ON product_assets (sku, category_code)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_product_assets_seq_group "
                    "ON product_assets (sku, category_code, sub_category, material_type)"
                ))
    except Exception as exc:
        logger.warning("failed to ensure product asset compatibility columns: %s", exc)


def _seed_default_groups(db):
    from ..models.group import Group

    existing = {g.group_name: g for g in db.query(Group).all()}
    changed = False
    for name, desc in DEFAULT_GROUPS:
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

    permissions = {p.permission_key: p for p in db.query(Permission).all()}
    changed = False
    for key, name, permission_type in PERMISSION_DEFS:
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

    routes = {r.route_path: r for r in db.query(Route).all()}
    changed = False
    for path, name, route_type in ROUTE_DEFS:
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

    group_permission_map = {group_name: list(permission_keys) for group_name, permission_keys in GROUP_PERMISSION_KEYS.items()}
    for permission_keys in group_permission_map.values():
        permission_keys.extend(COMMON_PERMISSION_KEYS)
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

    routes = {r.route_path: r for r in db.query(Route).all()}
    existing_pairs = {
        (str(pr.permission_id), str(pr.route_id))
        for pr in db.query(PermissionRoute).all()
    }
    changed = False
    for permission_key, route_paths in PERMISSION_ROUTE_MAP.items():
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
