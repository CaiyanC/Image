import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


_LOCK = threading.RLock()
_REQUESTS: dict[str, deque[float]] = defaultdict(deque)


def enforce_rate_limit(
    *,
    user_id: str,
    scope: str,
    limit: int,
    window_seconds: int,
) -> None:
    if limit <= 0 or window_seconds <= 0:
        return
    now = time.monotonic()
    key = f"{scope}:{user_id}"
    with _LOCK:
        bucket = _REQUESTS[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {scope}. Please retry later.",
            )
        bucket.append(now)


def reset_rate_limits() -> None:
    with _LOCK:
        _REQUESTS.clear()
