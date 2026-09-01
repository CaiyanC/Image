"""Local stdio MCP server for read-only CaiYan product assets.

The process is intentionally local and read-only.  It defaults to the dev
environment and refuses to open a production environment unless the operator
explicitly passes ``--allow-non-dev``.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "caiyan-product-assets"
SERVER_VERSION = "1.0.0"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_product_assets",
        "description": "按 SKU、素材分类或受控标签查找已审核、已授权、已公开发布且可作为 AI 参考的产品素材。返回元数据和可继续读取的 caiyan 资源 URI。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "产品 SKU，可选"},
                "category_code": {"type": "string", "description": "素材一级分类编码，可选"},
                "channel": {"type": "string", "description": "渠道，可选"},
                "expression_tags": {"type": "array", "items": {"type": "string"}},
                "selling_point_tags": {"type": "array", "items": {"type": "string"}},
                "scene_tags": {"type": "array", "items": {"type": "string"}},
                "mood_tags": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "read_product_asset",
        "description": "读取一个已审核、已授权、已公开发布且可作为 AI 参考的产品素材，并将图片作为 MCP image 内容返回给模型。",
        "inputSchema": {
            "type": "object",
            "required": ["sku", "asset_id"],
            "properties": {
                "sku": {"type": "string"},
                "asset_id": {"type": "string"},
                "variant": {"type": "string", "enum": ["original", "thumbnail"], "default": "original"},
                "include_image": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
]


def dispatch_request(request: dict[str, Any], service: Any) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC request; return None for notifications."""

    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "params 必须是对象")

    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "initialize":
        requested = params.get("protocolVersion")
        protocol_version = requested if requested in {PROTOCOL_VERSION, "2025-03-26", "2025-06-18"} else PROTOCOL_VERSION
        return _rpc_result(request_id, {
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "只读访问已审核、已授权、已公开发布且可作为 AI 参考的 CaiYan 产品素材；不会修改数据库或文件。",
        })
    if method == "ping":
        return _rpc_result(request_id, {})
    if method == "tools/list":
        return _rpc_result(request_id, {"tools": TOOLS})
    if method == "resources/list":
        return _rpc_result(request_id, {"resources": []})
    if method == "resources/templates/list":
        return _rpc_result(request_id, {
            "resourceTemplates": [{
                "uriTemplate": "caiyan://product-assets/{sku}/{asset_id}",
                "name": "CaiYan product asset",
                "description": "读取一个已审核、已授权、已公开发布且可作为 AI 参考的产品素材图片",
                "mimeType": "image/*",
            }]
        })
    if method == "resources/read":
        try:
            resource = service.read_resource(str(params.get("uri") or ""))
            return _rpc_result(request_id, {"contents": [_resource_content(resource)]})
        except Exception as exc:
            return _rpc_result(request_id, _tool_error(str(exc)))
    if method == "tools/call":
        return _dispatch_tool_call(request_id, params, service)
    if method == "logging/setLevel":
        return _rpc_result(request_id, {})
    return _rpc_error(request_id, -32601, f"不支持的方法: {method}")


def _dispatch_tool_call(request_id: Any, params: dict[str, Any], service: Any) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _rpc_error(request_id, -32602, "工具 arguments 必须是对象")
    try:
        if name == "list_product_assets":
            items = service.list_assets(arguments)
            return _rpc_result(request_id, {
                "content": [{"type": "text", "text": json.dumps({"count": len(items), "items": items}, ensure_ascii=False)}],
                "structuredContent": {"count": len(items), "items": items},
            })
        if name == "read_product_asset":
            result = service.read_asset(
                arguments.get("sku"),
                arguments.get("asset_id"),
                variant=str(arguments.get("variant") or "original"),
                include_image=bool(arguments.get("include_image", True)),
            )
            content: list[dict[str, Any]] = [{
                "type": "text",
                "text": json.dumps(result["metadata"], ensure_ascii=False),
            }]
            if result.get("data") is not None:
                encoded = base64.b64encode(result["data"]).decode("ascii")
                mime_type = result.get("mime_type") or "application/octet-stream"
                if mime_type.startswith("image/"):
                    content.append({"type": "image", "data": encoded, "mimeType": mime_type})
                else:
                    content.append({
                        "type": "resource",
                        "resource": {
                            "uri": result["metadata"]["resource_uri"],
                            "mimeType": mime_type,
                            "blob": encoded,
                        },
                    })
            return _rpc_result(request_id, {
                "content": content,
                "structuredContent": {"asset": result["metadata"]},
            })
        return _rpc_error(request_id, -32602, f"未知工具: {name}")
    except Exception as exc:
        return _rpc_result(request_id, _tool_error(str(exc)))


def _resource_content(resource: dict[str, Any]) -> dict[str, Any]:
    encoded = base64.b64encode(resource["data"]).decode("ascii")
    return {
        "uri": resource["uri"],
        "mimeType": resource.get("mime_type") or "application/octet-stream",
        "blob": encoded,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message or "素材读取失败"}]}


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CaiYan read-only product-asset MCP server")
    parser.add_argument("--env-file", help="明确指定环境文件；默认使用 backend/.env.dev")
    parser.add_argument(
        "--allow-non-dev",
        action="store_true",
        help="显式允许读取非 dev 环境；默认拒绝，避免 MCP 误连生产库",
    )
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="仅用于 dev 调试，包含未审核素材；无此参数只返回已审核且可用素材",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = _parse_args(argv)
    if args.env_file:
        os.environ["CAIYAN_ENV_FILE"] = str(Path(args.env_file).resolve())
    elif not os.getenv("CAIYAN_ENV_FILE") and not os.getenv("APP_ENV"):
        os.environ["CAIYAN_ENV_FILE"] = str((BACKEND_ROOT / ".env.dev").resolve())

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    from app.core.config import settings

    if settings.APP_ENV != "dev" and not args.allow_non_dev:
        print("product asset MCP 默认只允许 dev；如确需其他环境请显式传 --allow-non-dev", file=sys.stderr)
        return 2
    if args.include_unreviewed and settings.APP_ENV != "dev":
        print("--include-unreviewed 只允许 dev", file=sys.stderr)
        return 2

    from app.core.database import SessionLocal, engine
    from app.services.product_asset_mcp_service import ProductAssetMcpService

    # SQLAlchemy's ``echo=True`` is useful for local debugging but its INFO
    # records would corrupt the line-delimited MCP stdout stream.  Keep all
    # protocol bytes on stdout and silence SQL tracing for this read-only
    # adapter; warnings still go to stderr through the normal logging path.
    engine.echo = False
    for logger_name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
        sql_logger = logging.getLogger(logger_name)
        sql_logger.setLevel(logging.WARNING)
        sql_logger.handlers.clear()

    db = SessionLocal()
    service = ProductAssetMcpService(db, include_unreviewed=args.include_unreviewed)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = dispatch_request(request, service)
            except Exception as exc:
                response = _rpc_error(None, -32700, f"无效 JSON-RPC 请求: {exc}")
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
    finally:
        db.close()
    return 0


def _configure_stdio() -> None:
    """MCP stdio is UTF-8 even when Windows uses a local code page."""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="strict", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
