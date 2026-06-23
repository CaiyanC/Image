from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from . import customer_perf_service, dmxapi_service


async def chat_completion(
    db: Session,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    *,
    purpose: str = "chat",
) -> str:
    start_time = perf_counter()
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    prompt_tokens_est = max(1, prompt_chars // 4) if prompt_chars else 0
    model_cfg = None
    if model is None:
        try:
            model_cfg = dmxapi_service.get_default_model_by_type(db, "chat")
        except Exception:
            model_cfg = None
    else:
        try:
            model_cfg = dmxapi_service._resolve_model_config(db, model)  # type: ignore[attr-defined]
        except Exception:
            model_cfg = None
    model_name = str((model_cfg or {}).get("api_model") or (model_cfg or {}).get("id") or model or "")
    try:
        content = await dmxapi_service.chat_completion(
            db,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        customer_perf_service.record_llm_call(
            purpose=purpose,
            model=model_name,
            elapsed_ms=customer_perf_service.perf_ms(start_time),
            prompt_chars=prompt_chars,
            completion_chars=len(str(content)),
            prompt_tokens_est=prompt_tokens_est,
            completion_tokens_est=max(1, len(str(content)) // 4) if content else 0,
        )
        return content
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
        raise


async def chat_completion_stream(
    db: Session,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    *,
    purpose: str = "chat",
):
    start_time = perf_counter()
    prompt_chars = sum(len(str(message.get("content") or "")) for message in messages if isinstance(message, dict))
    prompt_tokens_est = max(1, prompt_chars // 4) if prompt_chars else 0
    model_cfg = None
    if model is None:
        try:
            model_cfg = dmxapi_service.get_default_model_by_type(db, "chat")
        except Exception:
            model_cfg = None
    else:
        try:
            model_cfg = dmxapi_service._resolve_model_config(db, model)  # type: ignore[attr-defined]
        except Exception:
            model_cfg = None
    model_name = str((model_cfg or {}).get("api_model") or (model_cfg or {}).get("id") or model or "")
    completion_parts: list[str] = []
    try:
        async for chunk in dmxapi_service.chat_completion_stream(
            db,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
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
        raise
