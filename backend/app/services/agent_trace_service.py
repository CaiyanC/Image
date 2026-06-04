import json
import logging
from typing import Any


logger = logging.getLogger("uvicorn")
MAX_TRACE_CHARS = 8000


def trace(label: str, payload: Any) -> None:
    text = _safe_json(payload)
    if len(text) > MAX_TRACE_CHARS:
        text = text[:MAX_TRACE_CHARS] + "...<truncated>"
    line = f"[CUSTOMER_AGENT_{label}] {text}"
    print(line, flush=True)
    logger.info(line)


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(_mask(payload), ensure_ascii=False, default=str, indent=2)
    except TypeError:
        return str(payload)


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if "key" in lowered or "token" in lowered or "password" in lowered or "authorization" in lowered:
                result[key] = "***"
            else:
                result[key] = _mask(item)
        return result
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value
