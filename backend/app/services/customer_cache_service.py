from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass
from time import time
from typing import Any


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


product_detail_cache = TTLCache(ttl_seconds=600, maxsize=4096)
embedding_cache = TTLCache(ttl_seconds=600, maxsize=4096)
recommendation_candidate_cache = TTLCache(ttl_seconds=300, maxsize=2048)
faq_cache = TTLCache(ttl_seconds=600, maxsize=1024)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def make_key(*parts: Any) -> str:
    payload = json.dumps([parts], ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
