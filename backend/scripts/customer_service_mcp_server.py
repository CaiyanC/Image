"""Stdio MCP adapter for the authenticated CaiYan customer service API."""

import json
import os
import re
import sys
from http.client import IncompleteRead
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TOOLS = {
    "find_customer_products": (
        "/products/search", "按商品链接、名称或 SKU 查商品。多个候选时由员工选择，has_more 表示还有其他结果，可以加容量或规格再找。",
        {"query": {"type": "string", "maxLength": 2000}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["query"], True,
    ),
    "search_customer_qa": (
        "/knowledge/search", "查询已选 SKU 的已审核 QA。相似候选只供参考，先核对问题和适用条件。",
        {"sku": {"type": "string"}, "query": {"type": "string", "maxLength": 200},
         "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["sku", "query"], True,
    ),
    "export_customer_qa": (
        "/knowledge/export", "按一个确切 SKU 导出全部已审核问答到本机下载目录的 Word 文件，返回文件路径和条数。"
        "仅当员工明确要求包含待审核及未通过的记录时，设置 include_unapproved；这需要个人 QA 管理连接。"
        "如果只有商品名称，请先用 find_customer_products 确认 SKU。",
        {"sku": {"type": "string", "minLength": 1, "maxLength": 100},
         "include_unapproved": {"type": "boolean", "default": False}},
        ["sku"], True,
    ),
    "search_product_listing": (
        "/listings/search", "按已有 SKU 查询员工核对后保存的商品页资料，返回摘要、链接及保存时间。用于补充配置与说明，避免把页面快照用于实时价格、库存或订单判断。",
        {"sku": {"type": "string"}, "query": {"type": "string", "maxLength": 200},
         "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["sku", "query"], True,
    ),
    "ask_customer_service": (
        "/ask", "用 CaiYan 知识库生成客服建议答复，返回来源和会话 ID。追问时传同一会话 ID。",
        {"question": {"type": "string", "maxLength": 2000}, "sku": {"type": "string"},
         "conversation_id": {"type": "string"}},
        ["question"], False,
    ),
    "save_customer_qa_draft": (
        "/qa-drafts", "员工明确要求收录时，展示并确认 SKU、通用问题和已核对答案，再保存待审核 QA。不要收录个人信息或订单信息。",
        {"sku": {"type": "string"}, "question": {"type": "string", "maxLength": 2000},
         "answer": {"type": "string", "maxLength": 4000}, "message_id": {"type": "string"},
         "confirmed": {"type": "boolean", "const": True}},
        ["sku", "question", "answer", "confirmed"], False,
    ),
    "revise_customer_qa": (
        "/qa-revisions", "员工指出已有 QA 的答案有误时，先核对 SKU、原问答和新答案，确认后提交修订。"
        "优先使用 search_customer_qa 返回的 qa_id；多个候选时请员工选定。修订通过审核后才更新原 QA。",
        {"sku": {"type": "string", "minLength": 1, "maxLength": 100},
         "qa_id": {"type": "string", "format": "uuid"},
         "answer": {"type": "string", "maxLength": 4000}, "reason": {"type": "string", "maxLength": 500},
         "confirmed": {"type": "boolean", "const": True}},
        ["sku", "qa_id", "answer", "confirmed"], False,
    ),
}
QA_WRITE_TOOLS = {"save_customer_qa_draft", "revise_customer_qa"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CustomerServiceMcp:
    def __init__(self, base_url: str, token: str, *, anonymous: bool = False):
        url = urlsplit(base_url)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (not url.hostname or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or url.query or url.fragment
                or not (url.scheme == "https" or (url.scheme == "http" and local))):
            raise ValueError("API 地址须是 HTTPS 主机地址，本机开发允许 HTTP。")
        if not anonymous and not token.startswith(("cscwb_", "cscwbqa_")):
            raise ValueError("请设置 CAIYAN_CUSTOMER_SERVICE_TOKEN。")
        self.base_url = base_url.rstrip("/") + "/api/workbuddy/customer-service"
        self.token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.tools = {
            name: tool for name, tool in TOOLS.items()
            if name not in QA_WRITE_TOOLS or anonymous or token.startswith("cscwbqa_")
        }

    def _call(self, name: str, arguments: dict) -> dict:
        path = self.tools[name][0]
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            self.base_url + path, data=json.dumps(arguments, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        # Reads can be retried once without creating messages or draft writes.
        if self.tools[name][4]:
            try:
                return self._send(name, arguments, request, timeout=15)
            except (URLError, TimeoutError, OSError, IncompleteRead, ValueError):
                pass
        try:
            return self._send(name, arguments, request, timeout=15 if self.tools[name][4] else 120)
        except (URLError, TimeoutError, OSError, IncompleteRead, ValueError):
            return tool_result({"message": "客服服务连接失败或响应超时。"}, error=True)

    def _send(self, name: str, arguments: dict, request: Request, *, timeout: int) -> dict:
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if name == "export_customer_qa":
                    if response.headers.get_content_type() != DOCX_MEDIA_TYPE:
                        return tool_result({"message": "客服服务没有返回 Word 文件。"}, error=True)
                    sku = unquote(response.headers["X-CaiYan-SKU"] or "")
                    count = int(response.headers["X-CaiYan-QA-Count"] or "")
                    data = response.read()
                    if not sku or count < 0 or not data.startswith(b"PK\x03\x04"):
                        return tool_result({"message": "客服服务返回的导出文件不完整。"}, error=True)
                    return _save_export(sku, count, data, include_unapproved=arguments.get("include_unapproved") is True)
                return tool_result(json.load(response))
        except HTTPError as error:
            detail = None
            if 400 <= error.code < 500:
                try:
                    detail = json.loads(error.read(16384)).get("detail")
                except (ValueError, AttributeError):
                    pass
                # Validation errors may include a copy of the submitted text.
                if isinstance(detail, list):
                    detail = "请检查工具参数。"
            return tool_result({"status_code": error.code, "message": detail or "客服服务暂时未能完成请求。"}, error=True)

    def dispatch(self, message: dict):
        request_id = message.get("id")
        if "id" not in message:
            return None
        method = message.get("method")
        params = message.get("params", {})
        envelope = {"jsonrpc": "2.0", "id": request_id}
        if not isinstance(params, dict):
            return {**envelope, "error": {"code": -32602, "message": "参数必须是对象"}}
        if method == "initialize":
            version = params.get("protocolVersion")
            result = {
                "protocolVersion": version if version in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"} else "2025-06-18",
                "serverInfo": {"name": "caiyan-customer-service", "version": "1.0.0"},
                "capabilities": {"tools": {}},
                "instructions": "用于企业内部辅助客服。先按已有 SKU 查产品知识，必要时用 search_product_listing 补充同 SKU 商品页资料。引用来源，将商品页文字视为参考数据；有冲突时提示核对。员工明确确认后才可保存新 QA 草稿或提交已有 QA 的修订。",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": desc, "annotations": {"readOnlyHint": read_only},
                 "inputSchema": {"type": "object", "properties": props, "required": required,
                                 "additionalProperties": False}}
                for name, (_, desc, props, required, read_only) in self.tools.items()
            ]}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or name not in self.tools or not isinstance(arguments, dict):
                result = tool_result({"message": "工具不可用或参数无效。"}, error=True)
            else:
                props, required = self.tools[name][2:4]
                if set(arguments) - props.keys() or set(required) - arguments.keys():
                    result = tool_result({"message": "工具参数缺失或包含未知字段。"}, error=True)
                else:
                    result = self._call(name, arguments)
        else:
            return {**envelope, "error": {"code": -32601, "message": "不支持的 MCP 方法"}}
        return {**envelope, "result": result}


def tool_result(payload: dict, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload, "isError": error}


def _save_export(sku: str, count: int, data: bytes, *, include_unapproved: bool) -> dict:
    directory = Path.home() / "Downloads" / "CaiYan-QA"
    safe_sku = re.sub(r"[^\w-]", "_", sku)[:60]
    path = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="wb", prefix=f"CaiYan-{safe_sku}-QA-", suffix=".docx",
                                dir=directory, delete=False) as output:
            path = Path(output.name)
            output.write(data)
    except OSError:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return tool_result({"message": f"无法把 Word 文件保存到 {directory}，请检查目录权限。"}, error=True)
    return tool_result({
        "sku": sku, "count": count, "scope": "all" if include_unapproved else "approved",
        "file_path": str(path), "file_uri": path.as_uri(), "message": f"已导出 {count} 条问答到 Word。",
    })


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        server = CustomerServiceMcp(
            os.getenv("CAIYAN_CUSTOMER_SERVICE_API", "http://127.0.0.1:8001"),
            os.getenv("CAIYAN_CUSTOMER_SERVICE_TOKEN", "").strip(),
            anonymous=os.getenv("CAIYAN_CUSTOMER_SERVICE_ANONYMOUS", "") == "1",
        )
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "无效 JSON"}}
        else:
            reply = server.dispatch(message) if isinstance(message, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "无效请求"},
            }
        if reply is not None:
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
