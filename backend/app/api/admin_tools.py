from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_super_admin
from ..models.tool import Tool
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
    payload_data = payload.model_dump(mode="json")
    tool = tool_registry_service.create_tool(db, payload_data)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="登记内部工具",
        target_type="tool",
        target_id=tool.tool_key,
        target_name=tool.name,
        request_data=payload_data,
        response_data={"entry_type": tool.entry_type, "is_enabled": tool.is_enabled},
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
    payload_data = payload.model_dump(exclude_unset=True, mode="json")
    tool = tool_registry_service.update_tool(db, tool_key, payload_data)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="更新内部工具",
        target_type="tool",
        target_id=tool.tool_key,
        target_name=tool.name,
        request_data=payload_data,
        response_data={"is_enabled": tool.is_enabled},
        request=request,
    )
    return tool


@router.delete("/{tool_key}")
def delete_registered_tool(
    tool_key: str,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    tool = db.query(Tool).filter(Tool.tool_key == tool_key).first()
    target_name = tool.name if tool else tool_key
    result = tool_registry_service.delete_tool(db, tool_key)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除外部工具",
        target_type="tool",
        target_id=tool_key,
        target_name=target_name,
        response_data=result,
        request=request,
    )
    return result
