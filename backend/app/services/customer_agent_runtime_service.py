import json
import re
from typing import Any

from sqlalchemy.orm import Session

from . import agent_trace_service, customer_agent_tool_service, dmxapi_service


MAX_TOOL_ROUNDS = 4
CONTEXT_REFERENCES = ("这些", "刚才那些", "上面这些", "刚才的", "上一轮")


async def process_agent_request(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
    conversation_history: list[dict] | None = None,
) -> dict | None:
    if _needs_previous_context(question) and not previous_result_skus:
        return {
            "answer": "你说的“这些”我还没有可引用的上一轮产品结果。请先告诉我要处理的 SKU，或先查询一批产品，比如“负责人为 Yao 的锅有哪些”。",
            "sku": sku,
            "sources": [{"type": "agent_clarification", "label": "需要明确产品范围"}],
            "actions": [],
            "results": [],
            "steps": [{"type": "clarify", "label": "需要明确产品范围", "detail": "检测到上下文引用，但没有上一轮产品结果。"}],
        }
    messages = _build_tool_selection_messages(question, sku, previous_result_skus or [], conversation_history or [])
    agent_trace_service.trace("TOOL_SELECTION_REQUEST", {"messages": messages, "tools": customer_agent_tool_service.list_tool_specs()})

    tool_results = []
    steps = []
    final_answer = None
    for round_index in range(MAX_TOOL_ROUNDS):
        try:
            content = await dmxapi_service.chat_completion(db, messages, temperature=0, max_tokens=1200)
        except Exception as exc:
            agent_trace_service.trace("TOOL_SELECTION_ERROR", {"error": str(exc)})
            return None if not tool_results else _build_result(question, sku, tool_results, None, steps)

        agent_trace_service.trace("TOOL_SELECTION_RESPONSE", {"round": round_index + 1, "content": content})
        plan = _parse_json_object(content)
        if not plan:
            return None if not tool_results else _build_result(question, sku, tool_results, None, steps)

        tool_calls = plan.get("tool_calls") or []
        if not tool_calls:
            final_answer = str(plan.get("answer") or "").strip() or None
            if final_answer:
                agent_trace_service.trace("FINAL_RESPONSE", {"content": final_answer})
            break

        round_results = []
        for call in tool_calls:
            name = str(call.get("name") or "").strip()
            arguments = call.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = _resolve_context_arguments(arguments, previous_result_skus or [], tool_results)
            agent_trace_service.trace("TOOL_CALL", {"name": name, "arguments": arguments})
            result = await customer_agent_tool_service.execute_tool_async(db, user_id=user_id, name=name, arguments=arguments)
            agent_trace_service.trace("TOOL_RESULT", result)
            tool_results.append(result)
            round_results.append(result)
            steps.append(_step_from_tool_result(name, arguments, result))

        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": json.dumps({"tool_results": round_results, "instruction": "你可以继续调用工具，或输出 {\"answer\":\"...\"} 结束。"}, ensure_ascii=False, default=str)})

    if not tool_results and final_answer:
        return {"answer": final_answer, "sku": sku, "sources": [{"type": "agent_model", "label": "AI回答"}], "actions": [], "results": [], "steps": steps}
    return await _build_result_async(db, question, sku, tool_results, final_answer, steps)


async def _build_result_async(db: Session, question: str, sku: str | None, tool_results: list[dict], final_answer: str | None, steps: list[dict]) -> dict:
    answer = final_answer or await _finalize_answer(db, question, sku, tool_results)
    return _build_result(question, sku, tool_results, answer, steps)


def _build_result(question: str, sku: str | None, tool_results: list[dict], answer: str | None, steps: list[dict] | None = None) -> dict:
    actions = _collect_actions(tool_results)
    results = _collect_results(tool_results)
    return {
        "answer": answer or _fallback_answer(tool_results),
        "sku": _single_sku(results, actions) or sku,
        "sources": _sources_from_tool_results(tool_results),
        "actions": actions,
        "results": results,
        "steps": steps or [],
    }


def _build_tool_selection_messages(question: str, sku: str | None, previous_result_skus: list[str], conversation_history: list[dict]) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是内部产品数据库 Agent。你可以自己选择后端白名单工具查询产品、读取详情、提出修改或删除建议。"
                "严禁编写 SQL，严禁直接执行写库。所有修改/删除只能调用 propose_* 工具生成待确认动作。"
                "如果用户要查询多个产品、条形码、类目或功能，优先调用 search_products。"
                "如果同时有精确条件和模糊语义需求，优先调用 hybrid_search_products。"
                "search_products 支持 term 全字段搜索，也支持 filters 精确筛选，例如 {\"负责人\":\"Yao\",\"类目\":\"锅具\"}。"
                "如果用户给了 SKU 并问单品字段，调用 get_product_detail。"
                "如果用户说“这些/刚才那些/上面这些”，使用 previous_result_skus。"
                "复杂任务可以多轮调用工具，例如先 search_products，再对结果 SKU 调 propose_update_product_field。"
                "你必须只输出 JSON，不要 Markdown。格式："
                "{\"tool_calls\":[{\"name\":\"search_products\",\"arguments\":{\"term\":\"\",\"filters\":{\"负责人\":\"Yao\",\"类目\":\"锅具\"},\"fields\":[\"容量\"]}}]}"
                "如果确实不需要工具，输出 {\"answer\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "selected_sku": sku,
                    "previous_result_skus": previous_result_skus,
                    "conversation_history": conversation_history[-6:] if len(conversation_history) > 6 else conversation_history,
                    "available_tools": customer_agent_tool_service.list_tool_specs(),
                },
                ensure_ascii=False,
            ),
        },
    ]


async def _finalize_answer(db: Session, question: str, sku: str | None, tool_results: list[dict]) -> str | None:
    messages = [
        {
            "role": "system",
            "content": (
                "你是产品知识库智能客服，请根据工具查询结果，用自然、专业、像同事一样的方式回答用户。"
                "格式要求：先说结论，再给具体依据。如果产品有优势/卖点，直接引用。如果有异常数据，友善提醒。"
                "如果有待确认的修改/删除动作，用自然语言说明'已为你生成待确认的修改建议，请在右侧确认卡中查看'。"
                "如果结果很多，总结关键信息并建议用户进一步筛选。"
                "只输出JSON：{\"answer\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "selected_sku": sku, "tool_results": tool_results},
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    agent_trace_service.trace("FINAL_REQUEST", {"messages": messages})
    try:
        content = await dmxapi_service.chat_completion(db, messages, temperature=0.2, max_tokens=1200)
    except Exception as exc:
        agent_trace_service.trace("FINAL_ERROR", {"error": str(exc)})
        return None
    agent_trace_service.trace("FINAL_RESPONSE", {"content": content})
    data = _parse_json_object(content)
    if data and data.get("answer"):
        return str(data["answer"]).strip()
    return content.strip() or None


def _parse_json_object(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _collect_actions(tool_results: list[dict]) -> list[dict]:
    actions = []
    for result in tool_results:
        action = result.get("action") if isinstance(result, dict) else None
        if action:
            actions.append(action)
        for item in result.get("actions") or []:
            actions.append(item)
    return actions


def _collect_results(tool_results: list[dict]) -> list[dict]:
    rows = []
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("tool") in {"search_products", "hybrid_search_products"}:
            rows.extend(result.get("results") or [])
        elif result.get("tool") == "get_product_detail" and result.get("detail"):
            rows.append(result["detail"])
        elif result.get("tool") == "semantic_search_knowledge":
            rows.extend(result.get("results") or [])
    return rows


def _sources_from_tool_results(tool_results: list[dict]) -> list[dict]:
    sources = []
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("tool") in {"search_products", "hybrid_search_products"}:
            sources.append({"type": "product_search", "label": "AI工具查询", "query": result.get("query"), "count": result.get("count", 0)})
        elif result.get("tool") == "get_product_detail":
            sources.append({"type": "product", "label": "AI工具读取详情", "sku": result.get("sku")})
        elif result.get("tool") == "semantic_search_knowledge":
            sources.append({"type": "knowledge_search", "label": "AI语义知识检索", "query": result.get("query"), "count": result.get("count", 0)})
        elif result.get("action"):
            sources.append({"type": "agent_action", "label": "AI工具生成待确认动作", "count": 1})
        elif result.get("actions"):
            sources.append({"type": "agent_action", "label": "AI工具生成待确认动作", "count": len(result.get("actions") or [])})
    return sources


def _single_sku(results: list[dict], actions: list[dict]) -> str | None:
    skus = {item.get("sku") for item in results + actions if item.get("sku")}
    return next(iter(skus)) if len(skus) == 1 else None


def _fallback_answer(tool_results: list[dict]) -> str:
    actions = _collect_actions(tool_results)
    if actions:
        return f"已生成 {len(actions)} 条待确认动作，请在确认卡中逐条确认或取消。"
    results = _collect_results(tool_results)
    if not results:
        return "没有找到匹配的产品资料。"
    lines = [f"找到 {len(results)} 条产品资料："]
    for index, item in enumerate(results[:10], start=1):
        field_values = item.get("field_values") or {}
        suffix = "，" + "，".join(f"{key}：{value}" for key, value in field_values.items()) if field_values else ""
        lines.append(f"{index}. {item.get('sku')}，{item.get('product_name_cn') or ''}{suffix}")
    return "\n".join(lines)


def _resolve_context_arguments(arguments: dict[str, Any], previous_result_skus: list[str], tool_results: list[dict]) -> dict[str, Any]:
    resolved = dict(arguments)
    if resolved.get("skus") in ("$previous_result_skus", "previous_result_skus", "这些", "刚才那些"):
        resolved["skus"] = previous_result_skus
    if resolved.get("sku") in ("$previous_result_skus", "previous_result_skus", "这些", "刚才那些"):
        resolved.pop("sku", None)
        resolved["skus"] = previous_result_skus
    if resolved.get("skus") in ("$last_search_skus", "last_search_skus"):
        resolved["skus"] = _latest_search_skus(tool_results)
    return resolved


def _latest_search_skus(tool_results: list[dict]) -> list[str]:
    for result in reversed(tool_results):
        if result.get("tool") in {"search_products", "hybrid_search_products"}:
            return [item.get("sku") for item in result.get("results") or [] if item.get("sku")]
    return []


def _needs_previous_context(question: str) -> bool:
    return any(item in question for item in CONTEXT_REFERENCES)


def _step_from_tool_result(name: str, arguments: dict[str, Any], result: dict) -> dict:
    labels = {
        "search_products": "查询产品",
        "hybrid_search_products": "融合查询产品",
        "semantic_search_knowledge": "检索知识库",
        "get_product_detail": "读取产品详情",
        "propose_update_product_field": "生成修改确认动作",
        "propose_delete_product_info": "生成删除信息确认动作",
        "propose_delete_product": "生成删除产品确认动作",
    }
    count = result.get("count")
    if count is None:
        count = len(result.get("actions") or ([] if not result.get("action") else [result.get("action")]))
    detail = f"参数：{json.dumps(arguments, ensure_ascii=False, default=str)}"
    if count is not None:
        detail += f"；结果：{count} 条"
    return {
        "type": name,
        "label": labels.get(name, name),
        "detail": detail,
        "ok": bool(result.get("ok", True)),
    }
