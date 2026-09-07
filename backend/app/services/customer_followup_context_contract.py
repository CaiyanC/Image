"""Bounded purchase-context carryover, not an intent router or catalogue engine.

Only a replacement request with a confirmed product/task inherits constraints.
Product facts come from live records; history contributes at most one user turn.
No database, model calls, SKU lists, or raw category equality in this module.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any


_FORMS = {
    "kettle": r"水壶|烧水壶|茶壶|\bkettle\b",
    "cup": r"水杯|茶杯|咖啡杯|马克杯|杯(?=\s|Pro|$)|\b(?:mug|cup)\b",
    "stove": r"酒精炉|燃气炉|卡式炉|炉具|炉芯|\b(?:stove|burner)\b",
}
_LABELS = {"kettle": "烧水壶", "cup": "饮水杯", "stove": "炉具"}
_VOLUME = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(毫升|ml|升|l)(?![a-z])", re.I)
_REPLACE = re.compile(r"推荐|替代|替换|换(?:一|另)?(?:款|个)|换一款|换成|换款|别的|其他(?:款|选择)|再来一款|找(?:一)?个|找一款|改买|改要|有没有.{0,14}(?:在售|供货|现货|便宜|相近|类似|差不多)")
_FACT_QUESTION = re.compile(r"什么材质|材质是什么|是什么材质|重量(?:是)?多少|容量(?:是)?(?:多少|多大)|什么颜色|颜色是什么|怎么(?:用|洗|安装)|如何(?:使用|清洗)|什么燃料|能用.{0,15}吗")
_RESET = re.compile(r"换个(?:话题|问题)|不说这个|重新开始|不买了|先不买|不要推荐|不用推荐")
_SUPPLY = re.compile(r"供货|在售|现货|停产|停售|无货|买得到|能买到")
_REGULAR = {"常规品", "正常供货", "在售", "正常销售"}
_UNAVAILABLE = {"老款无货不补", "停产", "停售", "已停售", "已停产", "清仓品", "未上市新品"}
# Conservative recall/acceptance policy for an unspecified "similar" capacity,
# not a numeric range attributed to the customer. Explicit units are normalized.
_NEAR_RELATIVE_TOLERANCE = 0.20


def _negated(prefix: str) -> bool:
    """Nearest explicit polarity wins (e.g. 不要1.4L，改要2L)."""
    markers = list(re.finditer(r"不要|不买|别|不想|改要|改买|改成|换成|推荐|要|找个|找一款", prefix))
    return bool(markers and markers[-1].group() in {"不要", "不买", "别", "不想"})


def _positive_clauses(question: str) -> list[str]:
    return [part.strip() for part in re.split(r"[，。；！？]|但是|还是", question)
            if part.strip() and not re.match(r"^(?:请)?(?:不要|不买|别|不想)", part.strip())]


def _task_hint(question: str, sku: str = "") -> str:
    # The original question remains provenance; identity/capacity are carried
    # separately so an old SKU or number cannot compete with an updated value.
    text = question.replace(sku, "") if sku else question
    return _VOLUME.sub("", text)[:180]


def _form(text: str) -> str:
    for form, pattern in _FORMS.items():
        if re.search(pattern, text, re.I):
            return form
    return ""


def product_form(product: dict[str, Any]) -> str:
    # Identity, never copied usage steps or compatibility/marketing neighbours.
    return _form(" ".join(str(product.get(k) or "") for k in (
        "product_name_cn", "product_name_en", "sub_category",
    )))


def volumes_ml(text: str) -> list[float]:
    return [round(float(n) * (1000 if unit.lower() in {"l", "升"} else 1), 6)
            for n, unit in _VOLUME.findall(text)
            if 0 < float(n) < 1000000]


def product_capacities_ml(product: dict[str, Any], form: str) -> list[float]:
    """Compare the same vessel, never burner fuel or aggregate kit capacity."""
    if product_form(product) != form:
        return []
    values = (product.get("specs") or {}).get("capacity") or []
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except (ValueError, TypeError):
            return []
    result = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("label") or "") + str(item.get("value") or "")
        if re.search(r"炉芯|燃料|酒精|合计|总容量|整套", scope):
            continue
        explicit_form = _form(scope)
        label = str(item.get("label") or "").strip()
        if label in {"壶", "主壶", "壶容量"}:
            explicit_form = "kettle"
        if label and not explicit_form:
            continue
        if explicit_form and explicit_form != form:
            continue
        if form not in {"kettle", "cup"}:
            continue
        # An unlabelled number in a multi-component kit is not vessel capacity.
        if not explicit_form and (len(values) != 1 or re.search(
            r"套装|套锅|组合|[+＋]|水壶.*炉|炉.*水壶", str(product.get("product_name_cn") or ""))):
            continue
        result.extend(volumes_ml(scope + " " + str(item.get("unit") or "")))
    return sorted(set(result))


def normalize_purchase_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        return {}
    form = value.get("form")
    if form not in {*_FORMS, "other"}:
        return {}
    capacity = value.get("capacity_ml")
    if isinstance(capacity, bool) or not isinstance(capacity, (int, float)) or not math.isfinite(capacity) or capacity <= 0:
        capacity = None
    relation = value.get("capacity_relation", "near")
    if relation not in {"near", "larger", "smaller", "different", "any"}:
        relation = "near"
    return {
        "version": 1, "form": form, "capacity_ml": capacity,
        "capacity_relation": relation,
        "subject_label": str(value.get("subject_label") or "")[:160],
        "require_regular": value.get("require_regular") is True,
        "anchor_sku": str(value.get("anchor_sku") or "")[:100],
        "use": str(value.get("use") or "")[:180],
        "source_question": str(value.get("source_question") or "")[:400],
    }


def seed_purchase_context(question: str, product: dict[str, Any]) -> dict[str, Any]:
    # A confirmed single-product fact is also a valid future comparison
    # reference. This does not activate recommendation checks on that turn.
    if _RESET.search(question):
        return {}
    if not product.get("sku") or not product.get("product_name_cn"):
        return {}
    form = product_form(product) or "other"
    capacities = product_capacities_ml(product, form)
    return normalize_purchase_context({
        "version": 1, "form": form,
        "subject_label": product.get("product_name_cn"),
        "capacity_ml": capacities[0] if len(capacities) == 1 else None,
        "anchor_sku": product.get("sku"), "source_question": question,
        "use": _task_hint(question, str(product.get("sku") or "")),
        "require_regular": bool(_SUPPLY.search(question)) or
            product.get("lifecycle_status") in _UNAVAILABLE,
    })


def prepare_followup_context(
    question: str, *, previous: Any, anchor_product: dict[str, Any] | None,
    last_user_question: str = "", current_product: dict[str, Any] | None = None,
    has_current_subject: bool = False,
) -> tuple[dict[str, Any], bool, bool]:
    """Return (persistent task, apply on this turn, drop old identity context).

    Exact current product facts always take precedence. Replacement language
    alone cannot create a task from unrelated search candidates.
    """
    if _RESET.search(question):
        return {}, False, True
    # Explicit product/name questions are not implicitly replacement requests.
    reset_identity = False
    if has_current_subject:
        seeded = seed_purchase_context(question, current_product or {})
        old = normalize_purchase_context(previous)
        if _FACT_QUESTION.search(question) or not _REPLACE.search(question):
            if old and (current_product or {}).get("sku") == old.get("anchor_sku"):
                return old, False, False
            return seeded, False, True
        context = seeded
        reset_identity = True
    else:
        context = normalize_purchase_context(previous)
    # None means an old record without this field. {} is an explicit clear.
    if not context and previous is None and anchor_product and not has_current_subject:
        context = seed_purchase_context(last_user_question, anchor_product)
    if not context:
        return {}, False, False
    positive = _positive_clauses(question)
    changes = [m for part in positive for m in re.finditer(
        r"(?:改(?:成|要|买)|现在(?:想买|要)|换成)\s*([^，。；！？]{1,50})", part)
        if not _negated(part[:m.start()])]
    changed_form = _form(changes[-1].group(1)) if changes else ""
    if changed_form and changed_form != context["form"]:
        # Explicit form change releases old use, vessel volume and anchor.
        context = normalize_purchase_context({
            "version": 1, "form": changed_form, "capacity_ml": None,
            "subject_label": _LABELS[changed_form],
            "source_question": question, "use": _task_hint("；".join(positive)),
            "require_regular": bool(_SUPPLY.search(question)),
        })
        # Apply any new numeric volume below, without inheriting the old one.
        reset_identity = True
    elif re.search(r"(?:不要|不买).{0,6}(?:水壶|茶壶|水杯|炉具|酒精炉).{0,3}(?:了|，|。|$)", question) and not any(_form(p) for p in positive):
        return {}, False, True
    applies = bool(_REPLACE.search(question) or re.search(
        r"(?:容量|大小).{0,8}(?:差不多|相近|一样)|便宜一点|便宜点|要更[大小]|比它[大小]|不要一样容量", question))
    context = dict(context)
    requested_volumes = []
    for clause in re.split(r"[，。；！？]", question):
        for match in _VOLUME.finditer(clause):
            if not _negated(clause[:match.start()]):
                requested_volumes.extend(volumes_ml(match.group()))
    if re.search(r"容量(?:不限|无所谓|不要求|随意)|不(?:限|要求|考虑)容量", question):
        context["capacity_ml"] = None
        context["capacity_relation"] = "any"
    elif len(requested_volumes) == 1:
        context["capacity_ml"] = requested_volumes[0]
        context["capacity_relation"] = "near"
    elif re.search(r"更大|大一些|大一点|大点|比它大", question):
        context["capacity_relation"] = "larger"
    elif re.search(r"更小|小一些|小一点|小点|比它小", question):
        context["capacity_relation"] = "smaller"
    elif "不要一样容量" in question:
        context["capacity_relation"] = "different"
    # A changed use is a replacement of the free task hint, not an additive
    # concatenation of contradictory historical and current requirements.
    if any(re.search(r"(?:改|现在|不再|这次).{0,30}(?:用|场景|用途)", p) for p in positive):
        context["use"] = _task_hint("；".join(positive))
    context["require_regular"] |= bool(_SUPPLY.search(question))
    return context, applies, reset_identity


def retrieval_query(question: str, context: dict[str, Any]) -> str:
    capacity = context.get("capacity_ml")
    relation = {"near": "接近", "larger": "大于", "smaller": "小于", "different": "不同于", "any": "不限，参照"}[context.get("capacity_relation", "near")]
    volume = f" 壶内饮水容量{relation}{capacity / 1000:g}L ({capacity:g}ml)" if capacity and context["form"] == "kettle" else (
        f" 饮水容量{relation}{capacity:g}ml" if capacity else "")
    # Exactly one source task, never the whole history or an old answer's facts.
    use = context.get("use", "")[:180]
    if context.get("anchor_sku"):
        use = use.replace(context["anchor_sku"], "")
    subject = _LABELS.get(context["form"], context.get("subject_label") or "同用途商品")
    return (f"{question[:400]}\n当前购买需求：{subject}{volume}；"
            f"任务语境提示：{use}；"
            + ("生命周期常规品；库存需另行确认。" if context.get("require_regular") else ""))


def candidate_issues(product: dict[str, Any], context: dict[str, Any]) -> list[str]:
    issues = []
    if context["form"] != "other" and product_form(product) != context["form"]:
        issues.append("product_form_mismatch")
    capacity = context.get("capacity_ml")
    relation = context.get("capacity_relation", "near")
    if capacity and relation != "any":
        values = product_capacities_ml(product, context["form"])
        if not values:
            issues.append("vessel_capacity_unverified")
        elif not any({
            "near": abs(v - capacity) <= capacity * _NEAR_RELATIVE_TOLERANCE + 1e-6,
            "larger": v > capacity, "smaller": v < capacity,
            "different": abs(v - capacity) > 1e-6,
        }.get(relation, False) for v in values):
            issues.append("vessel_capacity_not_similar")
    lifecycle = str(product.get("lifecycle_status") or "").strip()
    if product.get("active_flag") is False or lifecycle in _UNAVAILABLE:
        issues.append("not_regular_new_purchase")
    elif context.get("require_regular") and lifecycle not in _REGULAR:
        issues.append("regular_supply_unverified")
    return issues


def unsupported_stock_claim(answer: str) -> bool:
    # No inventory source is present in this contract. Catalogue lifecycle is
    # not a promise of stock, shipping date or uninterrupted supply.
    for clause in re.split(r"[。；，\n]", answer):
        if re.search(r"不能|不保证|无法|不确定|待确认|需.{0,6}确认|是否|以.{0,10}为准", clause):
            continue
        if re.search(r"有现货|现货充足|保证.{0,5}发货|马上发货|今天发货|正常供货", clause):
            return True
    return False


def mentioned_choices(answer: str, products: dict[str, dict[str, Any]]) -> list[str]:
    """Find affirmative choices, not every product used as a comparison.

    Bind each choice predicate locally. Negation of another product and a
    subsequent disclaimer cannot erase an affirmative recommendation.
    Metadata selections are checked separately by the caller.
    """
    found = []
    pending_correction = False
    choice = re.compile(r"推荐|建议(?:购买|选|买|考虑)|首选|优先(?:选|考虑)|可以(?:选|考虑|买)|值得(?:买|选)|选(?:择)?这款")
    for clause in re.split(r"[，,。；;\n]|但是|但", answer):
        mentions = []
        for sku, product in products.items():
            name = str(product.get("product_name_cn") or "")
            pattern = r"(?<![A-Z0-9-])" + re.escape(sku) + r"(?![A-Z0-9-])"
            if len(name) >= 3:
                pattern += "|" + re.escape(name)
            mentions.extend((m.start(), m.end(), sku) for m in re.finditer(pattern, clause, re.I))
        mentions.sort()
        # "推荐的不是A，而是B": A is explicitly excluded; only the
        # immediately following corrective clause inherits the choice verb.
        if pending_correction and re.match(r"\s*而是", clause) and mentions:
            sku = mentions[0][2]
            if sku not in found:
                found.append(sku)
        pending_correction = False
        predicates = list(choice.finditer(clause))
        for index, predicate in enumerate(predicates):
            if re.search(r"(?:不|别|不要|不能|无法|不再|不建议|(?:并非|不是)(?:我|我们|本人)?(?:所)?)\s*$", clause[:predicate.start()]):
                continue
            if re.match(r"\s*(?:的)?(?:不是|并非)", clause[predicate.end():]):
                pending_correction = True
                continue
            end = predicates[index + 1].start() if index + 1 < len(predicates) else len(clause)
            targets = [m for m in mentions if predicate.end() <= m[0] < end
                       and not re.search(r"(?:比|相比|对比|参照|相较于?|与|和)\s*$", clause[predicate.end():m[0]])]
            if targets:
                selected = [targets[0]]
                # Explicit coordination shares the predicate; arbitrary later
                # mentions (e.g. capacity equal to the old kettle) do not.
                for mention in mentions:
                    if mention[0] < selected[-1][1] or mention[0] >= end:
                        continue
                    between = clause[selected[-1][1]:mention[0]].strip(" *：:")
                    if re.fullmatch(r"(?:和|或|、|以及|还有|及)", between):
                        selected.append(mention)
                    else:
                        break
            else:
                # Subject-first predicate: "B值得买" / "B是我的首选".
                before = [m for m in mentions if m[1] <= predicate.start()]
                selected = before[-1:] if before else []
            for _, _, sku in selected:
                if sku not in found:
                    found.append(sku)
    return found


def blocked_answer(context: dict[str, Any]) -> str:
    capacity = context.get("capacity_ml")
    relation = {"near": "接近", "larger": "大于", "smaller": "小于", "different": "不同于", "any": "不限，参照"}[context.get("capacity_relation", "near")]
    volume = f"、饮水容量{relation}{capacity / 1000:g}L" if capacity else ""
    subject = _LABELS.get(context["form"], context.get("subject_label") or "原用途商品")
    return (f"你要找的仍是{subject}{volume}"
            + ("、正常在售的替代款" if context.get("require_regular") else "的替代款")
            + "。这轮还没有确认同时满足这些条件的选择，不能拿不同用途或容量的商品替代；实际库存和供货需要另行确认。")
