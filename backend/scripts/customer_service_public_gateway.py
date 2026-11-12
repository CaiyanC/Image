"""Loopback gateway exposing only the bearer-authenticated staff MCP API."""

import os
import re
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse


CONNECTOR_PREFIX = "/api/workbuddy/customer-service"
MCP_OPERATIONS = {"products/search", "knowledge/search", "knowledge/export", "listings/search", "ask", "qa-drafts", "qa-revisions"}
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_REQUEST_BYTES = 24_000
CONNECTOR_CREDENTIAL = re.compile(r"Bearer cscwb(?:qa)?_[A-Za-z0-9_-]{48}", re.IGNORECASE)


def public_service_authorization() -> str:
    default_root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local/share")
    path = Path(os.getenv(
        "CAIYAN_MCP_PUBLIC_SERVICE_FILE",
        str(default_root / "CaiYan/CustomerServiceMcp/public-service.json"),
    ))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("enabled") is not True:
            return ""
        authorization = "Bearer " + str(data.get("token") or "")
        return authorization if CONNECTOR_CREDENTIAL.fullmatch(authorization) else ""
    except (OSError, ValueError):
        return ""


@asynccontextmanager
async def lifespan(application: FastAPI):
    port = int(os.getenv("CAIYAN_MCP_UPSTREAM_PORT", "18001"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid loopback upstream port")
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}",
        timeout=httpx.Timeout(110, connect=3, pool=3),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        trust_env=False,
    ) as client:
        application.state.upstream = client
        yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.router.redirect_slashes = False


def error(status: int, detail: str, *, authenticate: bool = False) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if authenticate:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@app.post(CONNECTOR_PREFIX + "/{operation:path}")
async def relay(operation: str, request: Request) -> Response:
    if operation not in MCP_OPERATIONS or request.url.query:
        return error(404, "接口不存在")
    authorization = request.headers.get("authorization", "")
    shared_connection = not authorization
    if shared_connection:
        authorization = public_service_authorization()
    if not CONNECTOR_CREDENTIAL.fullmatch(authorization):
        return error(401, "请提供个人客服连接令牌", authenticate=True)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return error(415, "仅接受 JSON 请求")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            return error(413, "请求内容过长")
        body.extend(chunk)

    if operation == "knowledge/export" and shared_connection:
        try:
            payload = json.loads(body)
        except ValueError:
            return error(422, "请求参数校验失败，请检查必填项和长度")
        if isinstance(payload, dict) and payload.get("include_unapproved") is True:
            return error(403, "导出待审核和未通过的问答须使用 QA 管理连接")

    try:
        upstream = await request.app.state.upstream.post(
            f"{CONNECTOR_PREFIX}/{operation}",
            content=bytes(body),
            headers={"Authorization": authorization, "Content-Type": "application/json"},
        )
    except httpx.TimeoutException:
        return error(504, "客服接口响应超时")
    except httpx.RequestError:
        return error(502, "客服接口暂时不可用")
    if upstream.status_code >= 500 or upstream.is_redirect:
        return error(502, "客服接口暂时不可用")
    upstream_type = upstream.headers.get("content-type", "").partition(";")[0].strip().lower()
    if operation == "knowledge/export" and upstream.status_code == 200 and upstream_type == DOCX_MEDIA_TYPE:
        headers = {"Cache-Control": "no-store"}
        for name in ("Content-Disposition", "X-CaiYan-SKU", "X-CaiYan-QA-Count"):
            if name in upstream.headers:
                headers[name] = upstream.headers[name]
        return Response(upstream.content, media_type=DOCX_MEDIA_TYPE, headers=headers)
    if upstream_type != "application/json":
        return error(502, "客服接口返回格式异常")
    if upstream.status_code == 422:
        # Pydantic validation details can include the caller's raw payload.
        return error(422, "请求参数校验失败，请检查必填项和长度")
    headers = {"Cache-Control": "no-store"}
    for name in ("WWW-Authenticate", "Retry-After"):
        if name in upstream.headers:
            headers[name] = upstream.headers[name]
    return Response(upstream.content, status_code=upstream.status_code, media_type="application/json", headers=headers)
