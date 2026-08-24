import base64
import hashlib
import uuid
from dataclasses import dataclass
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.ai_governance import (
    AIFeatureModel,
    AIModel,
    AIModelAccessRule,
    AIProviderCredential,
)
from ..models.user import User
from ..models.group import Group
from ..models.user_group import UserGroup
from .outbound_url_service import validate_outbound_url


@dataclass(frozen=True)
class ResolvedModel:
    model: AIModel
    credential: AIProviderCredential
    api_key: str


@dataclass(frozen=True)
class AuthorizationOverviewModel:
    model_id: str
    display_name: str
    permission_source: str
    key_available: bool
    credential_scope_type: str | None


@dataclass(frozen=True)
class AuthorizationOverviewFeature:
    feature_key: str
    models: list[AuthorizationOverviewModel]


@dataclass(frozen=True)
class AuthorizationOverviewRow:
    subject_type: str
    subject_id: str
    subject_name: str
    has_personal_override: bool
    features: list[AuthorizationOverviewFeature]


@dataclass(frozen=True)
class AuthorizationOverviewCatalogModel:
    model_id: str
    display_name: str
    provider_name: str


@dataclass(frozen=True)
class AuthorizationOverviewFeatureCatalog:
    feature_key: str
    models: list[AuthorizationOverviewCatalogModel]


@dataclass(frozen=True)
class AuthorizationOverviewGroup:
    subject_id: str
    subject_name: str
    features: list[AuthorizationOverviewFeature]
    members: list[AuthorizationOverviewRow]


@dataclass(frozen=True)
class AuthorizationOverview:
    features: list[AuthorizationOverviewFeatureCatalog]
    groups: list[AuthorizationOverviewGroup]


def _derived_fernet() -> Fernet:
    if not settings.SECRET_KEY:
        raise ValueError("MODEL_CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY is required")
    digest = hashlib.sha256(
        f"caiyan:model-credential:v1:{settings.SECRET_KEY}".encode()
    ).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet() -> Fernet:
    key = settings.MODEL_CREDENTIAL_ENCRYPTION_KEY
    if not key:
        return _derived_fernet()
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise ValueError("MODEL_CREDENTIAL_ENCRYPTION_KEY is invalid") from exc


def encrypt_credential(api_key: str) -> str:
    if not api_key:
        raise ValueError("API credential must not be empty")
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_credential(credential: AIProviderCredential) -> str:
    return decrypt_credential_value(credential.api_key_ciphertext)


def decrypt_credential_value(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        # A deployment can introduce a dedicated key after initially using the
        # SECRET_KEY-derived fallback. Keep those existing rows readable while
        # all new writes use the dedicated key.
        if settings.MODEL_CREDENTIAL_ENCRYPTION_KEY and settings.SECRET_KEY:
            try:
                return _derived_fernet().decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                pass
        raise ValueError("Credential ciphertext cannot be decrypted") from exc


def normalize_credential_ciphertext(ciphertext: str) -> tuple[str, bool]:
    """Rewrap a fallback-encrypted value with the configured dedicated key."""
    primary = _fernet()
    try:
        primary.decrypt(ciphertext.encode())
        return ciphertext, False
    except InvalidToken as exc:
        if not settings.MODEL_CREDENTIAL_ENCRYPTION_KEY or not settings.SECRET_KEY:
            raise ValueError("Credential ciphertext cannot be decrypted") from exc
        try:
            plaintext = _derived_fernet().decrypt(ciphertext.encode()).decode()
        except InvalidToken as fallback_exc:
            raise ValueError("Credential ciphertext cannot be decrypted") from fallback_exc
        return encrypt_credential(plaintext), True


def migrate_provider_credential_encryption(db: Session) -> dict[str, int]:
    migrated = 0
    failed = 0
    credentials = db.query(AIProviderCredential).all()
    for credential in credentials:
        try:
            normalized, changed = normalize_credential_ciphertext(credential.api_key_ciphertext)
            if changed:
                credential.api_key_ciphertext = normalized
                migrated += 1
        except Exception:
            failed += 1
    if migrated:
        db.commit()
    elif failed:
        db.rollback()
    return {"migrated": migrated, "failed": failed}


def validate_provider_url(url: str, *, resolve_dns: bool = False) -> str:
    return validate_outbound_url(
        url,
        resolve_dns=resolve_dns,
        allow_private=settings.ALLOW_PRIVATE_MODEL_ENDPOINTS,
        allow_insecure_http=settings.ALLOW_INSECURE_MODEL_ENDPOINTS,
    )


def create_credential(
    db: Session,
    provider_name: str,
    api_base_url: str,
    api_key: str,
    scope_type: str,
    scope_id: str | None = None,
    *,
    is_enabled: bool = True,
) -> AIProviderCredential:
    if scope_type not in {"company", "group", "user"}:
        raise ValueError("Credential scope type is invalid")
    if scope_type == "company" and scope_id is not None:
        raise ValueError("Company credentials must not have a scope id")
    if scope_type != "company" and not scope_id:
        raise ValueError("User and group credentials require a scope id")
    api_base_url = validate_provider_url(api_base_url)

    credential = AIProviderCredential(
        provider_name=provider_name,
        api_base_url=api_base_url,
        api_key_ciphertext=encrypt_credential(api_key),
        key_hint=api_key[-4:],
        scope_type=scope_type,
        scope_id=scope_id,
        is_enabled=is_enabled,
    )
    db.add(credential)
    db.flush()
    return credential


def _access_subject_id(value: object) -> str:
    """Normalize UUID-backed user/group IDs for varchar governance columns."""
    return str(value)


def _uuid_identifier(value: object) -> object:
    """Bind route IDs correctly when the legacy users/groups tables use UUID."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return str(value)


def _user_group_ids(db: Session, user: User) -> list[str]:
    return [
        _access_subject_id(group_id)
        for group_id in db.scalars(select(UserGroup.group_id).where(UserGroup.user_id == user.id))
    ]


def _is_allowed(db: Session, user: User, feature_key: str, model_id: str) -> bool:
    user_subject_id = _access_subject_id(user.id)
    user_effects = list(db.scalars(select(AIModelAccessRule.effect).where(
        AIModelAccessRule.feature_key == feature_key,
        AIModelAccessRule.model_id == model_id,
        AIModelAccessRule.subject_type == "user",
        AIModelAccessRule.subject_id == user_subject_id,
    )))
    if "deny" in user_effects:
        return False
    if "allow" in user_effects:
        return True

    group_ids = _user_group_ids(db, user)
    if group_ids:
        group_effects = list(db.scalars(select(AIModelAccessRule.effect).where(
            AIModelAccessRule.feature_key == feature_key,
            AIModelAccessRule.model_id == model_id,
            AIModelAccessRule.subject_type == "group",
            AIModelAccessRule.subject_id.in_(group_ids),
        )))
        if "deny" in group_effects:
            return False
        if "allow" in group_effects:
            return True

    return bool(db.scalar(select(AIFeatureModel.id).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.model_id == model_id,
        AIFeatureModel.is_enabled.is_(True),
        AIFeatureModel.is_default.is_(True),
    )))


def _credential_candidates(db: Session, user: User, provider_name: str) -> list[AIProviderCredential]:
    """Return credentials by scope precedence; group ties use ascending group ID."""
    group_ids = _user_group_ids(db, user)
    user_id = _access_subject_id(user.id)
    credentials = list(db.scalars(select(AIProviderCredential).where(
        AIProviderCredential.provider_name == provider_name,
        AIProviderCredential.is_enabled.is_(True),
    )))
    personal = [item for item in credentials if item.scope_type == "user" and item.scope_id == user_id]
    group = sorted(
        (item for item in credentials if item.scope_type == "group" and item.scope_id in group_ids),
        key=lambda item: item.scope_id or "",
    )
    company = [item for item in credentials if item.scope_type == "company"]
    return personal + group + company


def _resolve_credential(db: Session, user: User, provider_name: str) -> tuple[AIProviderCredential, str] | None:
    for credential in _credential_candidates(db, user, provider_name):
        try:
            return credential, decrypt_credential(credential)
        except ValueError:
            continue
    return None


def _feature_model(db: Session, feature_key: str, model_id: str, capability: str) -> AIModel | None:
    return db.scalar(select(AIModel).join(AIFeatureModel, AIFeatureModel.model_id == AIModel.id).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.model_id == model_id,
        AIFeatureModel.is_enabled.is_(True),
        AIModel.capability == capability,
        AIModel.is_enabled.is_(True),
    ))


def list_selectable_models(db: Session, user: User, feature_key: str, capability: str) -> list[AIModel]:
    models = list(db.scalars(select(AIModel).join(AIFeatureModel, AIFeatureModel.model_id == AIModel.id).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.is_enabled.is_(True),
        AIModel.capability == capability,
        AIModel.is_enabled.is_(True),
    ).order_by(AIFeatureModel.sort_order, AIModel.display_name)))
    return [
        model for model in models
        if _is_allowed(db, user, feature_key, model.id)
        and _resolve_credential(db, user, model.provider_name) is not None
    ]


def resolve_authorized_model(
    db: Session,
    user: User,
    feature_key: str,
    model_id: str,
    capability: str,
) -> ResolvedModel:
    model = _feature_model(db, feature_key, model_id, capability)
    if model is None:
        raise HTTPException(status_code=403, detail="Model is unavailable for this feature or capability")
    if not _is_allowed(db, user, feature_key, model.id):
        raise HTTPException(status_code=403, detail="Model is not authorized for this user")
    resolved_credential = _resolve_credential(db, user, model.provider_name)
    if resolved_credential is None:
        raise HTTPException(status_code=403, detail="No usable credential is available for this model")
    credential, api_key = resolved_credential
    return ResolvedModel(model=model, credential=credential, api_key=api_key)


def resolve_default_authorized_model(
    db: Session,
    user: User,
    feature_key: str,
    capability: str,
) -> ResolvedModel:
    """Resolve the feature default through the same user policy gate."""
    default_model_id = db.scalar(select(AIFeatureModel.model_id).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.is_enabled.is_(True),
        AIFeatureModel.is_default.is_(True),
    ))
    if default_model_id is None:
        raise HTTPException(status_code=403, detail="No governed default model is configured for this feature")
    return resolve_authorized_model(db, user, feature_key, default_model_id, capability)


def _allowed_permission_source(
    db: Session,
    *,
    feature_key: str,
    model_id: str,
    group_ids: list[str],
    user_id: str | None = None,
) -> str | None:
    normalized_group_ids = [_access_subject_id(group_id) for group_id in group_ids]
    normalized_user_id = _access_subject_id(user_id) if user_id is not None else None
    if normalized_user_id is not None:
        user_effects = list(db.scalars(select(AIModelAccessRule.effect).where(
            AIModelAccessRule.feature_key == feature_key,
            AIModelAccessRule.model_id == model_id,
            AIModelAccessRule.subject_type == "user",
            AIModelAccessRule.subject_id == normalized_user_id,
        )))
        if "deny" in user_effects:
            return None
        if "allow" in user_effects:
            return "user_allow"

    if normalized_group_ids:
        group_effects = list(db.scalars(select(AIModelAccessRule.effect).where(
            AIModelAccessRule.feature_key == feature_key,
            AIModelAccessRule.model_id == model_id,
            AIModelAccessRule.subject_type == "group",
            AIModelAccessRule.subject_id.in_(normalized_group_ids),
        )))
        if "deny" in group_effects:
            return None
        if "allow" in group_effects:
            return "group_allow"

    if db.scalar(select(AIFeatureModel.id).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.model_id == model_id,
        AIFeatureModel.is_enabled.is_(True),
        AIFeatureModel.is_default.is_(True),
    )):
        return "feature_default"
    return None


def _credential_status_for_group(
    db: Session, group_id: str, provider_name: str,
) -> tuple[bool, str | None]:
    normalized_group_id = _access_subject_id(group_id)
    credentials = list(db.scalars(select(AIProviderCredential).where(
        AIProviderCredential.provider_name == provider_name,
        AIProviderCredential.is_enabled.is_(True),
    )))
    candidates = [
        *[item for item in credentials if item.scope_type == "group" and item.scope_id == normalized_group_id],
        *[item for item in credentials if item.scope_type == "company"],
    ]
    for credential in candidates:
        try:
            decrypt_credential(credential)
            return True, credential.scope_type
        except ValueError:
            continue
    return False, None


def _credential_status_for_user(
    db: Session, user: User, provider_name: str,
) -> tuple[bool, str | None]:
    resolved = _resolve_credential(db, user, provider_name)
    if resolved is None:
        return False, None
    return True, resolved[0].scope_type


def _provider_endpoint(db: Session, provider_name: str) -> str | None:
    """Return an administrator-provisioned endpoint for a provider.

    Personal users are deliberately not allowed to submit or change a base URL.
    The governance schema predates a separate provider table, so the endpoint
    is sourced from an existing credential row.  The endpoint is configuration,
    not a secret; the key itself is never read into this public response.
    Prefer shared scopes, then use a deterministic credential row as a
    compatibility path for deployments that currently have only an admin's
    personal provider row.
    """
    credentials = list(db.scalars(select(AIProviderCredential).where(
        AIProviderCredential.provider_name == provider_name,
    )))
    scope_order = {"company": 0, "group": 1, "user": 2}
    credentials.sort(key=lambda item: (
        scope_order.get(item.scope_type, 99),
        item.scope_id or "",
        item.id,
    ))
    return next((item.api_base_url for item in credentials if item.api_base_url), None)


def list_personal_credential_options(db: Session, user: User) -> list[dict]:
    """List safe provider choices for the signed-in user.

    The catalog comes from enabled governed models.  A user's own existing
    credential is included as well so it can be replaced or disabled after an
    administrator retires a model.  No other user's credential metadata or
    secret is returned.
    """
    model_rows = list(db.execute(select(AIModel, AIFeatureModel.feature_key).join(
        AIFeatureModel, AIFeatureModel.model_id == AIModel.id,
    ).where(
        AIFeatureModel.is_enabled.is_(True),
        AIModel.is_enabled.is_(True),
    ).order_by(AIModel.provider_name, AIFeatureModel.sort_order, AIModel.display_name, AIModel.id)))

    models_by_provider: dict[str, list[AIModel]] = {}
    seen_model_ids: set[str] = set()
    for model, feature_key in model_rows:
        if not _is_allowed(db, user, feature_key, model.id):
            continue
        if model.id in seen_model_ids:
            continue
        seen_model_ids.add(model.id)
        models_by_provider.setdefault(model.provider_name, []).append(model)

    user_id = _access_subject_id(user.id)
    personal_credentials = list(db.scalars(select(AIProviderCredential).where(
        AIProviderCredential.scope_type == "user",
        AIProviderCredential.scope_id == user_id,
    )))
    personal_by_provider = {item.provider_name: item for item in personal_credentials}
    provider_names = set(models_by_provider) | set(personal_by_provider)

    options: list[dict] = []
    for provider_name in sorted(provider_names):
        credential = personal_by_provider.get(provider_name)
        configured = False
        key_masked = "****"
        if credential is not None:
            try:
                # A decrypt check prevents a stale key_hint from being shown
                # as usable after encryption-key rotation or data corruption.
                decrypt_credential(credential)
                configured = True
                key_masked = f"****{credential.key_hint}" if len(credential.key_hint) == 4 else "****"
            except ValueError:
                configured = False

        resolved = _resolve_credential(db, user, provider_name)
        options.append({
            "provider_name": provider_name,
            "api_base_url": credential.api_base_url if credential is not None else _provider_endpoint(db, provider_name),
            "personal_credential_id": credential.id if credential is not None else None,
            "api_key_masked": key_masked,
            "is_configured": configured,
            "is_enabled": bool(credential.is_enabled) if credential is not None else False,
            "effective_credential_scope_type": resolved[0].scope_type if resolved is not None else None,
            "has_personal_credential": credential is not None,
            "can_configure": bool(models_by_provider.get(provider_name)) and bool(
                credential is not None and credential.api_base_url
                or credential is None and _provider_endpoint(db, provider_name)
            ),
            "models": [
                {
                    "model_id": model.id,
                    "display_name": model.display_name,
                    "capability": model.capability,
                }
                for model in models_by_provider.get(provider_name, [])
            ],
        })
    return options


def upsert_personal_credential(
    db: Session,
    user: User,
    provider_name: str,
    *,
    api_key: str | None = None,
    is_enabled: bool | None = None,
) -> AIProviderCredential:
    """Create or update only the current user's credential for a provider.

    The provider endpoint is copied from administrator-provisioned governance
    data.  There is intentionally no user-controlled scope, scope id, or base
    URL in this function's contract.
    """
    normalized_provider = provider_name.strip()
    if not normalized_provider:
        raise ValueError("Provider name must not be empty")

    user_id = _access_subject_id(user.id)
    credential = db.scalar(select(AIProviderCredential).where(
        AIProviderCredential.provider_name == normalized_provider,
        AIProviderCredential.scope_type == "user",
        AIProviderCredential.scope_id == user_id,
    ))

    normalized_key = api_key.strip() if api_key is not None else None
    if api_key is not None and not normalized_key:
        raise ValueError("API credential must not be empty")

    if credential is None:
        if normalized_key is None:
            raise ValueError("A new personal credential requires an API key")
        option = next(
            (item for item in list_personal_credential_options(db, user)
             if item["provider_name"] == normalized_provider),
            None,
        )
        if option is None or not option["can_configure"] or not option["api_base_url"]:
            raise ValueError("This provider is not configured for personal credentials")
        credential = create_credential(
            db,
            provider_name=normalized_provider,
            api_base_url=option["api_base_url"],
            api_key=normalized_key,
            scope_type="user",
            scope_id=user_id,
            is_enabled=True if is_enabled is None else is_enabled,
        )
        return credential

    if normalized_key is not None:
        credential.api_key_ciphertext = encrypt_credential(normalized_key)
        credential.key_hint = normalized_key[-4:]
    if is_enabled is not None:
        if is_enabled and normalized_key is None:
            try:
                decrypt_credential(credential)
            except ValueError as exc:
                raise ValueError("Enter a new API key before enabling this credential") from exc
        credential.is_enabled = is_enabled
    db.flush()
    return credential


def _enabled_feature_models(db: Session, feature_key: str) -> list[tuple[AIFeatureModel, AIModel]]:
    return list(db.execute(select(AIFeatureModel, AIModel).join(
        AIModel, AIFeatureModel.model_id == AIModel.id,
    ).where(
        AIFeatureModel.feature_key == feature_key,
        AIFeatureModel.is_enabled.is_(True),
        AIModel.is_enabled.is_(True),
    ).order_by(AIFeatureModel.sort_order, AIModel.display_name, AIModel.id)))


def _validate_subject_and_model_ids(
    db: Session,
    subject_type: Literal["group", "user"],
    subject_id: str,
    candidates: list[tuple[AIFeatureModel, AIModel]],
    model_ids: set[str],
) -> None:
    database_subject_id = _uuid_identifier(subject_id)
    if subject_type == "group":
        subject_exists = db.get(Group, database_subject_id) is not None
    elif subject_type == "user":
        subject_exists = db.get(User, database_subject_id) is not None
    else:
        raise HTTPException(status_code=422, detail="Subject type must be group or user")
    if not subject_exists:
        raise HTTPException(status_code=422, detail="Subject does not exist")

    candidate_ids = {model.id for _feature_model, model in candidates}
    if unknown_model_ids := model_ids - candidate_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Models are not enabled for this feature: {', '.join(sorted(unknown_model_ids))}",
        )


def _baseline_model_ids(
    db: Session,
    subject_type: Literal["group", "user"],
    subject_id: str,
    feature_key: str,
    candidates: list[tuple[AIFeatureModel, AIModel]],
) -> set[str]:
    if subject_type == "group":
        return {
            model.id for feature_model, model in candidates
            if feature_model.is_default
        }

    group_ids = [
        _access_subject_id(group_id)
        for group_id in db.scalars(
            select(UserGroup.group_id).where(UserGroup.user_id == _uuid_identifier(subject_id))
        )
    ]
    return {
        model.id for _feature_model, model in candidates
        if _allowed_permission_source(
            db,
            feature_key=feature_key,
            model_id=model.id,
            group_ids=group_ids,
        ) is not None
    }


def _upsert_rule(
    db: Session,
    feature_key: str,
    model_id: str,
    subject_type: Literal["group", "user"],
    subject_id: str,
    effect: Literal["allow", "deny"],
) -> AIModelAccessRule:
    rule = AIModelAccessRule(
        feature_key=feature_key,
        model_id=model_id,
        subject_type=subject_type,
        subject_id=_access_subject_id(subject_id),
        effect=effect,
    )
    db.add(rule)
    return rule


def _subject_feature_rules(
    db: Session,
    subject_type: Literal["group", "user"],
    subject_id: str,
    feature_key: str,
) -> list[AIModelAccessRule]:
    subject_id = _access_subject_id(subject_id)
    return list(db.scalars(select(AIModelAccessRule).where(
        AIModelAccessRule.feature_key == feature_key,
        AIModelAccessRule.subject_type == subject_type,
        AIModelAccessRule.subject_id == subject_id,
    ).order_by(AIModelAccessRule.model_id, AIModelAccessRule.effect)))


def replace_subject_feature_models(
    db: Session,
    *,
    subject_type: Literal["group", "user"],
    subject_id: str,
    feature_key: str,
    model_ids: set[str],
) -> list[AIModelAccessRule]:
    subject_id = _access_subject_id(subject_id)
    candidates = _enabled_feature_models(db, feature_key)
    _validate_subject_and_model_ids(db, subject_type, subject_id, candidates, model_ids)
    baseline_ids = _baseline_model_ids(db, subject_type, subject_id, feature_key, candidates)
    target_effects = {
        **{model_id: "allow" for model_id in model_ids - baseline_ids},
        **{model_id: "deny" for model_id in baseline_ids - model_ids},
    }
    existing_rules = _subject_feature_rules(db, subject_type, subject_id, feature_key)
    existing_by_model = {rule.model_id: rule for rule in existing_rules}

    for model_id, rule in existing_by_model.items():
        target_effect = target_effects.pop(model_id, None)
        if target_effect is None:
            db.delete(rule)
        elif rule.effect != target_effect:
            rule.effect = target_effect

    for model_id, effect in target_effects.items():
        _upsert_rule(db, feature_key, model_id, subject_type, subject_id, effect)
    db.flush()
    return _subject_feature_rules(db, subject_type, subject_id, feature_key)


def _overview_features_for_subject(
    db: Session,
    *,
    feature_keys: list[str],
    group_ids: list[str],
    user: User | None = None,
) -> list[AuthorizationOverviewFeature]:
    result: list[AuthorizationOverviewFeature] = []
    for feature_key in feature_keys:
        models: list[AuthorizationOverviewModel] = []
        for feature_model, model in _enabled_feature_models(db, feature_key):
            source = _allowed_permission_source(
                db,
                feature_key=feature_key,
                model_id=model.id,
                group_ids=group_ids,
                user_id=user.id if user else None,
            )
            if source is None:
                continue
            if user is None:
                available, scope_type = _credential_status_for_group(db, group_ids[0], model.provider_name)
            else:
                available, scope_type = _credential_status_for_user(db, user, model.provider_name)
            models.append(AuthorizationOverviewModel(
                model_id=model.id,
                display_name=model.display_name,
                permission_source=source,
                key_available=available,
                credential_scope_type=scope_type,
            ))
        result.append(AuthorizationOverviewFeature(feature_key=feature_key, models=models))
    return result


def _overview_feature_catalog(db: Session) -> list[AuthorizationOverviewFeatureCatalog]:
    feature_keys = list(db.scalars(select(AIFeatureModel.feature_key).join(
        AIModel, AIFeatureModel.model_id == AIModel.id,
    ).where(
        AIFeatureModel.is_enabled.is_(True),
        AIModel.is_enabled.is_(True),
    ).distinct().order_by(AIFeatureModel.feature_key)))
    return [
        AuthorizationOverviewFeatureCatalog(
            feature_key=feature_key,
            models=[
                AuthorizationOverviewCatalogModel(
                    model_id=model.id,
                    display_name=model.display_name,
                    provider_name=model.provider_name,
                )
                for _feature_model, model in _enabled_feature_models(db, feature_key)
            ],
        )
        for feature_key in feature_keys
    ]


def _has_personal_override(db: Session, user_id: str) -> bool:
    user_id = _access_subject_id(user_id)
    return bool(db.scalar(select(AIModelAccessRule.id).where(
        AIModelAccessRule.subject_type == "user",
        AIModelAccessRule.subject_id == user_id,
    )))


def _overview_group(
    db: Session,
    group: Group,
    feature_catalog: list[AuthorizationOverviewFeatureCatalog],
) -> AuthorizationOverviewGroup:
    members = list(db.scalars(select(User).join(
        UserGroup, UserGroup.user_id == User.id,
    ).where(
        UserGroup.group_id == group.id,
    ).order_by(User.username, User.id)))
    feature_keys = [feature.feature_key for feature in feature_catalog]
    return AuthorizationOverviewGroup(
        subject_id=_access_subject_id(group.id),
        subject_name=group.group_name,
        features=_overview_features_for_subject(
            db, feature_keys=feature_keys, group_ids=[_access_subject_id(group.id)],
        ),
        members=[
            AuthorizationOverviewRow(
                subject_type="user",
                subject_id=_access_subject_id(user.id),
                subject_name=user.display_name or user.username,
                has_personal_override=_has_personal_override(db, user.id),
                features=_overview_features_for_subject(
                    db,
                    feature_keys=feature_keys,
                    group_ids=_user_group_ids(db, user),
                    user=user,
                ),
            )
            for user in members
        ],
    )


def build_authorization_overview(db: Session) -> AuthorizationOverview:
    feature_catalog = _overview_feature_catalog(db)
    groups = list(db.scalars(select(Group).order_by(Group.group_name, Group.id)))
    return AuthorizationOverview(
        features=feature_catalog,
        groups=[_overview_group(db, group, feature_catalog) for group in groups],
    )
