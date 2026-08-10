from collections.abc import Iterable
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.permission_constants import DEFAULT_TOOL_DEFS, FULL_ACCESS_GROUP_NAMES
from ..models.group import Group
from ..models.permissions import GroupPermission, Permission
from ..models.tool import Tool


ALLOWED_TOOL_ENTRIES = {
    definition["tool_key"]: {
        "route_path": definition["route_path"],
        "permission_key": definition["permission_key"],
    }
    for definition in DEFAULT_TOOL_DEFS
}

TOOL_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
ENTRY_TYPES = {"internal", "external"}
OPEN_MODES = {"same_tab", "new_tab"}


def list_tools(db: Session) -> list[Tool]:
    return db.query(Tool).order_by(Tool.sort_order, Tool.name).all()


def list_visible_tools(db: Session, permission_keys: Iterable[str]) -> list[Tool]:
    allowed = set(permission_keys)
    return [
        tool
        for tool in list_tools(db)
        if tool.is_enabled and tool.permission_key in allowed
    ]


def create_tool(db: Session, payload: dict) -> Tool:
    tool_key = str(payload.get("tool_key") or "").strip()
    if not TOOL_KEY_PATTERN.fullmatch(tool_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tool key must use lowercase letters, numbers, and underscores",
        )
    entry_type = str(payload.get("entry_type") or "internal")
    if entry_type not in ENTRY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported tool entry type",
        )
    if db.query(Tool).filter(Tool.tool_key == tool_key).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool already exists")

    if entry_type == "external":
        return _create_external_tool(db, tool_key, payload)

    entry = ALLOWED_TOOL_ENTRIES.get(tool_key)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tool key is not registered in the application",
        )

    tool = Tool(
        tool_key=tool_key,
        name=payload.get("name") or tool_key,
        description=payload.get("description"),
        category=payload.get("category") or "通用工具",
        icon_key=payload.get("icon_key") or "tool",
        route_path=entry["route_path"],
        entry_type="internal",
        external_url=None,
        open_mode="same_tab",
        permission_key=entry["permission_key"],
        is_enabled=bool(payload.get("is_enabled", True)),
        sort_order=int(payload.get("sort_order", 0)),
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def update_tool(db: Session, tool_key: str, payload: dict) -> Tool:
    tool = db.query(Tool).filter(Tool.tool_key == tool_key).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

    if tool.entry_type == "external":
        if "external_url" in payload:
            tool.external_url = _normalize_external_url(payload.get("external_url"))
        if payload.get("open_mode") is not None:
            tool.open_mode = _validate_open_mode(payload["open_mode"])
    elif payload.get("external_url") is not None or payload.get("open_mode") is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Internal tool entry settings are code-controlled",
        )

    for field in ("name", "description", "category", "icon_key", "is_enabled", "sort_order"):
        if field in payload and payload[field] is not None:
            setattr(tool, field, payload[field])

    if tool.entry_type == "external":
        permission = db.query(Permission).filter(Permission.permission_key == tool.permission_key).first()
        if permission:
            permission.permission_name = f"使用外部应用：{tool.name}"
            permission.description = f"允许打开外部应用 {tool.name}"
    db.commit()
    db.refresh(tool)
    return tool


def delete_tool(db: Session, tool_key: str) -> dict[str, str]:
    tool = db.query(Tool).filter(Tool.tool_key == tool_key).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    if tool.entry_type != "external":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Built-in tools cannot be deleted; disable them instead",
        )

    permission = db.query(Permission).filter(Permission.permission_key == tool.permission_key).first()
    db.delete(tool)
    if permission:
        db.query(GroupPermission).filter(GroupPermission.permission_id == permission.id).delete(
            synchronize_session=False
        )
        db.delete(permission)
    db.commit()
    return {"detail": "External tool deleted", "tool_key": tool_key}


def _create_external_tool(db: Session, tool_key: str, payload: dict) -> Tool:
    external_url = _normalize_external_url(payload.get("external_url"))
    open_mode = _validate_open_mode(payload.get("open_mode") or "new_tab")
    name = str(payload.get("name") or tool_key).strip()
    permission_key = f"tool.{tool_key}.use"
    permission = db.query(Permission).filter(Permission.permission_key == permission_key).first()
    if permission is None:
        permission = Permission(
            permission_key=permission_key,
            permission_name=f"使用外部应用：{name}",
            permission_type="page",
            description=f"允许打开外部应用 {name}",
        )
        db.add(permission)
        db.flush()

    tool = Tool(
        tool_key=tool_key,
        name=name,
        description=payload.get("description"),
        category=payload.get("category") or "外部应用",
        icon_key=payload.get("icon_key") or "external-link",
        route_path=f"/tools/external/{tool_key}",
        entry_type="external",
        external_url=external_url,
        open_mode=open_mode,
        permission_key=permission_key,
        is_enabled=bool(payload.get("is_enabled", True)),
        sort_order=int(payload.get("sort_order", 0)),
    )
    db.add(tool)
    _grant_management_permission(db, permission)
    db.commit()
    db.refresh(tool)
    return tool


def _grant_management_permission(db: Session, permission: Permission) -> None:
    groups = db.query(Group).filter(Group.group_name.in_(FULL_ACCESS_GROUP_NAMES)).all()
    existing_group_ids = {
        group_id
        for (group_id,) in db.query(GroupPermission.group_id).filter(
            GroupPermission.permission_id == permission.id
        ).all()
    }
    for group in groups:
        if group.id not in existing_group_ids:
            db.add(GroupPermission(group_id=group.id, permission_id=permission.id))


def _normalize_external_url(value) -> str:
    url = str(value or "").strip()
    if not url or len(url) > 2048 or "\\" in url or any(ord(char) < 32 for char in url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="External URL is invalid",
        )
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="External URL is invalid",
        ) from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="External URL must use HTTP or HTTPS",
        )
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="External URL cannot contain credentials",
        )
    return url


def _validate_open_mode(value) -> str:
    open_mode = str(value or "")
    if open_mode not in OPEN_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported tool open mode",
        )
    return open_mode
