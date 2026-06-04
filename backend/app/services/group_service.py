from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from ..models.group import Group
from ..models.user_group import UserGroup
from ..models.user import User

PRESET_GROUPS = {
    "管理层", "产品团队", "设计团队", "AI工程师", "AI内容岗",
    "电商运营", "海外营销", "客服团队", "经销商", "外部达人", "广告代理商",
}


def _group_to_dict(group: Group) -> dict:
    return {
        "id": group.id,
        "group_name": group.group_name,
        "description": group.description,
        "is_preset": group.group_name in PRESET_GROUPS,
        "created_at": str(group.created_at) if group.created_at else None,
        "updated_at": str(group.updated_at) if group.updated_at else None,
    }


def _validate_role(group_role: str):
    if group_role not in {"member", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid group role")


def _active_management_count(db: Session) -> int:
    return db.query(User).join(UserGroup, UserGroup.user_id == User.id).join(
        Group, UserGroup.group_id == Group.id
    ).filter(
        User.is_active == True,  # noqa: E712
        Group.group_name == "管理层",
    ).count()


def get_group_by_id(db: Session, group_id: str):
    return db.query(Group).filter(Group.id == group_id).first()


def get_group_by_name(db: Session, name: str):
    return db.query(Group).filter(Group.group_name == name).first()


def get_groups(db: Session):
    groups = db.query(Group).order_by(Group.group_name).all()
    return [_group_to_dict(g) for g in groups]


def create_group(db: Session, name: str, description: str = None):
    if get_group_by_name(db, name):
        raise HTTPException(status_code=400, detail="Group already exists")
    group = Group(group_name=name, description=description)
    db.add(group)
    db.commit()
    db.refresh(group)
    return _group_to_dict(group)


def update_group(db: Session, group_id: str, name: str = None, description: str = None):
    group = get_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if name:
        existing = db.query(Group).filter(Group.group_name == name, Group.id != group_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Group name already exists")
        group.group_name = name
    if description is not None:
        group.description = description
    db.commit()
    db.refresh(group)
    return _group_to_dict(group)


def delete_group(db: Session, group_id: str):
    group = get_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.group_name in PRESET_GROUPS:
        raise HTTPException(status_code=400, detail="Preset groups cannot be deleted")
    db.query(UserGroup).filter(UserGroup.group_id == group_id).delete()
    db.delete(group)
    db.commit()
    return {"detail": "Group deleted"}


def add_user_to_group(db: Session, group_id: str, user_id: str, group_role: str = "member"):
    _validate_role(group_role)
    group = get_group_by_id(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(UserGroup).filter(
        UserGroup.user_id == user_id, UserGroup.group_id == group_id
    ).first()
    if existing:
        existing.group_role = group_role
        db.commit()
        db.refresh(existing)
        return existing

    ug = UserGroup(user_id=user_id, group_id=group_id, group_role=group_role)
    db.add(ug)
    db.commit()
    db.refresh(ug)
    return ug


def remove_user_from_group(db: Session, group_id: str, user_id: str):
    ug = db.query(UserGroup).join(Group, UserGroup.group_id == Group.id).filter(
        UserGroup.user_id == user_id, UserGroup.group_id == group_id
    ).first()
    if not ug:
        raise HTTPException(status_code=404, detail="User not in group")
    if ug.group and ug.group.group_name == "管理层":
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.is_active and _active_management_count(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last active management user",
            )
    db.delete(ug)
    db.commit()
    return {"detail": "User removed from group"}


def update_user_group_role(db: Session, group_id: str, user_id: str, group_role: str):
    _validate_role(group_role)
    ug = db.query(UserGroup).filter(
        UserGroup.user_id == user_id, UserGroup.group_id == group_id
    ).first()
    if not ug:
        raise HTTPException(status_code=404, detail="User not in group")
    ug.group_role = group_role
    db.commit()
    db.refresh(ug)
    return ug


def get_group_members(db: Session, group_id: str):
    rows = (
        db.query(UserGroup, User)
        .join(User, UserGroup.user_id == User.id)
        .filter(UserGroup.group_id == group_id)
        .all()
    )
    return [
        {
            "user_id": u.id,
            "username": u.username,
            "email": u.email,
            "group_role": ug.group_role,
        }
        for ug, u in rows
    ]
