"""Helpers for writing operation audit logs."""
import json
from datetime import datetime, time
from typing import Any

from fastapi import Request
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from ..models.operation_logs import OperationLog
from ..models.product_operation_snapshot import ProductOperationSnapshot
from ..models.user import User


SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "cookie",
)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if _is_sensitive_key(key) else _sanitize(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key or "").lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    return _sanitize(value)


def log_operation(
    db: Session,
    *,
    operator_id: str,
    action_type: str,
    action_name: str,
    target_type: str,
    target_id: str,
    target_name: str,
    request_data: Any = None,
    response_data: Any = None,
    status: str = "success",
    error_message: str | None = None,
    request: Request | None = None,
) -> OperationLog:
    log = OperationLog(
        operator_id=str(operator_id),
        operator_type="human",
        action_type=action_type,
        action_name=action_name,
        target_type=target_type,
        target_id=str(target_id),
        target_name=str(target_name),
        request_data=_json_value(request_data),
        response_data=_json_value(response_data),
        status=status,
        error_message=error_message,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_operation_logs(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 50,
    action_type: str | None = None,
    target_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    operator_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    skip = max(skip, 0)
    query = (
        db.query(OperationLog, User, ProductOperationSnapshot)
        .outerjoin(User, OperationLog.operator_id == User.id)
        .outerjoin(ProductOperationSnapshot, ProductOperationSnapshot.operation_log_id == cast(OperationLog.id, String))
    )

    if action_type:
        query = query.filter(OperationLog.action_type == action_type)
    if target_type:
        query = query.filter(OperationLog.target_type == target_type)
    if status:
        query = query.filter(OperationLog.status == status)
    if operator_id:
        query = query.filter(OperationLog.operator_id == str(operator_id))
    if date_from:
        query = query.filter(OperationLog.created_at >= _start_of_day_if_date(date_from))
    if date_to:
        query = query.filter(OperationLog.created_at <= _end_of_day_if_date(date_to))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            OperationLog.action_name.ilike(like),
            OperationLog.action_type.ilike(like),
            OperationLog.target_name.ilike(like),
            OperationLog.target_id.ilike(like),
            OperationLog.target_type.ilike(like),
            User.username.ilike(like),
            User.display_name.ilike(like),
        ))

    total = query.count()
    rows = (
        query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "items": [_serialize_operation_log(log, user, snapshot) for log, user, snapshot in rows],
        "total": total,
    }


def _serialize_operation_log(
    log: OperationLog,
    user: User | None,
    snapshot: ProductOperationSnapshot | None = None,
) -> dict[str, Any]:
    return {
        "id": log.id,
        "operator_id": log.operator_id,
        "operator_name": user.username if user else "-",
        "operator_display_name": user.display_name if user else None,
        "action_type": log.action_type,
        "action_name": log.action_name,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "target_name": log.target_name,
        "request_data": log.request_data,
        "response_data": log.response_data,
        "status": log.status,
        "error_message": log.error_message,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "created_at": log.created_at,
        "snapshot_id": snapshot.id if snapshot else None,
        "can_restore": bool(snapshot and not snapshot.restored_at),
        "restored_at": snapshot.restored_at if snapshot else None,
    }


def _start_of_day_if_date(value: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _end_of_day_if_date(value: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.max)
