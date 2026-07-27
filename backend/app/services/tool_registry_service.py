from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..core.permission_constants import DEFAULT_TOOL_DEFS
from ..models.tool import Tool


ALLOWED_TOOL_ENTRIES = {
    definition["tool_key"]: {
        "route_path": definition["route_path"],
        "permission_key": definition["permission_key"],
    }
    for definition in DEFAULT_TOOL_DEFS
}


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
    tool_key = str(payload.get("tool_key") or "")
    entry = ALLOWED_TOOL_ENTRIES.get(tool_key)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tool key is not registered in the application",
        )
    if db.query(Tool).filter(Tool.tool_key == tool_key).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tool already exists")

    tool = Tool(
        tool_key=tool_key,
        name=payload.get("name") or tool_key,
        description=payload.get("description"),
        category=payload.get("category") or "通用工具",
        icon_key=payload.get("icon_key") or "tool",
        route_path=entry["route_path"],
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
    for field in ("name", "description", "category", "icon_key", "is_enabled", "sort_order"):
        if field in payload and payload[field] is not None:
            setattr(tool, field, payload[field])
    db.commit()
    db.refresh(tool)
    return tool
