from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields as dataclass_fields
from typing import Any


_EMPTY_VALUES = {"", "/", "-", "--", "未知", "暂无", "无", "null", "none"}


@dataclass
class RecommendationRequestContract:
    subject_category: str | None = None
    subject_kind: str | None = None
    subject_subtype: str | None = None
    scenario: list[str] = field(default_factory=list)
    people_min: int | None = None
    people_max: int | None = None
    capacity_requirement: str | None = None
    capacity_min_ml: float | None = None
    capacity_max_ml: float | None = None
    weight_preference: str | None = None
    weight_max_g: float | None = None
    budget_level: str | None = None
    relative_price_preference: str | None = None
    price_anchor_sku: str | None = None
    heat_sources: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    stability_required: bool = False
    portability_required: bool = False
    storage_required: bool = False
    dishwasher_safe_required: bool = False
    exclusions: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    confidence: str = "medium"
    source_spans: dict[str, Any] = field(default_factory=dict)
    field_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RecommendationRequestContract":
        data = value if isinstance(value, dict) else {}
        allowed = {item.name for item in dataclass_fields(cls)}
        return cls(**{key: data[key] for key in allowed if key in data})


@dataclass
class CandidateVerification:
    sku: str
    subject_eligible: bool
    hard_constraints_passed: bool
    verification_level: str = "rejected"
    has_hard_constraint_conflict: bool = False
    all_hard_constraints_verified: bool = False
    evidence_by_constraint: dict[str, dict[str, Any]] = field(default_factory=dict)
    verified_preferences: list[str] = field(default_factory=list)
    unsupported_preferences: list[str] = field(default_factory=list)
    unsupported_constraints: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _span(text: str, pattern: str) -> tuple[int, int] | None:
    match = re.search(pattern, text)
    return match.span() if match else None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _parse_people(text: str) -> tuple[int | None, int | None, tuple[int, int] | None]:
    normalized = str(text or "")
    number_map = {char: index + 1 for index, char in enumerate("一二三四五六七八九十")}
    number_map["两"] = 2

    def parse_number(value: str) -> int | None:
        token = str(value or "").strip()
        if token.isdigit():
            return int(token)
        return number_map.get(token)

    def is_negated(span: tuple[int, int]) -> bool:
        prefix = normalized[max(0, span[0] - 8):span[0]]
        return any(marker in prefix for marker in ("不要", "排除", "别要", "不考虑", "去掉"))

    candidates: list[tuple[int, int, tuple[int, int]]] = []
    number = r"[1-9]\d?|[一二两三四五六七八九十]"
    for match in re.finditer(rf"({number})\s*(?:到|至|[-~～])\s*({number})\s*(?:个)?人", normalized):
        if is_negated(match.span()):
            continue
        lower = parse_number(match.group(1))
        upper = parse_number(match.group(2))
        if lower is not None and upper is not None:
            candidates.append((min(lower, upper), max(lower, upper), match.span()))
    # Chinese prose commonly writes “四五个人” without a range separator.
    for match in re.finditer(r"([一二两三四五六七八九])([一二两三四五六七八九])个?人", normalized):
        if is_negated(match.span()):
            continue
        lower = parse_number(match.group(1))
        upper = parse_number(match.group(2))
        if lower is not None and upper is not None:
            candidates.append((min(lower, upper), max(lower, upper), match.span()))
    for match in re.finditer(rf"({number})\s*(?:个)?人", normalized):
        if is_negated(match.span()):
            continue
        value = parse_number(match.group(1))
        if value is not None:
            candidates.append((value, value, match.span()))
    if candidates:
        # The earliest non-negated expression is the current request's people
        # requirement.  Prefer a range when multiple recognizers cover the
        # same span, then keep the original textual order.
        candidates.sort(key=lambda item: (item[2][0], -(item[2][1] - item[2][0])))
        people_min, people_max, span = candidates[0]
        return people_min, people_max, span
    for pattern, people in (
        (r"(?:一家)?四口", (4, 4)),
        (r"三口之家", (3, 3)),
        (r"双人", (2, 2)),
        (r"单人", (1, 1)),
    ):
        match = re.search(pattern, normalized)
        if match and not is_negated(match.span()):
            return people[0], people[1], match.span()
    return None, None, None


def _parse_numeric_limit(text: str, field_name: str) -> tuple[float | None, float | None, tuple[int, int] | None]:
    field_terms = "容量" if field_name == "capacity" else "重量"
    unit_pattern = r"(ml|毫升|l|升)" if field_name == "capacity" else r"(g|克|kg|千克|公斤)"
    match = re.search(
        rf"{field_terms}[^，。；;]{{0,8}}?(至少|不低于|不少于|大于|超过|不超过|至多|小于|低于)?\s*(\d+(?:\.\d+)?)\s*{unit_pattern}",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None, None
    operator = match.group(1) or "="
    value = float(match.group(2))
    unit = match.group(3).lower()
    if field_name == "capacity" and unit in {"l", "升"}:
        value *= 1000
    if field_name == "weight" and unit in {"kg", "千克", "公斤"}:
        value *= 1000
    if operator in {"至少", "不低于", "不少于", "大于", "超过"}:
        return value, None, match.span()
    if operator in {"不超过", "至多", "小于", "低于"}:
        return None, value, match.span()
    return value, value, match.span()


def _recommendation_stove_subject(text: str) -> tuple[tuple[int, int], str | None] | None:
    stove_terms = r"卡式炉|酒精炉|气炉|炉具"
    action_terms = r"推荐|买|购买|选|挑"
    match = re.search(
        rf"(?:{action_terms})[^，。；;]{{0,8}}?({stove_terms})|({stove_terms})[^，。；;]{{0,4}}?(?:推荐|怎么选|选哪个)",
        text,
    )
    if not match:
        return None
    for group_index in (1, 2):
        if match.group(group_index):
            value = match.group(group_index)
            subtype = "card_stove" if value == "卡式炉" else "alcohol_stove" if value == "酒精炉" else None
            return match.span(group_index), subtype
    return None


def _recommendation_contract_from_validated_semantic_constraints(
    constraints: dict[str, Any] | None,
) -> RecommendationRequestContract | None:
    """Map abstract semantic preferences into the DB-verification contract.

    This intentionally accepts no identity, answer, raw database value, or
    free-form product wording.  The semantic preplan is responsible for
    language understanding; this adapter only re-validates its small schema
    before the existing same-SKU candidate verifier consumes it.
    """
    if not isinstance(constraints, dict):
        return None
    allowed = {"subject_kind", "people", "heat_sources", "scenarios", "weight_preference", "price_preference", "storage_preference", "dishwasher_safe"}
    if not constraints or any(key not in allowed for key in constraints):
        return None
    contract = RecommendationRequestContract()
    subject_kind = constraints.get("subject_kind")
    subject_categories = {"cookware": "锅具", "waterware": "水具", "stove": "炉具", "coffee_gear": "咖啡器具", "accessories": "配件"}
    if subject_kind is not None and subject_kind not in subject_categories:
        return None
    if subject_kind is not None:
        contract.subject_kind = subject_kind
        contract.subject_category = subject_categories[subject_kind]
    people = constraints.get("people")
    if people is not None:
        if not isinstance(people, dict) or set(people) != {"min", "max"}:
            return None
        lower, upper = people.get("min"), people.get("max")
        if type(lower) is not int or type(upper) is not int or not (1 <= lower <= upper <= 99):
            return None
        contract.people_min, contract.people_max = lower, upper
        _append_unique(contract.hard_constraints, "people")
    heat_sources = constraints.get("heat_sources")
    heat_map = {
        "card_stove": "卡式炉",
        "gas_stove": "燃气炉",
        "alcohol_stove": "酒精炉",
        "open_flame": "明火",
        "induction": "电磁炉",
    }
    if heat_sources is not None:
        if not isinstance(heat_sources, list) or not heat_sources or len(heat_sources) > 5:
            return None
        if any(item not in heat_map for item in heat_sources):
            return None
        contract.heat_sources = list(dict.fromkeys(heat_map[item] for item in heat_sources))
        _append_unique(contract.hard_constraints, "heat_source")
    scenarios = constraints.get("scenarios")
    allowed_scenarios = {"camping", "hiking", "self_drive", "seaside", "soup"}
    if scenarios is not None:
        if not isinstance(scenarios, list) or not scenarios or len(scenarios) > 5:
            return None
        if any(item not in allowed_scenarios for item in scenarios):
            return None
        contract.scenario = list(dict.fromkeys(scenarios))
        _append_unique(contract.hard_constraints, "scenario")
    weight_preference = constraints.get("weight_preference")
    if weight_preference is not None:
        if weight_preference != "lightweight":
            return None
        contract.weight_preference = "lighter"
        _append_unique(contract.soft_preferences, "weight")
    price_preference = constraints.get("price_preference")
    if price_preference is not None:
        if price_preference not in {"affordable", "premium"}:
            return None
        contract.budget_level = price_preference
        _append_unique(contract.hard_constraints, "price_positioning")
    storage_preference = constraints.get("storage_preference")
    if storage_preference is not None:
        if storage_preference != "compact_storage":
            return None
        contract.storage_required = True
        _append_unique(contract.soft_preferences, "storage")
    if constraints.get("dishwasher_safe") is not None:
        if constraints.get("dishwasher_safe") is not True:
            return None
        contract.dishwasher_safe_required = True
        _append_unique(contract.hard_constraints, "dishwasher")
    for key in ("subject_category", "people", "heat_sources", "scenario", "weight", "price_positioning", "storage", "dishwasher"):
        present = {
            "subject_category": bool(contract.subject_category),
            "people": contract.people_min is not None,
            "heat_sources": bool(contract.heat_sources),
            "scenario": bool(contract.scenario),
            "weight": bool(contract.weight_preference),
            "price_positioning": bool(contract.budget_level),
            "storage": bool(contract.storage_required),
            "dishwasher": bool(contract.dishwasher_safe_required),
        }[key]
        if present:
            contract.field_provenance[key] = {"source_turn": 1, "provenance": "validated_semantic_preplan"}
    signal_count = len(contract.hard_constraints) + len(contract.soft_preferences)
    contract.confidence = "high" if contract.subject_category and signal_count >= 2 else "medium"
    return contract


def build_recommendation_request_contract(
    question: str,
    plan: dict[str, Any] | None = None,
    intent_result: dict[str, Any] | None = None,
    *,
    semantic_constraints: dict[str, Any] | None = None,
) -> RecommendationRequestContract:
    semantic_contract = _recommendation_contract_from_validated_semantic_constraints(semantic_constraints)
    if semantic_contract is not None:
        return semantic_contract
    text = str(question or "").strip()
    contract = RecommendationRequestContract()
    has_cookware_subject = any(term in text for term in ("锅具", "套锅", "炊具", "锅"))
    has_waterware_subject = any(term in text for term in ("水壶", "水杯", "水具", "杯子"))
    stove_subject = _recommendation_stove_subject(text)
    if has_cookware_subject:
        contract.subject_category = "锅具"
        contract.subject_kind = "cookware"
        contract.source_spans["subject"] = _span(text, r"锅具|套锅|炊具|锅")
    elif has_waterware_subject:
        contract.subject_category = "水具"
        contract.subject_kind = "waterware"
    elif stove_subject:
        contract.subject_category = "炉具"
        contract.subject_kind = "stove"
        contract.source_spans["subject"] = stove_subject[0]
        contract.subject_subtype = stove_subject[1]
    elif any(term in text for term in ("咖啡", "磨豆", "磨豆器", "手冲")):
        contract.subject_category = "咖啡器具"
        contract.subject_kind = "coffee_gear"

    contract.people_min, contract.people_max, people_span = _parse_people(text)
    if people_span:
        contract.source_spans["people"] = people_span
        _append_unique(contract.hard_constraints, "people")

    capacity_min, capacity_max, capacity_span = _parse_numeric_limit(text, "capacity")
    contract.capacity_min_ml = capacity_min
    contract.capacity_max_ml = capacity_max
    if capacity_span:
        contract.capacity_requirement = "numeric"
        contract.source_spans["capacity"] = capacity_span
        _append_unique(contract.hard_constraints, "capacity")
    elif any(term in text for term in ("容量大", "容量要大", "大容量", "容量宽裕", "容量别太小", "容量不要太小")):
        contract.capacity_requirement = "spacious"
        _append_unique(contract.soft_preferences, "capacity")

    _, weight_max, weight_span = _parse_numeric_limit(text, "weight")
    contract.weight_max_g = weight_max
    if weight_span and weight_max is not None:
        contract.weight_preference = "numeric_max"
        contract.source_spans["weight"] = weight_span
        _append_unique(contract.hard_constraints, "weight")
    elif any(term in text for term in ("轻一点", "轻便", "轻量", "别太重", "不要太重", "重量别太夸张")):
        contract.weight_preference = "lighter"
        _append_unique(contract.soft_preferences, "weight")

    heat_aliases = (
        ("燃气炉", ("燃气炉",)),
        ("卡式炉", ("卡式炉",)),
        ("明火", ("明火直烧", "直接明火", "明火加热", "适配明火", "明火")),
    )
    for normalized, terms in heat_aliases:
        if contract.subject_kind == "stove" and any(term in text for term in terms):
            continue
        if any(term in text for term in terms):
            _append_unique(contract.heat_sources, normalized)
    if contract.subject_kind != "stove":
        from app.services import customer_agent_intent_service

        normalized_heat = customer_agent_intent_service._normalize_structured_filter_value(
            "specs.heat_source",
            text,
        )
        if normalized_heat == "酒精炉":
            _append_unique(contract.heat_sources, normalized_heat)
            contract.source_spans["heat_source"] = _span(text, r"液体酒精|固体酒精|酒精燃料|酒精炉")
    if contract.heat_sources:
        _append_unique(contract.hard_constraints, "heat_source")

    for material in ("不锈钢", "硬质氧化铝", "铝合金", "钛"):
        if material in text:
            contract.materials.append(material)
    if contract.materials:
        _append_unique(contract.hard_constraints, "material")

    if any(term in text for term in ("更便宜", "便宜一点的替代", "便宜些")):
        contract.relative_price_preference = "cheaper_than_anchor"
        contract.budget_level = "relative"
    elif any(term in text for term in ("预算中等", "中等预算")):
        contract.budget_level = "medium"
    elif any(term in text for term in ("预算别太高", "预算不高", "低预算", "便宜点", "性价比")):
        contract.budget_level = "low"
    if contract.budget_level:
        _append_unique(contract.soft_preferences, "budget")

    contract.stability_required = any(term in text for term in ("稳定性", "稳定", "稳一点"))
    contract.portability_required = any(term in text for term in ("便携", "好带", "轻便"))
    contract.storage_required = any(term in text for term in ("收纳", "套娃"))
    for enabled, label in (
        (contract.stability_required, "stability"),
        (contract.portability_required, "portability"),
        (contract.storage_required, "storage"),
    ):
        if enabled:
            _append_unique(contract.soft_preferences, label)

    for label, terms in (
        ("hiking", ("徒步",)),
        ("self_drive", ("自驾",)),
        ("camping", ("露营", "营地")),
        ("seaside", ("海边",)),
        ("soup", ("煮汤",)),
    ):
        if any(term in text for term in terms):
            contract.scenario.append(label)

    signal_count = len(contract.hard_constraints) + len(contract.soft_preferences)
    contract.confidence = "high" if contract.subject_category and signal_count >= 2 else "medium"
    for key in (
        "subject_category",
        "people",
        "scenario",
        "capacity",
        "weight",
        "budget",
        "heat_sources",
        "materials",
        "stability",
        "portability",
        "storage",
    ):
        present = {
            "subject_category": bool(contract.subject_category),
            "people": contract.people_min is not None,
            "scenario": bool(contract.scenario),
            "capacity": bool(contract.capacity_requirement or contract.capacity_min_ml is not None or contract.capacity_max_ml is not None),
            "weight": bool(contract.weight_preference or contract.weight_max_g is not None),
            "budget": bool(contract.budget_level or contract.relative_price_preference),
            "heat_sources": bool(contract.heat_sources),
            "materials": bool(contract.materials),
            "stability": contract.stability_required,
            "portability": contract.portability_required,
            "storage": contract.storage_required,
        }[key]
        if present:
            contract.field_provenance[key] = {"source_turn": 1, "provenance": "current_turn"}
    return contract


def merge_recommendation_request_contracts(
    inherited: RecommendationRequestContract | dict[str, Any] | None,
    current: RecommendationRequestContract | dict[str, Any] | None,
    *,
    previous_result_skus: list[str] | None = None,
    anchor_sku: str | None = None,
    current_turn: int = 1,
) -> tuple[RecommendationRequestContract, dict[str, dict[str, Any]]]:
    inherited_contract = (
        inherited
        if isinstance(inherited, RecommendationRequestContract)
        else RecommendationRequestContract.from_dict(inherited)
    )
    current_contract = (
        current
        if isinstance(current, RecommendationRequestContract)
        else RecommendationRequestContract.from_dict(current)
    )
    effective = RecommendationRequestContract.from_dict(inherited_contract.to_dict())
    provenance: dict[str, dict[str, Any]] = {
        key: {
            "source_turn": int((value or {}).get("source_turn") or max(current_turn - 1, 1)),
            "provenance": "inherited",
        }
        for key, value in inherited_contract.field_provenance.items()
    }

    def override_scalar(field_name: str, provenance_key: str | None = None) -> None:
        current_value = getattr(current_contract, field_name)
        if current_value is None:
            return
        inherited_value = getattr(inherited_contract, field_name)
        setattr(effective, field_name, current_value)
        provenance[provenance_key or field_name] = {
            "source_turn": current_turn,
            "provenance": "current_turn_override" if inherited_value is not None and inherited_value != current_value else "current_turn_addition",
        }

    override_scalar("subject_category")
    override_scalar("subject_kind")
    override_scalar("subject_subtype")
    if current_contract.people_min is not None:
        inherited_people = (inherited_contract.people_min, inherited_contract.people_max)
        current_people = (current_contract.people_min, current_contract.people_max)
        effective.people_min, effective.people_max = current_people
        provenance["people"] = {
            "source_turn": current_turn,
            "provenance": "current_turn_override" if inherited_contract.people_min is not None and inherited_people != current_people else "current_turn_addition",
        }
    for field_name in (
        "capacity_requirement",
        "capacity_min_ml",
        "capacity_max_ml",
        "weight_preference",
        "weight_max_g",
        "budget_level",
        "relative_price_preference",
        "price_anchor_sku",
    ):
        override_scalar(field_name, "budget" if field_name == "budget_level" else field_name)
    for field_name, provenance_key in (
        ("scenario", "scenario"),
        ("heat_sources", "heat_sources"),
        ("materials", "materials"),
        ("hard_constraints", "hard_constraints"),
        ("soft_preferences", "soft_preferences"),
    ):
        current_values = list(getattr(current_contract, field_name) or [])
        if not current_values:
            continue
        inherited_values = list(getattr(effective, field_name) or [])
        setattr(effective, field_name, list(dict.fromkeys([*inherited_values, *current_values])))
        provenance[provenance_key] = {"source_turn": current_turn, "provenance": "current_turn_addition"}
    for field_name in ("stability_required", "portability_required", "storage_required"):
        if getattr(current_contract, field_name):
            setattr(effective, field_name, True)
            provenance[field_name.removesuffix("_required")] = {"source_turn": current_turn, "provenance": "current_turn_addition"}

    effective.source_spans = {**inherited_contract.source_spans, **current_contract.source_spans}
    exclusions = [str(sku or "").strip().upper() for sku in inherited_contract.exclusions if str(sku or "").strip()]
    current_exclusions = [str(sku or "").strip().upper() for sku in current_contract.exclusions if str(sku or "").strip()]
    exclusions.extend(current_exclusions)
    normalized_anchor = str(anchor_sku or "").strip().upper()
    if normalized_anchor:
        exclusions.append(normalized_anchor)
        effective.price_anchor_sku = normalized_anchor if effective.relative_price_preference else effective.price_anchor_sku
    effective.exclusions = list(dict.fromkeys(exclusions))
    if effective.exclusions:
        provenance["exclusions"] = {"source_turn": current_turn, "provenance": "system_exclusion"}
    effective.field_provenance = provenance
    effective.confidence = "high" if effective.subject_category and (effective.hard_constraints or effective.soft_preferences) else inherited_contract.confidence
    return effective, provenance


def _usable(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() not in _EMPTY_VALUES


def _row_scope(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get(key) or "") for key in ("category", "sub_category", "product_name_cn"))
    return "accessory" if any(term in text for term in ("配件", "附件", "锅盖", "手柄", "收纳袋", "替换件")) else "subject"


def _cookware_subject_identity_is_valid(row: dict[str, Any]) -> bool:
    """Keep a broad inventory category from widening the cookware domain.

    Product category is useful primary evidence, but catalogue imports can use
    ``锅具`` for a broader family.  Product identity and structured descriptive
    fields are first-party data too.  A water container is not a cookware
    candidate unless the same row explicitly identifies a cookware shape or
    cookware set.  This validates candidate evidence; it never parses the
    customer's wording or selects a SKU.
    """
    identity = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "name", "title")
    ).lower()
    descriptive = " ".join(
        str(row.get(key) or "")
        for key in (
            "product_name_cn", "product_name_en", "name", "title",
            "features", "usage_scenarios", "target_audience",
            "positioning", "long_description_cn",
        )
    ).lower()
    water_container_terms = ("水壶", "茶壶", "烧水壶", "kettle", "bottle", "flask", "cup", "杯")
    cookware_shape_terms = (
        "单锅", "套锅", "炒锅", "汤锅", "锅具套装", "炊具套装", "炊具组合",
        "野餐锅", "野营锅", "小方锅", "cookware set", "cook set", "pot set",
    )
    stove_identity_terms = ("炉", "stove", "burner")
    return not (
        any(term in identity for term in water_container_terms)
        and not any(term in descriptive for term in cookware_shape_terms)
    ) and not (
        any(term in identity for term in stove_identity_terms)
        and not any(term in identity for term in cookware_shape_terms)
    )


def _subject_evidence(contract: RecommendationRequestContract, row: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
    category = str(row.get("category") or "").strip()
    scope = _row_scope(row)
    evidence = {"status": "verified", "field_source": "product.category", "raw_value": category, "scope": scope}
    if contract.subject_category == "配件":
        if scope == "accessory" or "配件" in category:
            return True, evidence, None
        evidence["status"] = "conflict"
        return False, evidence, "subject_category_mismatch"
    if scope != "subject":
        evidence["status"] = "conflict"
        return False, evidence, "accessory_scope"
    if contract.subject_category == "锅具" and not any(term in category for term in ("锅具", "炉具、锅具")):
        evidence["status"] = "conflict"
        return False, evidence, "subject_category_mismatch"
    if contract.subject_kind == "cookware" and not _cookware_subject_identity_is_valid(row):
        evidence.update({"status": "conflict", "field_source": "product_identity_and_structured_description"})
        return False, evidence, "subject_category_mismatch"
    if contract.subject_category == "水具" and not any(term in category for term in ("水具", "水壶", "水杯")):
        evidence["status"] = "conflict"
        return False, evidence, "subject_category_mismatch"
    if contract.subject_category == "咖啡器具" and "咖啡器具" not in category:
        evidence["status"] = "conflict"
        return False, evidence, "subject_category_mismatch"
    # The catalog's first-party taxonomy has both broad ``炉具`` rows and
    # subtype-labelled ``酒精炉`` rows (including a combined-category row).
    # They are all stove candidates; accessories remain excluded above by
    # _row_scope and a requested subtype is still verified from this SKU's
    # own identity below.
    if contract.subject_category == "炉具" and not any(term in category for term in ("炉具", "酒精炉")):
        evidence["status"] = "conflict"
        return False, evidence, "subject_category_mismatch"
    return True, evidence, None


def _stove_subtype_evidence(
    contract: RecommendationRequestContract,
    row: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, str | None]:
    if not contract.subject_subtype:
        return True, None, None
    product_name = str(row.get("product_name_cn") or "").strip()
    if contract.subject_subtype == "card_stove":
        matched = "卡式炉" in product_name
    elif contract.subject_subtype == "alcohol_stove":
        matched = "炉" in product_name and "酒精" in product_name
    else:
        matched = False
    evidence = _condition(
        "verified" if matched else "conflict",
        "product_name_cn",
        product_name,
        subject_subtype=contract.subject_subtype,
    )
    return matched, evidence, None if matched else "subject_subtype_mismatch"


def prepare_recommendation_return_rows(
    matched_rows: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(matched_rows)
    returned = list(matched_rows[: max(int(limit), 0)])
    return returned, {
        "total_match_count": total,
        "returned_count": len(returned),
        "is_truncated": total > len(returned),
    }


def _people_range(row: dict[str, Any]) -> tuple[int | None, int | None, str, str]:
    # Customer-facing product titles are first-party SKU evidence.  They may
    # be the only place a fixed people range is recorded, so include them
    # before treating the people constraint as unknown.
    for key in ("people", "target_audience", "product_name_cn", "product_name_en", "capacity", "features"):
        raw = str(row.get(key) or "").strip()
        if not _usable(raw):
            continue
        match = re.search(r"(\d+)\s*[-~～－至到]\s*(\d+)\s*人", raw)
        if match:
            return int(match.group(1)), int(match.group(2)), raw, key
        match = re.search(r"(?:适合)?\s*(\d+)\s*人", raw)
        if match:
            value = int(match.group(1))
            return value, value, raw, key
        # Imported business fields commonly express the intended group with
        # Chinese count labels rather than an Arabic numeral. This normalizes
        # evidence already recorded on the candidate SKU; it never infers a
        # customer requirement or chooses a product.
        for label, value in (
            ("单人", 1),
            ("一人", 1),
            ("两人", 2),
            ("双人", 2),
            ("三人", 3),
            ("四人", 4),
            ("五人", 5),
        ):
            if label in raw:
                return value, value, raw, key
    return None, None, "", ""


def _numeric_values(raw: Any, *, kind: str) -> list[float]:
    text = str(raw or "")
    if not _usable(text):
        return []
    unit_pattern = r"(ml|毫升|l|升)" if kind == "capacity" else r"(g|克|kg|千克|公斤)"
    values: list[float] = []
    for match in re.finditer(rf"(\d+(?:\.\d+)?)\s*{unit_pattern}", text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit in {"l", "升", "kg", "千克", "公斤"}:
            value *= 1000
        values.append(value)
    return values


def _condition(status: str, source: str = "", raw: Any = None, **extra: Any) -> dict[str, Any]:
    result = {"status": status, "field_source": source, "raw_value": raw}
    result.update(extra)
    return result


def verify_recommendation_candidates(
    contract: RecommendationRequestContract,
    candidate_rows: list[dict[str, Any]],
) -> list[CandidateVerification]:
    results: list[CandidateVerification] = []
    for row in candidate_rows:
        sku = str(row.get("sku") or "").strip().upper()
        evidence: dict[str, dict[str, Any]] = {}
        verified_preferences: list[str] = []
        unsupported_preferences: list[str] = []
        rejection_reasons: list[str] = []

        subject_ok, subject_evidence, subject_reason = _subject_evidence(contract, row)
        evidence["subject"] = subject_evidence
        if subject_reason:
            rejection_reasons.append(subject_reason)
        subtype_ok, subtype_evidence, subtype_reason = _stove_subtype_evidence(contract, row)
        if subtype_evidence is not None:
            evidence["subject_subtype"] = subtype_evidence
        if subtype_reason:
            rejection_reasons.append(subtype_reason)
        subject_ok = subject_ok and subtype_ok

        if contract.people_min is not None:
            row_min, row_max, raw, source = _people_range(row)
            if row_min is None or row_max is None:
                evidence["people"] = _condition("unknown")
            elif row_max < contract.people_min or (contract.people_max is not None and row_min > contract.people_max):
                evidence["people"] = _condition("conflict", source, raw, people_min=row_min, people_max=row_max)
                rejection_reasons.append("people_capacity_conflict")
            else:
                evidence["people"] = _condition("verified", source, raw, people_min=row_min, people_max=row_max)

        if contract.scenario:
            raw_scenarios = str(row.get("usage_scenarios") or "").strip()
            scenario_terms = {
                "camping": ("露营", "营地"),
                "hiking": ("徒步",),
                "self_drive": ("自驾",),
                "seaside": ("海边",),
                "soup": ("煮汤",),
            }
            if not _usable(raw_scenarios):
                evidence["scenario"] = _condition("unknown")
            else:
                matched = all(any(term in raw_scenarios for term in scenario_terms[item]) for item in contract.scenario)
                evidence["scenario"] = _condition(
                    "verified" if matched else "conflict",
                    "usage_scenarios",
                    raw_scenarios,
                    canonical_scenarios=list(contract.scenario),
                )
                if not matched:
                    rejection_reasons.append("scenario_condition_not_met")

        capacity_values = _numeric_values(row.get("capacity"), kind="capacity")
        if contract.capacity_min_ml is not None or contract.capacity_max_ml is not None:
            if not capacity_values:
                evidence["capacity"] = _condition("unknown")
            else:
                capacity = max(capacity_values)
                matched = (
                    (contract.capacity_min_ml is None or capacity >= contract.capacity_min_ml)
                    and (contract.capacity_max_ml is None or capacity <= contract.capacity_max_ml)
                )
                evidence["capacity"] = _condition("verified" if matched else "conflict", "capacity", row.get("capacity"), normalized_ml=capacity)
                if not matched:
                    rejection_reasons.append("capacity_constraint_not_met")
        elif "capacity" in contract.soft_preferences:
            if capacity_values:
                evidence["capacity"] = _condition("verified", "capacity", row.get("capacity"), normalized_ml=max(capacity_values))
                verified_preferences.append("capacity")
            else:
                evidence["capacity"] = _condition("unsupported")
                unsupported_preferences.append("capacity")

        if contract.weight_max_g is not None:
            weights = _numeric_values(row.get("gross_weight_g"), kind="weight")
            if not weights and isinstance(row.get("gross_weight_g"), (int, float)):
                weights = [float(row["gross_weight_g"])]
            if not weights:
                evidence["weight"] = _condition("unknown")
            else:
                weight = weights[0]
                matched = weight <= contract.weight_max_g
                evidence["weight"] = _condition("verified" if matched else "conflict", "gross_weight_g", row.get("gross_weight_g"), normalized_g=weight)
                if not matched:
                    rejection_reasons.append("weight_constraint_not_met")
        elif "weight" in contract.soft_preferences:
            raw_weight = row.get("gross_weight_g")
            weights = _numeric_values(raw_weight, kind="weight")
            if not weights and isinstance(raw_weight, (int, float)) and raw_weight > 0:
                weights = [float(raw_weight)]
            if weights:
                evidence["weight"] = _condition("verified", "gross_weight_g", raw_weight, normalized_g=weights[0])
                verified_preferences.append("weight")
            else:
                evidence["weight"] = _condition("unsupported")
                unsupported_preferences.append("weight")

        if contract.heat_sources:
            raw_heat = str(row.get("heat_source") or "").strip()
            if not _usable(raw_heat):
                evidence["heat_source"] = _condition("unknown")
            else:
                from app.services import customer_agent_intent_service

                matched = all(
                    customer_agent_intent_service._alcohol_stove_support_verdict(raw_heat) is True
                    if source == "酒精炉"
                    else source in raw_heat or (source == "明火" and "明火" in raw_heat)
                    for source in contract.heat_sources
                )
                evidence["heat_source"] = _condition("verified" if matched else "conflict", "heat_source", raw_heat)
                if not matched:
                    rejection_reasons.append("heat_source_condition_not_met")

        if contract.materials:
            raw_material = str(row.get("body_material") or "").strip()
            if not _usable(raw_material):
                evidence["material"] = _condition("unknown")
            else:
                matched = all(material in raw_material for material in contract.materials)
                evidence["material"] = _condition("verified" if matched else "conflict", "body_material", raw_material)
            if _usable(raw_material) and not matched:
                rejection_reasons.append("material_condition_not_met")

        if contract.dishwasher_safe_required:
            raw_usage = str(row.get("usage_instruction") or "").strip()
            positive = ("洗碗机" in raw_usage and not any(token in raw_usage for token in ("不可", "不能", "不建议", "避免")))
            if not _usable(raw_usage):
                evidence["dishwasher"] = _condition("unknown")
            else:
                evidence["dishwasher"] = _condition("verified" if positive else "conflict", "usage_instruction", raw_usage)
                if not positive:
                    rejection_reasons.append("dishwasher_condition_not_met")

        if contract.budget_level in {"affordable", "premium"}:
            raw_price_positioning = str(row.get("price_positioning") or "").strip()
            if not _usable(raw_price_positioning):
                evidence["price_positioning"] = _condition("unknown")
            else:
                matched = (
                    any(value in raw_price_positioning for value in ("入门", "中端"))
                    if contract.budget_level == "affordable"
                    else "高端" in raw_price_positioning
                )
                evidence["price_positioning"] = _condition(
                    "verified" if matched else "conflict",
                    "price_positioning",
                    raw_price_positioning,
                    preference=contract.budget_level,
                )
                if not matched:
                    rejection_reasons.append("price_positioning_condition_not_met")
        elif contract.budget_level or contract.relative_price_preference:
            evidence["budget"] = _condition("unsupported")
            unsupported_preferences.append("budget")

        for label, required, fields in (
            ("stability", contract.stability_required, ("features", "positioning")),
            ("portability", contract.portability_required, ("features", "positioning")),
            # These are sealed first-party product fields.  They may establish
            # a storage fact only when the same SKU explicitly records it;
            # they do not route the customer's wording or infer compactness.
            ("storage", contract.storage_required, ("features", "top_selling_points", "positioning", "long_description_cn", "bullet_points", "size_info")),
        ):
            if not required:
                continue
            raw = "；".join(str(row.get(key) or "").strip() for key in fields if _usable(row.get(key)))
            terms = {
                "stability": ("稳定", "稳固"),
                "portability": ("便携", "好带"),
                "storage": ("收纳", "套娃"),
            }[label]
            if raw and any(term in raw for term in terms):
                evidence[label] = _condition("verified", "/".join(fields), raw)
                verified_preferences.append(label)
            else:
                evidence[label] = _condition("unsupported")
                unsupported_preferences.append(label)

        unsupported_constraints = [
            label
            for label in contract.hard_constraints
            if (evidence.get(label) or {}).get("status") == "unknown"
        ]
        conflicts = [
            label
            for label in contract.hard_constraints
            if (evidence.get(label) or {}).get("status") == "conflict"
        ]
        has_hard_constraint_conflict = not subject_ok or bool(conflicts)
        all_hard_constraints_verified = subject_ok and all(
            (evidence.get(label) or {}).get("status") == "verified"
            for label in contract.hard_constraints
        )
        if has_hard_constraint_conflict:
            verification_level = "rejected"
        elif all_hard_constraints_verified:
            verification_level = "fully_verified"
        else:
            verification_level = "partially_verified"
        results.append(
            CandidateVerification(
                sku=sku,
                subject_eligible=subject_ok,
                hard_constraints_passed=not has_hard_constraint_conflict,
                verification_level=verification_level,
                has_hard_constraint_conflict=has_hard_constraint_conflict,
                all_hard_constraints_verified=all_hard_constraints_verified,
                evidence_by_constraint=evidence,
                verified_preferences=verified_preferences,
                unsupported_preferences=unsupported_preferences,
                unsupported_constraints=unsupported_constraints,
                conflicts=conflicts,
                rejection_reasons=rejection_reasons,
            )
        )
    return results


def select_recommendation_candidates(
    candidate_rows: list[dict[str, Any]],
    verifications: list[CandidateVerification],
) -> list[dict[str, Any]]:
    verification_by_sku = {item.sku: item for item in verifications}
    fully_verified = [
        row
        for row in candidate_rows
        if verification_by_sku.get(str(row.get("sku") or "").strip().upper())
        and verification_by_sku[str(row.get("sku") or "").strip().upper()].verification_level == "fully_verified"
    ]
    partially_verified = [
        row
        for row in candidate_rows
        if verification_by_sku.get(str(row.get("sku") or "").strip().upper())
        and verification_by_sku[str(row.get("sku") or "").strip().upper()].verification_level == "partially_verified"
    ]
    if not fully_verified:
        return partially_verified
    # A missing people-range label is safe to disclose as uncertainty behind a
    # fully verified candidate.  Missing heat-source, material, capacity, or
    # other safety-relevant hard evidence must not be reinserted when a fully
    # verified option exists.
    safely_supplemental = [
        row
        for row in partially_verified
        if set(
            verification_by_sku[str(row.get("sku") or "").strip().upper()].unsupported_constraints
        ).issubset({"people"})
    ]
    return [*fully_verified, *safely_supplemental]


_CONSTRAINT_LABELS = {
    "people": "人数",
    "scenario": "使用场景",
    "capacity": "容量",
    "weight": "重量",
    "heat_source": "热源",
    "material": "材质",
    "budget": "预算",
    "stability": "稳定性",
    "portability": "便携性",
    "storage": "收纳",
}


def _customer_safe_missing_requirement_note(values: list[str]) -> str:
    """Describe missing recommendation evidence without exposing verifier state."""
    notices = [
        f"{_CONSTRAINT_LABELS.get(value, value)}资料暂未明确"
        for value in values
    ]
    return "；".join(notices)


def _display_verified_evidence_value(value: Any) -> str:
    """Render sealed structured evidence without leaking serialized JSON."""
    if isinstance(value, (list, tuple, set)):
        return "、".join(_display_verified_evidence_value(item) for item in value if _usable(item))
    if isinstance(value, dict):
        return "；".join(
            f"{key}：{_display_verified_evidence_value(item)}"
            for key, item in value.items()
            if _usable(item)
        )
    text = str(value or "").strip()
    if text.startswith(("[", "{")):
        try:
            return _display_verified_evidence_value(__import__("json").loads(text))
        except (TypeError, ValueError):
            pass
    return text.replace("\n", "；")


def build_verified_recommendation_answer(
    contract: RecommendationRequestContract,
    verified_rows: list[dict[str, Any]],
    verifications: list[CandidateVerification],
    *,
    total_match_count: int | None = None,
) -> str:
    accepted = {item.sku: item for item in verifications if item.verification_level != "rejected"}
    rows = [row for row in verified_rows if str(row.get("sku") or "").strip().upper() in accepted]
    if not rows:
        return "当前未找到符合条件且能验证所有硬性条件的商品。"
    partial_result = any(accepted[str(row.get("sku") or "").strip().upper()].verification_level == "partially_verified" for row in rows)
    fully_verified_result = any(
        accepted[str(row.get("sku") or "").strip().upper()].verification_level == "fully_verified"
        for row in rows
    )
    lines = (
        ["当前没有找到所有条件都能完整验证的商品。以下推荐锅具候选未发现明确冲突，但部分条件缺少资料，仅供参考；首项优先参考，其余作为备选："]
        if partial_result and not fully_verified_result
        else ["\u63a8\u8350\u4f18\u5148\u770b\u4ee5\u4e0b\u5019\u9009\uff1b\u5b83\u4eec\u901a\u8fc7\u4e86\u53ef\u9a8c\u8bc1\u7684\u786c\u6027\u6761\u4ef6\uff1a"]
    )
    if fully_verified_result and partial_result:
        lines = [
            "以下优先展示已通过当前可验证的硬性条件的候选；其余备选会明确标出尚未验证的条件，供你结合实际需求判断："
        ]
    if contract.subject_kind == "stove":
        subject_label = {
            "card_stove": "卡式炉",
            "alcohol_stove": "酒精炉",
        }.get(contract.subject_subtype, "炉具类商品")
        lines.append(f"本次按“{subject_label}”主体范围筛选：")
    if contract.heat_sources:
        heat_source_label = "、".join(contract.heat_sources)
        lines.append(f"本次仅保留同 SKU 热源字段明确标注支持{heat_source_label}的候选。")
    total = len(rows) if total_match_count is None else max(int(total_match_count), 0)
    if total > len(rows):
        lines.insert(0, f"共找到{total}款可供参考的商品，以下先展示前{len(rows)}款：")
    if partial_result and not fully_verified_result and contract.subject_category == "锅具":
        people_label = ""
        if contract.people_min is not None:
            people_label = (
                f"{contract.people_min} 人"
                if contract.people_min == contract.people_max
                else f"{contract.people_min}-{contract.people_max} 人"
            )
        scenario_label = "露营" if "camping" in contract.scenario else ""
        if people_label:
            lines.append(f"当前资料未明确标注 {people_label} 适用的候选；以下仅保留未见明确冲突的备选。")
        lines.append(f"本次仅按{people_label}{scenario_label}锅具主体范围筛选。")
    for row in rows[:5]:
        sku = str(row.get("sku") or "").strip().upper()
        item = accepted[sku]
        reasons: list[str] = []
        for label, evidence in item.evidence_by_constraint.items():
            if label == "subject" or evidence.get("status") != "verified":
                continue
            raw = evidence.get("raw_value")
            if not _usable(raw):
                continue
            if label == "people":
                people_min = evidence.get("people_min")
                people_max = evidence.get("people_max")
                display = f"{people_min}人" if people_min == people_max else f"{people_min}-{people_max}人"
            elif label == "capacity" and evidence.get("normalized_ml") is not None:
                display = f"{evidence['normalized_ml']:g}ml"
            elif label == "weight" and evidence.get("normalized_g") is not None:
                display = f"{evidence['normalized_g']:g}g"
            elif label in {"stability", "portability", "storage"}:
                display = "商品资料有明确标注"
            else:
                display = _display_verified_evidence_value(raw)
            reasons.append(f"{_CONSTRAINT_LABELS.get(label, label)}：{display}")
        name = str(row.get("product_name_cn") or sku).strip()
        line = f"- {name}（{sku}）"
        if reasons:
            line += "，" + "；".join(reasons)
        unsupported = list(dict.fromkeys([*item.unsupported_constraints, *item.unsupported_preferences]))
        if unsupported:
            line += f"。{_customer_safe_missing_requirement_note(unsupported)}"
        lines.append(line)
    return "\n".join(lines)
