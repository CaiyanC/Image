import json
import re
from typing import Any

from sqlalchemy.orm import Session

from . import agent_trace_service, customer_agent_tool_service, dmxapi_service


MAX_TOOL_ROUNDS = 4
CONTEXT_REFERENCES = ("这些", "刚才那些", "上面这些", "刚才的", "上一轮")
WRITE_TOOL_PREFIXES = ("propose_",)
PRODUCT_LOOKUP_TERMS = (
    "适合", "推荐", "哪些", "有没有", "有吗", "容量", "材质", "卖点", "场景",
    "做饭", "烹饪", "煮饭", "炒菜", "露营", "徒步", "锅", "炉", "咖啡", "泡咖啡",
)
PRODUCT_WRITE_TERMS = ("修改", "改成", "改为", "删除", "删掉", "清空", "取消")
COFFEE_TERMS = ("咖啡", "泡咖啡")
COOKING_TERMS = ("做饭", "烹饪", "煮饭", "炒菜", "煮东西")


async def process_agent_request(
    db: Session,
    *,
    user_id: str,
    question: str,
    sku: str | None = None,
    previous_result_skus: list[str] | None = None,
    conversation_history: list[dict] | None = None,
    feedback_lessons: list[dict] | None = None,
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
    messages = _build_tool_selection_messages(question, sku, previous_result_skus or [], conversation_history or [], feedback_lessons or [])
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

    if tool_results and _requires_write_tool(question) and not _collect_actions(tool_results):
        agent_trace_service.trace(
            "WRITE_REQUEST_WITHOUT_ACTION_REJECTED",
            {"question": question, "tool_results": tool_results},
        )
        return None
    if not tool_results and final_answer and _requires_write_tool(question):
        agent_trace_service.trace(
            "DIRECT_PRODUCT_WRITE_ANSWER_REJECTED",
            {"question": question, "answer": final_answer},
        )
        return None
    if not tool_results and final_answer and _requires_lookup_tool(question):
        arguments = {
            "semantic_query": question,
            "fields": [
                "specs.capacity",
                "specs.body_material",
                "business.top_selling_points",
                "business.usage_scenarios",
                "business.target_audience",
            ],
            "limit": 20,
        }
        agent_trace_service.trace(
            "DIRECT_PRODUCT_ANSWER_GUARDRAIL",
            {"question": question, "answer": final_answer, "fallback_tool": "hybrid_search_products"},
        )
        fallback_result = await customer_agent_tool_service.execute_tool_async(
            db,
            user_id=user_id,
            name="hybrid_search_products",
            arguments=arguments,
        )
        tool_results.append(fallback_result)
        steps.append(_step_from_tool_result("hybrid_search_products", arguments, fallback_result))
        final_answer = None
    if not tool_results and final_answer:
        return _build_result(
            question,
            sku,
            [],
            final_answer,
            steps,
            conversation_history=conversation_history or [],
            direct_answer=True,
        )
    return await _build_result_async(
        db,
        question,
        sku,
        tool_results,
        final_answer,
        steps,
        conversation_history=conversation_history or [],
    )


async def _build_result_async(
    db: Session,
    question: str,
    sku: str | None,
    tool_results: list[dict],
    final_answer: str | None,
    steps: list[dict],
    conversation_history: list[dict] | None = None,
) -> dict:
    answer = final_answer or await _finalize_answer(db, question, sku, tool_results, conversation_history or [])
    return _build_result(question, sku, tool_results, answer, steps, conversation_history=conversation_history or [])


def _build_result(
    question: str,
    sku: str | None,
    tool_results: list[dict],
    answer: str | None,
    steps: list[dict] | None = None,
    conversation_history: list[dict] | None = None,
    direct_answer: bool = False,
) -> dict:
    actions = _collect_actions(tool_results)
    results = _collect_results(tool_results)
    warnings = _warnings_from_tool_results(tool_results, direct_answer=direct_answer)
    provisional_answer = _clean_customer_answer(answer or "")
    provisional_needs_clarification = _needs_clarification(provisional_answer, results, warnings)
    intent = _infer_intent(question, tool_results, actions, results, provisional_needs_clarification)
    if intent == "recommend_products":
        results = _rank_recommendation_results(question, results)
        if not provisional_answer or _should_replace_recommendation_answer(provisional_answer, question, results):
            provisional_answer = _compose_recommendation_answer(question, results)
    elif results and _answer_conflicts_with_current_results(provisional_answer, question, results):
        warnings.append("LLM 原始回答与本轮问题或工具结果不一致，已改用工具结果兜底回答。")
        provisional_answer = _fallback_answer(tool_results)
    clean_answer = _clean_customer_answer(provisional_answer or _fallback_answer(tool_results))
    needs_clarification = _needs_clarification(clean_answer, results, warnings)
    suggested_followups = _suggested_followups(question, results, needs_clarification)
    final_steps = [
        {
            "type": "llm_decision",
            "label": "LLM理解问题并选择工具",
            "detail": "结合当前问题、历史对话和可用工具自主决策",
            "ok": True,
        },
        *(steps or []),
        {
            "type": "llm_reasoning",
            "label": "LLM基于工具结果推理回答",
            "detail": "根据工具返回的数据整理结论、依据和下一步建议",
            "ok": True,
        },
    ]
    return {
        "answer": clean_answer,
        "intent": intent,
        "answer_type": _answer_type_from_intent(intent),
        "confidence": _confidence(results, warnings, needs_clarification, direct_answer),
        "uncertainty": _uncertainty(clean_answer, results, warnings, needs_clarification),
        "needs_clarification": needs_clarification,
        "anomalies": _anomalies_from_tool_results(tool_results),
        "suggested_followups": suggested_followups,
        "followups": suggested_followups,
        "evidence": _evidence_from_results(results),
        "debug": {
            "agent_mode": "llm_tool_calling",
            "intent": intent,
            "history_turns": len(conversation_history or []),
            "steps": final_steps,
            "warnings": warnings,
            "raw_results": results,
            "tool_results": tool_results,
        },
        "sku": _single_sku(results, actions) or sku,
        "sources": _sources_from_tool_results(tool_results, direct_answer=direct_answer),
        "actions": actions,
        "results": results,
        "steps": final_steps,
        "warnings": warnings,
        "skip_polish": True,
    }


def _build_tool_selection_messages(
    question: str,
    sku: str | None,
    previous_result_skus: list[str],
    conversation_history: list[dict],
    feedback_lessons: list[dict],
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是内部产品数据库 Agent。你可以自己选择后端白名单工具查询产品、读取详情、提出修改或删除建议。"
                "严禁编写 SQL，严禁直接执行写库。所有修改/删除只能调用 propose_* 工具生成待确认动作。"
                "如果用户要查询多个产品、条形码、类目或功能，优先调用 search_products。"
                "如果同时有精确条件和模糊语义需求，优先调用 hybrid_search_products。"
                "search_products 支持 term 全字段搜索，也支持 filters 精确筛选，例如 {\"负责人\":\"Yao\",\"类目\":\"锅具\"}。"
                "如果用户在问题文本或历史对话里明确给了 SKU，并问单品字段，调用 get_product_detail。"
                "如果用户说“这些/刚才那些/上面这些”，使用 previous_result_skus。"
                "如果本轮问题是完整的新需求（例如重新说明人数、场景、用途、产品类型），以当前问题为准重新检索；不要把上一轮 SKU 当默认范围。"
                "如果用户在历史对话里已经给过范围，本轮追问如“哪种适合送礼/三个年轻人用哪个好”，要结合 conversation_history 和 previous_result_skus 决定工具。"
                "凡是涉及产品事实、推荐、对比、筛选、修改或删除，必须先调用工具；只有闲聊、解释能力边界或澄清问题可以直接 answer。"
                "如果问题缺少必要范围，不要猜，输出澄清 answer。"
                "做推荐/送礼/适合谁时，优先读取候选产品的容量、材质、卖点、使用场景、目标人群、情绪价值，再给取舍理由。"
                "如果 recent_feedback_lessons 里有相似问题，要避免重复其中的错误。"
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
                    "previous_result_skus": previous_result_skus,
                    "conversation_history": conversation_history[-6:] if len(conversation_history) > 6 else conversation_history,
                    "recent_feedback_lessons": feedback_lessons[:8],
                    "available_tools": customer_agent_tool_service.list_tool_specs(),
                },
                ensure_ascii=False,
            ),
        },
    ]


async def _finalize_answer(db: Session, question: str, sku: str | None, tool_results: list[dict], conversation_history: list[dict]) -> str | None:
    messages = [
        {
            "role": "system",
            "content": (
                "你是产品知识库智能客服，请根据工具查询结果，用自然、专业、像同事一样的方式回答用户。"
                "格式要求：先说结论，再给具体依据。如果产品有优势/卖点，直接引用。如果有异常数据，友善提醒。"
                "如果有待确认的修改/删除动作，用自然语言说明'已为你生成待确认的修改建议，请在右侧确认卡中查看'。"
                "如果结果很多，总结关键信息并建议用户进一步筛选。"
                "如果用户是在追问上一轮内容，要显式继承历史对话里的范围，不要当作孤立问题。"
                "如果本轮问题已经重新说明了人数、场景或用途，要以本轮 question 和 tool_results 为准，不要复读上一轮需求。"
                "不得新增工具结果之外的产品事实、参数、价格、库存或承诺。"
                "answer 字段里不要使用 Markdown 标记，不要出现 **、###、表格语法。"
                "只输出JSON：{\"answer\":\"...\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "conversation_history": conversation_history[-8:] if len(conversation_history) > 8 else conversation_history,
                    "tool_results": tool_results,
                },
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
        elif result.get("tool") == "get_product_detail" and result.get("details"):
            rows.extend(result.get("details") or [])
        elif result.get("tool") == "semantic_search_knowledge":
            rows.extend(result.get("results") or [])
    return rows


def _warnings_from_tool_results(tool_results: list[dict], *, direct_answer: bool) -> list[str]:
    warnings = []
    if direct_answer:
        warnings.append("模型未调用工具直接回答")
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            warnings.append(str(result.get("error") or "工具调用失败"))
    return warnings


def _clean_customer_answer(answer: str) -> str:
    text = str(answer or "").strip()
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _anomalies_from_tool_results(tool_results: list[dict]) -> list[dict]:
    anomalies = []
    for result in tool_results:
        if isinstance(result, dict) and result.get("ok") is False:
            anomalies.append({"type": "tool_error", "message": str(result.get("error") or ""), "tool": result.get("tool")})
    return anomalies


def _needs_clarification(answer: str | None, results: list[dict], warnings: list[str]) -> bool:
    text = answer or ""
    if any(item in text for item in ("请先", "需要先", "请告诉我", "需要明确", "范围")) and not results:
        return True
    return False


def _infer_intent(question: str, tool_results: list[dict], actions: list[dict], results: list[dict], needs_clarification: bool) -> str:
    if needs_clarification:
        return "clarify"
    tool_names = {_tool_name(item) for item in tool_results}
    if "propose_delete_product" in tool_names or "propose_delete_product_info" in tool_names:
        return "propose_delete"
    if actions or any(name.startswith(WRITE_TOOL_PREFIXES) for name in tool_names):
        return "propose_update"
    if any(word in question for word in ("对比", "比较", "区别", "差异")):
        return "compare_products"
    if any(word in question for word in ("推荐", "适合", "哪个好", "哪款", "送礼", "年轻人", "场景")):
        return "recommend_products"
    if "get_product_detail" in tool_names:
        return "product_detail"
    if results or any(name in {"search_products", "hybrid_search_products", "semantic_search_knowledge"} for name in tool_names):
        return "query_products"
    return "chat"


def _tool_name(result: dict) -> str:
    return str(result.get("tool") or "")


def _answer_type_from_intent(intent: str) -> str:
    return {
        "query_products": "product_query",
        "product_detail": "product_detail",
        "compare_products": "comparison",
        "recommend_products": "recommendation",
        "propose_update": "action_proposal",
        "propose_delete": "action_proposal",
        "clarify": "clarification",
        "chat": "chat",
    }.get(intent, "unknown")


def _confidence(results: list[dict], warnings: list[str], needs_clarification: bool, direct_answer: bool) -> str:
    if needs_clarification or direct_answer:
        return "low"
    if warnings or not results:
        return "medium"
    return "high"


def _uncertainty(answer: str, results: list[dict], warnings: list[str], needs_clarification: bool) -> str:
    if needs_clarification:
        return "ambiguous_product"
    if any(item in answer for item in ("没有标注", "资料未标注", "不能确认", "需要人工确认")):
        return "not_recorded"
    if warnings or (not results and any(item in answer for item in ("没有找到", "无法", "不能可靠"))):
        return "insufficient_data"
    return "confirmed"


def _suggested_followups(question: str, results: list[dict], needs_clarification: bool) -> list[str]:
    if needs_clarification:
        return ["请给我 SKU、类目、负责人，或先让我查一批产品。"]
    if len(results) > 10:
        return ["可以继续按负责人、类目、容量、材质或使用场景缩小范围。"]
    if any(word in question for word in ("推荐", "适合", "送礼")):
        return ["也可以告诉我预算、人数和使用场景，我再帮你缩小推荐。"]
    return []


def _evidence_from_results(results: list[dict]) -> list[dict]:
    evidence = []
    for item in results[:8]:
        if not isinstance(item, dict):
            continue
        field_values = item.get("field_values") if isinstance(item.get("field_values"), dict) else {}
        if field_values:
            for label, value in field_values.items():
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": value,
                    "source_layer": _layer_for_field_label(str(label)),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
            continue
        for label, key in (("容量", "capacity"), ("材质", "body_material"), ("颜色", "color"), ("负责人", "person_in_charge"), ("类目", "category"), ("卖点", "features")):
            value = item.get(key)
            if value not in (None, ""):
                evidence.append({
                    "sku": item.get("sku"),
                    "product_name": item.get("product_name_cn") or item.get("product_name_en"),
                    "field_label": label,
                    "value": str(value),
                    "source_layer": _layer_for_field_label(label),
                    "matched_by": item.get("matched_by") or "产品资料",
                })
    return evidence


def _layer_for_field_label(label: str) -> str:
    if any(item in label for item in ("容量", "重量", "材质", "颜色", "热源", "功率", "表面")):
        return "L2"
    if any(item in label for item in ("卖点", "场景", "定位", "人群", "竞品")):
        return "L3"
    if any(item in label for item in ("标题", "描述", "关键词", "listing", "Listing")):
        return "L4"
    return "L1"


def _sources_from_tool_results(tool_results: list[dict], *, direct_answer: bool = False) -> list[dict]:
    if direct_answer:
        return [{"type": "agent_model", "label": "AI直接回答"}]
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


def _rank_recommendation_results(question: str, results: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        sku = item.get("sku")
        if not sku or sku in unique:
            continue
        unique[sku] = item
    ranked = sorted(unique.values(), key=lambda row: _recommendation_score(question, row), reverse=True)
    return [row for row in ranked if _recommendation_score(question, row) > -20][:5]


def _recommendation_score(question: str, row: dict) -> float:
    text = _row_text(row)
    name = str(row.get("product_name_cn") or "")
    capacity_ml = _capacity_ml(row.get("capacity"))
    score = 0.0
    if "露营" in question and "露营" in text:
        score += 30
    if any(word in question for word in ("年轻人", "三人", "三个人", "三个")):
        if capacity_ml:
            if 1800 <= capacity_ml <= 4200:
                score += 35
            elif capacity_ml < 1500:
                score -= 25
            elif capacity_ml > 5000:
                score -= 15
        if any(word in text for word in ("家庭", "多人", "聚餐", "营地大餐", "精致露营")):
            score += 12
        if any(word in text for word in ("单人", "极限轻量", "速穿")):
            score -= 16
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")):
        if any(word in text for word in ("咖啡", "煮水", "速沸", "烧水", "单锅")):
            score += 35
        if capacity_ml:
            if 400 <= capacity_ml <= 1500:
                score += 35
            elif capacity_ml > 2000:
                score -= 35
        if any(word in name for word in ("炒锅", "煎锅", "煎盘")):
            score -= 50
        if "炉" in name and "锅" not in name:
            score -= 20
    if any(word in question for word in ("送礼", "礼物")):
        if any(word in text for word in ("颜值", "精致", "情绪价值", "优雅", "礼")):
            score += 25
        if any(word in text for word in ("套锅", "套装", "家庭", "精致露营")):
            score += 15
    if row.get("features"):
        score += 4
    return score


def _should_replace_recommendation_answer(answer: str, question: str, results: list[dict]) -> bool:
    if not results:
        return False
    if _answer_conflicts_with_current_results(answer, question, results):
        return True
    if _answer_focus_conflicts(answer, question):
        return True
    listed_count = len(re.findall(r"(^|\n)\s*\d+[\.、]", answer))
    if listed_count > 5:
        return True
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")) and any(word in answer for word in ("炒锅", "煎锅", "煎盘")):
        return True
    return "找到" in answer and "条产品资料" in answer


def _compose_recommendation_answer(question: str, results: list[dict]) -> str:
    if not results:
        return "没有找到足够匹配的产品资料。你可以补充人数、场景或容量要求，我再帮你缩小范围。"
    best = results[0]
    lines = [f"首选 {best.get('sku')}，{best.get('product_name_cn') or best.get('product_name_en') or ''}。"]
    reason = _recommendation_reason(question, best)
    if reason:
        lines.append(f"理由：{reason}")
    if len(results) > 1:
        lines.append("备选：")
        for item in results[1:3]:
            item_reason = _recommendation_reason(question, item)
            lines.append(f"{item.get('sku')}，{item.get('product_name_cn') or item.get('product_name_en') or ''}：{item_reason}")
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")):
        lines.append("我已把炒锅、煎锅这类容量偏大或器型不适合泡咖啡的产品降权，不作为优先推荐。")
    return "\n".join(line for line in lines if line.strip())


def _recommendation_reason(question: str, row: dict) -> str:
    parts = []
    capacity = row.get("capacity")
    if capacity:
        parts.append(f"容量 {capacity}")
    if row.get("body_material"):
        parts.append(f"材质 {row.get('body_material')}")
    if row.get("features"):
        parts.append(f"卖点 {row.get('features')}")
    scenes = row.get("usage_scenarios") or row.get("usage_scene") or ""
    if scenes:
        parts.append(f"场景 {scenes}")
    if any(word in question for word in ("咖啡", "泡咖啡", "小锅")) and _capacity_ml(capacity) and _capacity_ml(capacity) > 2000:
        parts.append("但容量偏大，不适合单人小锅泡咖啡")
    return "；".join(str(part) for part in parts[:4] if part)


def _row_text(row: dict) -> str:
    values = []
    for key in ("product_name_cn", "product_name_en", "category", "sub_category", "capacity", "body_material", "features", "target_audience", "usage_scenarios", "emotional_value", "semantic_match"):
        value = row.get(key)
        if value:
            values.append(str(value))
    field_values = row.get("field_values")
    if isinstance(field_values, dict):
        values.extend(str(value) for value in field_values.values())
    return " ".join(values)


def _capacity_ml(value: Any) -> float | None:
    text = str(value or "")
    numbers = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ML|ml|毫升)", text)]
    if numbers:
        return max(numbers)
    liters = [float(item) * 1000 for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:L|l|升)", text)]
    if liters:
        return max(liters)
    return None


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


def _requires_lookup_tool(question: str) -> bool:
    text = str(question or "")
    if _requires_write_tool(text):
        return False
    return any(term in text for term in PRODUCT_LOOKUP_TERMS)


def _requires_write_tool(question: str) -> bool:
    text = str(question or "")
    return any(term in text for term in PRODUCT_WRITE_TERMS)


def _answer_focus_conflicts(answer: str, question: str) -> bool:
    answer_text = str(answer or "")
    question_text = str(question or "")
    asks_cooking = any(term in question_text for term in COOKING_TERMS)
    asks_coffee = any(term in question_text for term in COFFEE_TERMS)
    if asks_cooking and not asks_coffee and any(term in answer_text for term in COFFEE_TERMS):
        return True
    return False


def _answer_conflicts_with_current_results(answer: str, question: str, results: list[dict]) -> bool:
    if not answer or not results:
        return False
    if _answer_focus_conflicts(answer, question):
        return True

    result_skus = {str(item.get("sku") or "").upper() for item in results if item.get("sku")}
    if not result_skus:
        return False

    mentioned_skus = _extract_skus(answer)
    if not mentioned_skus:
        return False

    if mentioned_skus.isdisjoint(result_skus):
        return True
    return bool(mentioned_skus - result_skus) and any(word in answer for word in ("首选", "推荐", "适合", "建议"))


def _extract_skus(text: str) -> set[str]:
    return {
        match.upper()
        for match in re.findall(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", str(text or ""), flags=re.IGNORECASE)
    }


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
