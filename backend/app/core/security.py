from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .permission_constants import MANAGEMENT_GROUP_NAME
from ..models.user import User
from ..models.group import Group
from ..models.user_group import UserGroup
from ..models.permissions import GroupPermission, Permission

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_user_groups(db: Session, user_id: str):
    rows = (
        db.query(UserGroup, Group)
        .join(Group, UserGroup.group_id == Group.id)
        .filter(UserGroup.user_id == user_id)
        .all()
    )
    return [
        {
            "group_id": ug.group_id,
            "group_name": g.group_name,
            "group_role": ug.group_role,
        }
        for ug, g in rows
    ]


def get_user_permissions(db: Session, user_id: str) -> list[str]:
    if _is_in_management(db, user_id):
        return [
            key for (key,) in db.query(Permission.permission_key).order_by(Permission.permission_key).all()
        ]
    rows = db.query(Permission.permission_key).join(
        GroupPermission, GroupPermission.permission_id == Permission.id
    ).join(
        UserGroup, UserGroup.group_id == GroupPermission.group_id
    ).filter(
        UserGroup.user_id == user_id,
    ).distinct().order_by(Permission.permission_key).all()
    return [key for (key,) in rows]


def _is_in_group(db: Session, user_id: str, group_name: str) -> bool:
    return db.query(UserGroup).join(Group, UserGroup.group_id == Group.id).filter(
        UserGroup.user_id == user_id, Group.group_name == group_name
    ).first() is not None


def _is_in_management(db: Session, user_id: str) -> bool:
    return _is_in_group(db, user_id, MANAGEMENT_GROUP_NAME)


def has_permission(db: Session, user_id: str, permission_key: str) -> bool:
    if _is_in_management(db, user_id):
        return True
    return db.query(GroupPermission).join(
        Permission, GroupPermission.permission_id == Permission.id
    ).join(
        UserGroup, UserGroup.group_id == GroupPermission.group_id
    ).filter(
        UserGroup.user_id == user_id,
        Permission.permission_key == permission_key,
    ).first() is not None


def require_permission(permission_key: str):
    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if has_permission(db, current_user.id, permission_key):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {permission_key}",
        )

    return checker


def require_any_permission(*permission_keys: str):
    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        for permission_key in permission_keys:
            if has_permission(db, current_user.id, permission_key):
                return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {' or '.join(permission_keys)}",
        )

    return checker


def get_current_super_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not _is_in_management(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required",
        )
    return current_user


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    return get_current_super_admin(current_user, db)


def require_product_permission(action: str):
    def checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        permission_key = {
            "read": "product.read",
            "create": "product.create",
            "update": "product.edit",
            "delete": "product.delete",
            "review": "product.review",
        }.get(action, f"product.{action}")

        if has_permission(db, current_user.id, permission_key):
            return current_user

        user_groups = get_user_groups(db, current_user.id)
        if not user_groups:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not in any team",
            )

        if action == "delete":
            for ug in user_groups:
                if ug["group_name"] == "产品团队" and ug["group_role"] == "admin":
                    return current_user
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Delete requires Product Team admin role",
            )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {permission_key}",
        )

    return checker
