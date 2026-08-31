from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, fields as dataclass_fields
from typing import Any


_EMPTY_VALUES = {"", "/", "-", "--", "未知", "暂无", "无", "null", "none"}

# These are model-owned product-form refinements inside a broad catalogue
# subject.  They are deliberately typed semantic state, not aliases searched
# in the customer question or a local candidate filter.  The same-SKU RAG
# adjudicator decides whether a recalled row actually expresses the subtype.
SEMANTIC_SUBJECT_SUBTYPE_KINDS = {
    "stove": frozenset({"card_stove", "alcohol_stove", "gas_stove"}),
    "waterware": frozenset({"kettle", "cup"}),
    "accessories": frozenset({"storage_bag"}),
}


@dataclass
class RecommendationRequestContract:
    subject_category: str | None = None
    subject_kind: str | None = None
    # Keep conjunctive product-form scope separate from the scalar catalogue
    # kind so a request such as cookware plus waterware is not collapsed into
    # the first form before same-SKU semantic coverage runs.
    subject_kinds: list[str] = field(default_factory=list)
    subject_subtype: str | None = None
    # When true, the subtype came from the validated semantic preplan and must
    # be adjudicated by same-SKU RAG.  Legacy contracts keep the old subtype
    # helper for compatibility with their dedicated unit tests.
    semantic_subject_subtype: bool = False
    # A semantic recommendation may carry a meaning-bearing subject_text
    # without Flash confidently assigning one of the closed catalogue kinds.
    # In that case the semantic coverage model must adjudicate product form
    # from the same-SKU packet; the structured verifier must not silently
    # treat an accessory row as a conflict merely because no typed scope was
    # supplied.
    subject_scope_open: bool = False
    excluded_categories: list[str] = field(default_factory=list)
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
    # An explicit solid/liquid alcohol requirement is narrower than the broad
    # ``酒精炉`` heat-source label.  Keep it as a separate contract field so a
    # generic alcohol-stove row cannot silently satisfy the customer's fuel
    # subtype.
    fuel_subtype: str | None = None
    fuel_subtypes: list[str] = field(default_factory=list)
    # Explicit structural exclusions (for example “不要分体”) are hard
    # evidence constraints, not product/SKU rules.
    structure_preference: str | None = None
    materials: list[str] = field(default_factory=list)
    accessory_requirements: list[str] = field(default_factory=list)
    stability_required: bool = False
    windproof_required: bool = False
    portability_required: bool = False
    storage_required: bool = False
    cleaning_required: bool = False
    dishwasher_safe_required: bool = False
    exclusions: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    confidence: str = "medium"
    source_spans: dict[str, Any] = field(default_factory=dict)
    field_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    predicate_constraints: list[dict[str, Any]] = field(default_factory=list)

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


def _is_negated_category_term(text: str, span: tuple[int, int]) -> bool:
    prefix = str(text or "")[max(0, span[0] - 10):span[0]]
    return any(marker in prefix for marker in (
        "不要", "不想要", "不需要", "不含", "不包括", "排除", "去掉", "别要", "不买",
        "除去", "除了", "除外",
    ))


def _contains_non_negated_term(text: str, terms: tuple[str, ...]) -> bool:
    """Return whether a literal requirement occurs outside an exclusion."""
    for term in terms:
        for match in re.finditer(re.escape(term), str(text or "")):
            if not _is_negated_category_term(text, match.span()):
                return True
    return False


def _literal_category_exclusions(text: str) -> tuple[list[str], dict[str, list[tuple[int, int]]]]:
    category_terms = {
        "炉具": ("燃气炉", "卡式炉", "酒精炉", "气炉", "炉具", "炉子"),
        "配件": ("配件", "附件"),
    }
    excluded: list[str] = []
    spans: dict[str, list[tuple[int, int]]] = {}
    for category, terms in category_terms.items():
        for term in terms:
            for match in re.finditer(re.escape(term), str(text or "")):
                span = match.span()
                if not _is_negated_category_term(text, span):
                    continue
                _append_unique(excluded, category)
                spans.setdefault(category, []).append(span)
    return excluded, spans


def _literal_sku_exclusions(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Extract only SKUs that are explicitly governed by an exclusion phrase."""
    value = str(text or "")
    excluded: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"(?i)\b[A-Z]{2,8}(?:-[A-Z0-9]{1,16})+\b", value):
        prefix = value[max(0, match.start() - 14):match.start()]
        if not any(marker in prefix for marker in (
            "不要", "不选", "不考虑", "排除", "去掉", "剔除", "别要",
            "除去", "除了", "除外",
        )):
            continue
        sku = match.group(0).strip().upper()
        _append_unique(excluded, sku)
        spans.append(match.span())
    return excluded, spans


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _apply_literal_use_requirements(
    contract: RecommendationRequestContract,
    text: str,
) -> None:
    for label, terms in (
        ("hiking", ("徒步",)),
        ("self_drive", ("自驾",)),
        ("camping", ("露营", "营地")),
        ("seaside", ("海边",)),
        ("soup", ("煮汤",)),
        ("hotpot", ("火锅", "涮锅")),
    ):
        if any(term in text for term in terms):
            added = label not in contract.scenario
            _append_unique(contract.scenario, label)
            if added and "scenario" not in contract.field_provenance:
                contract.field_provenance["scenario"] = {
                    "source_turn": 1,
                    "provenance": "current_turn",
                }
    if "hotpot" in contract.scenario:
        _append_unique(contract.hard_constraints, "scenario")

    if any(term in text for term in ("咖啡", "泡咖啡", "冲咖啡", "手冲")):
        added = "coffee_brewing" not in contract.soft_preferences
        _append_unique(contract.soft_preferences, "coffee_brewing")
        if added and "coffee_brewing" not in contract.field_provenance:
            contract.field_provenance["coffee_brewing"] = {
                "source_turn": 1,
                "provenance": "current_turn",
            }

    requirements = (
        ("stability_required", "stability", ("稳定性", "稳定", "稳一点", "又稳", "稳固")),
        ("windproof_required", "windproof", ("防风", "抗风")),
        ("portability_required", "portability", ("便携", "好带", "轻便")),
        ("storage_required", "storage", ("收纳", "套娃")),
        (
            "cleaning_required",
            "cleaning",
            ("好清洁", "易清洁", "容易清洁", "便于清洁", "清洗方便", "好洗", "容易洗", "方便洗"),
        ),
    )
    for field_name, label, terms in requirements:
        if any(term in text for term in terms):
            added = not getattr(contract, field_name)
            setattr(contract, field_name, True)
            if added and label not in contract.field_provenance:
                contract.field_provenance[label] = {
                    "source_turn": 1,
                    "provenance": "current_turn",
                }
        if getattr(contract, field_name):
            _append_unique(contract.soft_preferences, label)


def _explicit_alcohol_fuel_subtypes(text: str) -> list[str]:
    value = str(text or "")
    aliases = (
        ("\u56fa\u4f53\u9152\u7cbe", "\u56fa\u4f53\u9152\u7cbe"),
        ("\u56fa\u6001\u9152\u7cbe", "\u56fa\u4f53\u9152\u7cbe"),
        ("\u9152\u7cbe\u5757", "\u56fa\u4f53\u9152\u7cbe"),
        ("\u56fa\u4f53\u71c3\u6599", "\u56fa\u4f53\u9152\u7cbe"),
        ("\u6db2\u4f53\u9152\u7cbe", "\u6db2\u4f53\u9152\u7cbe"),
    )
    return list(dict.fromkeys(label for phrase, label in aliases if phrase in value))


def _explicit_structure_preference(text: str) -> str | None:
    """Parse a generic negative split-burner preference from the current turn."""
    value = str(text or "")
    if any(term in value for term in (
        "不要分体", "不想要分体", "不需要分体", "不选分体", "排除分体", "不考虑分体",
        "不要分体式", "不想要分体式", "不需要分体式", "不选分体式", "排除分体式",
    )):
        return "non_split"
    return None


def _exact_stainless_grade(text: str) -> str | None:
    """Return an explicitly requested stainless-steel grade, if present.

    A grade such as ``316L`` is a hard material constraint.  It must be
    captured before the broader ``不锈钢`` token so a 304 SKU cannot satisfy a
    316L request merely by sharing the generic material word.
    """
    value = str(text or "")
    match = re.search(r"(?i)(?:(316L|304|430)\s*不锈钢|不锈钢\s*(316L|304|430))", value)
    if not match:
        return None
    grade = (match.group(1) or match.group(2) or "").upper()
    return f"{grade}不锈钢" if grade else None


def _stainless_grade_options(text: str) -> list[str]:
    """Parse an explicit OR-list such as ``304或316的锅``.

    The customer is asking for either grade, not for a product whose material
    cell literally contains both grades.  Keep the alternatives as one
    verifiable contract token; the candidate verifier expands it back to an
    ``any`` match against the same-SKU material field.
    """
    value = str(text or "")
    if _exact_stainless_grade(value):
        return []
    match = re.search(
        r"(?i)(?P<grades>304|316)(?:\s*(?:或|或者|和|/|、|及)\s*(?:304|316))+",
        value,
    )
    if not match:
        return []
    grades = list(dict.fromkeys(re.findall(r"(?i)304|316", match.group(0))))
    return [f"{grade.upper()}不锈钢" for grade in grades]


def _material_token_matches(raw_material: str, requested: str) -> bool:
    """Match one material requirement, supporting an explicit OR token."""
    value = str(raw_material or "")
    token = str(requested or "").strip()
    if not token:
        return False
    options = [part.strip() for part in re.split(r"(?:或|或者|/|、|和)", token) if part.strip()]
    return any(option.lower() in value.lower() for option in (options or [token]))


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
    for match in re.finditer(rf"({number})\s*(?:个)?(?:年轻)?人", normalized):
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
    unit_pattern = r"(?:ml|毫升|l|升)" if field_name == "capacity" else r"(?:g|克|kg|千克|公斤)"
    before_operator_pattern = r"至少|不低于|不少于|大于|超过|不超过|至多|小于|低于"
    after_operator_pattern = r"以上|及以上|或以上|起|以下|及以下|以内"
    match = re.search(
        rf"{field_terms}[^，。；;]{{0,8}}?"
        rf"(?P<before>{before_operator_pattern})?\s*"
        rf"(?P<value>\d+(?:\.\d+)?)\s*"
        rf"(?P<unit>{unit_pattern})\s*"
        rf"(?P<after>{after_operator_pattern})?",
        text,
        re.IGNORECASE,
    )
    if not match:
        # Recommendation requests often put the unit range next to the
        # product noun ("0.6 到 0.8 升水壶") instead of saying "容量".
        # The repeated unit keeps this parser scoped to capacity and the
        # verifier still requires the same SKU to expose a numeric value.
        if field_name == "capacity":
            bounded = re.search(
                r"(?P<low>\d+(?:\.\d+)?)(?:\s*(?:ml|\u6beb\u5347|l|\u5347))?\s*(?:\u5230|\u81f3|-|~|\uff5e)\s*"
                r"(?P<high>\d+(?:\.\d+)?)\s*(?P<unit>ml|\u6beb\u5347|l|\u5347)",
                text,
                re.IGNORECASE,
            )
            if bounded:
                low = float(bounded.group("low"))
                high = float(bounded.group("high"))
                if bounded.group("unit").lower() in {"l", "\u5347"}:
                    low *= 1000
                    high *= 1000
                return low, high, bounded.span()
        # A bare unit with an explicit approximation word is still an
        # unambiguous capacity request (for example, "1L 左右的小锅").
        # Keep the tolerance bounded so it remains usable by the existing
        # same-SKU numeric verifier rather than becoming a vague preference.
        if field_name == "capacity":
            threshold = re.search(
                rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{unit_pattern})\s*"
                rf"(?P<operator>{after_operator_pattern})",
                text,
                re.IGNORECASE,
            )
            if threshold:
                value = float(threshold.group("value"))
                if threshold.group("unit").lower() in {"l", "升"}:
                    value *= 1000
                operator = threshold.group("operator")
                if operator in {"以上", "及以上", "或以上", "起"}:
                    return value, None, threshold.span()
                return None, value, threshold.span()
            approximate = re.search(
                r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升)\s*(?:左右|上下|约|大约)",
                text,
                re.IGNORECASE,
            )
            if approximate:
                value = float(approximate.group(1))
                if approximate.group(2).lower() in {"l", "升"}:
                    value *= 1000
                return value * 0.8, value * 1.2, approximate.span()
        return None, None, None
    before = match.group("before") or ""
    after = match.group("after") or ""
    operator = before or after or "="
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    if field_name == "capacity" and unit in {"l", "升"}:
        value *= 1000
    if field_name == "weight" and unit in {"kg", "千克", "公斤"}:
        value *= 1000
    if operator in {"至少", "不低于", "不少于", "大于", "超过", "以上", "及以上", "或以上", "起"}:
        return value, None, match.span()
    if operator in {"不超过", "至多", "小于", "低于", "以下", "及以下", "以内"}:
        return None, value, match.span()
    return value, value, match.span()


def _recommendation_stove_subject(text: str) -> tuple[tuple[int, int], str | None] | None:
    stove_terms = r"卡式炉|酒精炉|气炉|炉具"
    action_terms = r"推荐|买|购买|选|挑"
    named_subject = re.search(rf"(?:这|那|哪)(?:一)?(?:款|个)?\s*({stove_terms})", text)
    if named_subject:
        value = named_subject.group(1)
        subtype = "card_stove" if value == "卡式炉" else "alcohol_stove" if value == "酒精炉" else None
        return named_subject.span(1), subtype
    match = re.search(
        rf"(?:{action_terms})[^，。；;]{{0,8}}?({stove_terms})|({stove_terms})[^，。；;]{{0,4}}?(?:推荐|怎么选|选哪个)",
        text,
    )
    if not match:
        # Longer natural phrases often put the product noun after several
        # constraints (for example “支持固体酒精的酒精炉”), beyond the
        # short action window above. The trailing noun is a recommendation
        # subject only when an action governs the same punctuation-bounded
        # clause; compatibility wording alone is not a recommendation.
        trailing = re.search(
            r"(?:\u5361\u5f0f\u7089|\u9152\u7cbe\u7089|\u71c3\u6c14\u7089|\u7089\u5177)\s*(?:\u63a8\u8350|\u54ea\u4e2a\u597d|\u4e70\u54ea\u4e2a|\u9009\u54ea\u4e2a)?[?？!！。]*$",
            text,
        )
        if not trailing:
            return None
        governing_text = text[:trailing.start()]
        if not re.search(rf"(?:{action_terms})[^，。；;]*$", governing_text):
            return None
        value = trailing.group(0).strip(" ?？!！。")
        subtype = (
            "card_stove"
            if "\u5361\u5f0f\u7089" in value
            else "alcohol_stove"
            if "\u9152\u7cbe\u7089" in value
            else None
        )
        return (trailing.start(), trailing.start() + len(value)), subtype
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
    allowed = {"subject_kind", "subject_kinds", "subject_subtype", "people", "heat_sources", "scenarios", "weight_preference", "price_preference", "storage_preference", "dishwasher_safe", "structure_preference"}
    if not constraints or any(key not in allowed for key in constraints):
        return None
    contract = RecommendationRequestContract()
    subject_kind = constraints.get("subject_kind")
    subject_categories = {"cookware": "锅具", "waterware": "水具", "stove": "炉具", "coffee_gear": "咖啡器具", "accessories": "配件"}
    if subject_kind is not None and subject_kind not in subject_categories:
        return None
    subject_kinds = constraints.get("subject_kinds")
    if subject_kinds == []:
        subject_kinds = None
    if subject_kinds is not None:
        if (
            not isinstance(subject_kinds, list)
            or not subject_kinds
            or len(subject_kinds) > 5
            or any(item not in subject_categories for item in subject_kinds)
        ):
            return None
        subject_kinds = list(dict.fromkeys(subject_kinds))
        if subject_kind is not None and subject_kind not in subject_kinds:
            return None
        contract.subject_kinds = subject_kinds
        contract.field_provenance["subject_kinds"] = {
            "source_turn": 1,
            "provenance": "validated_semantic_constraints",
        }
        # Only a multi-form scope stays open. A one-item list remains
        # compatible with the existing scalar structural verifier.
        if len(subject_kinds) > 1:
            contract.subject_scope_open = True
            subject_kind = None
        elif subject_kind is None:
            subject_kind = subject_kinds[0]
    if subject_kind is not None:
        contract.subject_kind = subject_kind
        contract.subject_category = subject_categories[subject_kind]
    subject_subtype = constraints.get("subject_subtype")
    if subject_subtype is not None:
        if not isinstance(subject_subtype, str) or not subject_subtype.strip():
            return None
        subject_subtype = subject_subtype.strip()
        allowed_subtypes = SEMANTIC_SUBJECT_SUBTYPE_KINDS.get(subject_kind, frozenset())
        if subject_subtype not in allowed_subtypes:
            return None
        contract.subject_subtype = subject_subtype
        contract.semantic_subject_subtype = True
        contract.field_provenance["subject_subtype"] = {
            "source_turn": 1,
            "provenance": "validated_semantic_constraints",
        }
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
        "charcoal": "炭火",
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
    # The live semantic adapter receives only scene context from Flash.  Named
    # dishes/operations belong to the semantic RAG evidence requirement; the
    # legacy soup token must not become a hard filter for a task such as 煮面.
    allowed_scenarios = {"camping", "hiking", "self_drive", "seaside", "hotpot"}
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
        # A semantic affordability preference is useful for ranking and
        # explanation, but it is not a product eligibility fact unless the
        # customer supplies a concrete price ceiling or an explicit recorded
        # price-positioning requirement.  Product catalogue rows do not carry
        # live prices reliably enough to reject every candidate here.
        _append_unique(contract.soft_preferences, "budget")
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
    structure_preference = constraints.get("structure_preference")
    if structure_preference is not None:
        if structure_preference != "non_split":
            return None
        contract.structure_preference = structure_preference
        _append_unique(contract.hard_constraints, "structure")
    for key in ("subject_category", "people", "heat_sources", "scenario", "weight", "price_positioning", "storage", "dishwasher", "structure"):
        present = {
            "subject_category": bool(contract.subject_category),
            "people": contract.people_min is not None,
            "heat_sources": bool(contract.heat_sources),
            "scenario": bool(contract.scenario),
            "weight": bool(contract.weight_preference),
            "price_positioning": bool(contract.budget_level),
            "storage": bool(contract.storage_required),
            "dishwasher": bool(contract.dishwasher_safe_required),
            "structure": bool(contract.structure_preference),
        }[key]
        if present:
            contract.field_provenance[key] = {"source_turn": 1, "provenance": "validated_semantic_preplan"}
    signal_count = len(contract.hard_constraints) + len(contract.soft_preferences)
    contract.confidence = "high" if (contract.subject_category or contract.subject_kinds) and signal_count >= 2 else "medium"
    return contract


_SEMANTIC_RECOMMENDATION_PREDICATE_OPERATORS = {
    "material": {"contains"},
    "surface_finish": {"contains", "="},
    "capacity": {">=", ">", "<=", "<", "=", "between"},
    "weight": {">=", ">", "<=", "<", "=", "between"},
    "dimensions": {"contains", "="},
    "people": {">=", ">", "<=", "<", "=", "between"},
    "color": {"contains", "="},
    "heat_source": {"supports", "not_supports"},
    "usage_scene": {"contains"},
    "waterproof": {"="},
}

# These fields are customer-language properties rather than closed numeric or
# compatibility values.  A literal mismatch is not negative evidence: the
# same-SKU semantic evidence packet may contain a valid paraphrase such as
# “陶瓷不沾” for a request for a non-stick coating.
_SEMANTIC_TEXT_PREDICATE_FIELDS = {
    "material",
    "surface_finish",
    "dimensions",
    "color",
    "usage_scene",
}

# Flash uses stable ontology values for closed compatibility predicates while
# the evidence span remains in the customer's language.  This is a schema
# adapter, not an intent router: it only proves that a typed heat-source value
# such as ``alcohol_stove`` is anchored by the current-turn phrase ``酒精炉``.
_SEMANTIC_HEAT_SOURCE_LABELS = {
    # Flash emits the stable enum; the customer can use an ordinary Chinese
    # variant such as “气炉”.  These are typed schema aliases used only to
    # bind that enum to the customer's evidence and the same-SKU heat field;
    # they are not an intent or route detector.
    "card_stove": ("卡式炉", "卡式灶"),
    "gas_stove": (
        "燃气炉",
        "燃气灶",
        "气炉",
        "气灶",
        "高山气罐",
        "高山罐",
        "液化气罐",
        "卡式气罐",
        "气罐",
        "气瓶",
    ),
    "alcohol_stove": ("酒精炉", "酒精灶"),
    "open_flame": ("明火", "明火直烧"),
    "charcoal": ("炭火", "木炭", "竹炭"),
    "induction": ("电磁炉", "电磁灶"),
}


def _semantic_heat_source_labels(value: Any) -> tuple[str, ...]:
    canonical = str(value or "").strip()
    labels = _SEMANTIC_HEAT_SOURCE_LABELS.get(canonical)
    if labels:
        return tuple(labels)
    return (canonical,) if canonical else ()


def _semantic_predicate_span_anchors_field(
    evidence_span: str,
    *,
    field_name: str,
    normalized_value: Any,
    unit: str | None,
) -> bool:
    """Prove that a model predicate came from the same kind of customer fact.

    An exact substring proves turn provenance but not ontology: a planner can
    otherwise cite ``露营`` while inventing ``heat_source=户外炉具``. This
    check validates only field shape (numeric unit/count or the normalized
    textual value), never rediscovers intent or maps product aliases.
    """
    span = str(evidence_span or "").strip().casefold()
    if not span:
        return False
    quantity = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万半]+)"
    if field_name == "people":
        return bool(re.search(rf"(?:{quantity}\s*(?:个)?人|单人|双人)", span))
    if field_name == "capacity":
        return bool(re.search(rf"{quantity}\s*(?:ml|毫升|l|升)", span, re.I))
    if field_name == "weight":
        return bool(re.search(rf"{quantity}\s*(?:g|克|kg|千克|公斤)", span, re.I))
    if field_name == "dimensions":
        return bool(re.search(rf"{quantity}\s*(?:mm|毫米|cm|厘米|m|米|寸|英寸)", span, re.I))
    if field_name == "waterproof":
        return "防水" in span or "不防水" in span
    if field_name == "heat_source":
        return any(
            label.casefold() in span
            for label in _semantic_heat_source_labels(normalized_value)
        )
    if isinstance(normalized_value, str):
        normalized_text = normalized_value.strip().casefold()
        return bool(normalized_text and normalized_text in span)
    return False


def _normalize_semantic_predicate_value(
    value: Any,
    *,
    field_name: str,
    unit: str | None,
) -> tuple[Any, str | None] | None:
    """Normalize a model-authored typed value without interpreting wording."""
    normalized_unit = str(unit or "").strip().casefold()

    def normalize_number(item: Any) -> float | int | None:
        if type(item) not in {int, float}:
            return None
        number = float(item)
        if number < 0:
            return None
        if field_name == "capacity":
            if normalized_unit in {"l", "升"}:
                number *= 1000
            return number
        if field_name == "weight":
            if normalized_unit in {"kg", "千克", "公斤"}:
                number *= 1000
            return number
        if field_name == "people":
            return int(number) if number.is_integer() and number >= 1 else None
        return number

    if field_name in {"capacity", "weight", "people"}:
        if isinstance(value, list):
            if len(value) != 2:
                return None
            normalized_values = [normalize_number(item) for item in value]
            if any(item is None for item in normalized_values):
                return None
            if normalized_values[0] > normalized_values[1]:
                return None
            normalized_value: Any = normalized_values
        else:
            normalized_value = normalize_number(value)
            if normalized_value is None:
                return None
        canonical_unit = "ml" if field_name == "capacity" else "g" if field_name == "weight" else None
        return normalized_value, canonical_unit
    if field_name == "waterproof":
        return (True, None) if value is True else None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip(), str(unit or "").strip() or None


_SEMANTIC_SUBJECT_IDENTITY_ALIASES = {
    # These are canonical subject labels emitted by the semantic preplan.  The
    # adapter is deliberately applied to that already-validated field rather
    # than scanning the raw customer question, so it binds SKU identity
    # without recreating the old phrase-based intent route.
    "水杯": ("水具", "waterware", "cup"),
    "杯子": ("水具", "waterware", "cup"),
    "保温杯": ("水具", "waterware", "cup"),
    "水壶": ("水具", "waterware", "kettle"),
    "烧水壶": ("水具", "waterware", "kettle"),
    "茶壶": ("水具", "waterware", "kettle"),
    "水具": ("水具", "waterware", None),
}


def _semantic_subject_identity(
    subject_text: str | None,
) -> tuple[str, str, str | None] | None:
    """Resolve a small typed identity from the semantic subject field only."""
    normalized = re.sub(r"\s+", "", str(subject_text or "").strip().casefold())
    return _SEMANTIC_SUBJECT_IDENTITY_ALIASES.get(normalized)


def build_semantic_recommendation_request_contract(
    *,
    question: str,
    semantic_constraints: dict[str, Any] | None,
    predicate_constraints: list[dict[str, Any]] | None,
    semantic_subject_text: str | None = None,
) -> RecommendationRequestContract | None:
    """Build the live recommendation contract only from Flash semantics.

    The question is used solely to prove that each model-supplied evidence span
    belongs to the current customer turn.  No keyword, alias, or regex is used
    to rediscover the customer's meaning.  ``semantic_subject_text`` is the
    already-validated subject identity from the same semantic preplan; its
    narrow ontology adapter keeps a cup and kettle from crossing SKU scope.
    A model-supplied ``subject_subtype`` remains the authoritative semantic
    refinement for the live recommendation path; it is passed to the RAG
    coverage adjudicator rather than converted into a local name match.
    """
    contract = _recommendation_contract_from_validated_semantic_constraints(
        semantic_constraints
    ) or RecommendationRequestContract()
    subject_identity = _semantic_subject_identity(semantic_subject_text)
    if subject_identity is not None:
        subject_category, subject_kind, subject_subtype = subject_identity
        if contract.subject_kind and contract.subject_kind != subject_kind:
            # Contradictory semantic fields must fail closed rather than let a
            # broad model kind override the more specific subject identity.
            return None
        if contract.subject_kinds and subject_kind not in contract.subject_kinds:
            # A typed subject cannot silently override a multi-form semantic
            # scope supplied by the preplan.
            return None
        contract.subject_category = contract.subject_category or subject_category
        contract.subject_kind = contract.subject_kind or subject_kind
        if subject_subtype and contract.subject_subtype and contract.subject_subtype != subject_subtype:
            # The model supplied two incompatible semantic views of the
            # requested product form.  Do not let either one silently win.
            return None
        if subject_subtype and not contract.subject_subtype:
            contract.subject_subtype = subject_subtype
            contract.semantic_subject_subtype = True
        contract.field_provenance["subject_category"] = {
            "source_turn": 1,
            "provenance": "validated_semantic_subject",
        }
    if not contract.subject_category and not contract.subject_kind and not contract.subject_kinds:
        # Keep an untyped semantic subject open for RAG recall and Flash's
        # same-SKU product-form adjudication. This is a contract state, not a
        # lexical fallback to a guessed product category.
        contract.subject_scope_open = True
    raw_predicates = predicate_constraints or []
    if not isinstance(raw_predicates, list) or len(raw_predicates) > 8:
        return None
    text = str(question or "")
    normalized_predicates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_predicates):
        if not isinstance(raw, dict):
            return None
        field_name = str(raw.get("field") or "").strip()
        operator = str(raw.get("operator") or "").strip()
        evidence_span = str(raw.get("evidence_span") or "").strip()
        # Older semantic plans did not carry an importance field. Preserve
        # their former behavior for typed numeric/compatibility predicates,
        # while treating an unannotated textual property as ranking context;
        # a newer plan can explicitly promote that property to required.
        default_importance = (
            "preferred"
            if field_name in {"material", "surface_finish", "dimensions", "color", "usage_scene"}
            else "required"
        )
        importance = str(raw.get("importance") or default_importance).strip().lower()
        if (
            field_name not in _SEMANTIC_RECOMMENDATION_PREDICATE_OPERATORS
            or operator not in _SEMANTIC_RECOMMENDATION_PREDICATE_OPERATORS[field_name]
            or importance not in {"required", "preferred"}
        ):
            return None
        if not evidence_span or evidence_span not in text:
            # A model may express the same customer meaning with a normalized
            # or paraphrased span.  Do not let the retired literal-evidence
            # gate reject the whole semantic request in that case.  The
            # structured semantic constraints and the later same-SKU
            # coverage adjudicator remain authoritative; this individual
            # predicate simply cannot become a deterministic hard filter
            # without a current-turn anchor.
            continue
        normalized = _normalize_semantic_predicate_value(
            raw.get("value"),
            field_name=field_name,
            unit=raw.get("unit"),
        )
        if normalized is None:
            return None
        value, unit = normalized
        if not _semantic_predicate_span_anchors_field(
            evidence_span,
            field_name=field_name,
            normalized_value=value,
            unit=unit,
        ):
            # Preserve the semantic recommendation but drop a fabricated hard
            # field. The complete-question coverage model can still interpret
            # the customer's purpose; this predicate simply cannot authorize
            # deterministic candidate rejection.
            continue
        predicate = {
            "field": field_name,
            "operator": operator,
            "value": value,
            "unit": unit,
            "evidence_span": evidence_span,
        }
        if "importance" in raw:
            predicate["importance"] = importance
        normalized_predicates.append(predicate)
        label = f"predicate:{index}:{field_name}"
        # Numeric/boolean predicates and explicit heat-source compatibility
        # have deterministic same-SKU evaluators. Other textual predicates
        # remain semantic because catalogue wording may be a valid paraphrase
        # rather than a literal substring.
        # Textual product properties are intentionally left to the semantic
        # same-SKU evidence adjudicator.  A local literal mismatch is not a
        # factual contradiction: for example, “陶瓷不沾” may establish a
        # customer's request for a non-stick coating.  Numeric and closed
        # compatibility predicates still use this deterministic hard boundary.
        if importance == "required" and field_name not in _SEMANTIC_TEXT_PREDICATE_FIELDS:
            _append_unique(contract.hard_constraints, label)
        contract.source_spans[label] = (
            text.index(evidence_span),
            text.index(evidence_span) + len(evidence_span),
        )
        contract.field_provenance[label] = {
            "source_turn": 1,
            "provenance": "validated_semantic_predicate",
        }
    contract.predicate_constraints = normalized_predicates
    heat_source_predicates = [
        item
        for item in normalized_predicates
        if str(item.get("field") or "").strip() == "heat_source"
    ]
    if (
        contract.heat_sources
        and heat_source_predicates
        and all(
            str(item.get("importance") or "required").strip().lower()
            == "preferred"
            for item in heat_source_predicates
        )
    ):
        # The abstract constraint object historically treated every
        # ``heat_sources`` value as a hard filter.  Once Flash has reread the
        # complete turn and marked the corresponding typed predicates as
        # preferred, keep the preference on the typed predicates for ranking
        # and evidence, but do not reject candidates that support another
        # usable heat source.  This is semantic provenance preservation, not a
        # customer-language keyword rule.
        contract.heat_sources = []
        contract.hard_constraints = [
            item for item in contract.hard_constraints if item != "heat_source"
        ]
        contract.field_provenance.pop("heat_sources", None)
        _append_unique(contract.soft_preferences, "heat_source")
    # The abstract constraint object and the typed predicates are two views of
    # the same Flash interpretation.  Do not let an unanchored heat-source
    # value in the abstract view become a hard catalogue filter when the typed
    # view was dropped for lack of a customer span.  This is especially
    # important for cooking actions: boiling water or cooking noodles does not
    # name a gas, alcohol, open-flame, or induction source.
    if contract.heat_sources and not any(
        str(item.get("field") or "").strip() == "heat_source"
        for item in normalized_predicates
        if isinstance(item, dict)
    ):
        contract.heat_sources = []
        contract.hard_constraints = [
            item for item in contract.hard_constraints if item != "heat_source"
        ]
        contract.field_provenance.pop("heat_sources", None)
    signal_count = len(contract.hard_constraints) + len(contract.soft_preferences)
    contract.confidence = "high" if (contract.subject_category or contract.subject_kind or contract.subject_kinds) and signal_count else "medium"
    return contract


def build_recommendation_request_contract(
    question: str,
    plan: dict[str, Any] | None = None,
    intent_result: dict[str, Any] | None = None,
    *,
    semantic_constraints: dict[str, Any] | None = None,
) -> RecommendationRequestContract:
    text = str(question or "").strip()
    # This is a catalogue-scope boundary, not a product recommendation rule:
    # an explicit bag/accessory noun must not be widened to cookware because a
    # bundle happens to mention storage in its marketing copy.
    accessory_terms = (
        "收纳包", "收纳袋", "配件", "附件", "锅夹", "点火器",
        "炉子内胆", "炉具内胆", "炉芯", "炉心", "内胆",
    )
    category_exclusions, category_exclusion_spans = _literal_category_exclusions(text)
    sku_exclusions, sku_exclusion_spans = _literal_sku_exclusions(text)
    accessory_occurrences = [
        match.span()
        for term in accessory_terms
        for match in re.finditer(re.escape(term), text)
    ]
    explicit_accessory_subject = any(
        not _is_negated_category_term(text, span)
        for span in accessory_occurrences
    )
    storage_bag_subtype = (
        "storage_bag"
        if any(term in text for term in ("收纳包", "收纳袋", "装备包", "野炊包", "餐具包", "厨具包"))
        else None
    )
    waterware_subtype = (
        "kettle"
        if any(term in text for term in ("水壶", "烧水壶", "茶壶", "壶"))
        else "cup" if any(term in text for term in ("水杯", "杯子", "保温杯")) else None
    )
    has_waterware_subject = any(term in text for term in ("水壶", "水杯", "水具", "杯子", "壶"))
    explicit_accessory_requirements = []
    if any(term in text for term in ("蒸屉", "蒸笼", "蒸米饭", "蒸饭")):
        explicit_accessory_requirements.append("蒸屉兼容")
    cookware_subject_text = re.sub(r"火锅|涮锅", "", text)
    has_cookware_subject = any(term in text for term in ("锅具", "套锅", "炊具", "烤盘", "煎盘")) or (
        "锅" in cookware_subject_text
    )
    stove_subject = _recommendation_stove_subject(text)
    semantic_contract = _recommendation_contract_from_validated_semantic_constraints(semantic_constraints)
    if semantic_contract is not None:
        if explicit_accessory_subject:
            semantic_contract.subject_category = "配件"
            semantic_contract.subject_kind = "accessories"
            semantic_contract.subject_subtype = storage_bag_subtype
            semantic_contract.source_spans["subject"] = next(
                term for term in accessory_terms if term in text
            )
            semantic_contract.field_provenance["subject_category"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_subject",
            }
        elif has_cookware_subject:
            # The direct object owns the recommendation subject. A stove
            # mentioned as a compatible heat source must not turn an explicit
            # pan/griddle request into a stove recommendation.
            semantic_contract.subject_category = "锅具"
            semantic_contract.subject_kind = "cookware"
            semantic_contract.subject_subtype = None
            semantic_contract.source_spans["subject"] = _span(text, r"锅具|套锅|炊具|烤盘|煎盘|锅")
            semantic_contract.field_provenance["subject_category"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_subject",
            }
        elif has_waterware_subject:
            semantic_contract.subject_category = "水具"
            semantic_contract.subject_kind = "waterware"
            semantic_contract.subject_subtype = waterware_subtype
            semantic_contract.source_spans["subject"] = next(
                term for term in ("水壶", "烧水壶", "茶壶", "水具", "壶") if term in text
            )
            semantic_contract.field_provenance["subject_category"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_subject",
            }
        elif stove_subject:
            semantic_contract.subject_category = "炉具"
            semantic_contract.subject_kind = "stove"
            semantic_contract.subject_subtype = stove_subject[1]
            semantic_contract.source_spans["subject"] = stove_subject[0]
            semantic_contract.field_provenance["subject_category"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_subject",
            }
        if explicit_accessory_requirements:
            semantic_contract.accessory_requirements = list(explicit_accessory_requirements)
            _append_unique(semantic_contract.hard_constraints, "accessory")
            semantic_contract.field_provenance["accessory"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_accessory_requirement",
            }
        elif semantic_contract.subject_kind == "waterware" and waterware_subtype:
            semantic_contract.subject_subtype = waterware_subtype
            semantic_contract.source_spans["subject"] = next(
                term
                for term in (("水壶", "烧水壶", "茶壶", "壶") if waterware_subtype == "kettle" else ("水杯", "杯子", "保温杯"))
                if term in text
            )
        elif semantic_contract.subject_kind == "stove":
            # The semantic preplan often keeps only the broad stove kind.
            # Preserve an explicit current-turn subtype (酒精炉/卡式炉)
            # before verification so a neighbouring gas-stove result cannot
            # consume the request merely because the provider omitted that
            # narrower field.
            stove_subject = _recommendation_stove_subject(text)
            if stove_subject and stove_subject[1]:
                semantic_contract.subject_subtype = stove_subject[1]
                semantic_contract.source_spans["subject"] = stove_subject[0]
        structure_preference = _explicit_structure_preference(text)
        if category_exclusions:
            semantic_contract.excluded_categories = list(dict.fromkeys([
                *semantic_contract.excluded_categories,
                *category_exclusions,
            ]))
            semantic_contract.source_spans["excluded_categories"] = category_exclusion_spans
        if sku_exclusions:
            semantic_contract.exclusions = list(dict.fromkeys([
                *semantic_contract.exclusions,
                *sku_exclusions,
            ]))
            semantic_contract.source_spans["exclusions"] = sku_exclusion_spans
        if structure_preference:
            semantic_contract.structure_preference = structure_preference
            _append_unique(semantic_contract.hard_constraints, "structure")
            semantic_contract.source_spans["structure"] = _span(
                text,
                r"不要分体(?:式)?|不想要分体(?:式)?|不需要分体(?:式)?|不选分体(?:式)?|排除分体(?:式)?|不考虑分体(?:式)?",
            )
            semantic_contract.field_provenance["structure"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_requirement",
            }
        # Retain explicit literal capacity ranges for same-SKU verification.
        capacity_min, capacity_max, capacity_span = _parse_numeric_limit(text, "capacity")
        if capacity_span:
            semantic_contract.capacity_requirement = "numeric"
            semantic_contract.capacity_min_ml = capacity_min
            semantic_contract.capacity_max_ml = capacity_max
            semantic_contract.source_spans["capacity"] = capacity_span
            _append_unique(semantic_contract.hard_constraints, "capacity")
            semantic_contract.field_provenance["capacity"] = {
                "source_turn": 1,
                "provenance": "current_turn",
            }
        elif any(term in text for term in ("别太大", "不要太大", "小一点", "小一些", "小容量")):
            _append_unique(semantic_contract.soft_preferences, "capacity")
            semantic_contract.field_provenance["capacity"] = {
                "source_turn": 1,
                "provenance": "current_turn",
            }
        # A semantic preplan may describe only the product category.  Retain
        # explicit heat-source language from the customer turn as a hard
        # boundary instead of treating that omission as permission to widen
        # the recommendation to a nearby heat source.
        explicit_heat_aliases = (
            ("燃气炉", ("燃气炉",)),
            ("卡式炉", ("卡式炉",)),
            ("明火", ("明火直烧", "直接明火", "明火加热", "适配明火", "明火")),
            ("炭火", ("炭火", "炭烧", "烧炭", "碳火", "碳烧", "木炭", "炭炉", "碳炉")),
        )
        explicit_heat_added = False
        for normalized, terms in explicit_heat_aliases:
            has_positive_term = _contains_non_negated_term(text, terms)
            if semantic_contract.subject_kind == "stove" and has_positive_term:
                continue
            if has_positive_term:
                _append_unique(semantic_contract.heat_sources, normalized)
                explicit_heat_added = True
        if semantic_contract.subject_kind != "stove":
            from app.services import customer_agent_intent_service

            normalized_heat = customer_agent_intent_service._normalize_structured_filter_value(
                "specs.heat_source",
                text,
            )
            if normalized_heat == "酒精炉" and _contains_non_negated_term(text, ("酒精炉", "酒精")):
                _append_unique(semantic_contract.heat_sources, normalized_heat)
                explicit_heat_added = True
        if semantic_contract.heat_sources:
            _append_unique(semantic_contract.hard_constraints, "heat_source")
        if explicit_heat_added:
            semantic_contract.field_provenance["heat_sources"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_requirement",
            }
        explicit_fuel_subtypes = _explicit_alcohol_fuel_subtypes(text)
        if explicit_fuel_subtypes and semantic_contract.subject_kind != "cookware":
            semantic_contract.fuel_subtypes = list(dict.fromkeys(explicit_fuel_subtypes))
            semantic_contract.fuel_subtype = (
                semantic_contract.fuel_subtypes[0]
                if len(semantic_contract.fuel_subtypes) == 1
                else None
            )
            _append_unique(semantic_contract.hard_constraints, "fuel_subtype")
            semantic_contract.source_spans["fuel_subtype"] = _span(
                text,
                "\u56fa\u4f53\u9152\u7cbe|\u56fa\u6001\u9152\u7cbe|\u9152\u7cbe\u5757|\u56fa\u4f53\u71c3\u6599|\u6db2\u4f53\u9152\u7cbe",
            )
            semantic_contract.field_provenance["fuel_subtype"] = {
                "source_turn": 1,
                "provenance": "current_turn_explicit_requirement",
            }
        exact_grade = _exact_stainless_grade(text)
        if exact_grade:
            semantic_contract.materials = [exact_grade]
            _append_unique(semantic_contract.hard_constraints, "material")
            semantic_contract.source_spans["material"] = _span(text, r"(?i)(?:316L|304|430)\s*不锈钢|不锈钢\s*(?:316L|304|430)")
            semantic_contract.field_provenance["material"] = {
                "source_turn": 1,
                "provenance": "current_turn_exact_material_grade",
            }
        else:
            grade_options = _stainless_grade_options(text)
            if grade_options:
                semantic_contract.materials = ["或".join(grade_options)]
                _append_unique(semantic_contract.hard_constraints, "material")
                semantic_contract.source_spans["material"] = _span(text, r"(?i)304\s*(?:或|或者|和|/|、|及)\s*316|316\s*(?:或|或者|和|/|、|及)\s*304")
                semantic_contract.field_provenance["material"] = {
                    "source_turn": 1,
                    "provenance": "current_turn_material_grade_options",
                }
        # Once the semantic planner has supplied a scenario contract, literal
        # workflow words such as “煮汤” must not expand that validated hard
        # condition and reject otherwise matching candidates.
        semantic_scenarios = list(semantic_contract.scenario)
        _apply_literal_use_requirements(semantic_contract, text)
        if semantic_scenarios:
            semantic_contract.scenario = semantic_scenarios
        return semantic_contract
    contract = RecommendationRequestContract()
    if explicit_accessory_subject:
        contract.subject_category = "配件"
        contract.subject_kind = "accessories"
        contract.subject_subtype = storage_bag_subtype
        contract.source_spans["subject"] = next(term for term in accessory_terms if term in text)
    elif has_cookware_subject:
        contract.subject_category = "锅具"
        contract.subject_kind = "cookware"
        contract.source_spans["subject"] = _span(text, r"锅具|套锅|炊具|锅")
    elif has_waterware_subject:
        contract.subject_category = "水具"
        contract.subject_kind = "waterware"
        contract.subject_subtype = waterware_subtype
    elif stove_subject:
        contract.subject_category = "炉具"
        contract.subject_kind = "stove"
        contract.source_spans["subject"] = stove_subject[0]
        contract.subject_subtype = stove_subject[1]
    elif any(term in text for term in ("咖啡", "磨豆", "磨豆器", "手冲")):
        contract.subject_category = "咖啡器具"
        contract.subject_kind = "coffee_gear"

    if category_exclusions:
        contract.excluded_categories = list(dict.fromkeys(category_exclusions))
        contract.source_spans["excluded_categories"] = category_exclusion_spans
    if sku_exclusions:
        contract.exclusions = list(dict.fromkeys(sku_exclusions))
        contract.source_spans["exclusions"] = sku_exclusion_spans

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
    elif any(term in text for term in ("容量大", "容量要大", "大容量", "容量宽裕", "容量够用", "容量别太小", "容量不要太小")):
        contract.capacity_requirement = "spacious"
        _append_unique(contract.soft_preferences, "capacity")
    elif any(term in text for term in ("别太大", "不要太大", "小一点", "小一些", "小容量")):
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
        ("炭火", ("炭火", "炭烧", "烧炭", "碳火", "碳烧", "木炭", "炭炉", "碳炉")),
    )
    for normalized, terms in heat_aliases:
        has_positive_term = _contains_non_negated_term(text, terms)
        if contract.subject_kind == "stove" and has_positive_term:
            continue
        if has_positive_term:
            _append_unique(contract.heat_sources, normalized)
    if contract.subject_kind != "stove":
        from app.services import customer_agent_intent_service

        normalized_heat = customer_agent_intent_service._normalize_structured_filter_value(
            "specs.heat_source",
            text,
        )
        if normalized_heat == "酒精炉" and _contains_non_negated_term(text, ("酒精炉", "酒精")):
            _append_unique(contract.heat_sources, normalized_heat)
            contract.source_spans["heat_source"] = _span(text, r"液体酒精|固体酒精|酒精燃料|酒精炉")
    if contract.heat_sources:
        _append_unique(contract.hard_constraints, "heat_source")

    explicit_fuel_subtypes = _explicit_alcohol_fuel_subtypes(text)
    if explicit_fuel_subtypes and contract.subject_kind != "cookware":
        contract.fuel_subtypes = list(dict.fromkeys(explicit_fuel_subtypes))
        contract.fuel_subtype = contract.fuel_subtypes[0] if len(contract.fuel_subtypes) == 1 else None
        _append_unique(contract.hard_constraints, "fuel_subtype")
        contract.source_spans["fuel_subtype"] = _span(
            text,
            "\u56fa\u4f53\u9152\u7cbe|\u56fa\u6001\u9152\u7cbe|\u9152\u7cbe\u5757|\u56fa\u4f53\u71c3\u6599|\u6db2\u4f53\u9152\u7cbe",
        )

    structure_preference = _explicit_structure_preference(text)
    if structure_preference:
        contract.structure_preference = structure_preference
        _append_unique(contract.hard_constraints, "structure")
        contract.source_spans["structure"] = _span(
            text,
            r"不要分体(?:式)?|不想要分体(?:式)?|不需要分体(?:式)?|不选分体(?:式)?|排除分体(?:式)?|不考虑分体(?:式)?",
        )

    if explicit_accessory_requirements:
        contract.accessory_requirements = list(explicit_accessory_requirements)
        _append_unique(contract.hard_constraints, "accessory")

    exact_grade = _exact_stainless_grade(text)
    grade_options = _stainless_grade_options(text)
    material_terms = (
        (exact_grade,)
        if exact_grade
        else (("或".join(grade_options),) if grade_options else ("不锈钢", "硬质氧化铝", "铝合金", "钛"))
    )
    if grade_options:
        contract.materials.append("或".join(grade_options))
    else:
        for material in material_terms:
            if material in text:
                contract.materials.append(material)
    if contract.materials:
        _append_unique(contract.hard_constraints, "material")

    if any(term in text for term in ("更便宜", "便宜一点的替代", "便宜些")):
        contract.relative_price_preference = "cheaper_than_anchor"
        contract.budget_level = "relative"
    elif any(term in text for term in ("预算中等", "中等预算")):
        contract.budget_level = "medium"
    elif any(term in text for term in ("预算别太高", "预算不高", "预算有限", "预算紧", "预算不多", "低预算", "便宜点", "性价比")):
        contract.budget_level = "low"
    if contract.budget_level:
        _append_unique(contract.soft_preferences, "budget")

    _apply_literal_use_requirements(contract, text)

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
        "windproof",
        "portability",
        "storage",
        "cleaning",
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
            "windproof": contract.windproof_required,
            "portability": contract.portability_required,
            "storage": contract.storage_required,
            "cleaning": contract.cleaning_required,
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
        ("excluded_categories", "excluded_categories"),
    ):
        current_values = list(getattr(current_contract, field_name) or [])
        if not current_values:
            continue
        inherited_values = list(getattr(effective, field_name) or [])
        setattr(effective, field_name, list(dict.fromkeys([*inherited_values, *current_values])))
        provenance[provenance_key] = {"source_turn": current_turn, "provenance": "current_turn_addition"}
    for field_name in ("stability_required", "windproof_required", "portability_required", "storage_required", "cleaning_required"):
        if getattr(current_contract, field_name):
            setattr(effective, field_name, True)
            provenance[field_name.removesuffix("_required")] = {"source_turn": current_turn, "provenance": "current_turn_addition"}

    effective.source_spans = {**inherited_contract.source_spans, **current_contract.source_spans}
    effective.excluded_categories = list(dict.fromkeys([
        *inherited_contract.excluded_categories,
        *current_contract.excluded_categories,
    ]))
    if effective.excluded_categories:
        provenance["excluded_categories"] = {
            "source_turn": current_turn,
            "provenance": "current_turn_addition",
        }
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


def _row_matches_excluded_category(row: dict[str, Any], excluded_categories: list[str]) -> bool:
    structured_category = " ".join(
        str(row.get(key) or "")
        for key in ("category", "sub_category")
    ).strip()
    # Category fields are the authoritative scope. Product names can mention
    # the compatible appliance (for example “酒精炉单锅”) without turning a
    # cookware row into a stove. Use names only when imported category data is
    # absent or wholly generic.
    category_text = structured_category
    if not structured_category or structured_category in {"产品", "户外用品", "其他", "未分类"}:
        category_text = " ".join(
            str(row.get(key) or "")
            for key in ("category", "sub_category", "product_name_cn", "product_name_en")
        )
    aliases = {
        "炉具": ("炉具", "炉子", "燃气炉", "卡式炉", "酒精炉", "气炉"),
        "配件": ("配件", "附件", "锅夹", "点火器", "炉芯", "内胆"),
        "锅具": ("锅具", "套锅", "炊具"),
        "水具": ("水具", "水壶", "水杯"),
    }
    for excluded in excluded_categories or []:
        terms = aliases.get(str(excluded or "").strip(), (str(excluded or "").strip(),))
        if any(term and term in category_text for term in terms):
            return True
    return False


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


def _waterware_subject_identity_is_valid(contract: RecommendationRequestContract, row: dict[str, Any]) -> bool:
    """Keep an explicit kettle/cup request inside its named container type."""
    if not contract.subject_subtype:
        return True
    identity = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "name", "title")
    ).lower()
    if contract.subject_subtype == "kettle":
        return any(term in identity for term in ("水壶", "烧水壶", "茶壶", "kettle"))
    if contract.subject_subtype == "cup":
        return any(term in identity for term in ("水杯", "杯子", "保温杯", "cup"))
    return False


def _waterware_subtype_evidence(
    contract: RecommendationRequestContract,
    row: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, str | None]:
    if contract.subject_kind != "waterware" or not contract.subject_subtype:
        return True, None, None
    identity = " ".join(
        str(row.get(key) or "")
        for key in ("product_name_cn", "product_name_en", "name", "title")
    ).strip()
    matched = _waterware_subject_identity_is_valid(contract, row)
    evidence = _condition(
        "verified" if matched else "conflict",
        "product_name_cn",
        identity,
        subject_subtype=contract.subject_subtype,
    )
    return matched, evidence, None if matched else "subject_subtype_mismatch"


def _subject_evidence(contract: RecommendationRequestContract, row: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
    sku = str(row.get("sku") or "").strip().upper()
    category = str(row.get("category") or "").strip()
    scope = _row_scope(row)
    evidence = {"status": "verified", "field_source": "product.category", "raw_value": category, "scope": scope}
    if sku and sku in {str(item or "").strip().upper() for item in contract.exclusions}:
        evidence.update({"status": "conflict", "field_source": "current_turn_sku_exclusion", "excluded_sku": sku})
        return False, evidence, "excluded_sku"
    if _row_matches_excluded_category(row, contract.excluded_categories):
        evidence["status"] = "conflict"
        evidence["excluded_category"] = list(contract.excluded_categories)
        return False, evidence, "excluded_category"
    if contract.subject_scope_open:
        evidence["scope"] = "semantic_open"
        return True, evidence, None
    if contract.subject_category == "配件":
        if scope == "accessory" or "配件" in category:
            if contract.subject_subtype == "storage_bag":
                identity = " ".join(
                    str(row.get(key) or "")
                    for key in ("product_name_cn", "product_name_en", "title_cn", "website_title")
                ).lower()
                storage_terms = ("收纳包", "收纳袋", "装备包", "野炊包", "餐具包", "厨具包")
                if not any(term in identity for term in storage_terms):
                    evidence.update({"status": "conflict", "field_source": "product_identity"})
                    return False, evidence, "subject_subtype_mismatch"
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
    if (
        contract.subject_kind == "waterware"
        and not contract.semantic_subject_subtype
        and not _waterware_subject_identity_is_valid(contract, row)
    ):
        evidence.update({"status": "conflict", "field_source": "product_identity"})
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
    if contract.subject_kind != "stove" or not contract.subject_subtype:
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
    for match in re.finditer(rf"(?<![\d.])(\d+(?:\.\d+)?)\s*{unit_pattern}(?![A-Za-z])", text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit in {"l", "升", "kg", "千克", "公斤"}:
            value *= 1000
        values.append(value)
    return values


def _capacity_consistent_with_product_identity(row: dict[str, Any]) -> bool:
    """Do not treat a contradictory imported capacity cell as sealed evidence."""
    capacity_values = _numeric_values(row.get("capacity"), kind="capacity")
    identity_text = " ".join(
        str(value or "")
        for value in (
            row.get("product_name_cn") or row.get("product_name_en"),
            row.get("features") or row.get("technical_advantages"),
            row.get("long_description_cn"),
        )
    )
    identity_values = set(_numeric_values(identity_text, kind="capacity"))
    if (
        len(identity_values) == 1
        and capacity_values
        and next(iter(identity_values)) not in capacity_values
    ):
        return False

    # Imported rows occasionally attach the wrong size label to a numeric
    # value (for example, a smaller value labelled as "小锅" than the value
    # labelled "大锅").  Do not let the numeric verifier quietly use that
    # malformed cell to satisfy a capacity request.
    labelled_values: dict[str, list[float]] = {"大锅": [], "小锅": []}
    patterns = (
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ml|毫升|l|升)\s*(?P<label>大锅|小锅)",
        r"(?P<label>大锅|小锅)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ml|毫升|l|升)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, str(row.get("capacity") or ""), flags=re.IGNORECASE):
            amount = float(match.group("value"))
            if match.group("unit").casefold() in {"l", "升"}:
                amount *= 1000
            labelled_values[match.group("label")].append(amount)
    if labelled_values["大锅"] and labelled_values["小锅"]:
        return max(labelled_values["大锅"]) >= max(labelled_values["小锅"])
    return True


def _condition(status: str, source: str = "", raw: Any = None, **extra: Any) -> dict[str, Any]:
    result = {"status": status, "field_source": source, "raw_value": raw}
    result.update(extra)
    return result


def _compare_semantic_predicate(actual: Any, operator: str, target: Any) -> bool:
    if operator == "not_supports":
        actual_text = str(actual or "").casefold()
        labels = (
            tuple(target)
            if isinstance(target, (list, tuple, set))
            else (str(target or ""),)
        )
        return bool(labels and any(label.strip() for label in labels)) and not any(
            str(label or "").strip().casefold() in actual_text
            for label in labels
        )
    if operator == "supports" and isinstance(target, (list, tuple, set)):
        actual_text = str(actual or "").casefold()
        return any(
            str(label or "").strip().casefold() in actual_text
            for label in target
            if str(label or "").strip()
        )
    if operator in {"contains", "supports", "="} and not isinstance(target, (int, float, list, tuple, set)):
        actual_text = str(actual or "").casefold().replace("粘", "沾")
        target_text = str(target or "").casefold().replace("粘", "沾")
        return bool(target_text and target_text in actual_text)
    try:
        number = float(actual)
    except (TypeError, ValueError):
        return False
    if operator == ">=":
        return number >= float(target)
    if operator == ">":
        return number > float(target)
    if operator == "<=":
        return number <= float(target)
    if operator == "<":
        return number < float(target)
    if operator == "between":
        return float(target[0]) <= number <= float(target[1])
    return number == float(target)


def _semantic_predicate_evidence(
    row: dict[str, Any],
    predicate: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one typed predicate against only the candidate's own field."""
    field_name = str(predicate.get("field") or "")
    operator = str(predicate.get("operator") or "")
    target = predicate.get("value")
    comparison_target = target
    if field_name == "heat_source":
        # The planner's closed ontology is intentionally kept separate from
        # the catalogue's Chinese evidence text.  Normalize only this typed
        # relation before comparing; do not reinterpret any free-form request.
        comparison_target = _semantic_heat_source_labels(target)
    source_map = {
        "material": "body_material",
        "surface_finish": "surface_finish",
        "capacity": "capacity",
        "weight": "gross_weight_g",
        "dimensions": "size_info",
        "people": "target_audience",
        "color": "color",
        "heat_source": "heat_source",
        "usage_scene": "usage_scenarios",
        "waterproof": "waterproof",
    }
    source = source_map.get(field_name, "")
    raw = row.get(source) if source else None
    actual: Any = raw
    if field_name == "capacity":
        values = (
            _numeric_values(raw, kind="capacity")
            if _capacity_consistent_with_product_identity(row)
            else []
        )
        actual = max(values) if values else None
    elif field_name == "weight":
        values = _numeric_values(raw, kind="weight")
        if not values and isinstance(raw, (int, float)):
            values = [float(raw)]
        actual = values[0] if values else None
    elif field_name == "people":
        row_min, row_max, _, people_source = _people_range(row)
        source = people_source or source
        if row_min is None or row_max is None:
            actual = None
        elif operator in {">=", ">"}:
            actual = row_max
        elif operator in {"<=", "<"}:
            actual = row_min
        elif operator == "between":
            low, high = target
            matched = row_min <= float(low) and row_max >= float(high)
            return _condition(
                "verified" if matched else "conflict",
                source,
                raw,
                normalized_range=[row_min, row_max],
                target=target,
                operator=operator,
            )
        else:
            matched = row_min <= float(target) <= row_max
            return _condition(
                "verified" if matched else "conflict",
                source,
                raw,
                normalized_range=[row_min, row_max],
                target=target,
                operator=operator,
            )
    elif field_name == "waterproof":
        if raw is None:
            actual = None
        elif isinstance(raw, bool):
            actual = raw
        else:
            normalized = str(raw).strip().casefold()
            actual = normalized in {"true", "1", "yes", "是"}
    if actual is None or not _usable(raw):
        return _condition("unknown", source, raw, target=target, operator=operator)
    matched = _compare_semantic_predicate(actual, operator, comparison_target)
    if not matched and field_name in _SEMANTIC_TEXT_PREDICATE_FIELDS:
        return _condition(
            "unknown",
            source,
            raw,
            target=target,
            operator=operator,
            semantic_match_pending=True,
        )
    return _condition(
        "verified" if matched else "conflict",
        source,
        raw,
        normalized_value=actual,
        target=target,
        operator=operator,
    )


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
        # A subtype emitted by the validated semantic preplan is a product
        # identity meaning, not a deterministic name predicate.  Defer it to
        # the same-SKU RAG coverage adjudicator, which can distinguish a
        # product whose own evidence establishes the subtype from a product
        # that merely mentions it as a compatible fuel or nearby comparison.
        # Keep the legacy helper for contracts built by the retired/local
        # compatibility path and its focused tests.
        if contract.semantic_subject_subtype:
            subtype_ok = True
            subtype_evidence = _condition(
                "deferred",
                "semantic_same_sku_rag",
                contract.subject_subtype,
                subject_subtype=contract.subject_subtype,
            )
            subtype_reason = None
        else:
            subtype_ok, subtype_evidence, subtype_reason = _stove_subtype_evidence(contract, row)
        if subtype_evidence is not None:
            evidence["subject_subtype"] = subtype_evidence
        if subtype_reason:
            rejection_reasons.append(subtype_reason)
        subject_ok = subject_ok and subtype_ok
        if contract.semantic_subject_subtype:
            # The semantic preplan has already expressed the requested
            # waterware form.  Product names are not a reliable identity
            # authority here: a maintained cup may be named ``悠然杯`` or
            # ``camping mug`` without containing one of the legacy literal
            # aliases.  Keep the broad category check above, then let the
            # same-SKU RAG coverage adjudicator establish cup vs. kettle from
            # the product's own evidence.
            waterware_subtype_ok = True
            waterware_subtype_evidence = _condition(
                "deferred",
                "semantic_same_sku_rag",
                contract.subject_subtype,
                subject_subtype=contract.subject_subtype,
            )
            waterware_subtype_reason = None
        else:
            waterware_subtype_ok, waterware_subtype_evidence, waterware_subtype_reason = _waterware_subtype_evidence(contract, row)
        if waterware_subtype_evidence is not None:
            evidence["subject_subtype"] = waterware_subtype_evidence
        if waterware_subtype_reason:
            rejection_reasons.append(waterware_subtype_reason)
        subject_ok = subject_ok and waterware_subtype_ok

        if contract.structure_preference:
            structure_text = " ".join(
                str(row.get(key) or "")
                for key in (
                    "product_name_cn",
                    "product_name_en",
                    "category",
                    "sub_category",
                    "features",
                    "long_description_cn",
                    "usage_instruction",
                    "positioning",
                    "top_selling_points",
                )
            )
            split_terms = ("分体炉", "分体式", "远程炉头", "炉头分离", "炉具分体")
            integrated_terms = ("一体炉", "一体式", "整体炉", "整体", "桌炉一体", "一体收纳")
            if not _usable(structure_text):
                evidence["structure"] = _condition("unknown")
            elif any(term in structure_text for term in split_terms):
                evidence["structure"] = _condition("conflict", "product_structure_evidence", structure_text)
                rejection_reasons.append("structure_condition_not_met")
            elif any(term in structure_text for term in integrated_terms):
                evidence["structure"] = _condition("verified", "product_structure_evidence", structure_text)
            else:
                evidence["structure"] = _condition("unknown", "product_structure_evidence", structure_text)

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
                "hotpot": ("火锅", "涮锅"),
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

        capacity_values = (
            _numeric_values(row.get("capacity"), kind="capacity")
            if _capacity_consistent_with_product_identity(row)
            else []
        )
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

                gas_source_aliases = (
                    "燃气炉",
                    "燃气灶",
                    "气炉",
                    "气灶",
                    "高山气罐",
                    "高山罐",
                    "液化气罐",
                    "卡式气罐",
                    "气罐",
                    "气瓶",
                )
                matched = all(
                    customer_agent_intent_service._alcohol_stove_support_verdict(raw_heat) is True
                    if source == "酒精炉"
                    else any(
                        alias in raw_heat
                        for alias in (
                            gas_source_aliases
                            if source == "燃气炉"
                            else ("明火", "明火直烧")
                            if source == "明火"
                            else (source,)
                        )
                    )
                    for source in contract.heat_sources
                )
                evidence["heat_source"] = _condition("verified" if matched else "conflict", "heat_source", raw_heat)
                if not matched:
                    rejection_reasons.append("heat_source_condition_not_met")

        requested_fuel_subtypes = list(contract.fuel_subtypes or [])
        if not requested_fuel_subtypes and contract.fuel_subtype:
            requested_fuel_subtypes = [contract.fuel_subtype]
        if requested_fuel_subtypes:
            candidate_fuel_text = " ".join(
                str(row.get(key) or "")
                for key in (
                    "heat_source",
                    "product_name_cn",
                    "product_name_en",
                    "features",
                    "long_description_cn",
                    "usage_instruction",
                )
            )
            matched_fuels = all(term in candidate_fuel_text for term in requested_fuel_subtypes)
            evidence["fuel_subtype"] = _condition(
                "verified" if matched_fuels else "conflict",
                "heat_source",
                candidate_fuel_text.strip(),
                requested_fuel_subtypes=requested_fuel_subtypes,
            )
            if not matched_fuels:
                rejection_reasons.append("fuel_subtype_condition_not_met")

        if contract.materials:
            raw_material = str(row.get("body_material") or "").strip()
            if not _usable(raw_material):
                evidence["material"] = _condition("unknown")
            else:
                matched = all(_material_token_matches(raw_material, material) for material in contract.materials)
                evidence["material"] = _condition("verified" if matched else "conflict", "body_material", raw_material)
            if _usable(raw_material) and not matched:
                rejection_reasons.append("material_condition_not_met")

        if contract.accessory_requirements:
            raw_accessory = "；".join(
                str(row.get(key) or "").strip()
                for key in (
                    "accessories",
                    "features",
                    "top_selling_points",
                    "long_description_cn",
                    "bullet_points",
                    "usage_instruction",
                    "size_info",
                    "product_name_cn",
                )
                if _usable(row.get(key))
            )
            positive_terms = ("蒸屉", "蒸笼", "蒸米饭", "蒸饭")
            negative_terms = ("不支持蒸", "不能蒸", "不可蒸", "不适合蒸")
            if not _usable(raw_accessory):
                evidence["accessory"] = _condition("unknown")
            elif any(term in raw_accessory for term in negative_terms):
                evidence["accessory"] = _condition("conflict", "product_accessory_evidence", raw_accessory)
                rejection_reasons.append("accessory_condition_not_met")
            elif any(term in raw_accessory for term in positive_terms):
                evidence["accessory"] = _condition(
                    "verified",
                    "product_accessory_evidence",
                    raw_accessory,
                    requirements=list(contract.accessory_requirements),
                )
            else:
                evidence["accessory"] = _condition("unknown", "product_accessory_evidence", raw_accessory)

        if contract.dishwasher_safe_required:
            raw_usage = str(row.get("usage_instruction") or "").strip()
            positive = ("洗碗机" in raw_usage and not any(token in raw_usage for token in ("不可", "不能", "不建议", "避免")))
            if not _usable(raw_usage):
                evidence["dishwasher"] = _condition("unknown")
            else:
                evidence["dishwasher"] = _condition("verified" if positive else "conflict", "usage_instruction", raw_usage)
                if not positive:
                    rejection_reasons.append("dishwasher_condition_not_met")

        if contract.budget_level:
            raw_price_positioning = str(row.get("price_positioning") or "").strip()
            if not _usable(raw_price_positioning):
                evidence["price_positioning"] = _condition("unknown")
                unsupported_preferences.append("budget")
            else:
                matched = {
                    "low": any(value in raw_price_positioning for value in ("入门", "中端", "基础", "性价比")),
                    "affordable": any(value in raw_price_positioning for value in ("入门", "中端", "基础", "性价比")),
                    "medium": "中端" in raw_price_positioning,
                    "premium": "高端" in raw_price_positioning,
                }.get(contract.budget_level, False)
                evidence["price_positioning"] = _condition(
                    "verified" if matched else "conflict",
                    "price_positioning",
                    raw_price_positioning,
                    preference=contract.budget_level,
                )
                # Price positioning is a preference signal, not a live-price
                # fact or a hard eligibility condition. Preserve the mismatch
                # for semantic ranking/explanation but never reject the SKU.
                if not matched:
                    unsupported_preferences.append("budget")
        elif contract.relative_price_preference:
            evidence["price_positioning"] = _condition("unknown")
            unsupported_preferences.append("budget")

        for index, predicate in enumerate(contract.predicate_constraints or []):
            field_name = str(predicate.get("field") or "")
            label = f"predicate:{index}:{field_name}"
            predicate_evidence = _semantic_predicate_evidence(row, predicate)
            evidence[label] = predicate_evidence
            if label in contract.hard_constraints and predicate_evidence.get("status") == "conflict":
                rejection_reasons.append(f"{field_name}_predicate_not_met")
            elif label not in contract.hard_constraints:
                # Preferred predicates influence semantic ranking and answer
                # evidence, but they do not reject a candidate that lacks or
                # conflicts with the preference. Preserve only a verified
                # same-SKU match as positive evidence.
                if predicate_evidence.get("status") == "verified":
                    verified_preferences.append(label)
                elif predicate_evidence.get("status") in {"unknown", "conflict"}:
                    unsupported_preferences.append(label)

        for label, required, fields in (
            ("stability", contract.stability_required, ("features", "positioning")),
            ("windproof", contract.windproof_required, ("features", "positioning")),
            ("portability", contract.portability_required, ("features", "positioning")),
            # These are sealed first-party product fields.  They may establish
            # a storage fact only when the same SKU explicitly records it;
            # they do not route the customer's wording or infer compactness.
            ("storage", contract.storage_required, ("features", "top_selling_points", "positioning", "long_description_cn", "bullet_points", "size_info")),
            ("cleaning", contract.cleaning_required, ("surface_finish", "usage_instruction", "technical_advantages", "features", "long_description_cn", "bullet_points")),
        ):
            if not required:
                continue
            terms = {
                "stability": (
                    "支架稳固",
                    "支架稳定",
                    "底座稳固",
                    "底座稳定",
                    "结构稳固",
                    "结构稳定",
                    "放置平稳",
                    "放置稳定",
                    "不易倾倒",
                    "稳固支撑",
                ),
                "windproof": ("防风", "抗风"),
                "portability": ("便携", "好带"),
                "storage": ("收纳", "套娃"),
                "cleaning": ("易清洁", "好清洁", "容易清洁", "便于清洁", "清洗方便", "不粘", "不沾"),
            }[label]
            matched_field = next(
                (
                    (key, str(row.get(key) or "").strip())
                    for key in fields
                    if _usable(row.get(key))
                    and any(term in str(row.get(key) or "") for term in terms)
                ),
                None,
            )
            if matched_field:
                field_name, raw = matched_field
                evidence[label] = _condition("verified", field_name, raw)
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
        # An explicit non-split requirement is safety/fit-sensitive: unknown
        # structure evidence must not be surfaced as a recommendation when
        # the catalogue cannot verify the requested boundary.
        has_hard_constraint_conflict = not subject_ok or bool(conflicts) or (
            "structure" in contract.hard_constraints and "structure" in unsupported_constraints
        )
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
    *,
    retain_non_conflicting_partials: bool = False,
    preserve_input_order: bool = False,
) -> list[dict[str, Any]]:
    verification_by_sku = {item.sku: item for item in verifications}
    fully_verified = [
        row
        for row in candidate_rows
        if verification_by_sku.get(str(row.get("sku") or "").strip().upper())
        and verification_by_sku[str(row.get("sku") or "").strip().upper()].verification_level == "fully_verified"
    ]
    # Hard constraints decide eligibility; explicitly verified soft
    # preferences decide ordering within the eligible set.
    fully_verified.sort(
        key=lambda row: len(
            verification_by_sku[str(row.get("sku") or "").strip().upper()].verified_preferences
        ),
        reverse=True,
    )
    partially_verified = [
        row
        for row in candidate_rows
        if verification_by_sku.get(str(row.get("sku") or "").strip().upper())
        and verification_by_sku[str(row.get("sku") or "").strip().upper()].verification_level == "partially_verified"
    ]
    # A partial candidate is useful only when the unresolved hard fact is the
    # customer's group size.  That is a presentation uncertainty that can be
    # stated conditionally.  An unknown heat source, capacity, material,
    # structure, or scenario is different: showing that row would turn an
    # unverified requirement into an apparent recommendation, especially when
    # no fully verified row exists.  Keep this policy at the evidence contract
    # boundary so semantic wording remains free-form and does not need a
    # phrase-specific answer route.
    safe_partial_unknowns = {"people"}
    safe_partials = [
        row
        for row in partially_verified
        if set(
            verification_by_sku[str(row.get("sku") or "").strip().upper()].unsupported_constraints
            or []
        ).issubset(safe_partial_unknowns)
    ]
    if not fully_verified:
        selected_rows = safe_partials
        if preserve_input_order:
            selected_skus = {
                str(row.get("sku") or "").strip().upper()
                for row in selected_rows
                if str(row.get("sku") or "").strip()
            }
            return [
                row
                for row in candidate_rows
                if str(row.get("sku") or "").strip().upper() in selected_skus
            ]
        return selected_rows
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
    if retain_non_conflicting_partials:
        # A semantic evidence gate needs to see the same-SKU content that can
        # explain a qualitative request (for example, a capacity + camping
        # scenario explaining why a pot may work for a group), even when the
        # catalogue has not maintained an explicit people-range label.  Keep
        # only non-conflicting rows; the gate and the narrative still receive
        # the uncertainty and must phrase the conclusion conditionally.
        non_conflicting_partials = safe_partials
        selected_rows = [*fully_verified, *non_conflicting_partials]
    else:
        selected_rows = [*fully_verified, *safely_supplemental]
    if preserve_input_order:
        selected_skus = {
            str(row.get("sku") or "").strip().upper()
            for row in selected_rows
            if str(row.get("sku") or "").strip()
        }
        return [
            row
            for row in candidate_rows
            if str(row.get("sku") or "").strip().upper() in selected_skus
        ]
    return selected_rows


_CONSTRAINT_LABELS = {
    "people": "人数",
    "scenario": "使用场景",
    "capacity": "容量",
    "weight": "重量",
    "heat_source": "热源",
    "fuel_subtype": "酒精燃料类型",
    "material": "材质",
    "budget": "预算",
    "price_positioning": "价格定位",
    "stability": "稳定性",
    "windproof": "防风性",
    "portability": "便携性",
    "storage": "收纳",
    "cleaning": "清洁便利",
    "accessory": "蒸屉兼容",
    "structure": "结构",
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
        if _usable(value.get("value")):
            label = str(value.get("label") or "").strip()
            display_value = _display_verified_evidence_value(value.get("value"))
            unit = str(value.get("unit") or "").strip()
            rendered = f"{display_value}{unit}" if unit and unit.lower() not in display_value.lower() else display_value
            return f"{label}：{rendered}" if label else rendered
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


def _compact_customer_value(value: Any, *, limit: int = 56) -> str:
    """Keep catalogue evidence readable when a broad recommendation has no preference to rank by."""
    text = _display_verified_evidence_value(value).strip(" 。；;,")
    if not text or text in _EMPTY_VALUES:
        return ""
    # Product rows frequently store marketing copy as newline/comma-separated
    # fragments.  Keep the first two fragments so a broad answer remains a
    # comparison rather than a dump of the whole profile.
    fragments = [part.strip() for part in re.split(r"[\n,，;；。]", text) if part.strip()]
    if len(fragments) > 1:
        text = "、".join(fragments[:2])
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _row_customer_summary(row: dict[str, Any]) -> str:
    """Render only same-row, customer-safe fields for an unconstrained comparison."""
    field_values = row.get("field_values") if isinstance(row.get("field_values"), dict) else {}

    def value(*keys: str) -> Any:
        for key in keys:
            candidate = row.get(key)
            if _usable(candidate):
                return candidate
            candidate = field_values.get(key)
            if _usable(candidate):
                return candidate
        return ""

    details: list[str] = []
    power = _compact_customer_value(value("power", "功率"))
    power = re.sub(r"^(?:最大)?功率\s*[:：]?\s*", "", power)
    if power:
        details.append(f"功率{power}")
    weight = value("gross_weight_g", "weight", "重量")
    if isinstance(weight, (int, float)) and weight > 0:
        details.append(f"重量{weight:g}g")
    else:
        weight_text = _compact_customer_value(weight)
        if re.fullmatch(r"\d+(?:\.\d+)?", weight_text):
            weight_text = f"{float(weight_text):g}"
        if weight_text:
            details.append(f"重量{weight_text}g" if weight_text.replace(".", "", 1).isdigit() else f"重量{weight_text}")
    capacity = (
        _compact_customer_value(value("capacity", "容量"), limit=52)
        if _capacity_consistent_with_product_identity(row)
        else ""
    )
    if capacity:
        details.append(f"容量{capacity}")
    heat_source = _compact_customer_value(value("heat_source", "热源"))
    if heat_source:
        details.append(f"热源{heat_source}")
    scenario = _compact_customer_value(value("usage_scenarios", "使用场景"), limit=44)
    if scenario:
        details.append(f"场景{scenario}")
    if not details:
        feature = _compact_customer_value(value("features", "卖点", "positioning", "定位"), limit=48)
        if feature:
            details.append(feature)
    return "；".join(details)


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
        if contract.subject_category == "锅具" and contract.people_min is not None:
            people_label = (
                f"{contract.people_min} 人"
                if contract.people_min == contract.people_max
                else f"{contract.people_min}-{contract.people_max} 人"
            )
            return f"当前没有明确标注 {people_label} 适用且能验证所有硬性条件的锅具，现有资料证据不足。"
        return "当前未找到符合条件且能验证所有硬性条件的商品。"
    partial_result = any(accepted[str(row.get("sku") or "").strip().upper()].verification_level == "partially_verified" for row in rows)
    fully_verified_result = any(
        accepted[str(row.get("sku") or "").strip().upper()].verification_level == "fully_verified"
        for row in rows
    )
    lines = (
        ["当前没有找到所有条件都能完整验证的商品。以下推荐锅具候选未发现明确冲突，但部分条件缺少资料，仅供参考；首项优先参考，其余作为备选："]
        if partial_result and not fully_verified_result
        else [
            "\u63a8\u8350\u4f18\u5148\u770b\u8fd9\u6b3e\uff1a"
            if len(rows) == 1
            else "\u53ef\u4ee5\u4f18\u5148\u8003\u8651\u4ee5\u4e0b\u51e0\u6b3e\uff1a"
        ]
    )
    if fully_verified_result and partial_result:
        lines = [
            "以下推荐优先展示已通过当前可验证的硬性条件的候选；其余备选会明确标出尚未验证的条件，供你结合实际需求判断："
        ]
    if contract.budget_level in {"low", "affordable"}:
        lines.insert(
            0,
            "按预算不高的需求，优先看入门款或高性价比定位；资料里的价格定位不等同于实时售价。",
        )
    if contract.subject_kind == "stove":
        subject_label = {
            "card_stove": "卡式炉",
            "alcohol_stove": "酒精炉",
        }.get(contract.subject_subtype, "炉具类商品")
        lines.append(f"已找到符合“{subject_label}”类型的候选：")
    if contract.heat_sources:
        heat_source_label = "、".join(contract.heat_sources)
        lines.append(f"本次仅保留同 SKU 热源字段明确标注支持{heat_source_label}的候选。")
    requested_fuel_subtypes = list(contract.fuel_subtypes or [])
    if not requested_fuel_subtypes and contract.fuel_subtype:
        requested_fuel_subtypes = [contract.fuel_subtype]
    if requested_fuel_subtypes:
        lines.append(f"本次还要求同 SKU 资料明确标注支持{'、'.join(requested_fuel_subtypes)}。")
    if contract.structure_preference == "non_split":
        lines.append("本次排除同 SKU 资料标注为分体、分体式或远程炉头的候选；未标注结构的商品不作为已核验推荐。")
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

    # A broad request such as “户外的气炉推荐一下” has a valid subject but
    # no evidence-backed preference that can rank one SKU above the others.
    # A bare name list looks like a successful answer while giving the
    # customer no basis for choosing.  Keep the result set, add same-row
    # comparison evidence, and state what is still needed for a conclusion.
    unconstrained_multi_candidate = (
        len(rows) > 1
        and not contract.hard_constraints
        and not contract.soft_preferences
        and fully_verified_result
        and not partial_result
    )
    if unconstrained_multi_candidate:
        lines = [
            "以下是按当前主体范围核验通过的候选。你暂时没有给出人数、热源、火力或便携偏好，现有资料不足以负责任地只定一款；先把可直接对照的信息列出来："
        ]
        if contract.subject_kind == "stove":
            subject_label = {
                "card_stove": "卡式炉",
                "alcohol_stove": "酒精炉",
            }.get(contract.subject_subtype, "炉具类商品")
            lines.append(f"本次范围：{subject_label}。")
        total = len(rows) if total_match_count is None else max(int(total_match_count), 0)
        if total > len(rows):
            lines.append(f"共找到{total}款，以下先展示前{len(rows)}款：")

    for row in rows[:5]:
        sku = str(row.get("sku") or "").strip().upper()
        item = accepted[sku]
        reasons: list[str] = []
        for label, evidence in item.evidence_by_constraint.items():
            # Subject subtype is the scope boundary used to admit the row;
            # it is already expressed by the customer-facing heading and is
            # not a product feature to render as ``subject_subtype: ...``.
            if label in {"subject", "subject_subtype"} or evidence.get("status") != "verified":
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
            elif label in {"stability", "windproof", "portability", "storage"}:
                display = "商品资料有明确标注"
            else:
                display = _display_verified_evidence_value(raw)
            reasons.append(f"{_CONSTRAINT_LABELS.get(label, label)}：{display}")
        name = str(row.get("product_name_cn") or sku).strip()
        line = f"- {name}（{sku}）"
        if reasons:
            line += "，" + "；".join(reasons)
        elif contract.subject_subtype:
            # Subtype verification is a valid identity boundary, but it is
            # not itself a customer-facing product feature. Add one same-row
            # fact when available so a one-item recommendation still explains
            # why the item is being shown.
            subtype_fact = _compact_customer_value(
                row.get("features") or row.get("usage_scenarios") or row.get("capacity"),
                limit=72,
            )
            if subtype_fact:
                line += f"，资料显示{subtype_fact}"
        unsupported = list(dict.fromkeys([*item.unsupported_constraints, *item.unsupported_preferences]))
        if unsupported:
            line += f"。{_customer_safe_missing_requirement_note(unsupported)}"
        # A verified constraint explains eligibility, but customers also need
        # concrete same-SKU facts to judge the recommendation. Keep the
        # summary short and attach it even when the verifier already rendered
        # one or two matching constraints.
        summary = _row_customer_summary(row)
        if summary and summary not in line:
            separator = "：" if unconstrained_multi_candidate and not reasons else "；同 SKU 资料："
            line += f"{separator}{summary}"
        lines.append(line)
    if unconstrained_multi_candidate:
        lines.append("如果你更看重火力、轻量、燃料类型或使用人数，请告诉我优先条件，我再在这些已核验候选里给出明确首选。")
    return "\n".join(lines)
