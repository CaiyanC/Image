from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from time import time
from typing import Any

from redis import Redis, RedisError


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int, maxsize: int = 2048):
        self.ttl_seconds = ttl_seconds
        self.maxsize = maxsize
        self._data: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = time()
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            if entry.expires_at <= now:
                self._data.pop(key, None)
                return None
            return copy.deepcopy(entry.value)

    def set(self, key: str, value: Any) -> None:
        expires_at = time() + self.ttl_seconds
        with self._lock:
            if len(self._data) >= self.maxsize:
                self._purge_expired_locked()
            if len(self._data) >= self.maxsize:
                self._data.pop(next(iter(self._data)), None)
            self._data[key] = _CacheEntry(copy.deepcopy(value), expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _purge_expired_locked(self) -> None:
        now = time()
        expired = [key for key, entry in self._data.items() if entry.expires_at <= now]
        for key in expired:
            self._data.pop(key, None)


class SharedJsonTTLCache:
    """Small Redis-backed cache with an in-process fail-open fallback.

    Only JSON-compatible public response snapshots belong here. Redis makes
    parity isolation work across production workers; the local cache preserves
    availability when Redis is temporarily unavailable.
    """

    def __init__(self, ttl_seconds: int, maxsize: int = 2048, namespace: str = "shared"):
        self.ttl_seconds = ttl_seconds
        self.namespace = namespace
        self._local = TTLCache(ttl_seconds=ttl_seconds, maxsize=maxsize)
        self._redis_client = None
        self._redis_lock = threading.Lock()

    def _redis(self):
        with self._redis_lock:
            if self._redis_client is None:
                self._redis_client = Redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                )
            return self._redis_client

    def _key(self, key: str) -> str:
        app_env = str(os.getenv("APP_ENV") or "unknown").strip().lower()
        return f"customer_cache:{app_env}:{self.namespace}:{key}"

    def get(self, key: str) -> Any | None:
        shared_key = self._key(key)
        try:
            payload = self._redis().get(shared_key)
            if payload is not None:
                value = json.loads(payload)
                self._local.set(shared_key, value)
                return copy.deepcopy(value)
        except (RedisError, TypeError, ValueError):
            pass
        return self._local.get(shared_key)

    def set(self, key: str, value: Any) -> None:
        sealed = json.loads(json.dumps(value, ensure_ascii=False, default=str))
        shared_key = self._key(key)
        self._local.set(shared_key, sealed)
        try:
            self._redis().setex(
                shared_key,
                int(self.ttl_seconds),
                json.dumps(sealed, ensure_ascii=False),
            )
        except RedisError:
            pass

    def delete(self, key: str) -> None:
        shared_key = self._key(key)
        self._local.delete(shared_key)
        try:
            self._redis().delete(shared_key)
        except RedisError:
            pass

    def clear(self) -> None:
        self._local.clear()
        try:
            client = self._redis()
            keys = list(client.scan_iter(f"customer_cache:*:{self.namespace}:*"))
            if keys:
                client.delete(*keys)
        except RedisError:
            pass

    def set_redis_client(self, client) -> None:
        with self._redis_lock:
            self._redis_client = client


product_detail_cache = TTLCache(ttl_seconds=600, maxsize=4096)
embedding_cache = TTLCache(ttl_seconds=600, maxsize=4096)
recommendation_candidate_cache = TTLCache(ttl_seconds=300, maxsize=2048)
recommendation_response_cache = TTLCache(ttl_seconds=20, maxsize=512)
parity_result_snapshot_cache = SharedJsonTTLCache(
    ttl_seconds=300,
    maxsize=1024,
    namespace="parity_result_snapshot",
)
faq_cache = TTLCache(ttl_seconds=600, maxsize=1024)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def make_key(*parts: Any) -> str:
    payload = json.dumps([parts], ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
