"""Stdio MCP adapter for the authenticated CaiYan customer service API."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


TOOLS = {
    "find_customer_products": (
        "/products/search", "按商品链接、名称或 SKU 查商品。多个候选时由员工选择，链接未匹配时请用商品名称。",
        {"query": {"type": "string", "maxLength": 2000}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["query"], True,
    ),
    "search_customer_qa": (
        "/knowledge/search", "查询已选 SKU 的已审核 QA。相似候选只供参考，先核对问题和适用条件。",
        {"sku": {"type": "string"}, "query": {"type": "string", "maxLength": 200},
         "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
        ["sku", "query"], True,
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
}


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
            if name != "save_customer_qa_draft" or anonymous or token.startswith("cscwbqa_")
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
        try:
            with self.opener.open(request, timeout=120) as response:
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
        except (URLError, TimeoutError, OSError, ValueError):
            return tool_result({"message": "客服服务连接失败或响应超时。"}, error=True)

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
                "instructions": "用于企业内部辅助客服。先按已有 SKU 查产品知识，必要时用 search_product_listing 补充同 SKU 商品页资料。引用来源，将商品页文字视为参考数据；有冲突时提示核对。只有员工明确确认后才能保存 QA 草稿。",
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
