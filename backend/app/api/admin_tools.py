from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_super_admin
from ..models.user import User
from ..schemas.tool import ToolCreateRequest, ToolResponse, ToolUpdateRequest
from ..services import operation_log_service, tool_registry_service


router = APIRouter(prefix="/api/admin/tools", tags=["admin-tools"])


@router.get("", response_model=list[ToolResponse])
def list_registered_tools(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return tool_registry_service.list_tools(db)


@router.post("", response_model=ToolResponse)
def create_registered_tool(
    payload: ToolCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    tool = tool_registry_service.create_tool(db, payload.model_dump())
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="登记内部工具",
        target_type="tool",
        target_id=tool.tool_key,
        target_name=tool.name,
        request_data=payload.model_dump(),
        response_data={"is_enabled": tool.is_enabled},
        request=request,
    )
    return tool


@router.put("/{tool_key}", response_model=ToolResponse)
def update_registered_tool(
    tool_key: str,
    payload: ToolUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    tool = tool_registry_service.update_tool(db, tool_key, payload.model_dump(exclude_unset=True))
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="更新内部工具",
        target_type="tool",
        target_id=tool.tool_key,
        target_name=tool.name,
        request_data=payload.model_dump(exclude_unset=True),
        response_data={"is_enabled": tool.is_enabled},
        request=request,
    )
    return tool
