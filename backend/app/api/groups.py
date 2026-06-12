from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from ..core.database import get_db
from ..core.security import get_current_super_admin
from ..models.user import User
from ..services import group_service, operation_log_service

router = APIRouter(prefix="/api/admin/groups", tags=["groups"])


class GroupCreateRequest(BaseModel):
    group_name: str
    description: Optional[str] = None


class GroupUpdateRequest(BaseModel):
    group_name: Optional[str] = None
    description: Optional[str] = None


class AddUserRequest(BaseModel):
    user_id: str
    group_role: str = "member"


class UpdateRoleRequest(BaseModel):
    group_role: str


class UpdateGroupPermissionsRequest(BaseModel):
    permission_keys: list[str]


@router.get("")
def list_groups(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return group_service.get_groups(db)


@router.get("/permissions")
def list_permissions(
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return group_service.get_permissions(db)


@router.post("")
def create_group(
    req: GroupCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    group = group_service.create_group(db, name=req.group_name, description=req.description)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="创建团队",
        target_type="group",
        target_id=group["id"],
        target_name=group["group_name"],
        request_data=req.model_dump(),
        response_data=group,
        request=request,
    )
    return group


@router.put("/{group_id}")
def update_group(
    group_id: str,
    req: GroupUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    group = group_service.update_group(db, group_id, name=req.group_name, description=req.description)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="编辑团队",
        target_type="group",
        target_id=group_id,
        target_name=group["group_name"],
        request_data=req.model_dump(exclude_unset=True),
        response_data=group,
        request=request,
    )
    return group


@router.delete("/{group_id}")
def delete_group(
    group_id: str,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    group = group_service.get_group_by_id(db, group_id)
    target_name = group.group_name if group else group_id
    result = group_service.delete_group(db, group_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除团队",
        target_type="group",
        target_id=group_id,
        target_name=target_name,
        response_data=result,
        request=request,
    )
    return result


@router.get("/{group_id}/users")
def list_group_members(
    group_id: str,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return group_service.get_group_members(db, group_id)


@router.get("/{group_id}/permissions")
def list_group_permissions(
    group_id: str,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return group_service.get_group_permissions(db, group_id)


@router.put("/{group_id}/permissions")
def update_group_permissions(
    group_id: str,
    req: UpdateGroupPermissionsRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    permissions = group_service.update_group_permissions(db, group_id, req.permission_keys)
    group = group_service.get_group_by_id(db, group_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="更新团队权限",
        target_type="group_permissions",
        target_id=group_id,
        target_name=group.group_name if group else group_id,
        request_data=req.model_dump(),
        response_data={"permissions": permissions},
        request=request,
    )
    return permissions


@router.post("/{group_id}/users")
def add_user_to_group(
    group_id: str,
    req: AddUserRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    membership = group_service.add_user_to_group(db, group_id, req.user_id, req.group_role)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="添加团队成员",
        target_type="user_group",
        target_id=f"{group_id}:{req.user_id}",
        target_name=req.user_id,
        request_data=req.model_dump(),
        response_data={"group_id": group_id, "user_id": req.user_id, "group_role": req.group_role},
        request=request,
    )
    return membership


@router.delete("/{group_id}/users/{user_id}")
def remove_user_from_group(
    group_id: str,
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    result = group_service.remove_user_from_group(db, group_id, user_id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="移除团队成员",
        target_type="user_group",
        target_id=f"{group_id}:{user_id}",
        target_name=user_id,
        response_data=result,
        request=request,
    )
    return result


@router.put("/{group_id}/users/{user_id}")
def update_user_role(
    group_id: str,
    user_id: str,
    req: UpdateRoleRequest,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    membership = group_service.update_user_group_role(db, group_id, user_id, req.group_role)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="update",
        action_name="更新团队角色",
        target_type="user_group",
        target_id=f"{group_id}:{user_id}",
        target_name=user_id,
        request_data=req.model_dump(),
        response_data={"group_id": group_id, "user_id": user_id, "group_role": req.group_role},
        request=request,
    )
    return membership
