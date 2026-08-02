from __future__ import annotations

from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import customer_perf_service, dmxapi_service
from ..models.ai_governance import AIFeatureModel, AIModelUsageLog
from ..models.user import User
from .model_governance_service import resolve_default_authorized_model


_governed_customer_user: ContextVar[User | None] = ContextVar("governed_customer_user", default=None)


def set_governed_customer_user(user: User) -> Token:
    return _governed_customer_user.set(user)


def reset_governed_customer_user(token: Token) -> None:
    _governed_customer_user.reset(token)


def _safe_error_summary(exc: Exception) -> str:
    """Keep provider failures observable without persisting credentials or payloads."""
    return type(exc).__name__


def _governance_table_is_missing(exc: OperationalError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return (
        "no such table: ai_feature_models" in message
        or "relation \"ai_feature_models\" does not exist" in message
    )


def _resolve_customer_model_or_legacy(db: Session, user: User):
    """Use legacy system config only until customer-service governance is configured."""
    try:
        return resolve_default_authorized_model(db, user, "customer_service.chat", "chat")
    except OperationalError as exc:
        if _governance_table_is_missing(exc):
            return None
        raise
    except HTTPException:
        try:
            governance_exists = (
                db.query(AIFeatureModel.id)
                .filter(
                    AIFeatureModel.feature_key == "customer_service.chat",
                    AIFeatureModel.is_enabled.is_(True),
                )
                .first()
            )
        except OperationalError as exc:
            if _governance_table_is_missing(exc):
                return None
            raise
        if governance_exists:
            raise
        return None


def _write_governance_usage(
    db: Session,
    *,
    user: User,
    resolved_model,
    result: str,
    latency_ms: int,
    error_summary: str | None = None,
) -> None:
    db.add(AIModelUsageLog(
        user_id=user.id,
        feature_key="customer_service.chat",
        model_id=resolved_model.model.id,
        credential_scope_type=resolved_model.credential.scope_type,
        result=result,
        latency_ms=latency_ms,
        error_summary=error_summary,
    ))
    db.commit()


async def chat_completion(
    db: Session,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    *,
    purpose: str = "chat",
    api_model_override: str | None = None,
    response_format: dict[str, Any] | None = None,
    thinking: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    user: User | None = None,
) -> str:
    start_time = perf_counter()
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    prompt_tokens_est = max(1, prompt_chars // 4) if prompt_chars else 0
    user = user or _governed_customer_user.get()
    if user is None:
        raise ValueError("Customer chat requires a governed user context")
    resolved_model = _resolve_customer_model_or_legacy(db, user)
    # A governed decision is authoritative.  Before governance has any
    # customer-service config, retain the pre-existing system model/API path.
    model_name = str(resolved_model.model.request_model_name) if resolved_model else (
        str(api_model_override or model or "legacy_system_default")
    )
    response_metadata: dict[str, Any] = {}
    try:
        content = await dmxapi_service.chat_completion(
            db,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_model_override=None if resolved_model else api_model_override,
            response_format=response_format,
            thinking=thinking,
            response_metadata=response_metadata,
            resolved_model=resolved_model,
        )
        llm_record = customer_perf_service.record_llm_call(
            purpose=purpose,
            model=str(response_metadata.get("model") or model_name),
            elapsed_ms=customer_perf_service.perf_ms(start_time),
            prompt_chars=prompt_chars,
            completion_chars=len(str(content)),
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=max(1, len(str(content)) // 4) if content else 0,
        )
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "purpose": purpose,
                    "model": str(response_metadata.get("model") or model_name),
                    "request_model": response_metadata.get("request_model"),
                    "api_model_override": None if resolved_model else api_model_override,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": response_format if isinstance(response_format, dict) and response_format else None,
                    "thinking": thinking if isinstance(thinking, dict) and thinking else None,
                    "usage": response_metadata.get("usage"),
                    "elapsed_ms": llm_record.get("elapsed_ms"),
                    "prompt_chars": prompt_chars,
                    "prompt_tokens_est": prompt_tokens_est,
                    "completion_chars": len(str(content)),
                    "completion_tokens_est": max(1, len(str(content)) // 4) if content else 0,
                }
            )
        if resolved_model:
            _write_governance_usage(
                db, user=user, resolved_model=resolved_model, result="success",
                latency_ms=round(customer_perf_service.perf_ms(start_time)),
            )
        return content
    except Exception as exc:
        llm_record = customer_perf_service.record_llm_call(
            purpose=purpose,
            model=str(response_metadata.get("model") or model_name),
            elapsed_ms=customer_perf_service.perf_ms(start_time),
            prompt_chars=prompt_chars,
            completion_chars=None,
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=None,
            timeout=isinstance(exc, TimeoutError),
            error=str(exc),
        )
        if isinstance(metadata, dict):
            metadata.update(
                {
                    "purpose": purpose,
                    "model": str(response_metadata.get("model") or model_name),
                    "request_model": response_metadata.get("request_model"),
                    "api_model_override": None if resolved_model else api_model_override,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": response_format if isinstance(response_format, dict) and response_format else None,
                    "thinking": thinking if isinstance(thinking, dict) and thinking else None,
                    "usage": response_metadata.get("usage"),
                    "elapsed_ms": llm_record.get("elapsed_ms"),
                    "prompt_chars": prompt_chars,
                    "prompt_tokens_est": prompt_tokens_est,
                    "completion_chars": None,
                    "completion_tokens_est": None,
                    "timeout": isinstance(exc, TimeoutError),
                    "error": str(exc),
                }
            )
        is_timeout = isinstance(exc, (TimeoutError, dmxapi_service.httpx.TimeoutException))
        if resolved_model:
            _write_governance_usage(
                db,
                user=user,
                resolved_model=resolved_model,
                result="timeout" if is_timeout else "failed",
                latency_ms=round(customer_perf_service.perf_ms(start_time)),
                error_summary=_safe_error_summary(exc),
            )
        raise


async def chat_completion_stream(
    db: Session,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    *,
    purpose: str = "chat",
    api_model_override: str | None = None,
    user: User | None = None,
):
    start_time = perf_counter()
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    prompt_tokens_est = max(1, prompt_chars // 4) if prompt_chars else 0
    user = user or _governed_customer_user.get()
    if user is None:
        raise ValueError("Customer chat requires a governed user context")
    resolved_model = _resolve_customer_model_or_legacy(db, user)
    model_name = str(resolved_model.model.request_model_name) if resolved_model else (
        str(api_model_override or model or "legacy_system_default")
    )
    completion_parts: list[str] = []
    try:
        async for chunk in dmxapi_service.chat_completion_stream(
            db,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_model_override=None if resolved_model else api_model_override,
            resolved_model=resolved_model,
        ):
            completion_parts.append(str(chunk))
            yield str(chunk)
        content = "".join(completion_parts)
        customer_perf_service.record_llm_call(
            purpose=purpose,
            model=model_name,
            elapsed_ms=customer_perf_service.perf_ms(start_time),
            prompt_chars=prompt_chars,
            completion_chars=len(content),
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=max(1, len(content) // 4) if content else 0,
        )
        if resolved_model:
            _write_governance_usage(
                db, user=user, resolved_model=resolved_model, result="success",
                latency_ms=round(customer_perf_service.perf_ms(start_time)),
            )
    except Exception as exc:
        customer_perf_service.record_llm_call(
            purpose=purpose,
            model=model_name,
            elapsed_ms=customer_perf_service.perf_ms(start_time),
            prompt_chars=prompt_chars,
            completion_chars=None,
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=None,
            timeout=isinstance(exc, TimeoutError),
            error=str(exc),
        )
        is_timeout = isinstance(exc, (TimeoutError, dmxapi_service.httpx.TimeoutException))
        if resolved_model:
            _write_governance_usage(
                db,
                user=user,
                resolved_model=resolved_model,
                result="timeout" if is_timeout else "failed",
                latency_ms=round(customer_perf_service.perf_ms(start_time)),
                error_summary=_safe_error_summary(exc),
            )
        raise
