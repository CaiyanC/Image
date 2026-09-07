"""Regression coverage for company rollout and one-time permission splitting."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth, asset_search, assets, knowledge_base, tools
from app.core.database import Base, _seed_default_permissions, get_db
from app.core.permission_constants import DERIVED_PERMISSION_SOURCES, PERMISSION_DEFS
from app.core.security import get_current_user, require_product_permission
from app.models import Group, GroupPermission, Permission, PermissionRoute, Route, User, UserGroup
from app.models.product_specs import ProductSpecs
from app.models.product import Product
from app.services.product_service import _audit_source_requires_confirmation


def test_quarantined_source_is_not_reported_as_ready():
    assert _audit_source_requires_confirmation(ProductSpecs(usage_instruction='使用说明待产品负责人核实，暂不提供操作步骤，请以该型号正式说明书为准。'))
    assert not _audit_source_requires_confirmation(ProductSpecs(usage_instruction='按正式说明操作。'))
    assert not _audit_source_requires_confirmation(None)
    assert _audit_source_requires_confirmation(None, Product(quality_note='收纳尺寸单位混用，待产品负责人核实。'))


@pytest.fixture
def fixture_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[model.__table__ for model in (
        User, Group, UserGroup, Permission, GroupPermission, Route, PermissionRoute,
    )])
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(id="employee", username="employee", password_hash="unused", is_active=True)
    group = Group(id="department", group_name="产品部")
    db.add_all([user, group])
    db.add(UserGroup(user_id=user.id, group_id=group.id, group_role="admin"))
    # Mimic old production permission definitions, but customized actual grants.
    for key, name, kind in PERMISSION_DEFS:
        if key not in DERIVED_PERMISSION_SOURCES:
            db.add(Permission(permission_key=key, permission_name=name, permission_type=kind))
    db.commit()
    yield db, user, group
    db.close()
    engine.dispose()


def grant(db, group, key):
    permission = db.query(Permission).filter_by(permission_key=key).one()
    db.add(GroupPermission(group_id=group.id, permission_id=permission.id))
    db.commit()


def keys(db, group):
    return {key for key, in db.query(Permission.permission_key).join(
        GroupPermission, Permission.id == GroupPermission.permission_id
    ).filter(GroupPermission.group_id == group.id)}


def test_split_uses_actual_grants_and_preserves_revocation(fixture_db):
    db, _, group = fixture_db
    grant(db, group, "product.read")
    _seed_default_permissions(db)
    assert {"product.read", "product.audit.view", "product.full.view", "media.read", "media.search"} <= keys(db, group)
    assert not {"knowledge.manage", "knowledge.sync", "knowledge.files.manage"} & keys(db, group)
    permission = db.query(Permission).filter_by(permission_key="media.read").one()
    db.query(GroupPermission).filter_by(group_id=group.id, permission_id=permission.id).delete()
    db.commit()
    _seed_default_permissions(db)
    assert "media.read" not in keys(db, group)


def test_split_does_not_restore_preset_department_revoked_read(fixture_db):
    db, _, group = fixture_db
    grant(db, group, "profile.view")
    _seed_default_permissions(db)
    assert "tools.view" in keys(db, group)
    assert not {"product.read", "product.audit.view", "product.full.view", "media.read", "media.search"} & keys(db, group)


def test_custom_group_receives_only_equivalent_split(fixture_db):
    db, _, group = fixture_db
    group.group_name = "自定义客服组"
    grant(db, group, "ai.customer_service")
    _seed_default_permissions(db)
    assert keys(db, group) == {"ai.customer_service", "tools.view"}


def test_seed_does_not_restore_any_grants_when_all_groups_are_revoked(fixture_db):
    db, _, group = fixture_db
    assert db.query(GroupPermission).count() == 0
    _seed_default_permissions(db)
    assert keys(db, group) == set()
    assert db.query(GroupPermission).count() == 0
    _seed_default_permissions(db)
    assert db.query(GroupPermission).count() == 0


def test_department_admin_cannot_delete_without_explicit_permission(fixture_db):
    db, user, group = fixture_db
    with pytest.raises(HTTPException) as error:
        require_product_permission("delete")(user, db)
    assert error.value.status_code == 403
    grant(db, group, "product.delete")
    assert require_product_permission("delete")(user, db) == user


def client_for(db, user):
    app = FastAPI()
    for router in (auth.router, asset_search.router, assets.router, knowledge_base.router, tools.router):
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_identity_restore_does_not_require_profile_permission(fixture_db):
    db, user, _ = fixture_db
    with client_for(db, user) as client:
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json()["permissions"] == []
        assert client.put("/api/auth/me", json={"full_name": "changed"}).status_code == 403


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/tools", None),
    ("GET", "/api/assets/search", None),
    ("GET", "/api/assets/taxonomy", None),
    ("GET", "/api/products/P/assets", None),
    ("GET", "/api/products/P/assets/A", None),
    ("GET", "/api/knowledge-base/status", None),
    ("GET", "/api/knowledge-base/health", None),
    ("GET", "/api/knowledge-base/files", None),
    ("GET", "/api/knowledge-base/jobs", None),
    ("POST", "/api/knowledge-base/reindex-products", {}),
    ("POST", "/api/knowledge-base/jobs/reindex-products", {}),
    ("POST", "/api/knowledge-base/jobs/retry-embeddings", {}),
])
def test_old_general_grants_do_not_bypass_new_guards(fixture_db, method, path, payload):
    db, user, group = fixture_db
    grant(db, group, "ai.call")
    grant(db, group, "product.read")
    with client_for(db, user) as client:
        assert client.request(method, path, json=payload).status_code == 403


def test_seed_removes_obsolete_route_permission_relation(fixture_db):
    db, _, group = fixture_db
    grant(db, group, "product.read")
    route = Route(route_path="/assets", route_name="old", route_type="page")
    db.add(route)
    db.flush()
    permission = db.query(Permission).filter_by(permission_key="product.read").one()
    db.add(PermissionRoute(permission_id=permission.id, route_id=route.id))
    db.commit()
    _seed_default_permissions(db)
    assert db.query(PermissionRoute).filter_by(permission_id=permission.id, route_id=route.id).count() == 0
