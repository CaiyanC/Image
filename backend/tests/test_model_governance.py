from datetime import datetime, timezone
import uuid

import asyncio

from app.schemas.model_governance import CredentialResponse
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core import database
from app.core.database import Base
from app.core.security import get_current_super_admin, get_current_user
from app.main import app
from app.models import Generation, Group, OperationLog, User, UserGroup
from app.models.system_config import SystemConfig
from app.models.ai_governance import (
    AIFeatureModel,
    AIModel,
    AIModelAccessRule,
    AIModelUsageLog,
    AIProviderCredential,
)
from app.services.model_governance_service import (
    create_credential,
    list_selectable_models,
    resolve_authorized_model,
)
from app.services import customer_llm_service, model_governance_service
from app.api import generation as generation_api


def _override_route_user(app, path, user):
    """Bypass only the permission dependency; route behavior remains real."""
    def iter_routes(router):
        for route in router.routes:
            yield route
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                yield from iter_routes(original_router)

    def iter_dependencies(dependant):
        for dependency in dependant.dependencies:
            yield dependency
            yield from iter_dependencies(dependency)

    for route in iter_routes(app):
        if getattr(route, "path", None) != path:
            continue
        for dependency in iter_dependencies(route.dependant):
            if dependency.call and getattr(dependency.call, "__name__", "") == "checker":
                app.dependency_overrides[dependency.call] = lambda: user
                return
    raise AssertionError(f"permission dependency for {path} was not found")


def test_credential_response_masks_secret():
    response = CredentialResponse.model_validate(
        {"api_key_ciphertext": "cipher", "key_hint": "abcd"}
    )

    assert "cipher" not in response.model_dump_json()
    assert response.api_key_masked == "****abcd"


def test_credential_response_does_not_expose_short_key_hint():
    response = CredentialResponse.model_validate({"key_hint": "abc"})

    assert response.api_key_masked == "****"


def test_governance_normalizes_uuid_subject_values_at_db_boundaries():
    identifier = uuid.uuid4()

    assert model_governance_service._access_subject_id(identifier) == str(identifier)
    assert model_governance_service._uuid_identifier(str(identifier)) == identifier
    assert model_governance_service._uuid_identifier("legacy-subject") == "legacy-subject"


def test_customer_chat_uses_existing_system_model_when_governance_is_unconfigured(db, monkeypatch):
    user, _group = _seed_user_and_group(db)
    calls = []

    def unavailable_governed_model(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="No governed default model is configured for this feature")

    async def legacy_chat_completion(*_args, **kwargs):
        calls.append(kwargs)
        return "legacy response"

    monkeypatch.setattr(customer_llm_service, "resolve_default_authorized_model", unavailable_governed_model)
    monkeypatch.setattr(customer_llm_service.dmxapi_service, "chat_completion", legacy_chat_completion)

    result = asyncio.run(customer_llm_service.chat_completion(
        db,
        [{"role": "user", "content": "recommend cookware"}],
        user=user,
        api_model_override="deepseek-v4-flash",
    ))

    assert result == "legacy response"
    assert calls[0]["resolved_model"] is None
    assert calls[0]["api_model_override"] == "deepseek-v4-flash"


def test_generation_uses_legacy_model_when_governance_is_unconfigured(db, monkeypatch):
    user, _group = _seed_user_and_group(db)

    def unavailable_governed_model(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Model is unavailable for this feature or capability")

    monkeypatch.setattr(generation_api, "resolve_authorized_model", unavailable_governed_model)

    assert generation_api._resolve_generation_model_or_legacy(
        db, user, "legacy-image-model", "image",
    ) is None


def test_generation_rejects_legacy_model_when_governance_is_configured(db, monkeypatch):
    user, _group = _seed_user_and_group(db)
    db.add(AIFeatureModel(feature_key="generation.image", model_id="configured-model", is_enabled=True))
    db.commit()

    def unavailable_governed_model(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="Model is unavailable for this feature or capability")

    monkeypatch.setattr(generation_api, "resolve_authorized_model", unavailable_governed_model)

    with pytest.raises(HTTPException, match="unavailable"):
        generation_api._resolve_generation_model_or_legacy(db, user, "legacy-image-model", "image")


def test_governance_models_define_migration_unique_constraints():
    feature_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in AIFeatureModel.__table__.constraints
        if constraint.name
    }
    access_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in AIModelAccessRule.__table__.constraints
        if constraint.name
    }

    assert feature_constraints["uq_ai_feature_models_feature_model"] == (
        "feature_key", "model_id",
    )
    assert access_constraints["uq_ai_model_access_rules_subject"] == (
        "feature_key", "model_id", "subject_type", "subject_id",
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        User.__table__,
        Group.__table__,
        UserGroup.__table__,
        AIProviderCredential.__table__,
        AIModel.__table__,
        AIFeatureModel.__table__,
        AIModelAccessRule.__table__,
        AIModelUsageLog.__table__,
        Generation.__table__,
        SystemConfig.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY", key)
    return key


def _seed_model(db, model_id="image-model", capability="image"):
    model = AIModel(
        id=model_id,
        display_name=model_id,
        provider_name="provider-a",
        capability=capability,
        request_model_name=model_id,
    )
    db.add(model)
    db.add(AIFeatureModel(feature_key="generation.image", model_id=model.id, is_default=True))
    db.flush()
    return model


def _seed_user_and_group(db):
    user = User(username="member", password_hash="hash")
    group = Group(group_name="design")
    db.add_all([user, group])
    db.flush()
    db.add(UserGroup(user_id=user.id, group_id=group.id))
    db.flush()
    return user, group


def _add_rule(db, user, group, model, subject_type, effect):
    subject_id = user.id if subject_type == "user" else group.id
    db.add(AIModelAccessRule(
        feature_key="generation.image",
        model_id=model.id,
        subject_type=subject_type,
        subject_id=subject_id,
        effect=effect,
    ))
    db.flush()


def test_credential_is_encrypted_and_personal_credential_wins(db, encryption_key):
    user, group = _seed_user_and_group(db)
    model = _seed_model(db)
    create_credential(db, "provider-a", "https://company.example", "company-secret", "company")
    personal = create_credential(db, "provider-a", "https://personal.example", "personal-secret", "user", user.id)

    assert personal.api_key_ciphertext != "personal-secret"

    resolved = resolve_authorized_model(db, user, "generation.image", model.id, "image")
    assert resolved.api_key == "personal-secret"
    assert resolved.credential.id == personal.id


def test_credential_scope_has_one_deterministic_provider_key(db, encryption_key):
    create_credential(db, "provider-a", "https://first.example", "first-secret", "company")

    with pytest.raises(IntegrityError):
        create_credential(db, "provider-a", "https://second.example", "second-secret", "company")


def test_credential_database_constraints_reject_invalid_scope_combinations(db):
    db.add(AIProviderCredential(
        provider_name="provider-a",
        api_base_url="https://example.test",
        api_key_ciphertext="ciphertext",
        key_hint="hint",
        scope_type="company",
        scope_id="must-not-exist",
    ))

    with pytest.raises(IntegrityError):
        db.flush()


def test_personal_deny_overrides_group_allow(db, encryption_key):
    user, group = _seed_user_and_group(db)
    model = _seed_model(db)
    create_credential(db, "provider-a", "https://company.example", "company-secret", "company")
    _add_rule(db, user, group, model, "group", "allow")
    _add_rule(db, user, group, model, "user", "deny")

    assert list_selectable_models(db, user, "generation.image", "image") == []


def test_group_deny_overrides_group_allow(db, encryption_key):
    user, group = _seed_user_and_group(db)
    model = _seed_model(db)
    create_credential(db, "provider-a", "https://company.example", "company-secret", "company")
    denying_group = Group(group_name="legal")
    db.add(denying_group)
    db.flush()
    db.add(UserGroup(user_id=user.id, group_id=denying_group.id))
    db.flush()
    _add_rule(db, user, group, model, "group", "allow")
    _add_rule(db, user, denying_group, model, "group", "deny")

    assert list_selectable_models(db, user, "generation.image", "image") == []


def test_rule_database_constraint_rejects_unknown_effect(db):
    user, _group = _seed_user_and_group(db)
    model = _seed_model(db)
    db.add(AIModelAccessRule(
        feature_key="generation.image",
        model_id=model.id,
        subject_type="user",
        subject_id=user.id,
        effect="ignore",
    ))

    with pytest.raises(IntegrityError):
        db.flush()


def test_model_database_constraint_rejects_unknown_api_format(db):
    db.add(AIModel(
        id="invalid-api-format", display_name="Invalid", provider_name="provider-a",
        capability="image", request_model_name="image-v1", api_format="unsupported",
    ))

    with pytest.raises(IntegrityError):
        db.flush()


def test_feature_database_constraint_allows_only_one_default_model(db):
    _seed_model(db)
    second_model = AIModel(
        id="second-image-model",
        display_name="second-image-model",
        provider_name="provider-b",
        capability="image",
        request_model_name="second-image-model",
    )
    db.add_all([
        second_model,
        AIFeatureModel(feature_key="generation.image", model_id=second_model.id, is_default=True),
    ])

    with pytest.raises(IntegrityError):
        db.flush()


def test_resolve_rejects_missing_credential_and_capability_mismatch(db, encryption_key):
    user, _group = _seed_user_and_group(db)
    model = _seed_model(db)

    with pytest.raises(HTTPException, match="credential") as missing_credential:
        resolve_authorized_model(db, user, "generation.image", model.id, "image")
    assert missing_credential.value.status_code == 403
    assert missing_credential.value.detail == "No usable credential is available for this model"

    create_credential(db, "provider-a", "https://company.example", "company-secret", "company")
    with pytest.raises(HTTPException, match="capability") as mismatch:
        resolve_authorized_model(db, user, "generation.image", model.id, "chat")
    assert mismatch.value.status_code == 403
    assert mismatch.value.detail == "Model is unavailable for this feature or capability"


def test_create_credential_derives_fallback_key_but_rejects_invalid_explicit_key(db, monkeypatch):
    monkeypatch.setattr("app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setattr("app.services.model_governance_service.settings.SECRET_KEY", "fallback-secret-key")
    credential = create_credential(db, "provider-a", "https://example.test", "secret", "company")
    assert credential.api_key_ciphertext != "secret"

    db.rollback()
    monkeypatch.setattr("app.services.model_governance_service.settings.MODEL_CREDENTIAL_ENCRYPTION_KEY", "invalid")
    with pytest.raises(ValueError, match="invalid"):
        create_credential(db, "provider-b", "https://example.test", "secret", "company")


def test_dedicated_key_rewraps_credentials_before_secret_key_rotation(db, monkeypatch):
    monkeypatch.setattr(model_governance_service.settings, "MODEL_CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setattr(model_governance_service.settings, "SECRET_KEY", "old-signing-secret")
    credential = create_credential(
        db, "provider-a", "https://example.test", "provider-secret", "company"
    )
    derived_ciphertext = credential.api_key_ciphertext

    dedicated_key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        model_governance_service.settings,
        "MODEL_CREDENTIAL_ENCRYPTION_KEY",
        dedicated_key,
    )
    migrated = model_governance_service.migrate_provider_credential_encryption(db)

    db.refresh(credential)
    assert migrated == {"migrated": 1, "failed": 0}
    assert credential.api_key_ciphertext != derived_ciphertext
    monkeypatch.setattr(model_governance_service.settings, "SECRET_KEY", "rotated-signing-secret")
    assert model_governance_service.decrypt_credential(credential) == "provider-secret"


def test_group_credential_beats_company_and_falls_back_when_unusable(db, encryption_key):
    user, group = _seed_user_and_group(db)
    model = _seed_model(db)
    company = create_credential(db, "provider-a", "https://company.example", "company-secret", "company")
    group_credential = create_credential(
        db,
        "provider-a",
        "https://group.example",
        "group-secret",
        "group",
        group.id,
    )

    assert resolve_authorized_model(db, user, "generation.image", model.id, "image").credential.id == group_credential.id

    group_credential.is_enabled = False
    assert resolve_authorized_model(db, user, "generation.image", model.id, "image").credential.id == company.id

    group_credential.is_enabled = True
    group_credential.api_key_ciphertext = "corrupt"
    assert resolve_authorized_model(db, user, "generation.image", model.id, "image").credential.id == company.id


def test_group_credential_selection_uses_group_id_order(db, encryption_key):
    user = User(username="multi-group-member", password_hash="hash")
    later_group = Group(id="group-z", group_name="zebra")
    earlier_group = Group(id="group-a", group_name="alpha")
    db.add_all([user, later_group, earlier_group])
    db.flush()
    db.add_all([
        UserGroup(user_id=user.id, group_id=later_group.id),
        UserGroup(user_id=user.id, group_id=earlier_group.id),
    ])
    db.flush()
    model = _seed_model(db)
    later_credential = create_credential(
        db, "provider-a", "https://zebra.example", "zebra-secret", "group", later_group.id,
    )
    earlier_credential = create_credential(
        db, "provider-a", "https://alpha.example", "alpha-secret", "group", earlier_group.id,
    )

    resolved = resolve_authorized_model(db, user, "generation.image", model.id, "image")

    assert resolved.credential.id == earlier_credential.id
    assert resolved.credential.id != later_credential.id


def test_resolve_rejects_model_mapped_only_to_a_different_feature(db, encryption_key):
    user, _group = _seed_user_and_group(db)
    model = AIModel(
        id="customer-image-model",
        display_name="customer-image-model",
        provider_name="provider-a",
        capability="image",
        request_model_name="customer-image-model",
    )
    db.add_all([
        model,
        AIFeatureModel(feature_key="customer.image", model_id=model.id, is_default=True),
    ])
    db.flush()
    create_credential(db, "provider-a", "https://company.example", "company-secret", "company")

    with pytest.raises(Exception, match="feature"):
        resolve_authorized_model(db, user, "generation.image", model.id, "image")


@pytest.fixture
def api_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__,
        Group.__table__,
        UserGroup.__table__,
        OperationLog.__table__,
        AIProviderCredential.__table__,
        AIModel.__table__,
        AIFeatureModel.__table__,
        AIModelAccessRule.__table__,
        AIModelUsageLog.__table__,
        SystemConfig.__table__,
        Generation.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def api_client(api_db):
    def override_db():
        yield api_db

    app.dependency_overrides[database.get_db] = override_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_selectable_models_endpoint_returns_only_authorized_public_fields(api_client, api_db, encryption_key):
    user = User(id="member-user", username="member-api", password_hash="hash")
    model = AIModel(
        id="allowed-image", display_name="Allowed image", provider_name="provider-a",
        capability="image", request_model_name="allowed-image",
    )
    blocked = AIModel(
        id="blocked-image", display_name="Blocked image", provider_name="provider-a",
        capability="image", request_model_name="blocked-image",
    )
    api_db.add_all([user, model, blocked])
    api_db.add_all([
        AIFeatureModel(feature_key="generation.image", model_id=model.id),
        AIFeatureModel(feature_key="generation.image", model_id=blocked.id),
        AIModelAccessRule(
            feature_key="generation.image", model_id=model.id,
            subject_type="user", subject_id=user.id, effect="allow",
        ),
    ])
    api_db.flush()
    create_credential(api_db, "provider-a", "https://provider.example", "top-secret-key", "company")
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.get("/api/model-governance/features/generation.image/models?capability=image")

    assert response.status_code == 200, response.text
    assert response.json() == [{"id": "allowed-image", "name": "Allowed image", "capability": "image"}]
    assert "provider-a" not in response.text
    assert "top-secret-key" not in response.text


def test_model_governance_admin_endpoint_rejects_non_admin(api_client, api_db):
    user = User(id="regular-user", username="regular-api", password_hash="hash")
    api_db.add(user)
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.get("/api/admin/model-governance/credentials")

    assert response.status_code == 403


def test_regular_user_can_view_provider_catalog_without_other_users_credentials(api_client, api_db, encryption_key):
    user = User(id="self-service-user", username="self-service-user", password_hash="hash")
    other = User(id="other-self-service-user", username="other-self-service-user", password_hash="hash")
    model = AIModel(
        id="self-service-image", display_name="Self Service Image", provider_name="provider-self",
        capability="image", request_model_name="self-service-image-v1",
    )
    api_db.add_all([user, other, model, AIFeatureModel(
        feature_key="generation.image", model_id=model.id, is_default=True,
    )])
    create_credential(api_db, "provider-self", "https://provider.example", "other-secret", "user", other.id)
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.get("/api/model-governance/my-credentials")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0]["provider_name"] == "provider-self"
    assert body[0]["models"] == [{
        "model_id": "self-service-image",
        "display_name": "Self Service Image",
        "capability": "image",
    }]
    assert body[0]["has_personal_credential"] is False
    assert body[0]["api_key_masked"] == "****"
    assert body[0]["personal_credential_id"] is None
    assert "other-secret" not in response.text
    assert "other-self-service-user" not in response.text


def test_regular_user_can_create_replace_and_disable_only_their_personal_key(api_client, api_db, encryption_key):
    user = User(id="personal-key-owner", username="personal-key-owner", password_hash="hash")
    model = AIModel(
        id="personal-key-image", display_name="Personal Key Image", provider_name="provider-personal",
        capability="image", request_model_name="personal-key-image-v1",
    )
    api_db.add_all([user, model, AIFeatureModel(
        feature_key="generation.image", model_id=model.id, is_default=True,
    )])
    create_credential(api_db, "provider-personal", "https://provider.example", "company-secret", "company")
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    created = api_client.put(
        "/api/model-governance/my-credentials/provider-personal",
        json={"api_key": "personal-secret"},
    )

    assert created.status_code == 200, created.text
    assert "personal-secret" not in created.text
    assert created.json()["api_key_masked"] == "****cret"
    assert created.json()["has_personal_credential"] is True
    personal = api_db.query(AIProviderCredential).filter(
        AIProviderCredential.provider_name == "provider-personal",
        AIProviderCredential.scope_type == "user",
        AIProviderCredential.scope_id == user.id,
    ).one()
    assert model_governance_service.decrypt_credential(personal) == "personal-secret"
    assert personal.api_base_url == "https://provider.example"

    replaced = api_client.put(
        "/api/model-governance/my-credentials/provider-personal",
        json={"api_key": "replacement-secret", "is_enabled": True},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["api_key_masked"] == "****cret"
    assert model_governance_service.decrypt_credential(personal) == "replacement-secret"

    disabled = api_client.put(
        "/api/model-governance/my-credentials/provider-personal",
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_enabled"] is False
    assert disabled.json()["effective_credential_scope_type"] == "company"


def test_personal_credential_rejects_scope_and_endpoint_overrides_without_persisting_key(api_client, api_db, encryption_key):
    user = User(id="personal-boundary-user", username="personal-boundary-user", password_hash="hash")
    model = AIModel(
        id="personal-boundary-image", display_name="Personal Boundary Image", provider_name="provider-boundary",
        capability="image", request_model_name="personal-boundary-image-v1",
    )
    api_db.add_all([user, model, AIFeatureModel(
        feature_key="generation.image", model_id=model.id, is_default=True,
    )])
    create_credential(api_db, "provider-boundary", "https://provider.example", "company-secret", "company")
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    sentinel = "must-not-be-stored"

    response = api_client.put(
        "/api/model-governance/my-credentials/provider-boundary",
        json={
            "api_key": sentinel,
            "scope_type": "company",
            "scope_id": "someone-else",
            "api_base_url": "http://169.254.169.254/",
        },
    )

    assert response.status_code == 422, response.text
    assert sentinel not in response.text
    assert api_db.query(AIProviderCredential).filter(
        AIProviderCredential.scope_type == "user",
        AIProviderCredential.scope_id == user.id,
    ).count() == 0


def test_personal_credential_cannot_be_created_for_unprovisioned_provider(api_client, api_db, encryption_key):
    user = User(id="unprovisioned-provider-user", username="unprovisioned-provider-user", password_hash="hash")
    api_db.add(user)
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.put(
        "/api/model-governance/my-credentials/not-in-catalog",
        json={"api_key": "not-in-catalog-secret"},
    )

    assert response.status_code == 422, response.text
    assert "not-in-catalog-secret" not in response.text


def test_authorization_overview_returns_effective_group_and_personal_permissions(api_client, api_db, encryption_key):
    """Catches an overview that returns raw rules instead of resolved permissions."""
    admin = User(id="overview-admin", username="overview-admin", password_hash="hash")
    member = User(id="overview-member", username="overview-member", password_hash="hash", display_name="Overview Member")
    group = Group(id="overview-design", group_name="Overview Design")
    default_model = AIModel(
        id="overview-default", display_name="Default Image", provider_name="provider-default",
        capability="image", request_model_name="default-image",
    )
    overridden_model = AIModel(
        id="overview-overridden", display_name="Overridden Image", provider_name="provider-override",
        capability="image", request_model_name="overridden-image",
    )
    api_db.add_all([admin, member, group, default_model, overridden_model])
    api_db.add_all([
        UserGroup(user_id=member.id, group_id=group.id),
        AIFeatureModel(feature_key="generation.image", model_id=default_model.id, is_default=True),
        AIFeatureModel(feature_key="generation.image", model_id=overridden_model.id),
        AIModelAccessRule(feature_key="generation.image", model_id=overridden_model.id, subject_type="group", subject_id=group.id, effect="deny"),
        AIModelAccessRule(feature_key="generation.image", model_id=overridden_model.id, subject_type="user", subject_id=member.id, effect="allow"),
    ])
    create_credential(api_db, "provider-default", "https://company.example", "company-overview-key", "company")
    create_credential(api_db, "provider-override", "https://member.example", "member-overview-key", "user", member.id)
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.get("/api/admin/model-governance/authorization-overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["features"] == [{
        "feature_key": "generation.image",
        "models": [
        {"model_id": "overview-default", "display_name": "Default Image", "provider_name": "provider-default"},
        {"model_id": "overview-overridden", "display_name": "Overridden Image", "provider_name": "provider-override"},
        ],
    }]
    group = payload["groups"][0]
    assert group["subject_id"] == "overview-design"
    assert group["subject_name"] == "Overview Design"
    assert group["features"] == [{
        "feature_key": "generation.image",
        "models": [{
            "model_id": "overview-default",
            "display_name": "Default Image",
            "permission_source": "feature_default",
            "key_available": True,
            "credential_scope_type": "company",
        }],
    }]
    user_row = group["members"][0]
    assert user_row["subject_name"] == "Overview Member"
    assert user_row["has_personal_override"] is True
    assert user_row["features"] == [{
        "feature_key": "generation.image",
        "models": [
            {
                "model_id": "overview-default",
                "display_name": "Default Image",
                "permission_source": "feature_default",
                "key_available": True,
                "credential_scope_type": "company",
            },
            {
                "model_id": "overview-overridden",
                "display_name": "Overridden Image",
                "permission_source": "user_allow",
                "key_available": True,
                "credential_scope_type": "user",
            },
        ],
    }]
    assert "company-overview-key" not in response.text
    assert "member-overview-key" not in response.text
    assert "api_key_ciphertext" not in response.text


def test_authorization_overview_hierarchy_nests_all_group_members_and_keeps_model_ids(api_client, api_db):
    """Catches a flat overview that loses group membership or stable model identifiers."""
    admin = User(id="hierarchy-admin", username="hierarchy-admin", password_hash="hash")
    group = Group(id="design", group_name="Design")
    alice = User(id="alice", username="alice", password_hash="hash")
    bob = User(id="bob", username="bob", password_hash="hash")
    model = AIModel(
        id="image-default", display_name="Image Default", provider_name="image-provider",
        capability="image", request_model_name="image-default-v1",
    )
    api_db.add_all([admin, group, alice, bob, model])
    api_db.add_all([
        UserGroup(user_id=alice.id, group_id=group.id),
        UserGroup(user_id=bob.id, group_id=group.id),
        AIFeatureModel(feature_key="generation.image", model_id=model.id, is_default=True),
    ])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.get("/api/admin/model-governance/authorization-overview")

    assert response.status_code == 200, response.text
    body = response.json()
    design = next(item for item in body["groups"] if item["subject_id"] == "design")
    assert [member["subject_id"] for member in design["members"]] == ["alice", "bob"]
    assert [member["has_personal_override"] for member in design["members"]] == [False, False]
    assert design["features"][0]["models"][0]["model_id"] == "image-default"
    assert "api_key" not in str(body)
    assert "ciphertext" not in str(body)


def test_authorization_overview_marks_authorized_models_without_a_key(api_client, api_db):
    """Catches an overview that silently omits authorized models without credentials."""
    admin = User(id="no-key-admin", username="no-key-admin", password_hash="hash")
    group = Group(id="no-key-group", group_name="No Key Group")
    model = AIModel(
        id="no-key-model", display_name="No Key Model", provider_name="no-key-provider",
        capability="chat", request_model_name="no-key-chat",
    )
    api_db.add_all([admin, group, model])
    api_db.add(AIFeatureModel(feature_key="customer_service.chat", model_id=model.id, is_default=True))
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.get("/api/admin/model-governance/authorization-overview")

    assert response.status_code == 200, response.text
    overview_group = next(item for item in response.json()["groups"] if item["subject_id"] == group.id)
    assert overview_group["features"] == [{
        "feature_key": "customer_service.chat",
        "models": [{
            "model_id": "no-key-model",
            "display_name": "No Key Model",
            "permission_source": "feature_default",
            "key_available": False,
            "credential_scope_type": None,
        }],
    }]


def test_authorization_overview_rejects_regular_user(api_client, api_db):
    """Catches accidental exposure of administrative authorization state."""
    user = User(id="overview-regular", username="overview-regular", password_hash="hash")
    api_db.add(user)
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.get("/api/admin/model-governance/authorization-overview")

    assert response.status_code == 403


def test_replace_group_feature_models_creates_allow_and_deny_then_cleans_redundant_rules(api_client, api_db):
    admin = User(id="replace-group-admin", username="replace-group-admin", password_hash="hash")
    group = Group(id="design", group_name="Design")
    default_model = AIModel(
        id="model-a", display_name="Model A", provider_name="provider-a",
        capability="image", request_model_name="model-a",
    )
    selected_model = AIModel(
        id="model-b", display_name="Model B", provider_name="provider-b",
        capability="image", request_model_name="model-b",
    )
    api_db.add_all([admin, group, default_model, selected_model])
    api_db.add_all([
        AIFeatureModel(feature_key="generation.image", model_id=default_model.id, is_default=True),
        AIFeatureModel(feature_key="generation.image", model_id=selected_model.id),
    ])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.put(
        "/api/admin/model-governance/authorization-overview/group/design/features/generation.image",
        json={"model_ids": ["model-b"]},
    )

    assert response.status_code == 200, response.text
    assert {(item["model_id"], item["effect"]) for item in response.json()} == {
        ("model-a", "deny"), ("model-b", "allow"),
    }

    reset = api_client.put(
        "/api/admin/model-governance/authorization-overview/group/design/features/generation.image",
        json={"model_ids": ["model-a"]},
    )

    assert reset.status_code == 200, reset.text
    assert reset.json() == []


def test_replace_group_feature_models_repeat_save_preserves_rule_ids(api_client, api_db):
    admin = User(id="idempotent-admin", username="idempotent-admin", password_hash="hash")
    group = Group(id="idempotent-design", group_name="Idempotent Design")
    default_model = AIModel(
        id="idempotent-default", display_name="Default", provider_name="provider-a",
        capability="image", request_model_name="idempotent-default",
    )
    selected_model = AIModel(
        id="idempotent-selected", display_name="Selected", provider_name="provider-b",
        capability="image", request_model_name="idempotent-selected",
    )
    api_db.add_all([admin, group, default_model, selected_model])
    api_db.add_all([
        AIFeatureModel(feature_key="generation.image", model_id=default_model.id, is_default=True),
        AIFeatureModel(feature_key="generation.image", model_id=selected_model.id),
    ])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin
    url = "/api/admin/model-governance/authorization-overview/group/idempotent-design/features/generation.image"
    payload = {"model_ids": ["idempotent-selected"]}

    first = api_client.put(url, json=payload)
    second = api_client.put(url, json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert {(item["model_id"], item["effect"]) for item in second.json()} == {
        ("idempotent-default", "deny"), ("idempotent-selected", "allow"),
    }


def test_replace_user_feature_models_denies_deselected_inherited_group_model(api_client, api_db):
    admin = User(id="replace-user-admin", username="replace-user-admin", password_hash="hash")
    member = User(id="member", username="member", password_hash="hash")
    group = Group(id="design", group_name="Design")
    inherited_model = AIModel(
        id="inherited-model", display_name="Inherited", provider_name="provider-a",
        capability="image", request_model_name="inherited-model",
    )
    additional_model = AIModel(
        id="additional-model", display_name="Additional", provider_name="provider-b",
        capability="image", request_model_name="additional-model",
    )
    api_db.add_all([admin, member, group, inherited_model, additional_model])
    api_db.add_all([
        UserGroup(user_id=member.id, group_id=group.id),
        AIFeatureModel(feature_key="generation.image", model_id=inherited_model.id),
        AIFeatureModel(feature_key="generation.image", model_id=additional_model.id),
        AIModelAccessRule(
            feature_key="generation.image", model_id=inherited_model.id,
            subject_type="group", subject_id=group.id, effect="allow",
        ),
    ])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.put(
        "/api/admin/model-governance/authorization-overview/user/member/features/generation.image",
        json={"model_ids": ["additional-model"]},
    )

    assert response.status_code == 200, response.text
    assert {(item["model_id"], item["effect"]) for item in response.json()} == {
        ("additional-model", "allow"), ("inherited-model", "deny"),
    }


def test_replace_group_feature_models_rejects_models_not_enabled_for_feature(api_client, api_db):
    admin = User(id="invalid-model-admin", username="invalid-model-admin", password_hash="hash")
    group = Group(id="design", group_name="Design")
    api_db.add_all([admin, group, AIModel(
        id="other-feature-model", display_name="Other", provider_name="provider-a",
        capability="image", request_model_name="other-feature-model",
    )])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.put(
        "/api/admin/model-governance/authorization-overview/group/design/features/generation.image",
        json={"model_ids": ["other-feature-model"]},
    )

    assert response.status_code == 422


def test_replace_group_feature_models_rejects_regular_user(api_client, api_db):
    user = User(id="replace-regular", username="replace-regular", password_hash="hash")
    api_db.add(user)
    api_db.commit()
    app.dependency_overrides[get_current_user] = lambda: user

    response = api_client.put(
        "/api/admin/model-governance/authorization-overview/group/design/features/generation.image",
        json={"model_ids": []},
    )

    assert response.status_code == 403


def test_admin_credential_create_masks_key_and_audit_log_never_contains_raw_key(api_client, api_db, encryption_key):
    admin = User(id="super-admin", username="super-admin-api", password_hash="hash")
    api_db.add(admin)
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.post("/api/admin/model-governance/credentials", json={
        "provider_name": "provider-a",
        "api_base_url": "https://provider.example",
        "api_key": "raw-key-must-not-leak",
        "scope_type": "company",
    })

    assert response.status_code == 200, response.text
    assert "raw-key-must-not-leak" not in response.text
    assert response.json()["api_key_masked"] == "****leak"
    audit = api_db.query(OperationLog).one()
    assert "raw-key-must-not-leak" not in str(audit.request_data)
    assert "raw-key-must-not-leak" not in str(audit.response_data)


@pytest.mark.parametrize("method,path", [
    ("post", "/api/admin/model-governance/credentials"),
    ("put", "/api/admin/model-governance/credentials/missing-credential"),
])
def test_admin_credential_validation_never_echoes_raw_api_key(api_client, api_db, method, path):
    admin = User(id="validation-admin", username="validation-admin", password_hash="hash")
    api_db.add(admin)
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin
    sentinel = "credential-secret-must-never-appear-in-422"

    response = getattr(api_client, method)(path, json={"api_key": {"secret": sentinel}})

    assert response.status_code == 422
    assert sentinel not in response.text
    assert response.json()["detail"]


def test_admin_usage_logs_filter_and_paginate_stably_with_safe_response(api_client, api_db):
    admin = User(id="usage-admin", username="usage-admin", password_hash="hash")
    another_user = User(id="usage-other-user", username="usage-other", password_hash="hash")
    timestamp = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    api_db.add_all([admin, another_user])
    api_db.add_all([
        AIModelUsageLog(
            id="log-a", user_id=admin.id, feature_key="generation.image", model_id="model-a",
            result="success", error_summary="do-not-return-this", created_at=timestamp,
        ),
        AIModelUsageLog(
            id="log-z", user_id=admin.id, feature_key="generation.image", model_id="model-a",
            result="success", created_at=timestamp,
        ),
        AIModelUsageLog(
            id="log-filtered", user_id=admin.id, feature_key="generation.image", model_id="model-a",
            result="failed", created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        ),
        AIModelUsageLog(
            id="log-other", user_id=another_user.id, feature_key="customer.service", model_id="model-b",
            result="failed", created_at=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        ),
    ])
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.get(
        "/api/admin/model-governance/usage-logs",
        params={
            "user_id": admin.id,
            "feature_key": "generation.image",
            "model_id": "model-a",
            "status": "success",
            "date_from": "2026-07-28T00:00:00+00:00",
            "date_to": "2026-07-28T23:59:59+00:00",
            "limit": 1,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2
    assert [item["id"] for item in response.json()["items"]] == ["log-z"]
    assert "error_summary" not in response.json()["items"][0]

    second_page = api_client.get(
        "/api/admin/model-governance/usage-logs",
        params={"user_id": admin.id, "result": "success", "skip": 1, "limit": 1},
    )

    assert second_page.status_code == 200, second_page.text
    assert [item["id"] for item in second_page.json()["items"]] == ["log-a"]


def test_admin_can_replace_the_default_feature_model(api_client, api_db):
    admin = User(id="feature-admin", username="feature-admin-api", password_hash="hash")
    old_model = AIModel(id="old-model", display_name="Old", provider_name="provider-a", capability="image", request_model_name="old")
    new_model = AIModel(id="new-model", display_name="New", provider_name="provider-a", capability="image", request_model_name="new")
    api_db.add_all([admin, old_model, new_model])
    api_db.add(AIFeatureModel(feature_key="generation.image", model_id=old_model.id, is_default=True))
    api_db.commit()
    app.dependency_overrides[get_current_super_admin] = lambda: admin

    response = api_client.put(
        "/api/admin/model-governance/feature-models/generation.image/new-model",
        json={"is_default": True, "sort_order": 1, "is_enabled": True},
    )

    assert response.status_code == 200, response.text
    links = api_db.query(AIFeatureModel).filter_by(feature_key="generation.image").all()
    assert [link.model_id for link in links if link.is_default] == ["new-model"]


def test_generation_models_endpoint_only_returns_models_authorized_for_the_caller(api_client, api_db, encryption_key):
    user = User(id="generation-member", username="generation-member", password_hash="hash")
    allowed = AIModel(
        id="permitted-image", display_name="Permitted image", provider_name="provider-a",
        capability="image", request_model_name="provider-image-v1", api_format="gemini",
    )
    blocked = AIModel(
        id="blocked-image", display_name="Blocked image", provider_name="provider-a",
        capability="image", request_model_name="provider-image-v2",
    )
    api_db.add_all([user, allowed, blocked])
    api_db.add_all([
        AIFeatureModel(feature_key="generation.image", model_id=allowed.id),
        AIFeatureModel(feature_key="generation.image", model_id=blocked.id),
        AIModelAccessRule(feature_key="generation.image", model_id=allowed.id, subject_type="user", subject_id=user.id, effect="allow"),
    ])
    create_credential(api_db, "provider-a", "https://provider.example", "governed-secret", "company")
    api_db.commit()
    _override_route_user(app, "/api/generation/models", user)

    response = api_client.get("/api/generation/models")

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == ["permitted-image"]
    assert response.json()[0]["api_format"] == "gemini"


def test_generation_rejects_a_model_outside_the_users_policy(api_client, api_db, encryption_key):
    user = User(id="forged-model-member", username="forged-model-member", password_hash="hash")
    model = AIModel(
        id="approved-image", display_name="Approved image", provider_name="provider-a",
        capability="image", request_model_name="provider-image-v1",
    )
    api_db.add_all([user, model, AIFeatureModel(feature_key="generation.image", model_id=model.id)])
    create_credential(api_db, "provider-a", "https://provider.example", "governed-secret", "company")
    api_db.commit()
    _override_route_user(app, "/api/generation/txt2img", user)

    response = api_client.post("/api/generation/txt2img", json={"prompt": "cup", "model_name": "forged-image"})

    assert response.status_code == 403


def test_customer_llm_uses_governed_model_and_writes_safe_usage_record(db, encryption_key, monkeypatch):
    import asyncio
    from app.services import customer_llm_service

    user, group = _seed_user_and_group(db)
    model = AIModel(
        id="governed-chat", display_name="Governed chat", provider_name="provider-chat",
        capability="chat", request_model_name="provider-chat-v1",
    )
    db.add_all([
        model,
        AIFeatureModel(feature_key="customer_service.chat", model_id=model.id, is_default=True),
        AIModelAccessRule(feature_key="customer_service.chat", model_id=model.id, subject_type="user", subject_id=user.id, effect="allow"),
    ])
    create_credential(db, "provider-chat", "https://chat.provider.example", "private-chat-key", "company")
    db.commit()

    async def fake_chat_completion(_db, messages, **kwargs):
        assert kwargs["resolved_model"].model.id == "governed-chat"
        assert kwargs["resolved_model"].api_key == "private-chat-key"
        return "governed answer"

    monkeypatch.setattr(customer_llm_service.dmxapi_service, "chat_completion", fake_chat_completion)

    answer = asyncio.run(customer_llm_service.chat_completion(
        db, [{"role": "user", "content": "hello"}], user=user,
    ))

    assert answer == "governed answer"
    usage = db.query(AIModelUsageLog).one()
    assert (usage.user_id, usage.feature_key, usage.model_id, usage.credential_scope_type, usage.result) == (
        user.id, "customer_service.chat", "governed-chat", "company", "success",
    )
    assert "private-chat-key" not in str(usage.error_summary)


def test_customer_llm_stream_uses_governed_model_and_writes_success_usage(db, encryption_key, monkeypatch):
    import asyncio
    from app.services import customer_llm_service

    user, _group = _seed_user_and_group(db)
    model = AIModel(
        id="stream-governed-chat", display_name="Stream governed chat", provider_name="provider-chat",
        capability="chat", request_model_name="stream-provider-chat-v1",
    )
    db.add_all([
        model,
        AIFeatureModel(feature_key="customer_service.chat", model_id=model.id, is_default=True),
        AIModelAccessRule(feature_key="customer_service.chat", model_id=model.id, subject_type="user", subject_id=user.id, effect="allow"),
    ])
    create_credential(db, "provider-chat", "https://chat.provider.example", "private-stream-key", "company")
    db.commit()

    async def fake_stream(_db, _messages, **kwargs):
        assert kwargs["resolved_model"].model.id == model.id
        assert kwargs["resolved_model"].api_key == "private-stream-key"
        assert kwargs["api_model_override"] is None
        yield "governed "
        yield "stream"

    monkeypatch.setattr(customer_llm_service.dmxapi_service, "chat_completion_stream", fake_stream)

    async def collect():
        return [chunk async for chunk in customer_llm_service.chat_completion_stream(
            db, [{"role": "user", "content": "hello"}], user=user,
        )]

    assert asyncio.run(collect()) == ["governed ", "stream"]
    usage = db.query(AIModelUsageLog).one()
    assert (usage.user_id, usage.feature_key, usage.model_id, usage.credential_scope_type, usage.result) == (
        user.id, "customer_service.chat", model.id, "company", "success",
    )


@pytest.mark.parametrize(
    ("provider_error", "expected_result", "expected_summary"),
    [
        (TimeoutError("private-timeout-key must not be logged"), "timeout", "TimeoutError"),
        (RuntimeError("private-failure-key must not be logged"), "failed", "RuntimeError"),
    ],
)
def test_customer_llm_stream_logs_safe_failure(db, encryption_key, monkeypatch, provider_error, expected_result, expected_summary):
    import asyncio
    from app.services import customer_llm_service

    user, _group = _seed_user_and_group(db)
    model = AIModel(
        id="failed-governed-chat", display_name="Failed governed chat", provider_name="provider-chat",
        capability="chat", request_model_name="failed-provider-chat-v1",
    )
    db.add_all([
        model,
        AIFeatureModel(feature_key="customer_service.chat", model_id=model.id, is_default=True),
        AIModelAccessRule(feature_key="customer_service.chat", model_id=model.id, subject_type="user", subject_id=user.id, effect="allow"),
    ])
    create_credential(db, "provider-chat", "https://chat.provider.example", "private-stream-key", "company")
    db.commit()

    async def failed_stream(*_args, **_kwargs):
        raise provider_error
        yield "unreachable"

    monkeypatch.setattr(customer_llm_service.dmxapi_service, "chat_completion_stream", failed_stream)

    async def collect():
        return [chunk async for chunk in customer_llm_service.chat_completion_stream(
            db, [{"role": "user", "content": "hello"}], user=user,
        )]

    with pytest.raises(type(provider_error)):
        asyncio.run(collect())
    usage = db.query(AIModelUsageLog).one()
    assert usage.result == expected_result
    assert usage.error_summary == expected_summary
    assert "private-" not in str(usage.error_summary)


def test_governed_chat_ignores_api_model_override(db, encryption_key, monkeypatch):
    import asyncio
    from app.services import customer_llm_service

    user, _group = _seed_user_and_group(db)
    model = AIModel(
        id="authoritative-chat", display_name="Authoritative chat", provider_name="provider-chat",
        capability="chat", request_model_name="approved-provider-model",
    )
    db.add_all([
        model,
        AIFeatureModel(feature_key="customer_service.chat", model_id=model.id, is_default=True),
        AIModelAccessRule(feature_key="customer_service.chat", model_id=model.id, subject_type="user", subject_id=user.id, effect="allow"),
    ])
    create_credential(db, "provider-chat", "https://chat.provider.example", "private-key", "company")
    db.commit()

    async def fake_chat_completion(_db, _messages, **kwargs):
        assert kwargs["resolved_model"].model.request_model_name == "approved-provider-model"
        assert kwargs["api_model_override"] is None
        return "answer"

    monkeypatch.setattr(customer_llm_service.dmxapi_service, "chat_completion", fake_chat_completion)

    assert asyncio.run(customer_llm_service.chat_completion(
        db, [{"role": "user", "content": "hello"}], user=user, api_model_override="attacker-model",
    )) == "answer"


@pytest.mark.parametrize(
    ("api_format", "request_model_name", "expected_provider"),
    [
        ("gemini", "custom-image-model", "gemini"),
        ("openai", "gemini-looking-name", "openai"),
    ],
)
def test_generation_routes_by_configured_api_format(db, encryption_key, monkeypatch, api_format, request_model_name, expected_provider):
    import asyncio
    from app.schemas.generation import Txt2ImgRequest
    from app.services import generation_service

    user, _group = _seed_user_and_group(db)
    model = AIModel(
        id=f"{api_format}-route-model", display_name="Route model", provider_name="provider-image",
        capability="image", request_model_name=request_model_name, api_format=api_format,
    )
    db.add_all([model, AIFeatureModel(feature_key="generation.image", model_id=model.id, is_default=True)])
    create_credential(db, "provider-image", "https://image.provider.example", "image-key", "company")
    db.commit()
    resolved = resolve_authorized_model(db, user, "generation.image", model.id, "image")
    invoked: list[str] = []

    async def fake_openai(*_args, **_kwargs):
        invoked.append("openai")
        return {"data": []}

    async def fake_gemini(*_args, **_kwargs):
        invoked.append("gemini")
        return {"data": []}

    monkeypatch.setattr(generation_service, "txt2img", fake_openai)
    monkeypatch.setattr(generation_service, "txt2img_gemini", fake_gemini)

    asyncio.run(generation_service.create_txt2img(
        db, user, Txt2ImgRequest(prompt="cup", model_name=model.id), resolved_model=resolved,
    ))

    assert invoked == [expected_provider]
