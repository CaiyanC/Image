import re
from typing import Any


SKU_RE = re.compile(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,4}\b", flags=re.IGNORECASE)

PROMPT_INJECTION_TERMS = (
    "忽略之前",
    "忽略以上",
    "无视之前",
    "系统提示词",
    "内部提示词",
    "developer message",
    "system prompt",
    "prompt injection",
    "越狱",
    "工具列表",
)
SECRET_TERMS = (
    "系统密钥",
    "数据库连接串",
    "连接串",
    "api key",
    "apikey",
    "secret",
    "token",
    "密码",
    "密钥",
)
HANDOFF_TERMS = (
    "人工客服",
    "转人工",
    "找人工",
    "真人客服",
    "人工处理",
    "找人处理",
    "投诉",
)
FABRICATION_TERMS = (
    "编一个",
    "编个",
    "瞎编",
    "猜一个",
    "随便给",
    "随便写",
    "估一个",
    "大概数字",
)
UNSUPPORTED_FACT_TERMS = (
    "库存",
    "现货",
    "最低价",
    "最低多少钱",
    "价格",
    "报价",
    "折扣",
    "认证",
    "质保",
    "售后政策",
)


def evaluate_question(question: str) -> dict[str, Any] | None:
    """Return a deterministic enterprise guardrail response when needed."""
    text = str(question or "").strip()
    lowered = text.lower()
    if not text:
        return None

    if _contains_any(text, lowered, HANDOFF_TERMS):
        return _build_guardrail_result(
            question=text,
            category="human_handoff",
            intent="human_handoff",
            answer_type="escalation",
            confidence="high",
            uncertainty="needs_human",
            answer=(
                "可以，我会把这个问题升级给人工客服处理。请补充你的具体诉求、相关 SKU 或订单/客户信息；"
                "在人工接手前，我不会继续猜测或替你做不可确认的承诺。"
            ),
            followups=["请补充相关 SKU、客户诉求和需要人工确认的点。"],
            warnings=["human_handoff_requested"],
        )

    if _contains_any(text, lowered, SECRET_TERMS) or _contains_any(text, lowered, PROMPT_INJECTION_TERMS):
        return _build_guardrail_result(
            question=text,
            category="security_refusal",
            intent="safety_refusal",
            answer_type="safety",
            confidence="high",
            uncertainty="policy_blocked",
            answer=(
                "抱歉，我不能提供系统提示词、工具清单、密钥、数据库连接串或其他内部敏感信息。"
                "我可以继续帮你查询、对比、推荐产品，或生成需要确认的产品资料修改建议。"
            ),
            followups=["请告诉我 SKU、产品类目、使用场景或需要查询的产品字段。"],
            warnings=["security_sensitive_request"],
        )

    if _contains_any(text, lowered, FABRICATION_TERMS) and _contains_any(text, lowered, UNSUPPORTED_FACT_TERMS):
        sku = _first_sku(text)
        prefix = f"{sku} " if sku else ""
        return _build_guardrail_result(
            question=text,
            category="anti_fabrication",
            intent="safety_refusal",
            answer_type="safety",
            confidence="high",
            uncertainty="not_recorded",
            answer=(
                f"{prefix}不能编造库存、价格、认证、质保或售后政策。"
                "如果产品库没有记录，我只能说明“资料未标注/不能确认”，并建议联系仓库、销售或负责人确认真实数据。"
            ),
            followups=["请提供真实库存、价格或负责人确认后的口径，我可以再帮你整理成客服回复。"],
            warnings=["fabrication_request_blocked"],
        )

    return None


def _build_guardrail_result(
    *,
    question: str,
    category: str,
    intent: str,
    answer_type: str,
    confidence: str,
    uncertainty: str,
    answer: str,
    followups: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    step = {
        "type": "enterprise_guardrail",
        "label": "企业级客服护栏",
        "detail": f"命中 {category}，未进入普通产品检索或写库流程。",
        "ok": True,
    }
    return {
        "answer": answer,
        "intent": intent,
        "answer_type": answer_type,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "needs_clarification": False,
        "anomalies": [],
        "suggested_followups": followups,
        "followups": followups,
        "evidence": [],
        "debug": {
            "agent_mode": "enterprise_guardrail",
            "intent": intent,
            "guardrail_category": category,
            "question": question,
            "steps": [step],
            "warnings": warnings,
            "anomalies": [],
            "raw_results": [],
            "tool_results": [],
        },
        "sku": _first_sku(question),
        "sources": [{"type": "enterprise_guardrail", "label": "企业级客服护栏", "category": category}],
        "actions": [],
        "results": [],
        "steps": [step],
        "warnings": warnings,
        "skip_polish": True,
    }


def _contains_any(text: str, lowered: str, terms: tuple[str, ...]) -> bool:
    return any((term.lower() in lowered) if term.isascii() else (term in text) for term in terms)


def _first_sku(text: str) -> str | None:
    match = SKU_RE.search(text or "")
    return match.group(0).upper() if match else None
