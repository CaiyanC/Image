import json
import logging
import uuid
from contextvars import ContextVar
from time import perf_counter
from typing import Any


logger = logging.getLogger("uvicorn")

TRACE_ID_VAR: ContextVar[str | None] = ContextVar("customer_perf_trace_id", default=None)
STATE_VAR: ContextVar[dict[str, Any] | None] = ContextVar("customer_perf_state", default=None)


def start_trace(trace_id: str | None = None) -> str:
    trace_id = trace_id or uuid.uuid4().hex
    STATE_VAR.set(
        {
            "trace_id": trace_id,
            "started_at": perf_counter(),
            "stages": [],
            "llm_calls": [],
            "first_answer_delta_at": None,
            "done_at": None,
        }
    )
    TRACE_ID_VAR.set(trace_id)
    return trace_id


def get_trace_id() -> str | None:
    return TRACE_ID_VAR.get()


def get_state() -> dict[str, Any] | None:
    return STATE_VAR.get()


def perf_ms(start_time: float) -> float:
    return (perf_counter() - start_time) * 1000.0


def log_stage(stage: str, start_time: float, **extra: Any) -> float:
    elapsed_ms = perf_ms(start_time)
    _log(
        {
            "trace_id": get_trace_id(),
            "stage": stage,
            "elapsed_ms": round(elapsed_ms, 2),
            "extra": extra or {},
        }
    )
    state = get_state()
    if state is not None:
        state["stages"].append(
            {
                "stage": stage,
                "elapsed_ms": round(elapsed_ms, 2),
                "extra": extra or {},
            }
        )
    return elapsed_ms


def log_event(stage: str, **extra: Any) -> None:
    _log(
        {
            "trace_id": get_trace_id(),
            "stage": stage,
            "elapsed_ms": None,
            "extra": extra or {},
        }
    )


def record_llm_call(
    *,
    purpose: str,
    model: str | None,
    elapsed_ms: float,
    prompt_chars: int,
    completion_chars: int | None,
    prompt_tokens_est: int | None = None,
    completion_tokens_est: int | None = None,
    retries: int = 0,
    timeout: bool = False,
    fallback: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    state = get_state()
    call_index = len(state["llm_calls"]) + 1 if state is not None else 1
    payload = {
        "trace_id": get_trace_id(),
        "stage": "llm_call",
        "elapsed_ms": round(elapsed_ms, 2),
        "extra": {
            "llm_call_index": call_index,
            "purpose": purpose,
            "model": model,
            "prompt_chars": prompt_chars,
            "prompt_tokens_est": prompt_tokens_est,
            "completion_chars": completion_chars,
            "completion_tokens_est": completion_tokens_est,
            "retries": retries,
            "timeout": timeout,
            "fallback": fallback,
            "error": error,
        },
    }
    _log(payload)
    record = payload["extra"].copy()
    if state is not None:
        state["llm_calls"].append(record)
    return record


def mark_first_answer_delta() -> float | None:
    state = get_state()
    if not state or state.get("first_answer_delta_at") is not None:
        return None
    elapsed_ms = perf_ms(state["started_at"])
    state["first_answer_delta_at"] = elapsed_ms
    _log(
        {
            "trace_id": get_trace_id(),
            "stage": "sse_first_answer_delta",
            "elapsed_ms": round(elapsed_ms, 2),
            "extra": {},
        }
    )
    return elapsed_ms


def mark_done() -> float | None:
    state = get_state()
    if not state:
        return None
    elapsed_ms = perf_ms(state["started_at"])
    state["done_at"] = elapsed_ms
    _log(
        {
            "trace_id": get_trace_id(),
            "stage": "sse_done",
            "elapsed_ms": round(elapsed_ms, 2),
            "extra": {},
        }
    )
    return elapsed_ms


def summarize_request(**extra: Any) -> dict[str, Any] | None:
    state = get_state()
    if not state:
        return None
    total_ms = perf_ms(state["started_at"])
    summary = {
        "trace_id": get_trace_id(),
        "stage": "summary",
        "elapsed_ms": round(total_ms, 2),
        "extra": {
            "llm_call_count": len(state["llm_calls"]),
            "llm_calls": state["llm_calls"],
            "stages": state["stages"],
            "first_answer_delta_ms": round(state["first_answer_delta_at"], 2) if state.get("first_answer_delta_at") is not None else None,
            "done_ms": round(state["done_at"], 2) if state.get("done_at") is not None else None,
            **extra,
        },
    }
    _log(summary)
    return summary


def _log(payload: dict[str, Any]) -> None:
    logger.info("[CUSTOMER_PERF] %s", json.dumps(payload, ensure_ascii=False, default=str))
