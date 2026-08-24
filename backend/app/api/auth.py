from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.config import settings
from ..core.rate_limit import enforce_rate_limit, get_request_identifier
from ..core.security import verify_password, create_access_token, get_current_user, require_permission
from ..core.security import get_user_groups, get_user_permissions
from ..models.user import User
from ..schemas.user import (
    PasswordChange,
    UserCreate,
    UserProfileUpdate,
    UserResponse,
    Token,
    BearerToken,
    LoginRequest,
    UserGroupInfo,
)
from ..services import operation_log_service, user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
def register(user_data: UserCreate, request: Request = None, db: Session = Depends(get_db)):
    enforce_rate_limit(
        user_id=f"{get_request_identifier(request)}:{user_data.username.strip().lower()}",
        scope="auth.register",
        limit=8,
        window_seconds=60,
    )
    if not settings.ENABLE_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled",
        )
    return user_service.create_user(db, user_data)


def _authenticate(req: LoginRequest, request: Request, db: Session) -> User:
    enforce_rate_limit(
        user_id=f"{get_request_identifier(request)}:{req.username.strip().lower()}",
        scope="auth.login",
        limit=8,
        window_seconds=60,
    )
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
    return user


def _user_response(db: Session, user: User) -> UserResponse:
    groups = get_user_groups(db, user.id)
    user_response = UserResponse.model_validate(user)
    user_response.groups = [UserGroupInfo(**group) for group in groups]
    user_response.permissions = get_user_permissions(db, user.id)
    return user_response


def _issue_access_token(user: User) -> str:
    return create_access_token(data={"sub": str(user.id), "ver": user.auth_version})


@router.post("/login", response_model=Token)
def login(
    req: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _authenticate(req, request, db)
    access_token = _issue_access_token(user)
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/api",
    )
    return Token(user=_user_response(db, user))


@router.post("/token", response_model=BearerToken)
def create_bearer_token(
    req: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Issue a bearer token for trusted scripts and non-browser API clients."""
    user = _authenticate(req, request, db)
    return BearerToken(access_token=_issue_access_token(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/api",
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(require_permission("profile.view")),
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
    current_user: User = Depends(require_permission("profile.view")),
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
