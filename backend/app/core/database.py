import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from .config import settings
from .permission_constants import (
    COMMON_PERMISSION_KEYS,
    DEPRECATED_EMPTY_GROUP_NAMES,
    DEFAULT_GROUPS,
    GROUP_PERMISSION_KEYS,
    LEGACY_GROUP_NAME_MAP,
    PERMISSION_DEFS,
    PERMISSION_ROUTE_MAP,
    ROUTE_DEFS,
    DEFAULT_TOOL_DEFS,
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
        _ensure_product_qa_integrity_compat()
        _init_vector_storage()

        db = SessionLocal()
        try:
            # Startup must seed missing defaults, but the destructive legacy
            # membership migration is an explicit maintenance action.  Running
            # it for every TestClient/app startup races isolated test fixtures.
            _seed_default_groups(db, migrate_legacy=False)
            _seed_default_permissions(db)
            seed_default_tools(db)
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
            "source_key": "VARCHAR(128)",
            "angle_scene": "VARCHAR(128)",
            "channel": "VARCHAR(64)",
            "language_tag": "VARCHAR(32)",
            "version_tag": "VARCHAR(32)",
            "product_version": "VARCHAR(32)",
            "market_version": "VARCHAR(32)",
            "date_tag": "VARCHAR(16)",
            "status_tag": "VARCHAR(32)",
            "file_name": "VARCHAR(255)",
            "file_format": "VARCHAR(20)",
            "resolution": "VARCHAR(32)",
            "aspect_ratio": "VARCHAR(16)",
            "asset_level": "VARCHAR(10) DEFAULT 'C'",
            "is_real_product": "BOOLEAN DEFAULT TRUE",
            "is_ai_generated": "BOOLEAN DEFAULT FALSE",
            "is_competitor": "BOOLEAN DEFAULT FALSE",
            "is_latest_version": "BOOLEAN DEFAULT TRUE",
            "is_public": "BOOLEAN DEFAULT FALSE",
            "ai_customer_usable": "BOOLEAN DEFAULT FALSE",
            "ai_marketing_usable": "BOOLEAN DEFAULT FALSE",
            "ai_reference_usable": "BOOLEAN DEFAULT FALSE",
            "editable_flag": "BOOLEAN DEFAULT FALSE",
            "review_status": "VARCHAR(32) DEFAULT 'pending'",
            "authorization_status": "VARCHAR(32) DEFAULT 'unknown'",
            "forbidden_usage": "TEXT",
            "maintainer": "VARCHAR(100)",
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
            conn.execute(text(
                "UPDATE product_assets SET "
                "asset_level = COALESCE(asset_level, 'C'), "
                "is_real_product = COALESCE(is_real_product, TRUE), "
                "is_ai_generated = COALESCE(is_ai_generated, FALSE), "
                "is_competitor = COALESCE(is_competitor, FALSE), "
                "is_latest_version = COALESCE(is_latest_version, TRUE), "
                "is_public = COALESCE(is_public, FALSE), "
                "ai_customer_usable = COALESCE(ai_customer_usable, FALSE), "
                "ai_marketing_usable = COALESCE(ai_marketing_usable, FALSE), "
                "ai_reference_usable = COALESCE(ai_reference_usable, FALSE), "
                "editable_flag = COALESCE(editable_flag, FALSE), "
                "review_status = COALESCE(review_status, 'pending'), "
                "authorization_status = COALESCE(authorization_status, 'unknown'), "
                "file_name = COALESCE(file_name, url), "
                "product_version = COALESCE(product_version, version_tag)"
            ))
            if settings.DATABASE_URL.startswith("postgresql"):
                orphan_count = conn.execute(text(
                    "SELECT COUNT(*) FROM product_assets pa "
                    "LEFT JOIN products p ON p.sku = pa.sku "
                    "WHERE p.sku IS NULL"
                )).scalar_one()
                if orphan_count:
                    raise RuntimeError(f"product_assets contains {orphan_count} orphan sku rows")
                conn.execute(text(
                    "DO $$ DECLARE constraint_name text; BEGIN "
                    "IF NOT EXISTS ("
                    "SELECT 1 FROM pg_constraint c "
                    "WHERE c.conrelid = 'product_assets'::regclass "
                    "AND c.contype = 'f' "
                    "AND pg_get_constraintdef(c.oid) LIKE '%FOREIGN KEY (sku)%ON UPDATE CASCADE ON DELETE CASCADE%'"
                    ") THEN "
                    "FOR constraint_name IN "
                    "SELECT c.conname FROM pg_constraint c "
                    "WHERE c.conrelid = 'product_assets'::regclass AND c.contype = 'f' "
                    "LOOP EXECUTE format('ALTER TABLE product_assets DROP CONSTRAINT %I', constraint_name); END LOOP; "
                    "ALTER TABLE product_assets ADD CONSTRAINT fk_product_assets_sku_products_sku "
                    "FOREIGN KEY (sku) REFERENCES products (sku) ON UPDATE CASCADE ON DELETE CASCADE; "
                    "END IF; END $$;"
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


def _ensure_product_qa_integrity_compat():
    """Upgrade legacy product_qa tables before customer-service queries use audit fields."""
    try:
        inspector = inspect(engine)
        if "product_qa" not in set(inspector.get_table_names()):
            return
        existing_columns = {column["name"] for column in inspector.get_columns("product_qa")}
        audited_at_type = "TIMESTAMP" if settings.DATABASE_URL.startswith("postgresql") else "DATETIME"
        expected_columns = {
            "integrity_status": "VARCHAR(20) NOT NULL DEFAULT 'review'",
            "integrity_reason": "TEXT",
            "integrity_model": "VARCHAR(100)",
            "integrity_audited_at": audited_at_type,
        }
        with engine.begin() as conn:
            for name, definition in expected_columns.items():
                if name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE product_qa ADD COLUMN {name} {definition}"))
            conn.execute(text(
                "UPDATE product_qa SET integrity_status = 'review' "
                "WHERE integrity_status IS NULL"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_product_qa_integrity "
                "ON product_qa (product_id, integrity_status)"
            ))
    except Exception as exc:
        logger.warning("failed to ensure product QA integrity compatibility columns: %s", exc)


def _seed_default_groups(db, *, migrate_legacy: bool = True):
    from ..models.group import Group
    from ..models.permissions import GroupPermission
    from ..models.user_group import UserGroup

    existing = {g.group_name: g for g in db.query(Group).all()}
    changed = False
    if not migrate_legacy:
        for name, desc in DEFAULT_GROUPS:
            group = existing.get(name)
            if group:
                if group.description != desc:
                    group.description = desc
                    changed = True
            else:
                group = Group(group_name=name, description=desc)
                setattr(group, "_seed_permissions_pending", True)
                db.add(group)
                changed = True
        if changed:
            db.commit()
        return

    for legacy_name, department_name in LEGACY_GROUP_NAME_MAP.items():
        legacy = existing.get(legacy_name)
        if not legacy:
            continue
        target = existing.get(department_name)
        if target is None:
            legacy.group_name = department_name
            existing.pop(legacy_name, None)
            existing[department_name] = legacy
            changed = True
            continue

        target_users = {
            str(row.user_id): row
            for row in db.query(UserGroup).filter(UserGroup.group_id == target.id).all()
        }
        for membership in db.query(UserGroup).filter(UserGroup.group_id == legacy.id).all():
            existing_membership = target_users.get(str(membership.user_id))
            if existing_membership:
                if membership.group_role == "admin":
                    existing_membership.group_role = "admin"
                db.delete(membership)
            else:
                membership.group_id = target.id

        db.query(GroupPermission).filter(GroupPermission.group_id == legacy.id).delete(
            synchronize_session=False
        )
        db.query(Group).filter(Group.id == legacy.id).delete(synchronize_session=False)
        existing.pop(legacy_name, None)
        changed = True

    removable_names = set(DEPRECATED_EMPTY_GROUP_NAMES)
    removable_names.update(name for name in existing if name.startswith("test-group-"))
    for group_name in removable_names:
        group = existing.get(group_name)
        if not group:
            continue
        if db.query(UserGroup).filter(UserGroup.group_id == group.id).first():
            continue
        db.query(GroupPermission).filter(GroupPermission.group_id == group.id).delete(
            synchronize_session=False
        )
        db.query(Group).filter(Group.id == group.id).delete(synchronize_session=False)
        existing.pop(group_name, None)
        changed = True

    for name, desc in DEFAULT_GROUPS:
        group = existing.get(name)
        if group:
            if group.description != desc:
                group.description = desc
                changed = True
        else:
            group = Group(group_name=name, description=desc)
            setattr(group, "_seed_permissions_pending", True)
            db.add(group)
            changed = True
    if changed:
        db.commit()

    obsolete_names = set(LEGACY_GROUP_NAME_MAP)
    obsolete_names.update(DEPRECATED_EMPTY_GROUP_NAMES)
    obsolete_names.update(
        name for (name,) in db.query(Group.group_name).all() if name.startswith("test-group-")
    )
    obsolete_group_ids = [
        group_id for (group_id,) in db.query(Group.id).filter(
            Group.group_name.in_(obsolete_names),
            ~Group.id.in_(db.query(UserGroup.group_id)),
        ).all()
    ]
    if obsolete_group_ids:
        db.query(GroupPermission).filter(GroupPermission.group_id.in_(obsolete_group_ids)).delete(
            synchronize_session=False
        )
        db.query(Group).filter(Group.id.in_(obsolete_group_ids)).delete(synchronize_session=False)
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
    has_any_group_permissions = bool(existing_pairs)
    changed = False
    for group_name, permission_keys in group_permission_map.items():
        group = groups.get(group_name)
        if not group:
            continue
        should_initialize = (
            not has_any_group_permissions
            or bool(getattr(group, "_seed_permissions_pending", False))
        )
        if not should_initialize:
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


def seed_default_tools(db):
    from ..models.tool import Tool

    existing = {tool.tool_key: tool for tool in db.query(Tool).all()}
    changed = False
    for definition in DEFAULT_TOOL_DEFS:
        tool = existing.get(definition["tool_key"])
        if tool is None:
            db.add(Tool(**definition))
            changed = True
            continue
        for field, value in definition.items():
            if getattr(tool, field) != value:
                setattr(tool, field, value)
                changed = True
    if changed:
        db.commit()
