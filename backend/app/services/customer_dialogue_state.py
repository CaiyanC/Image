from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


CONTEXT_REFERENCES = ("这些", "刚才那些", "上面这些", "刚才的", "上一轮", "前面", "这几个", "这几款", "这款", "这个", "那个", "他", "他的", "她", "她的", "它", "它的", "他们", "它们", "其中")
PRONOUN_CONTEXT_REFERENCES = ("他", "他的", "她", "她的", "它", "它的", "他们", "她们", "它们")
NON_CONTEXT_REFERENCE_TERMS = ("其他", "其它", "其他的", "其它的")
LOW_BUDGET_TERMS = ("预算不高", "预算低", "便宜", "实惠", "性价比", "入门", "低预算", "省钱", "不要太贵")
HIGH_PRICE_TERMS = ("高端", "高价", "高预算", "旗舰", "专业级", "premium", "Premium")
VALUE_PRICE_TERMS = ("入门", "亲民", "经济", "实惠", "低价", "基础", "性价比", "常规")
FOLLOWUP_PREFIXES = ("那", "如果", "那么", "还有", "另外", "继续", "改成", "换成", "再", "那如果")
AUDIENCE_TERMS = (
    "单人", "双人", "两人", "三人", "四人", "几人", "年轻人", "家庭", "朋友", "情侣", "送礼", "徒步", "露营",
    "野餐", "自驾", "房车", "背包客", "轻量", "速穿", "户外", "宝宝", "新手", "办公室", "家用",
)
SCENE_TERMS = (
    "露营", "徒步", "野餐", "送礼", "自驾", "房车", "泡咖啡", "做饭", "煮饭", "炒菜", "煎", "烤", "炖",
    "家庭", "营地", "户外", "旅行", "登山", "野宿", "便携",
)
PRODUCT_TYPE_TERMS = (
    "锅", "套锅", "单锅", "煎锅", "炒锅", "烤盘", "水壶", "炉", "炉具", "餐具", "杯", "壶", "锅具",
    "装备", "产品", "物料",
)
RECOMMENDATION_TERMS = ("推荐", "适合", "哪款", "哪种", "哪个", "选哪", "选哪个", "有什么")
EXPLICIT_REF_TERMS = CONTEXT_REFERENCES + ("刚才", "上轮", "上一条")
FIELD_FOLLOWUP_TERMS = (
    "容量", "材质", "卖点", "价格", "适合", "好不好", "条形码", "条码", "尺寸", "规格",
    "上架平台", "平台", "售卖地区", "销售地区", "地区", "关键词", "关键词库", "负责人",
)
CONFIRMATION_TERMS = ("是的", "对", "对的", "确认", "嗯", "可以", "没错")
SKU_RE = re.compile(r"\b[A-Za-z]{1,6}[-_][A-Za-z0-9][A-Za-z0-9_-]{1,40}\b")


@dataclass(slots=True)
class DialogueState:
    mode: str
    question: str
    previous_user_need: str
    combined_user_need: str
    summary: str
    product_scope: str
    scene: str
    audience: str
    budget: str
    quantity: str
    comparison_target: str
    has_explicit_sku: bool
    requires_previous_result_skus: bool
    should_inherit_user_need: bool
    is_budget_followup: bool
    is_context_followup: bool
    is_complete_new_need: bool
    confidence: str
    needs_clarification: bool
    clarification_reason: str
    missing_slots: list[str]
    slots: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_dialogue_state(question: str, conversation_history: list[dict] | None = None) -> DialogueState:
    text = _normalize(question)
    history = conversation_history or []
    previous_user_need = _latest_contextual_user_need(text, history)
    has_explicit_sku = bool(SKU_RE.search(text))
    requires_previous_result_skus = _should_use_previous_result_skus(text)
    is_budget_followup = _is_budget_followup(text)
    is_context_followup = _should_inherit_user_need(text)
    is_complete_new_need = _looks_like_complete_new_need(text)
    slots = _extract_slots(text)
    mode = _decide_mode(text, slots, previous_user_need, is_budget_followup, is_context_followup, is_complete_new_need, has_explicit_sku)
    combined_user_need = _combine_user_need(previous_user_need, text, mode)
    summary = _build_summary(slots, combined_user_need)
    confidence, needs_clarification, clarification_reason, missing_slots = _assess_clarity(
        text,
        mode,
        slots,
        previous_user_need,
        has_explicit_sku,
        requires_previous_result_skus,
    )
    return DialogueState(
        mode=mode,
        question=text,
        previous_user_need=previous_user_need,
        combined_user_need=combined_user_need,
        summary=summary,
        product_scope=slots["product_scope"],
        scene=slots["scene"],
        audience=slots["audience"],
        budget=slots["budget"],
        quantity=slots["quantity"],
        comparison_target=slots["comparison_target"],
        has_explicit_sku=has_explicit_sku,
        requires_previous_result_skus=requires_previous_result_skus,
        should_inherit_user_need=bool(previous_user_need) and (is_budget_followup or is_context_followup),
        is_budget_followup=is_budget_followup,
        is_context_followup=is_context_followup,
        is_complete_new_need=is_complete_new_need,
        confidence=confidence,
        needs_clarification=needs_clarification,
        clarification_reason=clarification_reason,
        missing_slots=missing_slots,
        slots=slots,
    )


def build_conversation_context(question: str, conversation_history: list[dict] | None = None) -> dict[str, Any]:
    state = build_dialogue_state(question, conversation_history)
    if state.mode == "budget_followup":
        instruction = "本轮是预算/性价比追问，继承上一轮场景、人群和用途，并重新按价格定位筛选。"
    elif state.mode == "context_followup":
        instruction = "本轮是短追问或补充条件，继承上一轮用户需求；若当前问题已给出新场景，则以当前问题为准。"
    else:
        instruction = "本轮问题信息较完整，优先按当前问题重新检索和回答；历史只作背景参考。"
    return {
        "mode": state.mode,
        "previous_user_need": state.previous_user_need,
        "combined_user_need": state.combined_user_need,
        "instruction": instruction,
        "summary": state.summary,
        "slots": state.slots,
        "requires_previous_result_skus": state.requires_previous_result_skus,
        "confidence": state.confidence,
        "needs_clarification": state.needs_clarification,
        "clarification_reason": state.clarification_reason,
        "missing_slots": state.missing_slots,
    }


def should_use_previous_result_skus(question: str) -> bool:
    return _should_use_previous_result_skus(question)


def needs_previous_context(question: str) -> bool:
    return _has_context_reference(_normalize(question), include_broad_terms=True)


def is_budget_followup(question: str) -> bool:
    return _is_budget_followup(question)


def is_low_budget_query(question: str) -> bool:
    text = _normalize(question)
    return any(term in text for term in LOW_BUDGET_TERMS)


def recommendation_question_with_context(question: str, conversation_history: list[dict] | None = None) -> str:
    text = _normalize(question)
    if not is_budget_followup(text):
        return text
    history = conversation_history or []
    previous_user_turns = [
        _normalize(item.get("content") or "")
        for item in history
        if item.get("role") == "user" and _normalize(item.get("content") or "")
    ]
    for previous in reversed(previous_user_turns[-4:]):
        if previous == text:
            continue
        if any(word in previous for word in RECOMMENDATION_TERMS + SCENE_TERMS):
            return f"{previous}；追加条件：{text}"
    return text


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _should_use_previous_result_skus(question: str) -> bool:
    text = _normalize(question)
    if text.strip(" ，。！？?") in CONFIRMATION_TERMS:
        return True
    has_reference = _has_context_reference(text)
    if _looks_like_complete_new_need(text) and not has_reference:
        return False
    if has_reference:
        return True
    if len(text) <= 16 and any(item in text for item in FIELD_FOLLOWUP_TERMS):
        return True
    return False


def _should_inherit_user_need(question: str) -> bool:
    text = _normalize(question)
    if not text or _looks_like_complete_new_need(text):
        return False
    if _is_budget_followup(text) or _should_use_previous_result_skus(text):
        return True
    if text.startswith(FOLLOWUP_PREFIXES) and len(text) <= 36:
        return True
    if len(text) <= 18 and any(word in text for word in ("推荐", "适合", "哪种", "哪款", "怎么样", "容量", "材质", "价格")):
        return True
    return False


def _is_budget_followup(question: str) -> bool:
    text = _normalize(question)
    if not _is_low_budget_query(text) or _looks_like_complete_new_need(text):
        return False
    if _extract_product_scope(text) and (_extract_quantity(text) or _extract_scene(text) or _extract_audience(text)):
        return False
    return not any(word in text for word in SCENE_TERMS + AUDIENCE_TERMS)


def _is_low_budget_query(question: str) -> bool:
    text = _normalize(question)
    return any(term in text for term in LOW_BUDGET_TERMS)


def _looks_like_complete_new_need(text: str) -> bool:
    has_audience = any(word in text for word in AUDIENCE_TERMS) or bool(re.search(r"\d+\s*人", text))
    has_scene = any(word in text for word in SCENE_TERMS)
    has_product_type = any(word in text for word in PRODUCT_TYPE_TERMS)
    has_action = any(word in text for word in RECOMMENDATION_TERMS)
    return has_action and has_product_type and (has_audience or has_scene)


def _latest_contextual_user_need(question: str, conversation_history: list[dict]) -> str:
    if not conversation_history or not (_is_budget_followup(question) or _should_inherit_user_need(question)):
        return ""
    previous_user_turns = [
        _normalize(item.get("content") or "")
        for item in conversation_history
        if item.get("role") == "user" and _normalize(item.get("content") or "")
    ]
    for previous in reversed(previous_user_turns[-6:]):
        if previous == _normalize(question):
            continue
        if _looks_like_user_need(previous):
            return previous
    return ""


def _looks_like_user_need(text: str) -> bool:
    return any(word in _normalize(text) for word in ("推荐", "适合", "露营", "做饭", "泡咖啡", "送礼", "徒步", "预算", "几人", "三人", "两人"))


def _extract_slots(text: str) -> dict[str, str]:
    quantity = _extract_quantity(text)
    budget = _extract_budget(text)
    scene = _extract_scene(text)
    audience = _extract_audience(text)
    product_scope = _extract_product_scope(text)
    comparison_target = _extract_comparison_target(text)
    return {
        "quantity": quantity,
        "budget": budget,
        "scene": scene,
        "audience": audience,
        "product_scope": product_scope,
        "comparison_target": comparison_target,
    }


def _has_context_reference(text: str, *, include_broad_terms: bool = False) -> bool:
    cleaned = _normalize(text)
    for term in NON_CONTEXT_REFERENCE_TERMS:
        cleaned = cleaned.replace(term, "")
    references = EXPLICIT_REF_TERMS if include_broad_terms else CONTEXT_REFERENCES
    phrase_references = tuple(ref for ref in references if ref not in PRONOUN_CONTEXT_REFERENCES)
    return any(ref in cleaned for ref in phrase_references) or any(ref in cleaned for ref in PRONOUN_CONTEXT_REFERENCES)


def _extract_quantity(text: str) -> str:
    match = re.search(r"(\d+\s*-\s*\d+\s*人|\d+\s*个人?|\d+\s*人|单人|双人|两人|三人|四人|五人|几人|一个人|两个人|三个人|四个人|五个人)", text)
    if not match:
        return ""
    value = _normalize(match.group(1))
    value = value.replace("个人", "人")
    return value


def _extract_budget(text: str) -> str:
    lowered = text.lower()
    if any(term in text for term in LOW_BUDGET_TERMS):
        return "low"
    if any(term.lower() in lowered for term in HIGH_PRICE_TERMS):
        return "high"
    if any(term in text for term in VALUE_PRICE_TERMS):
        return "value"
    return ""


def _extract_scene(text: str) -> str:
    for term in ("露营", "徒步", "野餐", "送礼", "自驾", "房车", "泡咖啡", "做饭", "煮饭", "炒菜", "煎", "烤", "炖", "旅行", "户外"):
        if term in text:
            return term
    return ""


def _extract_audience(text: str) -> str:
    for term in ("年轻人", "家庭", "朋友", "情侣", "送礼", "徒步者", "背包客", "新手", "办公室", "户外", "露营", "野餐"):
        if term in text:
            return term
    return ""


def _extract_product_scope(text: str) -> str:
    for term in ("套锅", "单锅", "煎锅", "炒锅", "烤盘", "水壶", "锅具", "炉具", "锅", "壶", "杯"):
        if term in text:
            return term
    return ""


def _extract_comparison_target(text: str) -> str:
    if any(term in text for term in ("对比", "比较", "哪个更好", "哪款更好", "区别")):
        return "comparison"
    return ""


def _decide_mode(
    question: str,
    slots: dict[str, str],
    previous_user_need: str,
    is_budget_followup: bool,
    is_context_followup: bool,
    is_complete_new_need: bool,
    has_explicit_sku: bool,
) -> str:
    if has_explicit_sku and any(word in question for word in ("容量", "材质", "参数", "详情", "是什么", "多少")):
        return "product_detail"
    if is_complete_new_need:
        return "current_question"
    if is_budget_followup and previous_user_need:
        return "budget_followup"
    if is_context_followup and previous_user_need:
        return "context_followup"
    if slots["comparison_target"]:
        return "comparison_followup"
    if previous_user_need and _should_inherit_user_need(question):
        return "context_followup"
    return "current_question"


def _combine_user_need(previous_user_need: str, question: str, mode: str) -> str:
    if not previous_user_need:
        return question
    if mode in {"budget_followup", "context_followup"}:
        return f"{previous_user_need}；追加条件：{question}"
    return question


def _build_summary(slots: dict[str, str], combined_user_need: str) -> str:
    parts = []
    if slots.get("quantity"):
        parts.append(f"人数={slots['quantity']}")
    if slots.get("scene"):
        parts.append(f"场景={slots['scene']}")
    if slots.get("audience"):
        parts.append(f"人群={slots['audience']}")
    if slots.get("product_scope"):
        parts.append(f"品类={slots['product_scope']}")
    if slots.get("budget"):
        parts.append(f"预算={slots['budget']}")
    if slots.get("comparison_target"):
        parts.append("对比=是")
    if not parts:
        return combined_user_need
    return "；".join(parts)


def _assess_clarity(
    question: str,
    mode: str,
    slots: dict[str, str],
    previous_user_need: str,
    has_explicit_sku: bool,
    requires_previous_result_skus: bool,
) -> tuple[str, bool, str, list[str]]:
    text = _normalize(question)
    if not text:
        return "low", True, "empty_question", ["question"]
    if mode in {"product_detail", "budget_followup", "context_followup"}:
        return "high", False, "", []
    if requires_previous_result_skus and not previous_user_need and not has_explicit_sku:
        return "medium", False, "requires_previous_result_skus", []
    has_product_or_context = bool(
        has_explicit_sku
        or slots.get("product_scope")
        or slots.get("scene")
        or slots.get("audience")
        or slots.get("quantity")
        or slots.get("comparison_target")
    )
    if has_product_or_context:
        return "high", False, "", []
    if any(word in text for word in RECOMMENDATION_TERMS + FIELD_FOLLOWUP_TERMS + LOW_BUDGET_TERMS):
        return "low", True, "missing_product_scope", ["product_scope"]
    return "medium", False, "", []
