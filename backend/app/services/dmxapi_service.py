import asyncio
import httpx
import json
import logging
from time import perf_counter
from urllib.parse import urljoin, urlparse
from sqlalchemy.orm import Session
from ..models.system_config import SystemConfig
from ..core.config import settings
from ..core.database import release_session_connection
from . import agent_trace_service, customer_perf_service

logger = logging.getLogger("uvicorn")

DEFAULT_BASE_URL = "https://www.dmxapi.cn"

DEFAULT_MODELS = [
    {"id": "deepseek-customer-service", "name": "DeepSeek 客服模型", "type": "chat", "description": "智能客服推荐模型", "api_key": "", "api_base_url": "https://api.deepseek.com", "api_format": "openai", "api_model": "deepseek-v4-flash", "chat_url": "https://api.deepseek.com/chat/completions", "enabled": True},
    {"id": "gpt-4o-mini", "name": "Customer Service Chat", "type": "chat", "description": "Smart customer service answers", "api_key": "", "api_base_url": DEFAULT_BASE_URL, "api_format": "openai"},
    {"id": "text-embedding-3-small", "name": "Knowledge Embedding", "type": "embedding", "description": "Vector knowledge base embeddings", "api_key": "", "api_base_url": DEFAULT_BASE_URL, "api_format": "openai"},
    {"id": "gpt-image-2-ssvip", "name": "GPT Image 2 SSVIP", "type": "image", "description": "GPT Image 2 增强版（推荐）", "api_key": "", "api_base_url": DEFAULT_BASE_URL, "api_format": "openai"},
    {"id": "gpt-image-2", "name": "GPT Image 2", "type": "image", "description": "GPT Image 第二代图像模型", "api_key": "", "api_base_url": DEFAULT_BASE_URL, "api_format": "openai"},
    {"id": "gemini-3.1-flash-image-preview", "name": "Nano Banana 2", "type": "image", "description": "Gemini 文生图/图生图（计划接入）", "api_key": "", "api_base_url": DEFAULT_BASE_URL, "api_format": "gemini"},
]

_AI_SEMAPHORE = asyncio.Semaphore(max(1, settings.AI_MAX_CONCURRENT_REQUESTS))
_HTTP_CLIENTS: dict[tuple[int, str, bool], httpx.AsyncClient] = {}


def _timeout_key(timeout: object) -> str:
    return repr(timeout)


async def _get_http_client(timeout: object, *, trust_env: bool = False) -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, _timeout_key(timeout), trust_env)
    client = _HTTP_CLIENTS.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=timeout, trust_env=trust_env)
        _HTTP_CLIENTS[key] = client
    return client


async def _run_ai_request(factory, *, timeout: float | None = None):
    if _AI_SEMAPHORE.locked():
        raise RuntimeError("当前请求较多，请稍后再试")
    async with _AI_SEMAPHORE:
        try:
            return await asyncio.wait_for(
                factory(),
                timeout=timeout or float(settings.AI_REQUEST_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("AI 响应超时，请稍后重试") from exc


def _make_url(base: str, path: str) -> str:
    parsed = urlparse(base)
    clean_base = f"{parsed.scheme}://{parsed.netloc}/"
    return urljoin(clean_base, path)


async def _run_ai_request(factory, *, timeout: float | None = None):
    queue_timeout = max(0.0, float(settings.AI_REQUEST_QUEUE_TIMEOUT_SECONDS))
    wait_start = perf_counter()
    acquired = False
    try:
        await asyncio.wait_for(_AI_SEMAPHORE.acquire(), timeout=queue_timeout)
        acquired = True
    except asyncio.TimeoutError as exc:
        wait_ms = (perf_counter() - wait_start) * 1000.0
        _record_ai_semaphore_wait(wait_ms, acquired=False, queue_timeout=queue_timeout)
        raise RuntimeError("当前请求较多，请稍后再试") from exc

    wait_ms = (perf_counter() - wait_start) * 1000.0
    _record_ai_semaphore_wait(wait_ms, acquired=True, queue_timeout=queue_timeout)
    try:
        return await asyncio.wait_for(
            factory(),
            timeout=timeout or float(settings.AI_REQUEST_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError("AI 响应超时，请稍后重试") from exc
    finally:
        if acquired:
            _AI_SEMAPHORE.release()


def _record_ai_semaphore_wait(wait_ms: float, *, acquired: bool, queue_timeout: float) -> None:
    payload = {
        "ai_semaphore_wait_ms": round(wait_ms, 2),
        "acquired": acquired,
        "queue_timeout_seconds": queue_timeout,
        "max_concurrent_requests": settings.AI_MAX_CONCURRENT_REQUESTS,
    }
    customer_perf_service.log_event("ai_semaphore_wait", **payload)
    agent_trace_service.trace("AI_SEMAPHORE_WAIT", payload)


def _get_model_config(db: Session, model_id: str) -> dict | None:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == f"model_{model_id}").first()
    if not row:
        return None
    try:
        data = json.loads(row.config_value)
        data.setdefault("id", model_id)
        data.setdefault("name", model_id)
        data.setdefault("type", "image")
        data.setdefault("description", "")
        data.setdefault("api_key", "")
        data.setdefault("api_base_url", DEFAULT_BASE_URL)
        data.setdefault("api_format", "openai")
        data.setdefault("api_model", data.get("id", model_id))
        data.setdefault("enabled", True)
        return data
    except (json.JSONDecodeError, TypeError):
        pass
    parts = row.config_value.split("|")
    if len(parts) < 5:
        return None
    return {
        "id": model_id,
        "name": parts[0],
        "type": parts[1],
        "description": parts[2],
        "api_key": parts[3],
        "api_base_url": parts[4] if parts[4] else DEFAULT_BASE_URL,
        "api_format": parts[5] if len(parts) > 5 and parts[5] else "openai",
        "api_model": model_id,
        "enabled": True,
    }


def _resolve_model_config(db: Session, model_id: str) -> dict:
    cfg = _get_model_config(db, model_id)
    if cfg:
        return cfg
    for m in DEFAULT_MODELS:
        if m["id"] == model_id:
            return dict(m)
    return {
        "id": model_id,
        "name": model_id,
        "type": "image",
        "description": "",
        "api_key": "",
        "api_base_url": DEFAULT_BASE_URL,
        "api_format": "openai",
        "api_model": model_id,
        "enabled": True,
    }


async def txt2img(
    db: Session,
    prompt: str,
    model: str = "gpt-image-1",
    n: int = 1,
    size: str = "1024x1024",
    **kwargs,
) -> dict:
    cfg = _resolve_model_config(db, model)
    base_url = cfg["api_base_url"]
    api_key = cfg["api_key"]

    if not api_key or not api_key.strip():
        raise ValueError(f"模型 '{model}' 未配置 API Key，请先在管理设置中配置")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    api_model = cfg.get("api_model") or model
    body = {
        "model": api_model,
        "prompt": prompt,
        "n": n,
        "size": size,
    }

    if kwargs.get("quality"):
        body["quality"] = kwargs["quality"]
    if kwargs.get("output_format"):
        body["output_format"] = kwargs["output_format"]
    if kwargs.get("output_compression") is not None:
        fmt = kwargs.get("output_format", "") or ""
        if fmt.lower() in ("jpeg", "webp"):
            body["output_compression"] = kwargs["output_compression"]
    if kwargs.get("moderation"):
        body["moderation"] = kwargs["moderation"]

    url = cfg.get("txt2img_url") or _make_url(base_url, "v1/images/generations")

    body["n"] = 1

    async def _do_request():
        async with httpx.AsyncClient(timeout=float(settings.DMXAPI_TXT2IMG_TIMEOUT), trust_env=False) as client:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"dmxapi.cn: {response.status_code} — {response.text[:500]}",
                    request=response.request,
                    response=response,
                )
            return response.json().get("data", [])

    if n <= 1:
        data = await _do_request()
        return {"data": data}

    tasks = [_do_request() for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_data = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"txt2img request {i+1}/{n} failed: {r}, retrying...")
            for retry in range(2):
                await asyncio.sleep(3 * (retry + 1))
                try:
                    data = await _do_request()
                    all_data.extend(data)
                    break
                except Exception as retry_err:
                    if retry == 1:
                        raise RuntimeError(f"txt2img request {i+1}/{n} failed after 3 attempts") from retry_err
            continue
        all_data.extend(r)

    if not all_data:
        raise RuntimeError(f"txt2img: all {n} requests produced no images")

    return {"data": all_data}


async def img2img(
    db: Session,
    prompt: str,
    image_files: list[tuple[str, bytes, str]],
    model: str = "gpt-image-1",
    n: int = 1,
    size: str = "1024x1024",
    **kwargs,
) -> dict:
    cfg = _resolve_model_config(db, model)
    base_url = cfg["api_base_url"]
    api_key = cfg["api_key"]

    if not api_key or not api_key.strip():
        raise ValueError(f"模型 '{model}' 未配置 API Key，请先在管理设置中配置")

    headers = {"Authorization": f"Bearer {api_key}"}

    data = {
        "prompt": prompt,
        "model": cfg.get("api_model") or model,
        "n": n,
        "size": size,
    }

    if kwargs.get("quality"):
        data["quality"] = kwargs["quality"]
    if kwargs.get("output_format"):
        data["output_format"] = kwargs["output_format"]
    if kwargs.get("output_compression") is not None:
        fmt = kwargs.get("output_format", "") or ""
        if fmt.lower() in ("jpeg", "webp"):
            data["output_compression"] = kwargs["output_compression"]
    if kwargs.get("moderation"):
        data["moderation"] = kwargs["moderation"]
    if kwargs.get("background"):
        data["background"] = kwargs["background"]

    data["n"] = 1

    url = cfg.get("img2img_url") or _make_url(base_url, "v1/images/edits")
    timeout = httpx.Timeout(connect=float(settings.DMXAPI_IMG2IMG_CONNECT_TIMEOUT), read=float(settings.DMXAPI_IMG2IMG_READ_TIMEOUT), write=300.0, pool=10.0)

    async def _do_request():
        req_files = [("image", (filename, content, mime_type)) for filename, content, mime_type in image_files]
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url, headers=headers, data=data, files=req_files)
            if response.status_code >= 400:
                logger.warning(f"dmxapi img2img error: {response.status_code} - {response.text[:300]}")
                raise httpx.HTTPStatusError(
                    f"dmxapi.cn: {response.status_code} — {response.text[:500]}",
                    request=response.request,
                    response=response,
                )
            return response.json().get("data", [])

    if n <= 1:
        data = await _do_request()
        return {"data": data}

    tasks = [_do_request() for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_data = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning(f"img2img request {i+1}/{n} failed: {r}, retrying...")
            for retry in range(2):
                await asyncio.sleep(3 * (retry + 1))
                try:
                    data = await _do_request()
                    all_data.extend(data)
                    break
                except Exception as retry_err:
                    if retry == 1:
                        raise RuntimeError(f"img2img request {i+1}/{n} failed after 3 attempts") from retry_err
            continue
        all_data.extend(r)

    if not all_data:
        raise RuntimeError(f"img2img: all {n} requests produced no images")

    return {"data": all_data}


async def _gemini_single_request(
    base_url: str,
    api_key: str,
    model_id: str,
    body: dict,
    timeout: float,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = _make_url(base_url, f"v1beta/models/{model_id}:generateContent")
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0), trust_env=False) as client:
        response = await client.post(url, headers=headers, json=body)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"dmxapi.cn Gemini: {response.status_code} — {response.text[:500]}",
                request=response.request,
                response=response,
            )
        return response.json()


async def txt2img_gemini(
    db: Session,
    prompt: str,
    model: str = "gemini-3.1-flash-image-preview",
    n: int = 1,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
) -> dict:
    cfg = _resolve_model_config(db, model)
    base_url = cfg["api_base_url"]
    api_key = cfg["api_key"]

    if not api_key or not api_key.strip():
        raise ValueError(f"模型 '{model}' 未配置 API Key，请先在管理设置中配置")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
            }
        }
    }

    if n <= 1:
        response = await _gemini_single_request(base_url, api_key, model, body, 300.0)
        image_data = _extract_gemini_image(response)
        return {"data": image_data}

    tasks = [_gemini_single_request(base_url, api_key, model, body, 300.0) for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    image_list = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Gemini txt2img sub-request {i+1}/{n} failed: {result}, retrying...")
            for retry in range(2):
                await asyncio.sleep(3 * (retry + 1))
                try:
                    resp = await _gemini_single_request(base_url, api_key, model, body, 300.0)
                    image_list.extend(_extract_gemini_image(resp))
                    break
                except Exception as retry_err:
                    if retry == 1:
                        logger.error(f"Gemini txt2img sub-request {i+1}/{n} failed after 3 attempts: {retry_err}")
            continue
        try:
            image_list.extend(_extract_gemini_image(result))
        except Exception as e:
            logger.warning(f"Gemini image extraction failed for request {i+1}/{n}: {e}")
            continue

    if not image_list:
        raise RuntimeError(f"Gemini txt2img: 所有 {n} 个请求均失败")

    return {"data": image_list}


async def img2img_gemini(
    db: Session,
    prompt: str,
    images: list[dict],
    model: str = "gemini-3.1-flash-image-preview",
    n: int = 1,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
) -> dict:
    cfg = _resolve_model_config(db, model)
    base_url = cfg["api_base_url"]
    api_key = cfg["api_key"]

    if not api_key or not api_key.strip():
        raise ValueError(f"模型 '{model}' 未配置 API Key，请先在管理设置中配置")

    parts: list[dict] = [{"text": prompt}]
    for img in images:
        parts.append({
            "inlineData": {
                "mimeType": img["mimeType"],
                "data": img["data"]
            }
        })

    body = {
        "contents": [
            {
                "role": "user",
                "parts": parts
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
            }
        }
    }

    if n <= 1:
        response = await _gemini_single_request(base_url, api_key, model, body, 1000.0)
        image_data = _extract_gemini_image(response)
        return {"data": image_data}

    tasks = [_gemini_single_request(base_url, api_key, model, body, 1000.0) for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    image_list = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Gemini img2img sub-request {i+1}/{n} failed: {result}, retrying...")
            for retry in range(2):
                await asyncio.sleep(3 * (retry + 1))
                try:
                    resp = await _gemini_single_request(base_url, api_key, model, body, 1000.0)
                    image_list.extend(_extract_gemini_image(resp))
                    break
                except Exception as retry_err:
                    if retry == 1:
                        logger.error(f"Gemini img2img sub-request {i+1}/{n} failed after 3 attempts: {retry_err}")
            continue
        try:
            image_list.extend(_extract_gemini_image(result))
        except Exception as e:
            logger.warning(f"Gemini image extraction failed for request {i+1}/{n}: {e}")
            continue

    if not image_list:
        raise RuntimeError(f"Gemini img2img: 所有 {n} 个请求均失败")

    return {"data": image_list}


def _extract_gemini_image(response: dict) -> list[dict]:
    image_list = []
    try:
        candidates = response.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                inline_data = part.get("inlineData")
                if inline_data and inline_data.get("data"):
                    image_list.append({"b64_json": inline_data["data"]})
    except Exception:
        pass
    return image_list


def get_available_models(db: Session) -> list[dict]:
    configured = (
        db.query(SystemConfig)
        .filter(SystemConfig.config_key.like("model_%", escape="\\"))
        .all()
    )

    if configured:
        result = []
        for row in configured:
            model_id = row.config_key.replace("model_", "", 1)
            cfg = _get_model_config(db, model_id)
            if cfg:
                result.append(cfg)
        configured_ids = {m["id"] for m in result}
        for model in DEFAULT_MODELS:
            if model["id"] not in configured_ids:
                result.append(dict(model))
        return result

    return [dict(m) for m in DEFAULT_MODELS]


def set_model_config(db: Session, models: list[dict]):
    existing_keys = db.query(SystemConfig.config_key).filter(
        SystemConfig.config_key.like("model_%", escape="\\")
    ).all()
    existing_key_set = {k[0] for k in existing_keys}

    new_keys = set()
    for m in models:
        key = f"model_{m['id']}"
        value = json.dumps({
            "id": m.get("id", ""),
            "name": m.get("name", ""),
            "type": m.get("type", "image"),
            "description": m.get("description", ""),
            "api_key": m.get("api_key", ""),
            "api_base_url": m.get("api_base_url", DEFAULT_BASE_URL),
            "api_format": m.get("api_format", "openai"),
            "api_model": m.get("api_model") or m.get("id", ""),
            "txt2img_url": m.get("txt2img_url", ""),
            "img2img_url": m.get("img2img_url", ""),
            "chat_url": m.get("chat_url", ""),
            "embedding_url": m.get("embedding_url", ""),
            "enabled": m.get("enabled", True),
        }, ensure_ascii=False)
        config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if config:
            config.config_value = value
        else:
            db.add(SystemConfig(config_key=key, config_value=value))
        new_keys.add(key)

    for key in existing_key_set - new_keys:
        config = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
        if config:
            db.delete(config)

    db.commit()


def get_default_model_by_type(db: Session, model_type: str) -> dict | None:
    models = get_available_models(db)
    for model in models:
        if model.get("type") == model_type and model.get("api_key") and model.get("enabled", True):
            return model
    for model in models:
        if model.get("type") == model_type and model.get("enabled", True):
            return model
    return None


async def chat_completion(
    db: Session,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    cfg = _resolve_model_config(db, model) if model else get_default_model_by_type(db, "chat")
    if not cfg:
        raise ValueError("未配置聊天模型，请先在管理设置中添加 type=chat 的模型")
    if cfg.get("api_format") != "openai":
        raise ValueError("智能客服当前仅支持 OpenAI 格式的聊天模型")

    api_key = cfg.get("api_key", "").strip()
    if not api_key:
        raise ValueError(f"聊天模型 '{cfg['id']}' 未配置 API Key")

    body = {
        "model": cfg.get("api_model") or cfg["id"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = cfg.get("chat_url") or _make_url(cfg.get("api_base_url") or DEFAULT_BASE_URL, "v1/chat/completions")
    agent_trace_service.trace("AI_REQUEST", {"url": url, "body": body})
    release_session_connection(db)

    async def _request():
        client = await _get_http_client(float(settings.AI_REQUEST_TIMEOUT_SECONDS), trust_env=False)
        return await client.post(url, headers=headers, json=body)

    response = await _run_ai_request(_request)
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"聊天模型请求失败: {response.status_code} - {response.text[:500]}",
            request=response.request,
            response=response,
        )
    data = response.json()
    agent_trace_service.trace("AI_RESPONSE", data)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("聊天模型返回格式异常") from exc


async def chat_completion_stream(
    db: Session,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 1200,
):
    cfg = _resolve_model_config(db, model) if model else get_default_model_by_type(db, "chat")
    if not cfg:
        raise ValueError("chat model is not configured")
    if cfg.get("api_format") != "openai":
        raise ValueError("chat model must use OpenAI-compatible API format")

    api_key = cfg.get("api_key", "").strip()
    if not api_key:
        raise ValueError(f"chat model '{cfg['id']}' has no API key")

    body = {
        "model": cfg.get("api_model") or cfg["id"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = cfg.get("chat_url") or _make_url(cfg.get("api_base_url") or DEFAULT_BASE_URL, "v1/chat/completions")
    agent_trace_service.trace("AI_STREAM_REQUEST", {"url": url, "body": body})
    release_session_connection(db)

    client = await _get_http_client(float(settings.AI_REQUEST_TIMEOUT_SECONDS), trust_env=False)
    async with client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code >= 400:
            text = await response.aread()
            raise httpx.HTTPStatusError(
                f"chat model request failed: {response.status_code} - {text[:500]!r}",
                request=response.request,
                response=response,
            )
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_text = line.removeprefix("data:").strip()
            if data_text == "[DONE]":
                break
            try:
                data = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            try:
                content = data["choices"][0].get("delta", {}).get("content") or ""
            except (KeyError, IndexError, TypeError):
                content = ""
            if content:
                yield content


async def create_embedding(
    db: Session,
    text: str,
    model: str | None = None,
) -> tuple[list[float], str]:
    api_key = settings.DASHSCOPE_API_KEY.strip()
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY is not configured")

    model_name = "text-embedding-v4"
    body = {
        "model": model_name,
        "input": text,
        "dimensions": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    release_session_connection(db)

    def _request_sync():
        timeout = float(settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS)
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            return client.post(url, headers=headers, json=body)

    if _AI_SEMAPHORE.locked():
        raise RuntimeError("褰撳墠璇锋眰杈冨锛岃绋嶅悗鍐嶈瘯")
    async with _AI_SEMAPHORE:
        response = await asyncio.wait_for(
            asyncio.to_thread(_request_sync),
            timeout=float(settings.EMBEDDING_REQUEST_TIMEOUT_SECONDS) + 1.0,
        )
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"Embedding 模型请求失败: {response.status_code} - {response.text[:500]}",
            request=response.request,
            response=response,
        )
    data = response.json()
    try:
        return data["data"][0]["embedding"], model_name
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Embedding 模型返回格式异常") from exc
