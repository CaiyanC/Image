import json
import logging
import os
import sys
from typing import Any

from sqlalchemy.orm import Session

from ..models.agent_trace import AgentTrace


logger = logging.getLogger("uvicorn")
MAX_TRACE_CHARS = int(os.getenv("CUSTOMER_AGENT_TRACE_MAX_CHARS", "2000"))
TRACE_STDOUT = os.getenv("CUSTOMER_AGENT_TRACE_STDOUT", "").lower() in {"1", "true", "yes", "on"}
TRACE_FULL_PAYLOAD = os.getenv("CUSTOMER_AGENT_TRACE_FULL_PAYLOAD", "").lower() in {"1", "true", "yes", "on"}
MAX_SUMMARY_TEXT_CHARS = 240


def create_trace(
    db: Session,
    *,
    user_id: str,
    conversation_id: str | None = None,
    sku: str | None = None,
    question: str,
) -> AgentTrace:
    trace_record = AgentTrace(
        user_id=str(user_id),
        conversation_id=str(conversation_id) if conversation_id else None,
        sku=sku,
        question=question,
        status="started",
    )
    db.add(trace_record)
    db.commit()
    db.refresh(trace_record)
    return trace_record


def complete_trace(
    db: Session,
    trace_id: str,
    *,
    intent: str | None = None,
    parser_output: Any | None = None,
    actions: Any | None = None,
    results: Any | None = None,
    sources: Any | None = None,
    final_answer: str | None = None,
    final_output: Any | None = None,
    status: str = "success",
    error_message: str | None = None,
) -> AgentTrace | None:
    trace_record = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
    if not trace_record:
        return None

    trace_record.intent = intent
    trace_record.parser_output_json = _dumps(parser_output or {})
    trace_record.actions_json = _dumps(actions or [])
    trace_record.results_json = _dumps(results or [])
    trace_record.sources_json = _dumps(sources or [])
    trace_record.final_output_json = _dumps(final_output if final_output is not None else {"answer": final_answer or ""})
    trace_record.status = status
    trace_record.error_message = error_message
    db.commit()
    db.refresh(trace_record)
    return trace_record


def serialize_trace(trace_record: AgentTrace | None) -> dict | None:
    if not trace_record:
        return None
    return {
        "id": trace_record.id,
        "user_id": trace_record.user_id,
        "conversation_id": trace_record.conversation_id,
        "sku": trace_record.sku,
        "user_input": {"question": trace_record.question},
        "intent": trace_record.intent,
        "parser_output": trace_record.parser_output,
        "actions": trace_record.actions,
        "results": trace_record.results,
        "sources": trace_record.sources,
        "final_output": trace_record.final_output,
        "status": trace_record.status,
        "error_message": trace_record.error_message,
        "created_at": str(trace_record.created_at) if trace_record.created_at else None,
        "updated_at": str(trace_record.updated_at) if trace_record.updated_at else None,
    }


def trace(label: str, payload: Any) -> None:
    line = _format_trace_line(label, payload)
    if TRACE_STDOUT:
        _safe_print(line)
    logger.info(line)


def _format_trace_line(label: str, payload: Any) -> str:
    safe_payload = _mask(payload)
    if not TRACE_FULL_PAYLOAD:
        safe_payload = _summarize_payload(safe_payload)
    text = _safe_json(safe_payload)
    if len(text) > MAX_TRACE_CHARS:
        text = text[:MAX_TRACE_CHARS] + "...<truncated>"
    return f"[CUSTOMER_AGENT_{label}] {text}"


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    except TypeError:
        return str(payload)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


def _summarize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _summarize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        summary: dict[str, Any] = {"type": "list", "count": len(value)}
        if value:
            summary["sample"] = [_summarize_payload(item) for item in value[:3]]
        return summary
    if isinstance(value, tuple):
        return _summarize_payload(list(value))
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str) and len(value) > MAX_SUMMARY_TEXT_CHARS:
        return f"{value[:MAX_SUMMARY_TEXT_CHARS]}...<chars:{len(value)}>"
    return value


def _safe_print(line: str) -> None:
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        stream = getattr(sys.stdout, "buffer", None)
        if stream is not None:
            stream.write((line + "\n").encode("utf-8", errors="replace"))
            stream.flush()
        else:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
