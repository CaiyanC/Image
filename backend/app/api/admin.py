from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from ..core.database import get_db
from ..core.security import get_current_super_admin
from ..models.operation_logs import OperationLog
from ..models.user import User
from ..services import dmxapi_service, operation_log_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ModelItem(BaseModel):
    id: str
    name: str
    type: str
    description: str = ""
    api_key: str = ""
    api_base_url: str = ""
    api_format: str = "openai"
    api_model: str = ""
    txt2img_url: str = ""
    img2img_url: str = ""
    chat_url: str = ""
    embedding_url: str = ""
    enabled: bool = True


class ModelsConfigRequest(BaseModel):
    models: list[ModelItem]


@router.get("/models-config")
def get_models_config(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return dmxapi_service.get_available_models(db)


@router.put("/models-config")
def update_models_config(
    req: ModelsConfigRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    dmxapi_service.set_model_config(db, [m.model_dump() for m in req.models])
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="更新模型配置",
        target_type="system_config",
        target_id="models-config",
        target_name="模型配置",
        request_data=req.model_dump(),
        response_data={"status": "ok"},
        request=request,
    )
    return {"status": "ok"}


@router.get("/operation-logs")
def list_operation_logs(
    skip: int = 0,
    limit: int = 50,
    action_type: str | None = None,
    target_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    limit = min(max(limit, 1), 200)
    query = db.query(OperationLog, User).outerjoin(User, OperationLog.operator_id == User.id)

    if action_type:
        query = query.filter(OperationLog.action_type == action_type)
    if target_type:
        query = query.filter(OperationLog.target_type == target_type)
    if status:
        query = query.filter(OperationLog.status == status)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            OperationLog.action_name.ilike(like),
            OperationLog.target_name.ilike(like),
            User.username.ilike(like),
        ))

    total = query.count()
    rows = (
        query.order_by(OperationLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": log.id,
                "operator_id": log.operator_id,
                "operator_name": user.username if user else "-",
                "action_type": log.action_type,
                "action_name": log.action_name,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "target_name": log.target_name,
                "request_data": log.request_data,
                "response_data": log.response_data,
                "status": log.status,
                "error_message": log.error_message,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at,
            }
            for log, user in rows
        ],
        "total": total,
    }
