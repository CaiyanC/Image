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

TRAVEL_SAFETY_TERMS = ("飞机", "航班", "安检", "托运", "随身", "高铁", "火车", "地铁")
FLAMMABLE_PRODUCT_TERMS = ("酒精炉", "酒精", "燃料", "炉具", "气罐", "燃气", "CS-B14", "CS-B02")
REALTIME_WEATHER_TERMS = ("天气", "下雨", "降雨", "气温", "风力", "台风", "今天", "明天", "现在")
INTERNAL_BUSINESS_TERMS = ("成本价", "成本", "进价", "利润", "毛利", "底价", "采购价")
BUSINESS_SUPPORT_TERMS = ("退换货", "退货", "换货", "退换", "瑕疵", "破损", "坏了", "物流", "快递", "发货", "支付", "售后政策", "售后")
CREATIVE_REQUEST_TERMS = ("写游记", "露营游记", "写文章", "写一篇", "作文", "文案")
CASUAL_WEATHER_TERMS = ("天气真好", "今天天气真好", "适合出去玩吗", "出去玩吗")
PRODUCT_CONSULTATION_TERMS = (
    "推荐", "哪款", "哪种", "产品", "装备", "锅", "炉", "杯", "壶", "套装", "预算", "人数",
    "三个人", "四个人", "3人", "4人", "做饭", "煮咖啡", "泡咖啡", "露营装备", "轻便", "容量", "材质", "热源",
)


def evaluate_question(question: str) -> dict[str, Any] | None:
    """Return a deterministic enterprise guardrail response when needed."""
    text = str(question or "").strip()
    lowered = text.lower()
    if not text:
        return None

    if _contains_any(text, lowered, INTERNAL_BUSINESS_TERMS):
        return _build_guardrail_result(
            question=text,
            category="internal_business_data",
            intent="safety_refusal",
            answer_type="safety",
            confidence="high",
            uncertainty="permission_or_data_required",
            answer=(
                "成本价、进价、利润、底价属于内部经营数据，我不能直接对外披露或猜测。"
                "如果系统里没有明确授权字段，也不能把它当作普通客服资料返回。"
                "你可以提供具体 SKU 和已授权字段，我可以帮你整理成内部查询或审批口径。"
            ),
            followups=["请提供具体 SKU，或确认你要查询的是公开售价、价格定位还是内部授权成本字段。"],
            warnings=["internal_business_data_blocked"],
        )

    if _contains_any(text, lowered, BUSINESS_SUPPORT_TERMS):
        return _build_guardrail_result(
            question=text,
            category="business_support",
            intent="business_consultation",
            answer_type="business_policy",
            confidence="high",
            uncertainty="policy_or_order_required",
            answer=(
                "这属于售后/订单类业务咨询，不需要查询产品库。"
                "请根据店铺退换货政策、订单状态和实际凭证处理；如涉及瑕疵或破损，建议先收集照片、订单号和问题描述，再转人工或售后流程确认。"
            ),
            followups=["请补充订单号、购买渠道、问题照片和客户诉求，方便售后确认。"],
            warnings=["business_support_no_product_search"],
        )

    if _contains_any(text, lowered, CREATIVE_REQUEST_TERMS):
        return _build_guardrail_result(
            question=text,
            category="creative_or_chat",
            intent="chitchat",
            answer_type="out_of_scope",
            confidence="high",
            uncertainty="non_product_request",
            answer="这是写作/闲聊类请求，不需要调用产品检索。当前客服系统主要用于产品资料查询、推荐、对比和售后分流。",
            followups=["如果你要写具体产品的露营内容，请提供 SKU 或产品名，我可以基于产品资料整理卖点。"],
            warnings=["non_product_request_no_search"],
        )

    if _contains_any(text, lowered, CASUAL_WEATHER_TERMS) and _is_weather_only_question(text):
        return _build_guardrail_result(
            question=text,
            category="casual_weather_chat",
            intent="chitchat",
            answer_type="out_of_scope",
            confidence="high",
            uncertainty="external_realtime_data_required",
            answer="天气相关闲聊不需要调用产品检索；我当前也没有实时天气数据。是否适合出行请以天气 App 和当地预警为准。",
            followups=["如果你已经确认要出行，我可以按人数、场景和预算推荐露营装备。"],
            warnings=["casual_weather_no_product_search"],
        )

    if _contains_any(text, lowered, TRAVEL_SAFETY_TERMS) and _contains_any(text, lowered, FLAMMABLE_PRODUCT_TERMS):
        sku = _first_sku(text)
        prefix = f"{sku} " if sku else ""
        return _build_guardrail_result(
            question=text,
            category="travel_safety",
            intent="safety_refusal",
            answer_type="safety",
            confidence="high",
            uncertainty="external_policy_required",
            answer=(
                f"{prefix}这类炉具/燃料相关问题需要以航司、机场安检和当地法规为准，我无法替代航司或安检规定。"
                "稳妥口径是：不要携带酒精、燃料、气罐等易燃物；炉具本体也应在出行前彻底清空、清洁并向承运方确认。"
                "客服回复时不要承诺“可以带上飞机”，只能建议用户出发前咨询航司/机场安检。"
            ),
            followups=["如果你要对客户回复，我可以帮你整理一版更稳妥的客服话术。"],
            warnings=["external_travel_safety_policy_required"],
        )

    if _contains_any(text, lowered, REALTIME_WEATHER_TERMS) and not _has_product_consultation_intent(text):
        return _build_guardrail_result(
            question=text,
            category="realtime_weather",
            intent="out_of_scope",
            answer_type="unsupported_realtime",
            confidence="high",
            uncertainty="external_realtime_data_required",
            answer=(
                "我当前没有实时天气数据，不能判断今天或明天某个城市是否适合露营。"
                "建议以天气 App、气象台预警和营地公告为准。"
                "如果你已经确认天气，我可以继续按人数、场景和预算推荐露营装备。"
            ),
            followups=["你可以告诉我人数、目的地场景和预算，我帮你准备装备清单。"],
            warnings=["realtime_weather_unavailable"],
        )

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


def _has_product_consultation_intent(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if any(term in value for term in PRODUCT_CONSULTATION_TERMS):
        return True
    return bool(SKU_RE.search(value))


def _is_weather_only_question(text: str) -> bool:
    value = str(text or "")
    lowered = value.lower()
    if not _contains_any(value, lowered, REALTIME_WEATHER_TERMS + CASUAL_WEATHER_TERMS):
        return False
    return not _has_product_consultation_intent(value)


def _first_sku(text: str) -> str | None:
    match = SKU_RE.search(text or "")
    return match.group(0).upper() if match else None
