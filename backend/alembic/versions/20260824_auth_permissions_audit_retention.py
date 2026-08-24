"""Harden authentication, permissions, and audit retention.

Revision ID: 20260824_auth_security
Revises: 20260823_asset_file_metadata
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_auth_security"
down_revision = "20260823_asset_file_metadata"
branch_labels = None
depends_on = None


LEGACY_GROUP_NAME_MAP = {
    "管理层": "总经办",
    "产品团队": "产品部",
    "设计团队": "视觉一部",
    "电商运营": "跨境电商部",
    "海外营销": "国际贸易部",
    "AI内容岗": "品牌部",
    "客服团队": "商务部",
    "AI工程师": "IT部",
}


def _replace_user_fk(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key.get("constrained_columns") != [column_name]:
            continue
        name = foreign_key.get("name")
        options = foreign_key.get("options") or {}
        if str(options.get("ondelete", "")).upper() == "SET NULL":
            return
        if name:
            op.drop_constraint(name, table_name, type_="foreignkey")
    op.create_foreign_key(
        f"fk_{table_name}_{column_name}_users",
        table_name,
        "users",
        [column_name],
        ["id"],
        ondelete="SET NULL",
    )


def _merge_legacy_departments() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    groups = sa.Table("groups", metadata, autoload_with=bind)
    user_groups = sa.Table("user_groups", metadata, autoload_with=bind)
    group_permissions = sa.Table("group_permissions", metadata, autoload_with=bind)

    for legacy_name, target_name in LEGACY_GROUP_NAME_MAP.items():
        legacy = bind.execute(
            sa.select(groups.c.id).where(groups.c.group_name == legacy_name)
        ).first()
        if legacy is None:
            continue
        target = bind.execute(
            sa.select(groups.c.id).where(groups.c.group_name == target_name)
        ).first()
        legacy_id = legacy[0]
        if target is None:
            bind.execute(
                groups.update().where(groups.c.id == legacy_id).values(group_name=target_name)
            )
            continue

        target_id = target[0]
        memberships = bind.execute(
            sa.select(user_groups.c.user_id, user_groups.c.group_role).where(
                user_groups.c.group_id == legacy_id
            )
        ).all()
        for user_id, legacy_role in memberships:
            current = bind.execute(
                sa.select(user_groups.c.group_role).where(
                    user_groups.c.group_id == target_id,
                    user_groups.c.user_id == user_id,
                )
            ).first()
            if current is None:
                bind.execute(
                    user_groups.update().where(
                        user_groups.c.group_id == legacy_id,
                        user_groups.c.user_id == user_id,
                    ).values(group_id=target_id)
                )
            else:
                if legacy_role == "admin" and current[0] != "admin":
                    bind.execute(
                        user_groups.update().where(
                            user_groups.c.group_id == target_id,
                            user_groups.c.user_id == user_id,
                        ).values(group_role="admin")
                    )
                bind.execute(
                    user_groups.delete().where(
                        user_groups.c.group_id == legacy_id,
                        user_groups.c.user_id == user_id,
                    )
                )

        legacy_permissions = bind.execute(
            sa.select(group_permissions.c.permission_id).where(
                group_permissions.c.group_id == legacy_id
            )
        ).all()
        for (permission_id,) in legacy_permissions:
            exists = bind.execute(
                sa.select(group_permissions.c.group_id).where(
                    group_permissions.c.group_id == target_id,
                    group_permissions.c.permission_id == permission_id,
                )
            ).first()
            if exists is None:
                bind.execute(
                    group_permissions.update().where(
                        group_permissions.c.group_id == legacy_id,
                        group_permissions.c.permission_id == permission_id,
                    ).values(group_id=target_id)
                )
            else:
                bind.execute(
                    group_permissions.delete().where(
                        group_permissions.c.group_id == legacy_id,
                        group_permissions.c.permission_id == permission_id,
                    )
                )
        bind.execute(groups.delete().where(groups.c.id == legacy_id))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "auth_version" not in user_columns:
        op.add_column(
            "users",
            sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
        )

    log_columns = {column["name"] for column in inspector.get_columns("operation_logs")}
    if "operator_name_snapshot" not in log_columns:
        op.add_column(
            "operation_logs",
            sa.Column("operator_name_snapshot", sa.String(length=100), nullable=True),
        )
    bind.execute(sa.text(
        "UPDATE operation_logs SET operator_name_snapshot = "
        "COALESCE((SELECT COALESCE(users.display_name, users.username) FROM users "
        "WHERE users.id = operation_logs.operator_id), CAST(operator_id AS VARCHAR)) "
        "WHERE operator_name_snapshot IS NULL"
    ))
    op.alter_column("operation_logs", "operator_id", existing_type=sa.String(length=36), nullable=True)
    _replace_user_fk("operation_logs", "operator_id")

    op.alter_column("generations", "user_id", existing_type=sa.String(length=36), nullable=True)
    _replace_user_fk("generations", "user_id")

    _merge_legacy_departments()


def downgrade() -> None:
    """Remove columns understood only by the new application.

    Department normalization and SET NULL retention are intentionally kept:
    reversing either could discard memberships or historical records.
    """
    inspector = sa.inspect(op.get_bind())
    log_columns = {column["name"] for column in inspector.get_columns("operation_logs")}
    if "operator_name_snapshot" in log_columns:
        op.drop_column("operation_logs", "operator_name_snapshot")
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "auth_version" in user_columns:
        op.drop_column("users", "auth_version")
