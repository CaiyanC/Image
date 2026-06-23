from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ..core.database import get_db
from ..core.security import get_current_super_admin
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
    operator_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return operation_log_service.list_operation_logs(
        db,
        skip=skip,
        limit=limit,
        action_type=action_type,
        target_type=target_type,
        status=status,
        search=search,
        operator_id=operator_id,
        date_from=date_from,
        date_to=date_to,
    )
