import ipaddress
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
_LOCAL_BUCKETS: dict[str, tuple[int, float]] = {}
_MAX_LOCAL_BUCKETS = 10_000


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
        _enforce_local_rate_limit(key=_build_key(scope, user_id), limit=limit, window_seconds=window_seconds, detail=detail)
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
        _enforce_local_rate_limit(key=key, limit=limit, window_seconds=window_seconds, detail=detail)
        return

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=detail,
        )


def get_request_identifier(request: Request | None) -> str:
    if request is None:
        return "unknown"
    peer_host = request.client.host if request.client and request.client.host else ""
    if not peer_host:
        return "unknown"

    trusted_networks = _trusted_proxy_networks()
    peer_address = _parse_ip_address(peer_host)
    if peer_address is None or not _is_trusted_proxy(peer_address, trusted_networks):
        return peer_host

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer_host

    forwarded_addresses = [
        address
        for item in forwarded_for.split(",")
        if (address := _parse_ip_address(item.strip())) is not None
    ]
    for address in reversed(forwarded_addresses):
        if not _is_trusted_proxy(address, trusted_networks):
            return str(address)
    return peer_host


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = os.getenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
    networks = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            _LOGGER.warning("Ignoring invalid trusted proxy CIDR: %s", value)
    return tuple(networks)


def _parse_ip_address(value: str):
    try:
        return ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None


def _is_trusted_proxy(address, networks) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def reset_rate_limits() -> None:
    with _LOCK:
        _LOCAL_BUCKETS.clear()
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
    _LOGGER.warning("%s; using bounded in-process rate limit fallback", message)


def _enforce_local_rate_limit(*, key: str, limit: int, window_seconds: int, detail: str) -> None:
    now = time.monotonic()
    with _LOCK:
        if len(_LOCAL_BUCKETS) >= _MAX_LOCAL_BUCKETS:
            expired = [bucket_key for bucket_key, (_, expires_at) in _LOCAL_BUCKETS.items() if expires_at <= now]
            for bucket_key in expired:
                _LOCAL_BUCKETS.pop(bucket_key, None)
            if len(_LOCAL_BUCKETS) >= _MAX_LOCAL_BUCKETS:
                oldest_key = min(_LOCAL_BUCKETS, key=lambda bucket_key: _LOCAL_BUCKETS[bucket_key][1])
                _LOCAL_BUCKETS.pop(oldest_key, None)

        count, expires_at = _LOCAL_BUCKETS.get(key, (0, now + window_seconds))
        if expires_at <= now:
            count, expires_at = 0, now + window_seconds
        count += 1
        _LOCAL_BUCKETS[key] = (count, expires_at)

    if count > limit:
        raise HTTPException(status_code=429, detail=detail)


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
