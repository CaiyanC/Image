"""Seed test users and teams for permission testing.

Run from the repository root:
    python scripts/seed_permission_test_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.group import Group  # noqa: E402
from app.models.permissions import GroupPermission, Permission  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_group import UserGroup  # noqa: E402


PASSWORD = "Test123456"

TEST_CASES = [
    {
        "group_name": "权限测试-只生图",
        "description": "只能进入创作页和历史/个人资料，不能进入客服或产品。",
        "username": "perm_gen_only",
        "display_name": "权限测试-只生图",
        "permissions": ["ai.generate", "history.view", "profile.view"],
    },
    {
        "group_name": "权限测试-只客服",
        "description": "只能进入智能客服和历史/个人资料，不能进入生图或产品。",
        "username": "perm_customer_only",
        "display_name": "权限测试-只客服",
        "permissions": ["ai.customer_service", "history.view", "profile.view"],
    },
    {
        "group_name": "权限测试-产品只读",
        "description": "可以查看产品和品类，不能新增、编辑、删除产品。",
        "username": "perm_product_readonly",
        "display_name": "权限测试-产品只读",
        "permissions": ["product.read", "category.read", "history.view", "profile.view"],
    },
    {
        "group_name": "权限测试-产品编辑",
        "description": "可以查看、新增、编辑产品和上传素材，不能删除产品。",
        "username": "perm_product_editor",
        "display_name": "权限测试-产品编辑",
        "permissions": [
            "product.read",
            "product.create",
            "product.edit",
            "category.read",
            "media.upload",
            "history.view",
            "profile.view",
        ],
    },
    {
        "group_name": "权限测试-无页面权限",
        "description": "没有任何业务页面权限，用于测试无权限落地页。",
        "username": "perm_no_access",
        "display_name": "权限测试-无页面权限",
        "permissions": [],
    },
]


def get_or_create_group(db, group_name: str, description: str) -> Group:
    group = db.query(Group).filter(Group.group_name == group_name).first()
    if group:
        group.description = description
        return group
    group = Group(group_name=group_name, description=description)
    db.add(group)
    db.flush()
    return group


def get_or_create_user(db, username: str, display_name: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    password_hash = get_password_hash(PASSWORD)
    email = f"{username}@permission-test.local"
    if user:
        user.password_hash = password_hash
        user.display_name = display_name
        user.email = email
        user.is_active = True
        return user
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        user_type="human",
        display_name=display_name,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def set_group_permissions(db, group: Group, permission_keys: list[str]) -> None:
    db.query(GroupPermission).filter(GroupPermission.group_id == group.id).delete()
    if not permission_keys:
        return

    permissions = db.query(Permission).filter(Permission.permission_key.in_(permission_keys)).all()
    found = {permission.permission_key for permission in permissions}
    missing = sorted(set(permission_keys) - found)
    if missing:
        raise RuntimeError(f"Missing permissions: {', '.join(missing)}")

    for permission in permissions:
        db.add(GroupPermission(group_id=group.id, permission_id=permission.id))


def set_user_single_group(db, user: User, group: Group) -> None:
    db.query(UserGroup).filter(UserGroup.user_id == user.id).delete()
    db.add(UserGroup(user_id=user.id, group_id=group.id, group_role="member"))


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for case in TEST_CASES:
            group = get_or_create_group(db, case["group_name"], case["description"])
            user = get_or_create_user(db, case["username"], case["display_name"])
            set_group_permissions(db, group, case["permissions"])
            set_user_single_group(db, user, group)
            print(
                f"{case['username']} / {PASSWORD} -> {case['group_name']} "
                f"({', '.join(case['permissions']) or 'no permissions'})"
            )
        db.commit()
        print("Permission test data seeded successfully.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
