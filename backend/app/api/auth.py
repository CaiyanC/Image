from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.security import verify_password, create_access_token, get_current_user
from ..core.security import get_user_groups, get_user_permissions
from ..models.user import User
from ..schemas.user import (
    PasswordChange,
    UserCreate,
    UserProfileUpdate,
    UserResponse,
    Token,
    LoginRequest,
    UserGroupInfo,
)
from ..services import operation_log_service, user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    return user_service.create_user(db, user_data)


@router.post("/login")
def login(
    req: LoginRequest,
    db: Session = Depends(get_db),
):
    user = user_service.get_user_by_username(db, req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )

    access_token = create_access_token(data={"sub": str(user.id)})

    groups = get_user_groups(db, user.id)
    user_response = UserResponse.model_validate(user)
    user_response.groups = [UserGroupInfo(**g) for g in groups]
    user_response.permissions = get_user_permissions(db, user.id)

    return Token(
        access_token=access_token,
        user=user_response,
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    groups = get_user_groups(db, current_user.id)
    resp = UserResponse.model_validate(current_user)
    resp.groups = [UserGroupInfo(**g) for g in groups]
    resp.permissions = get_user_permissions(db, current_user.id)
    return resp


@router.put("/me", response_model=UserResponse)
def update_me(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = user_service.update_own_profile(db, current_user.id, profile_data)
    groups = get_user_groups(db, user.id)
    resp = UserResponse.model_validate(user)
    resp.groups = [UserGroupInfo(**g) for g in groups]
    resp.permissions = get_user_permissions(db, user.id)
    return resp


@router.put("/me/password")
def change_my_password(
    password_data: PasswordChange,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = user_service.change_own_password(
        db,
        current_user.id,
        password_data.current_password,
        password_data.new_password,
    )
    operation_log_service.log_operation(
        db,
        operator_id=current_user.id,
        action_type="change_password",
        action_name="用户修改密码",
        target_type="user",
        target_id=current_user.id,
        target_name=current_user.username,
        request_data=password_data.model_dump(),
        response_data=result,
        request=request,
    )
    return result
