from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..core.security import get_current_super_admin, get_user_groups, get_user_permissions
from ..models.user import User
from ..schemas.user import AdminPasswordReset, UserCreate, UserResponse, UserUpdate, UserGroupInfo
from ..services import operation_log_service, user_service

router = APIRouter(prefix="/api/users", tags=["users"])


class AdminUserCreate(UserCreate):
    group_id: str | None = None
    group_role: str = "member"


def _enrich_user_response(user, db):
    groups = get_user_groups(db, user.id)
    resp = UserResponse.model_validate(user)
    resp.groups = [UserGroupInfo(**g) for g in groups]
    resp.permissions = get_user_permissions(db, user.id)
    return resp


@router.get("", response_model=List[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    users = user_service.get_users(db, skip, limit)
    return [_enrich_user_response(u, db) for u in users]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    _: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    user = user_service.get_user_by_id(db, user_id)
    return _enrich_user_response(user, db)


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    user_data: AdminUserCreate,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    user = user_service.create_user_with_group(
        db,
        UserCreate(**user_data.model_dump(exclude={"group_id", "group_role"})),
        group_id=user_data.group_id,
        group_role=user_data.group_role,
    )
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="create",
        action_name="创建用户",
        target_type="user",
        target_id=user.id,
        target_name=user.username,
        request_data=user_data.model_dump(),
        response_data={"user_id": user.id, "username": user.username},
        request=request,
    )
    return _enrich_user_response(user, db)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    user_data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    before = user_service.get_user_by_id(db, user_id)
    old_active = before.is_active if before else None
    user = user_service.update_user(db, user_id, user_data)
    payload = user_data.model_dump(exclude_unset=True)
    if "is_active" in payload and payload["is_active"] != old_active:
        action_name = "启用用户" if payload["is_active"] else "禁用用户"
        action_type = "enable" if payload["is_active"] else "disable"
    elif "password" in payload:
        action_name = "修改用户密码"
        action_type = "reset_password"
    else:
        action_name = "更新用户"
        action_type = "update"
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type=action_type,
        action_name=action_name,
        target_type="user",
        target_id=user.id,
        target_name=user.username,
        request_data=payload,
        response_data={"user_id": user.id, "username": user.username},
        request=request,
    )
    return _enrich_user_response(user, db)


@router.put("/{user_id}/password/reset", response_model=UserResponse)
def reset_user_password(
    user_id: str,
    password_data: AdminPasswordReset,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    user = user_service.reset_user_password(db, user_id, password_data.new_password)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="reset_password",
        action_name="管理员重置密码",
        target_type="user",
        target_id=user.id,
        target_name=user.username,
        request_data={"user_id": user_id, "new_password": password_data.new_password},
        response_data={"user_id": user.id, "username": user.username},
        request=request,
    )
    return _enrich_user_response(user, db)


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    target = user_service.get_user_by_id(db, user_id)
    target_name = target.username if target else user_id
    user_service.delete_user(db, user_id, current_user_id=current_user.id)
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="delete",
        action_name="删除用户",
        target_type="user",
        target_id=user_id,
        target_name=target_name,
        response_data={"detail": "User deleted"},
        request=request,
    )
    return {"detail": "User deleted"}
