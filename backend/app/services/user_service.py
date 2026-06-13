from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from ..models.user import User
from ..models.user_group import UserGroup
from ..models.group import Group
from ..models.generation import Generation
from ..models.operation_logs import OperationLog
from ..schemas.user import UserCreate, UserUpdate, UserProfileUpdate
from ..core.security import get_password_hash, verify_password


def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: str):
    return db.query(User).filter(User.id == user_id).first()


def get_users(db: Session, skip: int = 0, limit: int = 100):
    skip = max(int(skip or 0), 0)
    limit = min(max(int(limit or 100), 1), 200)
    return db.query(User).offset(skip).limit(limit).all()


def _is_management_user(db: Session, user_id: str) -> bool:
    return db.query(UserGroup).join(Group, UserGroup.group_id == Group.id).filter(
        UserGroup.user_id == user_id,
        Group.group_name == "管理层",
    ).first() is not None


def _active_management_count(db: Session) -> int:
    return db.query(User).join(UserGroup, UserGroup.user_id == User.id).join(
        Group, UserGroup.group_id == Group.id
    ).filter(
        User.is_active == True,  # noqa: E712
        Group.group_name == "管理层",
    ).count()


def create_user(db: Session, user_data: UserCreate):
    if get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    if user_data.email and get_user_by_email(db, user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        user_type="human",
        display_name=user_data.display_name or user_data.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_user_with_group(
    db: Session,
    user_data: UserCreate,
    group_id: str = None,
    group_role: str = "member",
):
    if group_role not in {"member", "admin"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid group role")
    if get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
    if user_data.email and get_user_by_email(db, user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    group = None
    if group_id:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        user_type="human",
        display_name=user_data.display_name or user_data.username,
    )
    db.add(user)
    db.flush()

    if group:
        db.add(UserGroup(user_id=user.id, group_id=group.id, group_role=group_role))

    db.commit()
    db.refresh(user)
    return user


def update_user(db: Session, user_id: str, user_data: UserUpdate):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_dict = user_data.model_dump(exclude_unset=True)
    if update_dict.get("is_active") is False and user.is_active and _is_management_user(db, user_id):
        if _active_management_count(db) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot disable the last active management user",
            )
    if "password" in update_dict:
        update_dict["password_hash"] = get_password_hash(update_dict.pop("password"))

    for key, value in update_dict.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user


def update_own_profile(db: Session, user_id: str, profile_data: UserProfileUpdate):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_dict = profile_data.model_dump(exclude_unset=True)
    username = update_dict.get("username")
    if username is not None:
        username = username.strip()
        if not username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username cannot be empty")
        existing = get_user_by_username(db, username)
        if existing and str(existing.id) != str(user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")
        user.username = username

    if "email" in update_dict:
        email = update_dict.get("email")
        existing = get_user_by_email(db, email) if email else None
        if existing and str(existing.id) != str(user_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        user.email = email

    if "display_name" in update_dict:
        display_name = update_dict.get("display_name")
        user.display_name = display_name.strip() if display_name else None

    db.commit()
    db.refresh(user)
    return user


def change_own_password(db: Session, user_id: str, current_password: str, new_password: str):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 6 characters")

    user.password_hash = get_password_hash(new_password)
    db.commit()
    return {"detail": "Password updated"}


def reset_user_password(db: Session, user_id: str, new_password: str):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 6 characters")

    user.password_hash = get_password_hash(new_password)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: str, current_user_id: str = None):
    user = get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_user_id and str(user_id) == str(current_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    if user.is_active and _is_management_user(db, user_id) and _active_management_count(db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last active management user",
        )

    for membership in db.query(UserGroup).filter(UserGroup.user_id == user_id).all():
        db.delete(membership)
    db.query(Generation).filter(Generation.user_id == user_id).delete(synchronize_session=False)
    db.query(OperationLog).filter(OperationLog.operator_id == user_id).delete(synchronize_session=False)
    db.flush()
    db.delete(user)
    db.commit()
