import logging
import os
import threading
import time
from logging.handlers import TimedRotatingFileHandler

from fastapi import HTTPException, Request
from redis import Redis, RedisError


_LOGGER = logging.getLogger("app.rate_limit")
_LOCK = threading.RLock()
_REDIS_CLIENT: Redis | None = None
_LAST_REDIS_WARNING_AT = 0.0
_WARNING_INTERVAL_SECONDS = 30
_KEY_PREFIX = "rate_limit"
_FILE_LOGGING_CONFIGURED = False


def enforce_rate_limit(
    *,
    user_id: str,
    scope: str,
    limit: int,
    window_seconds: int,
    detail: str = "请求过于频繁，请稍后再试",
) -> None:
    if limit <= 0 or window_seconds <= 0:
        return
    client = _get_redis_client()
    if client is None:
        _warn_redis_unavailable("Redis rate limit client is not configured")
        return

    key = _build_key(scope, user_id)
    try:
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, int(window_seconds))
        else:
            ttl = int(client.ttl(key))
            if ttl == -1:
                client.expire(key, int(window_seconds))
    except RedisError as exc:
        _warn_redis_unavailable(f"Redis rate limit check failed: {exc}")
        return

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=detail,
        )


def get_request_identifier(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def reset_rate_limits() -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        keys = list(client.scan_iter(f"{_KEY_PREFIX}:*"))
        if keys:
            client.delete(*keys)
    except RedisError as exc:
        _warn_redis_unavailable(f"Redis rate limit reset failed: {exc}")


def set_rate_limit_redis_client(client) -> None:
    global _REDIS_CLIENT
    with _LOCK:
        _REDIS_CLIENT = client


def _get_redis_client():
    global _REDIS_CLIENT
    with _LOCK:
        if _REDIS_CLIENT is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            _REDIS_CLIENT = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
        return _REDIS_CLIENT


def _build_key(scope: str, user_id: str) -> str:
    return f"{_KEY_PREFIX}:{scope}:{user_id}"


def _warn_redis_unavailable(message: str) -> None:
    global _LAST_REDIS_WARNING_AT
    _configure_file_logging()
    now = time.monotonic()
    if now - _LAST_REDIS_WARNING_AT < _WARNING_INTERVAL_SECONDS:
        return
    _LAST_REDIS_WARNING_AT = now
    _LOGGER.warning("%s; fail open and allow request", message)


def _configure_file_logging() -> None:
    global _FILE_LOGGING_CONFIGURED
    if _FILE_LOGGING_CONFIGURED:
        return
    with _LOCK:
        if _FILE_LOGGING_CONFIGURED:
            return
        logs_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "..", "logs"))
        os.makedirs(logs_dir, exist_ok=True)
        target = os.path.join(logs_dir, "rate_limit.log")
        if not any(isinstance(handler, TimedRotatingFileHandler) and getattr(handler, "baseFilename", "") == target for handler in _LOGGER.handlers):
            handler = TimedRotatingFileHandler(
                target,
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
            )
            handler.setLevel(logging.WARNING)
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
            _LOGGER.addHandler(handler)
        _LOGGER.setLevel(logging.WARNING)
        _FILE_LOGGING_CONFIGURED = True
