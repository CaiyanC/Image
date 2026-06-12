from __future__ import annotations

import re
from typing import Any


FACT_INTENTS = {"query_products", "product_detail", "compare_products", "recommend_products"}
WRITE_INTENTS = {"propose_update", "propose_delete"}
PRODUCT_LOOKUP_TERMS = (
    "适合", "推荐", "哪些", "有没有", "有吗", "容量", "材质", "卖点", "场景",
    "做饭", "烹饪", "煮饭", "炒菜", "露营", "徒步", "锅", "炉", "咖啡", "泡咖啡",
    "对比", "比较", "区别", "价格", "库存",
)
WRITE_TERMS = ("修改", "改成", "改为", "删除", "删掉", "清空", "不用确认", "直接改")
DIRECT_WRITE_CLAIMS = ("已经修改完成", "已直接修改", "已经删除", "已删除完成", "已写入")
CONTEXT_TERMS = ("这些", "这款", "这个", "那个", "刚才", "上面", "前面", "上一轮", "他", "它")
CLARIFICATION_TERMS = ("请先", "需要明确", "告诉我", "SKU", "范围", "类目", "场景")
SKU_RE = re.compile(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", flags=re.IGNORECASE)


def evaluate_agent_response(
    question: str,
    *,
    answer: str,
    intent: str,
    results: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    needs_clarification: bool = False,
    direct_answer: bool = False,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score the observable behavior of one customer-service answer.

    This intentionally avoids model judging so it can run in unit tests and CI.
    It mirrors common production agent checks: groundedness, tool use, task
    adherence, intent resolution, context handling, and answer hygiene.
    """
    results = results or []
    sources = sources or []
    actions = actions or []
    warnings = warnings or []
    tool_results = tool_results or []
    answer = str(answer or "")
    intent = str(intent or "")

    risks: list[str] = []
    dimensions = {
        "intent_resolution": _score_intent_resolution(question, intent, results, actions, needs_clarification, answer),
        "groundedness": _score_groundedness(question, answer, intent, results, sources, actions, direct_answer, risks),
        "tool_use": _score_tool_use(question, intent, sources, actions, warnings, direct_answer, tool_results, risks),
        "task_adherence": _score_task_adherence(question, answer, intent, actions, risks),
        "context_handling": _score_context_handling(question, answer, results, actions, needs_clarification, risks),
        "answer_hygiene": _score_answer_hygiene(answer, intent, risks),
    }
    weights = {
        "intent_resolution": 0.18,
        "groundedness": 0.24,
        "tool_use": 0.18,
        "task_adherence": 0.18,
        "context_handling": 0.10,
        "answer_hygiene": 0.12,
    }
    score = sum(dimensions[key] * weights[key] for key in weights)
    score = max(0.0, min(1.0, round(score, 3)))
    return {
        "score": score,
        "level": _quality_level(score, risks),
        "passed": score >= 0.82 and not _has_blocking_risk(risks),
        "dimensions": dimensions,
        "risks": list(dict.fromkeys(risks)),
        "recommendations": _recommendations(risks),
    }


def _score_intent_resolution(
    question: str,
    intent: str,
    results: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    needs_clarification: bool,
    answer: str,
) -> float:
    if needs_clarification:
        return 1.0 if any(term in answer for term in CLARIFICATION_TERMS) else 0.55
    if any(term in question for term in WRITE_TERMS):
        return 1.0 if intent in WRITE_INTENTS and actions else 0.25
    if any(term in question for term in ("对比", "比较", "区别")):
        return 1.0 if intent == "compare_products" and (len(results) >= 2 or results) else 0.45
    if any(term in question for term in ("推荐", "适合", "送礼", "哪款", "哪个好")):
        return 1.0 if intent == "recommend_products" and results else 0.45
    if any(term in question for term in PRODUCT_LOOKUP_TERMS):
        return 1.0 if intent in FACT_INTENTS and results else 0.55
    return 1.0


def _score_groundedness(
    question: str,
    answer: str,
    intent: str,
    results: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    direct_answer: bool,
    risks: list[str],
) -> float:
    if intent in WRITE_INTENTS:
        return 1.0 if actions else 0.35
    if intent not in FACT_INTENTS:
        return 0.9 if not direct_answer else 0.75
    if not results:
        risks.append("missing_product_results")
        return 0.25
    if not sources:
        risks.append("missing_sources")
        return 0.55
    result_skus = _known_skus(results)
    mentioned = _extract_skus(answer)
    extra = mentioned - result_skus
    if extra:
        risks.append(f"answer_mentions_unreturned_sku:{','.join(sorted(extra))}")
        return 0.35
    if intent == "recommend_products" and _is_low_budget_query(question) and _is_high_price_row(results[0]):
        if any(term in answer for term in ("首选", "推荐", "适合")) and "不符合低预算" not in answer:
            risks.append("low_budget_high_end_first_choice")
            return 0.45
    if direct_answer:
        risks.append("direct_answer_for_product_fact")
        return 0.65
    return 1.0


def _score_tool_use(
    question: str,
    intent: str,
    sources: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    warnings: list[str],
    direct_answer: bool,
    tool_results: list[dict[str, Any]],
    risks: list[str],
) -> float:
    failed_tools = [item for item in tool_results if isinstance(item, dict) and item.get("ok") is False]
    if failed_tools:
        risks.append("tool_call_failed")
        return 0.45
    if warnings:
        return 0.75
    if direct_answer and any(term in question for term in PRODUCT_LOOKUP_TERMS):
        risks.append("tool_required_but_not_used")
        return 0.35
    if intent in WRITE_INTENTS:
        return 1.0 if actions else 0.3
    if intent in FACT_INTENTS:
        return 1.0 if sources else 0.5
    return 1.0


def _score_task_adherence(
    question: str,
    answer: str,
    intent: str,
    actions: list[dict[str, Any]],
    risks: list[str],
) -> float:
    score = 1.0
    if any(claim in answer for claim in DIRECT_WRITE_CLAIMS):
        risks.append("unsafe_direct_write_claim")
        score = 0.0
    if any(term in question for term in WRITE_TERMS):
        if intent in WRITE_INTENTS and actions and any(term in answer for term in ("待确认", "确认")):
            return score
        risks.append("write_request_without_confirmable_action")
        return min(score, 0.25)
    return score


def _score_context_handling(
    question: str,
    answer: str,
    results: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    needs_clarification: bool,
    risks: list[str],
) -> float:
    if not any(term in question for term in CONTEXT_TERMS):
        return 1.0
    if results or actions or needs_clarification:
        return 1.0
    if any(term in answer for term in CLARIFICATION_TERMS):
        return 0.85
    risks.append("context_reference_not_resolved")
    return 0.35


def _score_answer_hygiene(answer: str, intent: str, risks: list[str]) -> float:
    if not answer.strip():
        risks.append("empty_answer")
        return 0.0
    score = 1.0
    if any(mark in answer for mark in ("```", "**", "###")):
        risks.append("markdown_leaked")
        score -= 0.25
    if "Agent 执行过程" in answer:
        risks.append("debug_trace_leaked")
        score -= 0.35
    if len(answer) > 1800:
        risks.append("answer_too_long")
        score -= 0.15
    if intent == "recommend_products" and "找到" in answer and "条产品资料" in answer:
        if not any(term in answer for term in ("首选", "推荐", "理由", "适合")):
            risks.append("generic_recommendation_answer")
            score -= 0.35
    return max(0.0, score)


def _known_skus(rows: list[dict[str, Any]]) -> set[str]:
    skus = set()
    for row in rows:
        sku = str(row.get("sku") or "").upper()
        if sku:
            skus.add(sku)
    return skus


def _extract_skus(text: str) -> set[str]:
    return {match.upper() for match in SKU_RE.findall(str(text or ""))}


def _is_low_budget_query(question: str) -> bool:
    return any(term in str(question or "") for term in ("预算不高", "预算低", "便宜", "实惠", "性价比", "入门", "低预算", "省钱", "不要太贵"))


def _is_high_price_row(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("price_positioning", "positioning", "product_level", "features", "semantic_match")
    ).lower()
    return any(term in text for term in ("高端", "高价", "高预算", "旗舰", "专业级", "premium"))


def _quality_level(score: float, risks: list[str]) -> str:
    if _has_blocking_risk(risks) or score < 0.6:
        return "low"
    if score < 0.82 or risks:
        return "medium"
    return "high"


def _has_blocking_risk(risks: list[str]) -> bool:
    return any(
        risk.startswith("answer_mentions_unreturned_sku:")
        or risk in {
            "unsafe_direct_write_claim",
            "write_request_without_confirmable_action",
            "generic_recommendation_answer",
            "low_budget_high_end_first_choice",
        }
        for risk in risks
    )


def _recommendations(risks: list[str]) -> list[str]:
    mapping = {
        "missing_product_results": "产品事实类问题必须先拿到产品结果；没有结果时明确说明未找到并建议缩小范围。",
        "missing_sources": "返回产品事实时补充 sources，方便前端展示依据。",
        "direct_answer_for_product_fact": "产品事实不要直接由模型回答，应以工具结果为准。",
        "tool_required_but_not_used": "涉及产品事实、推荐、对比时强制走检索工具。",
        "tool_call_failed": "工具失败时降级回答并暴露可恢复提示。",
        "unsafe_direct_write_claim": "写操作只能生成待确认动作，不能承诺已经写库。",
        "write_request_without_confirmable_action": "写操作必须生成 action 卡片或澄清缺失 SKU/字段。",
        "context_reference_not_resolved": "遇到指代词时必须使用上一轮结果，或明确要求用户补充范围。",
        "empty_answer": "回答不能为空。",
        "markdown_leaked": "客服回答不要泄漏 Markdown 控制符。",
        "debug_trace_leaked": "不要把 Agent 调试过程暴露给用户。",
        "answer_too_long": "回答应先给结论，长内容拆成后续追问。",
        "generic_recommendation_answer": "推荐问题必须给首选和理由，不能只列数据库记录。",
        "low_budget_high_end_first_choice": "低预算问题不能把高端/高价定位产品作为首选；应优先选亲民/常规/性价比候选，或说明没有低预算匹配。",
    }
    recommendations = []
    for risk in risks:
        key = risk.split(":", 1)[0]
        item = mapping.get(key)
        if item:
            recommendations.append(item)
    return list(dict.fromkeys(recommendations))
