"""Versioned, auditable service rules. No product facts or live promises here.

Examples are prompt/rule training, not a fine-tuned model. Held-out evaluation
questions live separately in scripts/customer_service_plan_eval.py.
"""
from __future__ import annotations

import re
from typing import Any

POLICY_VERSION = "service-plan-20261008-v7"
TRAINING_EXAMPLES = (
    ("连接处漏气了，还要尝试点火吗？", "先停止使用，不要点火，远离火源并离开危险区域。请联系购买平台人工客服；有持续危险时联系当地应急服务。不要猜测故障原因。"),
    ("收到时支架坏了，下午就要带出门", "按紧急售后处理：先停止使用损坏商品，建议联系订单平台人工客服核实破损和出行时间；不承诺补发或赔付时间。"),
    ("能承诺后天收到吗？", "无法在没有实时库存和物流查询时保证到货，请以订单平台信息和人工核实为准。"),
    ("想买给房车旅行的两个人用", "区分两人适用人数与房车人群标签，以当前商品证据推荐；产品不明确时只问一个关键澄清问题。"),
    ("这个尺寸是包装还是展开尺寸？", "逐项核对尺寸范围，不把包装尺寸改说成展开尺寸；毛重也不能当净重。"),
    ("要求补偿损失", "补偿与争议处理需要授权人工决定，解释提交问题和订单渠道的下一步，不承诺金额或处理结论。"),
)


def classify(question: str, *, previous_question: str | None = None, product_context: bool = False, purchase_context: dict[str, Any] | None = None) -> dict[str, Any]:
    from .customer_purchase_urgency import analyze_purchase
    purchase = analyze_purchase(question, purchase_context)
    q = re.sub(r"\s+", "", str(question))
    # Negated or preventative mentions must not bypass the product RAG.
    risk = re.sub(r"(?:没有|不存在|未发生|避免|防止|预防|如何防止|如何避免)(?:发生)?(?:漏气|触电|起火|冒烟)", "", q)
    # Suppress only the how-to phrase. A separate report of smoke, gas odor,
    # or uncontrolled fire in the same message must still trigger triage.
    risk = re.sub(r"(?:怎么|怎样|如何)(?:就|才能)?让(?:这[款台个]?)?(?:它|他|酒精炉|炉子|炉具|酒精)烧起来(?:了)?", "", risk)
    kind = "general"
    elliptical_application = bool(re.fullmatch(r"(?:能|不能|可以|可不可以|不可以)?(?:申请|办理|安排)(?:一下|下)?(?:吗|么)?[？?]*", q))
    if previous_question and re.fullmatch(r"(?:那)?(?:现在|然后|接下来)?(?:怎么办|怎么处理|怎么做|还能用吗|能继续吗)[？?]*", q):
        prior = classify(previous_question)
        if prior['urgency'] == 'immediate':
            return {**prior, 'purchase': purchase, 'context_inherited': True}
    if re.search(r"账户被盗|账号被盗|盗刷|支付不是我|未经.*支付", risk):
        kind = "account_security"
    elif re.search(r"烫伤|烧伤|触电了|被电到|电击|(?:严重|剧烈)(?:头疼|头痛)|(?:头疼|头痛).*严重", risk):
        kind = "injury"
    elif re.search(r"起火了|烧起来|着火了|正在着火|冒烟|焦味|窜火|哄哄响.*不敢用|闻到.*(?:燃气|煤气|气体).*味|漏气了|正在漏气|一直嘶嘶", risk):
        kind = "safety"
    elif re.search(r"破损|损坏|(?:支架|炉架|炉子|锅|壶|商品|产品).{0,5}坏了|少了.*(?:件|配件)|缺件|缺少.*配件|严重投诉|强烈投诉", q):
        kind = "urgent_after_sales"
    elif re.search(r"赔偿|赔付|补偿|起诉|法律|保证.*退款|承诺.*退款", q):
        kind = "authorized_handoff"
    elif re.search(r"现在有货|库存|(?:今天|明天|后天).*(?:到|发货|发出|能发)|(?:什么时候|多久|几天|何时).*(?:发货|发出|到货|送到)|发货到哪|物流到哪|订单.*(?:物流|发货)|当前价格|实时价格", q):
        kind = "realtime"
    elif re.search(r"优惠|折扣|打折|批量报价|赠品", q):
        kind = "pricing_request"
    elif not product_context and (
        re.search(r"^(?:你好[，,]?|您好[，,]?)?(?:这款|这个|这套).*(?:固体酒精|液体酒精|气罐|配套.*炉|区别|对比)", q)
        or re.fullmatch(r"(?:电磁炉|卡式炉)(?:可以|能)(?:使用|用)吗[？?]*", q)
        or re.search(r"^酒精炉的?底座.*(?:其他锅|别的锅)", q)
    ):
        # No anchored SKU: candidate product retrieval must not turn a fuel /
        # heat-source compatibility question into an affirmative safety claim.
        kind = "ambiguous_product"
    elif re.search(r"怎么用|使用|清洁|清洗|退货|换货|兼容|漏气|点火", q):
        kind = "normal"
    elif elliptical_application:
        if previous_question and re.search(r"优惠|折扣|便宜|赠品|批量", previous_question):
            kind = "pricing_followup"
        elif not previous_question:
            kind = "ambiguous_request"
    urgency = "immediate" if kind in {"safety", "injury", "account_security"} else "urgent" if kind == "urgent_after_sales" else "normal" if kind in {"normal", "authorized_handoff", "realtime"} else "general"
    handoff = kind in {"safety", "injury", "account_security", "urgent_after_sales", "authorized_handoff", "realtime", "pricing_followup", "pricing_request"}
    return {
        "policy_version": POLICY_VERSION, "urgency": urgency, "question_kind": kind, "purchase": purchase,
        "handoff": {"required": handoff, "status": "recommended" if handoff else "not_required", "connected": False, "reason": kind if handoff else None, "followup_status": "pending" if handoff else "not_required"},
        "live_data_available": False if kind == "realtime" else None,
        "training_mode": "rules_and_prompt_examples", "human_approved": False,
    }


def safe_reply(triage: dict[str, Any], *, question: str = "") -> str | None:
    # Bounded wording changes only: do not invent product facts or live actions.
    q = str(question)
    if triage["question_kind"] in {"pricing_request", "pricing_followup"}:
        opening = "明白，您是想买得更划算些。"
        if "赠品" in q and re.search(r"赠品.*(?:没收到|没有|没见到)|结果没有.*失望", q):
            opening = "期待赠品却没有收到，确实容易失望。"
        elif re.search(r"预算.*(?:紧|有限)|太贵|贵了", q):
            opening = "预算有限，您希望买得更划算些，这个顾虑我明白。"
        elif triage["question_kind"] == "pricing_followup":
            opening = "可以向店铺人工提出申请，但需要对方按活动规则确认。"
        return opening + "您可以联系购买平台人工，询问当前优惠或赠品规则；已经下单的话，请对方核实订单是否符合活动条件。我不能保证折扣或赠品，也不能直接代办，这里尚未接通人工。"
    if triage["question_kind"] == "realtime":
        purchase = triage.get("purchase") or {}
        opening = "您着急用，我先帮您理清需要核实的安排。" if purchase.get("level") == "urgent" else ""
        topics = []
        if re.search(r"库存|有货|现货", q):
            topics.append("实时库存")
        if re.search(r"价格|价钱|多少钱", q):
            topics.append("实时价格")
        if re.search(r"订单|物流|发货|发出|能发|收到|到货|送达", q):
            topics.append("订单和物流进度")
        subject = "、".join(topics) or "实时库存、订单、价格和物流信息"
        boundary = "不能保证发货或到货时间" if "订单和物流进度" in topics else "不能确认是否有货" if "实时库存" in topics else "价格需要以平台当前信息为准"
        next_step = "您可以联系购买平台人工，说明最晚需用时间，请对方核实可行安排。" if purchase.get("level") == "urgent" else "您可以查看购买平台商品页或订单页的预计时效，再向平台人工核实。"
        if re.search(r"赠品|优惠|折扣|打折", q):
            next_step += "也请对方一并核实订单是否符合优惠或赠品活动；我不能直接代办或保证活动结果。"
        return opening + f"我这里查不到{subject}，{boundary}。" + next_step + "我这里无法直接接通人工。"
    return {
        "ambiguous_request": "您想申请的是哪件事呢？说明具体需求后，我可以帮您确认该怎么咨询。",
        "ambiguous_product": "咱们先确认一下，您说的是哪款商品或哪个型号呢？确认后我才能核对燃料、热源、配件兼容或商品区别，避免给您不适配的建议。",
        "safety": "请立即停止使用，不要继续点火或操作，远离火源并离开危险区域。您的安全最重要，不要冒险自行排查。若存在持续危险，请联系当地应急服务。安全后再联系购买平台人工客服处理；这里无法直接为您接通人工。",
        "injury": "请立即停止使用并远离危险设备，不要继续操作或尝试复现问题。先照顾好自己，有人受伤时请尽快寻求医疗帮助，情况严重请联系当地急救服务。安全后再联系购买平台人工客服处理，我无法在这里判断伤情或直接接通人工。",
        "account_security": "请立即停止可疑支付操作，不要提供密码或验证码；通过官方入口联系支付平台及账户平台人工客服，核实异常交易并保护账户。我无法查询账户或承诺追回款项，也无法在这里直接接通人工。",
        "urgent_after_sales": "遇到这样的问题确实影响使用，您希望尽快处理的心情我明白。商品损坏时请先停止使用；现在可以从购买平台订单页联系人工，提供问题照片，说明具体问题和急用时间，请对方优先核实处理方式。不需要在这里发送密码、支付信息或完整个人资料。我无法直接接通人工，也不能保证补发、退款或到货时间。",
        "authorized_handoff": "您希望把这件事妥善处理，这个诉求我明白。赔偿或退款结果需要购买平台授权人工核实，我不能保证退款结果或赔偿金额。您可以从订单页联系人工，说明具体问题和诉求；这里尚未接通人工，请以平台核实结果为准。",
    }.get(triage["question_kind"])


def training_prompt() -> str:
    from ..core.config import settings
    if not settings.CUSTOMER_SERVICE_PLAN_ENABLED:
        return ""
    return (
        f"\n服务分流规则版本：{POLICY_VERSION}。先判断立即/紧急/正常/一般四档紧急程度，再检查意图、商品、证据、下一步。"
        "实际危险优先安全行动和人工/应急处理，禁止故障猜测和促销。预防性提问或否定危险不是正在发生的事故。"
        "没有实时系统查询时不能确认库存、订单、价格、物流，不作到货或退款赔偿承诺。"
        "缺件破损及急用问题提供订单平台人工处理步骤。不能声称已转人工，除非系统实际确认接通。"
        "产品不明确只问一个关键问题；多轮追问承接当前意图，不把议价的‘申请一下’错当售后退款。"
        "商品身份尚未确认时，不能用检索候选商品的燃料、热源或配件信息直接回答兼容；先确认具体型号。"
        "以下仅为行为训练示例，不构成商品事实来源：\n"
        + "\n".join(f"客户：{q}\n应答原则：{a}" for q, a in TRAINING_EXAMPLES)
    )
