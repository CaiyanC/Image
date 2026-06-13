"""Helpers for writing operation audit logs."""
import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..models.operation_logs import OperationLog


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
