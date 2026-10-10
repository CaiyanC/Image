"""Customer-stated buying urgency, separate from safety and product facts."""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

purchase_turn_context: ContextVar[dict[str, Any] | None] = ContextVar("purchase_turn_context", default=None)
_LEVELS = {"urgent", "planned", "browsing", "unknown"}
_STAGES = {"inquiry", "intending", "ordered", "paused"}
_TIME = r"(?:今天|明天|后天|今晚|明早|周[一二三四五六日天]|周末|下周|\d{1,2}[月日号]|\d{1,2}点)"
_DEADLINE = re.compile(
    _TIME + r"[^，。！？?]{0,16}(?:务必|必须|就要|需要|要用|急用|出发|出行|出门|露营|赶上|得用)"
    + r"|(?:最晚|必须|务必)[^，。！？?]{0,16}" + _TIME
    + r"|" + _TIME + r"(?:前|之前)[^，。！？?]{0,12}(?:收到|到货|送到|用|到)"
)
_LOW = re.compile(r"不(?:太)?(?:着急|急)|先(?:了解|问问|看看)|只是(?:了解|问问|来问)|随便看看|暂时不(?:买|需要)|先不买")
_RESET = re.compile(r"换个话题|重新开始|不说这个|另一笔订单|另一个订单")


def analyze_purchase(question: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    q = re.sub(r"\s+", "", str(question))
    prior = previous if isinstance(previous, dict) else {}
    if _RESET.search(q):
        prior = {}
    level = prior.get("level") if prior.get("level") in _LEVELS else "unknown"
    stage = prior.get("stage") if prior.get("stage") in _STAGES else "inquiry"
    deadline = str(prior.get("deadline_expression") or "")[:80]
    inherited = bool(prior and (level != "unknown" or deadline))
    # Asking today's shipping time isn't itself a requirement to ship today.
    nonurgent_removed = re.sub(r"不(?:太)?(?:着急|急)", "", q)
    deadline_match = _DEADLINE.search(q)
    urgent = bool(deadline_match or re.search(r"急用|急着(?:买|用)|比较着急|很着急|急死了|很急|赶时间|来不及|等不及|(?:务必|必须).{0,10}(?:发出|发货|送到|收到)", nonurgent_removed))
    ordered = bool(re.search(r"(?:我)?(?:应该是)?(?:已经|已|刚)(?:支付|付款|下单|买了)|订单.*(?:付过|付款|支付)|收到(?:货|商品)|收货", q))
    intending = bool(re.search(r"想买|要买|准备买|打算买|我就买|我(?:想|要|需要).{0,8}(?:套|个|件|款)|购买\d|买\d|买[一二两三四五六七八九十]|购买链接", q))
    if ordered:
        stage = "ordered"
    elif intending:
        stage = "intending"
    if urgent:
        level, inherited = "urgent", False
        if deadline_match:
            deadline = deadline_match.group(0)[:80]
    elif _LOW.search(q):
        level, deadline, inherited = "browsing", "", False
        if re.search(r"暂时不买|先不买", q):
            stage = "paused"
    elif intending and level not in {"urgent"}:
        level, inherited = "planned", False
    return {
        "version": "purchase-urgency-20261008-v1", "level": level, "stage": stage,
        "deadline_expression": deadline, "inherited": inherited,
        "basis": "customer_stated_or_prior_customer_context" if level != "unknown" else "insufficient_explicit_signal",
        "live_status_verified": False,
    }


def purchase_reply_guidance() -> str:
    state = purchase_turn_context.get()
    if not state:
        return ""
    # Only validated labels enter the system prompt, never quoted user text.
    level = state.get("level") if state.get("level") in _LEVELS else "unknown"
    stage = state.get("stage") if state.get("stage") in _STAGES else "inquiry"
    return (
        f"\n本轮购买处境：紧迫程度={level}，阶段={stage}。这只是客户自述需求，不是订单核实结果。"
        "urgent时先回应急用目标，回答当前最关键问题和可行的核实渠道，不先促销或罗列参数；"
        "期限仅可引用客户原话，不能当成已确认发货/到货日期。"
        "planned时帮助比较、配置和选择，不因购买数量多就说着急；"
        "browsing时按当前问题简短解答，不催单，也不要每轮追问预算和时间；"
        "unknown表示尚无明确急用/只是了解的证据，不可猜测；仅涉及发货到货选择且缺少关键期限时，最多问一次最晚需用时间。"
        "已付款仅是客户说已付款，不得声称查到订单；礼貌收尾或话题结束时不要强行续聊。"
    )
