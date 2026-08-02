from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_super_admin, get_current_user
from ..models.ai_governance import (
    AIFeatureModel,
    AIModel,
    AIModelAccessRule,
    AIModelUsageLog,
    AIProviderCredential,
)
from ..models.user import User
from ..schemas.model_governance import (
    AccessRuleResponse,
    AccessRuleSetRequest,
    AuthorizationOverviewSelectionRequest,
    AuthorizationOverviewResponse,
    CredentialCreateRequest,
    CredentialResponse,
    CredentialUpdateRequest,
    FeatureModelResponse,
    FeatureModelSetRequest,
    ModelCreateRequest,
    ModelResponse,
    ModelUpdateRequest,
    SelectableModelResponse,
    UsageLogListResponse,
)
from ..services import model_governance_service, operation_log_service


router = APIRouter(tags=["model-governance"])
admin_router = APIRouter(prefix="/api/admin/model-governance", tags=["admin-model-governance"])


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} not found")


@admin_router.get("/authorization-overview", response_model=AuthorizationOverviewResponse)
def authorization_overview(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return model_governance_service.build_authorization_overview(db)


@admin_router.put(
    "/authorization-overview/{subject_type}/{subject_id}/features/{feature_key}",
    response_model=list[AccessRuleResponse],
)
def replace_authorization_overview_feature_models(
    subject_type: str,
    subject_id: str,
    feature_key: str,
    payload: AuthorizationOverviewSelectionRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    if subject_type not in {"group", "user"}:
        raise HTTPException(status_code=422, detail="Subject type must be group or user")
    rules = model_governance_service.replace_subject_feature_models(
        db,
        subject_type=subject_type,
        subject_id=subject_id,
        feature_key=feature_key,
        model_ids=set(payload.model_ids),
    )
    audit_data = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "feature_key": feature_key,
        "model_count": len(payload.model_ids),
    }
    _write_audit(
        db, current_user, request,
        action_type="replace", action_name="Replace subject feature models",
        target_type="ai_model_access_rule", target_id=subject_id,
        target_name=f"{subject_type}:{feature_key}",
        request_data=audit_data, response_data=audit_data,
    )
    return rules


def _validate_credential_scope(scope_type: str, scope_id: str | None) -> None:
    if scope_type == "company" and scope_id is not None:
        raise HTTPException(status_code=422, detail="Company credentials cannot have a scope id")
    if scope_type in {"group", "user"} and not scope_id:
        raise HTTPException(status_code=422, detail="User and group credentials require a scope id")


def _audit_payload(payload: dict) -> dict:
    safe = {key: value for key, value in payload.items() if key != "api_key"}
    if "api_key" in payload:
        safe["api_key_changed"] = True
    return safe


def _write_audit(
    db: Session,
    current_user: User,
    request: Request,
    *,
    action_type: str,
    action_name: str,
    target_type: str,
    target_id: str,
    target_name: str,
    request_data: dict,
    response_data: dict,
) -> None:
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type=action_type,
        action_name=action_name,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        request_data=_audit_payload(request_data),
        response_data=_audit_payload(response_data),
        request=request,
    )


@router.get("/api/model-governance/features/{feature_key}/models", response_model=list[SelectableModelResponse])
def selectable_models(
    feature_key: str,
    capability: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return [
        SelectableModelResponse(id=model.id, name=model.display_name, capability=model.capability)
        for model in model_governance_service.list_selectable_models(db, current_user, feature_key, capability)
    ]


@admin_router.get("/credentials", response_model=list[CredentialResponse])
def list_credentials(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(AIProviderCredential).order_by(AIProviderCredential.provider_name, AIProviderCredential.scope_type)))


@admin_router.post("/credentials", response_model=CredentialResponse)
def create_credential(
    payload: CredentialCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    _validate_credential_scope(data["scope_type"], data["scope_id"])
    credential = model_governance_service.create_credential(db, **data)
    response = CredentialResponse.model_validate(credential)
    _write_audit(
        db, current_user, request,
        action_type="create", action_name="Create AI provider credential",
        target_type="ai_provider_credential", target_id=credential.id, target_name=credential.provider_name,
        request_data=data, response_data=response.model_dump(),
    )
    return response


@admin_router.put("/credentials/{credential_id}", response_model=CredentialResponse)
def update_credential(
    credential_id: str,
    payload: CredentialUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    credential = db.get(AIProviderCredential, credential_id)
    if credential is None:
        raise _not_found("Credential")
    changes = payload.model_dump(exclude_unset=True)
    scope_type = changes.get("scope_type", credential.scope_type)
    scope_id = changes.get("scope_id", credential.scope_id)
    _validate_credential_scope(scope_type, scope_id)
    for key, value in changes.items():
        if key == "api_key":
            credential.api_key_ciphertext = model_governance_service.encrypt_credential(value)
            credential.key_hint = value[-4:]
        else:
            setattr(credential, key, value)
    db.flush()
    response = CredentialResponse.model_validate(credential)
    _write_audit(
        db, current_user, request,
        action_type="update", action_name="Update AI provider credential",
        target_type="ai_provider_credential", target_id=credential.id, target_name=credential.provider_name,
        request_data=changes, response_data=response.model_dump(),
    )
    return response


@admin_router.get("/models", response_model=list[ModelResponse])
def list_models(_: User = Depends(get_current_super_admin), db: Session = Depends(get_db)):
    return list(db.scalars(select(AIModel).order_by(AIModel.display_name)))


@admin_router.post("/models", response_model=ModelResponse)
def create_model(
    payload: ModelCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    model = AIModel(**payload.model_dump())
    db.add(model)
    db.flush()
    _write_audit(
        db, current_user, request,
        action_type="create", action_name="Create AI model", target_type="ai_model",
        target_id=model.id, target_name=model.display_name,
        request_data=payload.model_dump(), response_data=ModelResponse.model_validate(model).model_dump(),
    )
    return model


@admin_router.put("/models/{model_id}", response_model=ModelResponse)
def update_model(
    model_id: str,
    payload: ModelUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    model = db.get(AIModel, model_id)
    if model is None:
        raise _not_found("Model")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(model, key, value)
    db.flush()
    _write_audit(
        db, current_user, request,
        action_type="update", action_name="Update AI model", target_type="ai_model",
        target_id=model.id, target_name=model.display_name,
        request_data=changes, response_data=ModelResponse.model_validate(model).model_dump(),
    )
    return model


@admin_router.get("/feature-models", response_model=list[FeatureModelResponse])
def list_feature_models(
    feature_key: str | None = None,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    query = select(AIFeatureModel).order_by(AIFeatureModel.feature_key, AIFeatureModel.sort_order)
    if feature_key:
        query = query.where(AIFeatureModel.feature_key == feature_key)
    return list(db.scalars(query))


@admin_router.put("/feature-models/{feature_key}/{model_id}", response_model=FeatureModelResponse)
def set_feature_model(
    feature_key: str,
    model_id: str,
    payload: FeatureModelSetRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    if db.get(AIModel, model_id) is None:
        raise _not_found("Model")
    if payload.is_default:
        db.query(AIFeatureModel).filter(
            AIFeatureModel.feature_key == feature_key,
            AIFeatureModel.model_id != model_id,
            AIFeatureModel.is_default.is_(True),
        ).update({AIFeatureModel.is_default: False}, synchronize_session=False)
        db.flush()
    link = db.scalar(select(AIFeatureModel).where(
        AIFeatureModel.feature_key == feature_key, AIFeatureModel.model_id == model_id,
    ))
    if link is None:
        link = AIFeatureModel(feature_key=feature_key, model_id=model_id, **payload.model_dump())
        db.add(link)
        action_type = "create"
    else:
        for key, value in payload.model_dump().items():
            setattr(link, key, value)
        action_type = "update"
    db.flush()
    _write_audit(
        db, current_user, request,
        action_type=action_type, action_name="Set feature model link", target_type="ai_feature_model",
        target_id=link.id, target_name=f"{feature_key}:{model_id}",
        request_data=payload.model_dump(), response_data=FeatureModelResponse.model_validate(link).model_dump(),
    )
    return link


@admin_router.get("/access-rules", response_model=list[AccessRuleResponse])
def list_access_rules(
    feature_key: str | None = None,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    query = select(AIModelAccessRule).order_by(AIModelAccessRule.feature_key, AIModelAccessRule.subject_type)
    if feature_key:
        query = query.where(AIModelAccessRule.feature_key == feature_key)
    return list(db.scalars(query))


@admin_router.put("/access-rules/{feature_key}", response_model=AccessRuleResponse)
def set_access_rule(
    feature_key: str,
    payload: AccessRuleSetRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    if db.get(AIModel, payload.model_id) is None:
        raise _not_found("Model")
    rule = db.scalar(select(AIModelAccessRule).where(
        AIModelAccessRule.feature_key == feature_key,
        AIModelAccessRule.model_id == payload.model_id,
        AIModelAccessRule.subject_type == payload.subject_type,
        AIModelAccessRule.subject_id == payload.subject_id,
    ))
    if rule is None:
        rule = AIModelAccessRule(feature_key=feature_key, **payload.model_dump())
        db.add(rule)
        action_type = "create"
    else:
        rule.effect = payload.effect
        action_type = "update"
    db.flush()
    _write_audit(
        db, current_user, request,
        action_type=action_type, action_name="Set AI model access rule", target_type="ai_model_access_rule",
        target_id=rule.id, target_name=f"{feature_key}:{payload.model_id}",
        request_data=payload.model_dump(), response_data=AccessRuleResponse.model_validate(rule).model_dump(),
    )
    return rule


@admin_router.get("/usage-logs", response_model=UsageLogListResponse)
def list_usage_logs(
    skip: int = 0,
    limit: int = 50,
    user_id: str | None = None,
    feature_key: str | None = None,
    model_id: str | None = None,
    result: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    if result is not None and status is not None and result != status:
        raise HTTPException(status_code=422, detail="result and status filters must match when both are provided")
    limit = min(max(limit, 1), 200)
    skip = max(skip, 0)
    effective_result = result if result is not None else status
    filters = []
    if user_id:
        filters.append(AIModelUsageLog.user_id == user_id)
    if feature_key:
        filters.append(AIModelUsageLog.feature_key == feature_key)
    if model_id:
        filters.append(AIModelUsageLog.model_id == model_id)
    if effective_result:
        filters.append(AIModelUsageLog.result == effective_result)
    if date_from:
        filters.append(AIModelUsageLog.created_at >= date_from)
    if date_to:
        filters.append(AIModelUsageLog.created_at <= date_to)
    query = (
        select(AIModelUsageLog)
        .where(*filters)
        .order_by(AIModelUsageLog.created_at.desc(), AIModelUsageLog.id.desc())
    )
    total_query = select(func.count()).select_from(AIModelUsageLog).where(*filters)
    return {
        "items": list(db.scalars(query.offset(skip).limit(limit))),
        "total": db.scalar(total_query),
    }
