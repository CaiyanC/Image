from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field as dataclass_field
from typing import Any


@dataclass(frozen=True)
class StructuredQueryContract:
    subject_category: str | None = None
    field: str | None = None
    operator: str | None = None
    value: Any = None
    unit: str | None = None
    relation: str | None = None
    exclusions: list[str] = dataclass_field(default_factory=list)
    confidence: str = "low"
    status: str = "unresolved"
    source_spans: dict[str, tuple[int, int]] = dataclass_field(default_factory=dict)
    conditions: list[dict[str, Any]] = dataclass_field(default_factory=list)
    subject_kind: str | None = None
    requested_scope: str = "subject"
    subject_span: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _display_contract_value(value: Any, unit: str | None = None) -> str:
    def display_number(item: Any) -> str:
        if isinstance(item, float) and item.is_integer():
            return str(int(item))
        return str(item)

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{display_number(value[0])}{unit or ''}到{display_number(value[1])}{unit or ''}"
    return f"{display_number(value)}{unit or ''}"


def format_structured_condition_summary(contract: StructuredQueryContract) -> str:
    """Render a resolved structured condition without changing its semantics."""
    if len(contract.conditions) > 1:
        return "且".join(
            format_structured_condition_summary(
                StructuredQueryContract(
                    field=item.get("field"), operator=item.get("operator"), value=item.get("value"),
                    unit=item.get("unit"), relation=item.get("relation"),
                )
            )
            for item in contract.conditions
        )
    field = str(contract.field or "").strip()
    operator = str(contract.operator or "").strip()
    value = _display_contract_value(contract.value, contract.unit)
    field_label = {
        "material": "材质",
        "capacity": "容量",
        "weight": "重量",
        "dimensions": "尺寸",
        "people": "适用人数",
        "color": "颜色",
        "heat_source": "适用炉具",
        "usage_scene": "适用场景",
        "waterproof": "防水",
    }.get(field, "条件")
    if operator == "supports":
        return f"支持{value}"
    if operator == "not_supports":
        return f"不支持{value}"
    if operator == "contains":
        return f"{field_label}包含{value}"
    if operator == ">=":
        return f"{field_label}不低于{value}"
    if operator == ">":
        return f"{field_label}大于{value}"
    if operator == "<=":
        return f"{field_label}不超过{value}"
    if operator == "<":
        return f"{field_label}小于{value}"
    if operator == "between":
        return f"{field_label}在{value}之间"
    if field == "waterproof" and operator == "=":
        return "明确标注防水"
    if operator == "=":
        return f"{field_label}为{value}"
    return f"{field_label}{value}" if value else field_label


_SUBJECT_ALIASES = (
    ("咖啡器具", "咖啡器具"),
    ("户外收纳包", "配件"),
    ("露营椅", "桌椅"),
    ("户外水壶", "水壶"),
    ("户外杯", "水杯"),
    ("酒精炉", "炉具"),
    ("水壶", "水壶"),
    ("水具", "水具"),
    ("杯子", "水杯"),
    ("水杯", "水杯"),
    ("锅具", "锅具"),
    ("户外锅", "锅具"),
    ("锅", "锅具"),
    ("炉具", "炉具"),
    ("炉子", "炉具"),
    ("桌椅", "桌椅"),
    ("椅子", "桌椅"),
    ("配件", "配件"),
    ("帐篷", "帐篷"),
    ("产品", "all_products"),
    ("商品", "all_products"),
)

_HEAT_SOURCE_SUBJECT_ALIASES = frozenset({"酒精炉"})

# A deictic noun phrase needs an entity from conversation context; it is not
# a catalogue category.  Keep these markers at the structured-query boundary
# so “这个锅/那款水壶/该产品” cannot silently expand into an all-products
# filter before EntityResolutionContract has had a chance to clarify or bind
# the reference.
_DEICTIC_SUBJECT_PREFIXES = (
    "这个", "这款", "这件", "这只", "这口", "这种", "这类",
    "那个", "那款", "那件", "那只", "那口", "那种", "那类",
    "该", "本", "此",
)

_COMPOSITE_SUBJECT_ALIASES = (
    ("水壶配件", "水壶", "kettle", "accessory"),
    ("咖啡壶", "咖啡器具", "coffee_kettle", "subject"),
)

_FIELD_ALIASES = (
    ("适用人数", "people"),
    ("能装", "capacity"),
    ("容量", "capacity"),
    ("材质", "material"),
    ("材料", "material"),
    ("重量", "weight"),
    ("多重", "weight"),
    ("尺寸", "dimensions"),
    ("颜色", "color"),
    ("热源", "heat_source"),
    ("防水", "waterproof"),
)

_CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _chinese_number(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    if text == "十":
        return 10.0
    if "百" in text:
        left, right = text.split("百", 1)
        hundreds = _CHINESE_DIGITS.get(left, 1)
        remainder = _chinese_number(right) if right else 0
        return float(hundreds * 100 + (remainder or 0))
    if "十" in text:
        left, right = text.split("十", 1)
        tens = _CHINESE_DIGITS.get(left, 1)
        ones = _CHINESE_DIGITS.get(right, 0) if right else 0
        return float(tens * 10 + ones)
    digits = [_CHINESE_DIGITS.get(char) for char in text]
    if digits and all(item is not None for item in digits):
        return float("".join(str(item) for item in digits))
    return None


def _normalize_numeric(value: float, unit: str | None, field: str) -> tuple[float, str]:
    normalized_unit = str(unit or "").lower()
    if field == "capacity":
        return (value * 1000, "ml") if normalized_unit in {"l", "升"} else (value, "ml")
    if field == "weight":
        return (value * 1000, "g") if normalized_unit in {"kg", "千克", "公斤"} else (value, "g")
    return value, normalized_unit


def normalize_measurement(raw: Any, field: str) -> tuple[float | None, str | None]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|g|克|kg|千克|公斤)?", str(raw or ""), re.I)
    if not match:
        return None, None
    return _normalize_numeric(float(match.group(1)), match.group(2), field)


_SEARCH_REQUEST_PREFIX = re.compile(
    r"^\s*(?:请)?(?:帮我)?(?:找一下|找出|查找|筛选|列出|看看有哪些|找)\s*"
)


def _strip_search_request_prefix(text: str) -> tuple[str, int]:
    match = _SEARCH_REQUEST_PREFIX.match(text)
    if not match:
        return text, 0
    return text[match.end():], match.end()


def _subject_match(text: str) -> tuple[str | None, tuple[int, int] | None, str | None, str]:
    # Only relation markers delimit the subject. Field phrases may precede the
    # subject, as in "容量大于 600ml 的水杯".
    condition_markers = [
        index
        for marker in (
            "适配", "支持", "不支持", "能用", "不能用", "可以配", "可以烧",
            "可以在", "用于", "适用于", "不适用", "无法使用",
        )
        if (index := text.find(marker)) >= 0
    ]
    condition_start = min(condition_markers) if condition_markers else len(text)
    composite_matches = []
    for alias, category, subject_kind, requested_scope in _COMPOSITE_SUBJECT_ALIASES:
        start = text.find(alias)
        if start >= 0 and start < condition_start:
            composite_matches.append((start, -len(alias), alias, category, subject_kind, requested_scope))
    if composite_matches:
        start, _, alias, category, subject_kind, requested_scope = sorted(composite_matches)[0]
        return category, (start, start + len(alias)), subject_kind, requested_scope
    matches = []
    for alias, category in _SUBJECT_ALIASES:
        start = text.find(alias)
        is_deictic_reference = any(
            text[:start].endswith(prefix)
            for prefix in _DEICTIC_SUBJECT_PREFIXES
        )
        if start >= 0 and start < condition_start and not is_deictic_reference:
            matches.append((start, -len(alias), alias, category))
    # In wording such as ``适合酒精炉的锅`` the heat source appears before
    # the requested product.  Prefer the later non-stove subject so the
    # alcohol stove remains a compatibility condition rather than becoming
    # the catalogue category being searched.
    heat_source_matches = [item for item in matches if item[2] in _HEAT_SOURCE_SUBJECT_ALIASES]
    non_stove_matches = [item for item in matches if item[3] != "炉具"]
    if heat_source_matches and non_stove_matches:
        earliest_non_stove_start = min(item[0] for item in non_stove_matches)
        matches = [
            item
            for item in matches
            if item[2] not in _HEAT_SOURCE_SUBJECT_ALIASES or item[0] >= earliest_non_stove_start
        ]
    if not matches:
        return None, None, None, "subject"
    start, _, alias, category = sorted(matches)[0]
    subject_kind = {"水壶": "kettle", "水杯": "cup"}.get(category)
    return category, (start, start + len(alias)), subject_kind, "subject"


def _validated_semantic_subject_category(
    question: str,
    subject_text: Any,
) -> tuple[str, tuple[int, int], str | None, str] | None:
    """Validate an LLM subject span against the existing category taxonomy.

    This is deliberately not a product lookup or a second language router.
    The semantic preplan supplies a verbatim subject span; deterministic code
    only accepts it when it is exactly one existing generic category alias in
    the current customer question and not a deictic product reference.
    """
    text = str(question or "")
    candidate = str(subject_text or "").strip()
    if not text or not candidate:
        return None
    categories = {category for alias, category in _SUBJECT_ALIASES if alias == candidate}
    if len(categories) != 1:
        return None
    start = text.find(candidate)
    if start < 0 or any(text[:start].endswith(prefix) for prefix in _DEICTIC_SUBJECT_PREFIXES):
        return None
    category = next(iter(categories))
    subject_kind = {"水壶": "kettle", "水杯": "cup"}.get(category)
    return category, (start, start + len(candidate)), subject_kind, "subject"


def _numeric_condition(text: str, field: str) -> tuple[str | None, Any, str | None, tuple[int, int] | None]:
    unit_pattern = r"(ml|毫升|l|升|g|克|kg|千克|公斤)"
    number_pattern = r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+)"
    between = re.search(rf"(?:介于|在)\s*{number_pattern}\s*{unit_pattern}?\s*(?:到|至|和|~|-)\s*{number_pattern}\s*{unit_pattern}?\s*(?:之间)?", text, re.I)
    if between:
        low = _chinese_number(between.group(1)); high = _chinese_number(between.group(3))
        unit = between.group(4) or between.group(2)
        if low is not None and high is not None:
            low, normalized_unit = _normalize_numeric(low, unit, field)
            high, _ = _normalize_numeric(high, unit, field)
            return "between", [low, high], normalized_unit, between.span()
    match = re.search(rf"{number_pattern}\s*{unit_pattern}", text, re.I)
    if not match:
        return None, None, None, None
    value = _chinese_number(match.group(1))
    if value is None:
        return None, None, None, None
    value, unit = _normalize_numeric(value, match.group(2), field)
    prefix = text[:match.start()]
    suffix = text[match.end():]
    if any(term in prefix[-6:] + suffix[:6] for term in ("至少", "不少于", "不小于", "以上", "不低于")):
        operator = ">="
    elif any(term in prefix[-6:] + suffix[:6] for term in ("不超过", "至多", "以下", "不高于")):
        operator = "<="
    elif any(term in prefix[-6:] + suffix[:6] for term in ("超过", "大于", "高于")):
        operator = ">"
    elif any(term in prefix[-6:] + suffix[:6] for term in ("小于", "低于", "不到")):
        operator = "<"
    else:
        operator = "="
    return operator, value, unit, match.span()


def build_structured_query_contract(question: str) -> StructuredQueryContract:
    original_text = str(question or "").strip()
    text, prefix_offset = _strip_search_request_prefix(original_text)
    if not text or re.search(r"\b[A-Z]{1,6}[A-Z0-9]*(?:-[A-Z0-9()（）]+)+\b", text, re.I):
        return StructuredQueryContract(status="not_applicable")
    if any(term in text for term in ("推荐", "怎么选", "选哪", "哪个好", "对比", "比较")):
        return StructuredQueryContract(status="not_applicable")
    subject, subject_span, subject_kind, requested_scope = _subject_match(text)
    field = None
    field_span = None
    for alias, field_type in _FIELD_ALIASES:
        start = text.find(alias)
        if start >= 0:
            field, field_span = field_type, (start, start + len(alias))
            break
    relation = None
    operator = None
    value: Any = None
    unit = None
    value_span = None
    negative_compatibility = any(
        term in text
        for term in ("不能用于", "不支持", "不可用于", "无法使用", "不适用")
    )
    if negative_compatibility or any(
        term in text
        for term in (
            "适配", "支持", "能用", "可以配", "可以用", "可以烧", "烧酒精",
            "可以在", "用于", "适用于", "适合",
        )
    ):
        field = "heat_source"
        relation = "compatible_with"
        operator = "not_supports" if negative_compatibility else "supports"
        for candidate in ("燃气炉", "卡式炉", "电磁炉", "电陶炉", "明火", "酒精"):
            start = text.rfind(candidate)
            if start >= 0 and (not subject_span or start >= subject_span[1]):
                value, value_span = candidate, (start, start + len(candidate))
                break
    if field in {"capacity", "weight", "dimensions", "people"}:
        operator, value, unit, value_span = _numeric_condition(text, field)
    if field == "material":
        for candidate, normalized in (("硬质氧化铝合金", "硬质氧化铝"), ("硬质氧化铝", "硬质氧化铝"), ("硬氧", "硬质氧化铝"), ("铝合金", "铝合金"), ("不锈钢", "不锈钢"), ("钛", "钛")):
            start = text.find(candidate)
            if start >= 0:
                operator, value, value_span = "contains", normalized, (start, start + len(candidate))
                break
    if field == "color":
        for candidate in ("黑色", "白色", "红色", "橙色", "灰色", "绿色", "蓝色"):
            start = text.find(candidate)
            if start >= 0:
                operator, value, value_span = "contains", candidate, (start, start + len(candidate))
                break
    if field == "waterproof":
        operator, value = "=", True
        start = text.find("防水")
        value_span = (start, start + len("防水")) if start >= 0 else None
    spans = {}
    if subject_span: spans["subject"] = tuple(index + prefix_offset for index in subject_span)
    if field_span: spans["field"] = tuple(index + prefix_offset for index in field_span)
    if value_span: spans["value"] = tuple(index + prefix_offset for index in value_span)
    conditions: list[dict[str, Any]] = []
    if field and operator and value is not None:
        conditions.append({"field": field, "operator": operator, "value": value, "unit": unit, "relation": relation})

    material_condition = None
    for candidate, normalized in (("硬质氧化铝合金", "硬质氧化铝"), ("硬质氧化铝", "硬质氧化铝"), ("硬氧", "硬质氧化铝"), ("铝合金", "铝合金"), ("不锈钢", "不锈钢"), ("钛", "钛")):
        if candidate in text:
            material_condition = {"field": "material", "operator": "contains", "value": normalized, "unit": None, "relation": None}
            break
    if material_condition and not any(item["field"] == "material" for item in conditions):
        conditions.append(material_condition)

    compatibility_marked = negative_compatibility or any(
        term in text for term in ("适配", "支持", "能用", "可以配", "可以用", "可以烧", "烧酒精", "可以在", "用于", "适用于", "适合", "明火直烧")
    )
    if compatibility_marked and not any(item["field"] == "heat_source" for item in conditions):
        for candidate in ("燃气炉", "卡式炉", "电磁炉", "电陶炉", "明火直烧", "明火", "酒精炉", "酒精"):
            if candidate in text:
                start = text.find(candidate)
                conditions.append({
                    "field": "heat_source",
                    "operator": "not_supports" if negative_compatibility else "supports",
                    "value": candidate,
                    "unit": None,
                    "relation": "compatible_with",
                })
                if "value" not in spans:
                    spans["value"] = (start + prefix_offset, start + len(candidate) + prefix_offset)
                break

    if len(conditions) > 1:
        condition_order = {"material": 0, "heat_source": 1}
        conditions.sort(key=lambda item: condition_order.get(str(item.get("field") or ""), 10))

    if subject and conditions:
        primary = conditions[0]
        return StructuredQueryContract(
            subject_category=subject,
            field=primary["field"], operator=primary["operator"], value=primary["value"],
            unit=primary.get("unit"), relation=primary.get("relation"), confidence="high",
            status="resolved", source_spans=spans, conditions=conditions,
            subject_kind=subject_kind, requested_scope=requested_scope,
            subject_span=spans.get("subject"),
        )
    if subject and field:
        return StructuredQueryContract(
            subject_category=subject, field=field, confidence="high", status="generic", source_spans=spans,
            subject_kind=subject_kind, requested_scope=requested_scope, subject_span=spans.get("subject"),
        )
    return StructuredQueryContract(
        subject_category=subject, field=field, operator=operator, value=value, unit=unit, relation=relation,
        confidence="low", status="unresolved", source_spans=spans,
        subject_kind=subject_kind, requested_scope=requested_scope, subject_span=spans.get("subject"),
    )


_SEMANTIC_STRUCTURED_OPERATORS = {
    "material": {"contains"},
    "capacity": {">=", ">", "<=", "<", "=", "between"},
    "weight": {">=", ">", "<=", "<", "=", "between"},
    "dimensions": {"contains", "="},
    "people": {">=", ">", "<=", "<", "=", "between"},
    "color": {"contains", "="},
    "heat_source": {"supports", "not_supports"},
    "usage_scene": {"contains"},
    "waterproof": {"="},
}


def adapt_semantic_structured_query_contract(
    *,
    question: str,
    base_contract: StructuredQueryContract,
    semantic_preplan: dict[str, Any] | None,
) -> StructuredQueryContract | None:
    """Merge a validated semantic multi-field plan into a literal query contract.

    Semantic planning owns which field concepts the customer expressed.  This
    adapter deliberately accepts no product identity or database value from the
    model: each predicate must be allowlisted and quote an exact span from the
    customer's current question.  The caller still evaluates every predicate
    against database rows before returning a SKU.
    """
    preplan = semantic_preplan if isinstance(semantic_preplan, dict) else {}
    if not (
        preplan.get("called")
        and str(preplan.get("route_family") or "").strip() == "structured_query"
        and str(preplan.get("route_hint") or "").strip() == "query_products"
        and str(preplan.get("question_type") or "").strip() == "filter"
        and str(preplan.get("subtype") or "").strip() == "structured_query"
        and not preplan.get("ambiguity")
    ):
        return None
    try:
        confidence = float(preplan.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return None
    if confidence < 0.9 or confidence > 1.0:
        return None
    canonical_fields = [str(item or "").strip() for item in (preplan.get("canonical_fields") or [])]
    canonical_fields = list(dict.fromkeys(item for item in canonical_fields if item in _SEMANTIC_STRUCTURED_OPERATORS))
    raw_constraints = preplan.get("structured_query_constraints")
    if len(canonical_fields) < 2 or not isinstance(raw_constraints, list) or not (2 <= len(raw_constraints) <= 4):
        return None
    subject_category = base_contract.subject_category
    subject_span = base_contract.subject_span
    subject_kind = base_contract.subject_kind
    requested_scope = base_contract.requested_scope
    if not subject_category:
        validated_subject = _validated_semantic_subject_category(
            question,
            preplan.get("subject_text"),
        )
        if validated_subject is None:
            return None
        subject_category, subject_span, subject_kind, requested_scope = validated_subject

    text = str(question or "")
    conditions: list[dict[str, Any]] = []
    source_spans = dict(base_contract.source_spans or {})
    if subject_span is not None:
        source_spans["subject"] = subject_span
    for raw in raw_constraints:
        if not isinstance(raw, dict):
            return None
        field = str(raw.get("field") or "").strip()
        operator = str(raw.get("operator") or "").strip()
        value = raw.get("value")
        evidence_span = str(raw.get("evidence_span") or "").strip()
        unit = raw.get("unit")
        if (
            field not in canonical_fields
            or operator not in _SEMANTIC_STRUCTURED_OPERATORS.get(field, set())
            or not evidence_span
            or evidence_span not in text
            or value in (None, "")
        ):
            return None
        # Semantic values must remain a literal customer phrase for textual
        # predicates. Numeric normalization remains deterministic and uses the
        # existing measurement evaluator below.
        if field in {"material", "dimensions", "color", "heat_source", "usage_scene"} and str(value).strip() not in evidence_span:
            return None
        if field == "waterproof" and value is not True:
            return None
        condition = {
            "field": field,
            "operator": operator,
            "value": value,
            "unit": unit,
            "relation": "compatible_with" if field == "heat_source" else None,
        }
        if condition not in conditions:
            conditions.append(condition)
        source_spans.setdefault(f"semantic_value_{field}", (text.index(evidence_span), text.index(evidence_span) + len(evidence_span)))

    if set(item["field"] for item in conditions) != set(canonical_fields):
        return None
    primary = conditions[0]
    return StructuredQueryContract(
        subject_category=subject_category,
        field=primary["field"],
        operator=primary["operator"],
        value=primary["value"],
        unit=primary.get("unit"),
        relation=primary.get("relation"),
        confidence="high",
        status="resolved",
        source_spans=source_spans,
        conditions=conditions,
        subject_kind=subject_kind,
        requested_scope=requested_scope,
        subject_span=subject_span,
    )


def _subject_matches(row: dict[str, Any], subject: str) -> bool:
    category = str(row.get("category") or "")
    sub_category = str(row.get("sub_category") or "")
    names = f"{row.get('product_name_cn') or ''} {row.get('product_name_en') or ''}"
    if subject == "all_products":
        return True
    if subject == "水杯":
        return any(term in names for term in ("杯", "cup")) and not any(term in names for term in ("壶", "kettle"))
    if subject == "水壶":
        return "壶" in names and "杯" not in names
    if subject == "水具":
        return category in {"水具", "水壶"} or any(term in names for term in ("杯", "壶", "cup", "kettle"))
    if subject == "锅具":
        return "锅" in f"{category} {sub_category} {names}"
    if subject == "炉具":
        return "炉" in f"{category} {sub_category} {names}"
    if subject == "桌椅":
        return category == "桌椅" or any(term in names for term in ("椅", "chair"))
    if subject == "配件":
        return category == "配件"
    return subject in f"{category} {sub_category} {names}"


_NON_SUBJECT_SCOPES = {"accessory", "component", "package", "gift", "unknown"}
_ACCESSORY_CATEGORY_TERMS = ("配件", "附件", "替换件", "零件")
_ACCESSORY_NAME_TERMS = ("配件", "附件", "替换件", "锅盖", "手柄", "收纳", "袋", "组件", "零件")


def resolve_waterware_subject_kind(row: dict[str, Any]) -> dict[str, Any]:
    """Classify a catalog row for directional waterware subject matching."""
    category = str(row.get("category") or "").strip()
    sub_category = str(row.get("sub_category") or "").strip()
    name = " ".join(str(row.get(key) or "").strip() for key in ("product_name_cn", "product_name_en"))
    classification = f"{category} {sub_category}".strip()
    if any(term in classification for term in _ACCESSORY_CATEGORY_TERMS) or any(
        term in name for term in _ACCESSORY_NAME_TERMS
    ):
        return {"kind": "accessory", "matched_by": "canonical_category" if classification else "controlled_name_fallback"}

    kettle_terms = ("水壶", "烧水壶", "保温壶", "冷水壶", "手冲壶", "细口壶", "咖啡壶", "茶壶", "kettle")
    cup_terms = ("水杯", "保温杯", "随行杯", "咖啡杯", "茶杯", "杯", "cup")
    if category == "水壶" or any(term in sub_category for term in ("水壶", "壶具")):
        return {"kind": "kettle", "matched_by": "canonical_category" if category == "水壶" else "canonical_sub_category"}
    if category in {"水杯", "杯具"} or any(term in sub_category for term in ("水杯", "杯具")):
        return {"kind": "cup", "matched_by": "canonical_category" if category in {"水杯", "杯具"} else "canonical_sub_category"}
    if category == "咖啡器具":
        if any(term in name for term in kettle_terms):
            return {"kind": "coffee_kettle", "matched_by": "strict_water_kettle_compatibility"}
        return {"kind": "other", "matched_by": "canonical_category"}
    if category == "水具" or any(term in sub_category for term in ("水具", "饮水容器")):
        if any(term in name for term in kettle_terms):
            return {"kind": "kettle", "matched_by": "strict_water_kettle_compatibility"}
        if any(term in name for term in cup_terms):
            return {"kind": "cup", "matched_by": "strict_water_cup_compatibility"}
        return {"kind": "waterware_broad", "matched_by": "canonical_category" if category == "水具" else "canonical_sub_category"}
    if classification:
        return {"kind": "other", "matched_by": "canonical_category"}
    if any(term in name for term in kettle_terms):
        return {"kind": "kettle", "matched_by": "controlled_name_fallback"}
    if any(term in name for term in cup_terms):
        return {"kind": "cup", "matched_by": "controlled_name_fallback"}
    return {"kind": "other", "matched_by": "controlled_name_fallback"}


def match_requested_waterware_subject(requested_subject: str, row_kind: str) -> bool:
    if requested_subject == "水具":
        return row_kind in {"waterware_broad", "kettle", "cup", "coffee_kettle"}
    if requested_subject == "水壶":
        return row_kind in {"kettle", "coffee_kettle"}
    if requested_subject == "水杯":
        return row_kind == "cup"
    return False


def resolve_structured_subject_scope(
    *,
    row: dict[str, Any],
    subject_category: str,
    subject_kind: str | None = None,
    requested_scope: str = "subject",
) -> dict[str, Any]:
    """Resolve structured-query subject identity from canonical catalog data."""
    subject = str(subject_category or "").strip()
    category = str(row.get("category") or "").strip()
    sub_category = str(row.get("sub_category") or "").strip()
    name = " ".join(str(row.get(key) or "").strip() for key in ("product_name_cn", "product_name_en"))
    classification = f"{category} {sub_category}".strip()

    if subject == "all_products":
        return {"matched": True, "normalized_subject": subject, "matched_by": "all_products", "scope": "subject", "excluded_reason": None}
    if requested_scope == "accessory":
        kind_decision = resolve_waterware_subject_kind(row)
        if kind_decision["kind"] != "accessory":
            return {"matched": False, "normalized_subject": subject, "subject_kind": kind_decision["kind"], "matched_by": kind_decision["matched_by"], "scope": "subject", "excluded_reason": "accessory_scope_mismatch"}
        ownership = " ".join(
            str(row.get(key) or "").strip()
            for key in ("parent_category", "compatible_category", "owner_category", "subject_category")
        ).strip()
        if not ownership:
            return {"matched": False, "normalized_subject": subject, "subject_kind": "accessory", "matched_by": "structured_accessory_scope", "scope": "accessory", "excluded_reason": "accessory_subject_compatibility_unknown"}
        compatible = subject in ownership or (subject_kind == "kettle" and "水壶" in ownership)
        return {"matched": compatible, "normalized_subject": subject, "subject_kind": "accessory", "matched_by": "structured_accessory_scope", "scope": "accessory", "excluded_reason": None if compatible else "subject_specificity_mismatch"}
    if subject_kind == "coffee_kettle":
        kind_decision = resolve_waterware_subject_kind(row)
        matched = kind_decision["kind"] == "coffee_kettle"
        return {
            "matched": matched,
            "normalized_subject": subject,
            "subject_kind": kind_decision["kind"],
            "matched_by": kind_decision["matched_by"],
            "scope": "subject" if matched else "unknown",
            "excluded_reason": None if matched else "subject_specificity_mismatch",
        }
    if subject in {"水具", "水壶", "水杯"}:
        kind_decision = resolve_waterware_subject_kind(row)
        kind = kind_decision["kind"]
        if kind == "accessory":
            return {"matched": False, "normalized_subject": subject, "subject_kind": kind, "matched_by": kind_decision["matched_by"], "scope": "accessory", "excluded_reason": "accessory_scope"}
        matched = match_requested_waterware_subject(subject, kind)
        return {
            "matched": matched,
            "normalized_subject": subject,
            "subject_kind": kind,
            "matched_by": kind_decision["matched_by"],
            "scope": "subject" if matched else "unknown",
            "excluded_reason": None if matched else "subject_specificity_mismatch",
        }
    if classification:
        if any(term in classification for term in _ACCESSORY_CATEGORY_TERMS):
            return {"matched": False, "normalized_subject": subject, "matched_by": "canonical_category", "scope": "accessory", "excluded_reason": "accessory_scope"}
        if subject == "锅具":
            matched = "锅具" in category or "锅具" in sub_category
        else:
            matched = subject in category or subject in sub_category
        matched_by = "canonical_category" if matched and (
            subject in category or (subject in {"水壶", "水具"} and category in {"水壶", "水具"})
        ) else "canonical_sub_category" if matched else "canonical_category"
        return {
            "matched": matched,
            "normalized_subject": subject,
            "matched_by": matched_by,
            "scope": "subject" if matched else "unknown",
            "excluded_reason": None if matched else "subject_category_mismatch",
        }

    if any(term in name for term in _ACCESSORY_NAME_TERMS):
        return {"matched": False, "normalized_subject": subject, "matched_by": "controlled_name_fallback", "scope": "accessory", "excluded_reason": "accessory_scope"}
    if subject == "锅具":
        matched = "锅" in name
    else:
        matched = subject in name
    return {
        "matched": matched,
        "normalized_subject": subject,
        "matched_by": "controlled_name_fallback",
        "scope": "subject" if matched else "unknown",
        "excluded_reason": None if matched else "subject_category_mismatch",
    }


def resolve_material_subject_scope(row: dict[str, Any], subject_category: str) -> dict[str, Any]:
    decision = resolve_structured_subject_scope(row=row, subject_category=subject_category)
    return {
        "eligible": decision["matched"],
        "subject_scope": decision["scope"],
        "matched_by": decision["matched_by"],
        "excluded_reason": decision["excluded_reason"],
    }


def _subject_material_text(raw_value: Any) -> tuple[str, str]:
    raw = str(raw_value or "").strip()
    if not raw:
        return "", "subject"
    labeled_lines = []
    for line in re.split(r"[\n\r]+", raw):
        if "：" in line or ":" in line:
            label, value = re.split(r"[：:]", line, maxsplit=1)
            labeled_lines.append((label.strip(), value.strip()))
    if not labeled_lines:
        return raw, "subject"
    subject_values = [
        value for label, value in labeled_lines
        if any(term in label for term in ("主体", "锅体", "锅具"))
    ]
    return "、".join(value for value in subject_values if value), "subject" if subject_values else "component"


def _normalized_material_tokens(value: str) -> list[str]:
    return [token.strip() for token in re.split(r"[\s,，、;/；]+", str(value or "")) if token.strip()]


def match_material_condition(
    *,
    contract: StructuredQueryContract,
    row: dict[str, Any],
    subject_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Match a material condition using only subject-scoped body material."""
    scope = subject_scope or resolve_material_subject_scope(row, str(contract.subject_category or ""))
    raw_value = str(row.get("body_material") or "").strip()
    result = {
        "sku": str(row.get("sku") or "").strip().upper(),
        "product_name": str(row.get("product_name_cn") or row.get("product_name_en") or "").strip(),
        "subject_category": contract.subject_category,
        "subject_scope": scope.get("subject_scope") or "unknown",
        "field": "material",
        "field_source": "body_material",
        "evidence_scope": "subject",
        "raw_value": raw_value,
        "normalized_material_tokens": [],
        "matched_term": None,
        "matched": False,
        "excluded_reason": scope.get("excluded_reason"),
    }
    if not scope.get("eligible"):
        return result
    declared_scope = str(row.get("material_scope") or "subject").strip().lower()
    if declared_scope in _NON_SUBJECT_SCOPES:
        result.update({"evidence_scope": declared_scope, "excluded_reason": "non_subject_evidence_only"})
        return result
    subject_material, evidence_scope = _subject_material_text(raw_value)
    result["evidence_scope"] = evidence_scope
    result["normalized_material_tokens"] = _normalized_material_tokens(subject_material)
    if not subject_material:
        result["excluded_reason"] = "non_subject_evidence_only" if raw_value else "missing_subject_material"
        return result

    target = str(contract.value or "").strip()
    if any(term in target for term in ("硬氧", "硬质氧化", "硬质阳极氧化")):
        match = re.search(r"硬氧|硬质氧化铝(?:合金)?|硬质氧化(?!铝)|硬质阳极氧化铝", subject_material)
    else:
        match = re.search(re.escape(target), subject_material, re.I) if target else None
    if not match:
        result["excluded_reason"] = "material_condition_not_met"
        return result
    result.update({"matched_term": match.group(0), "matched": True, "excluded_reason": None})
    return result


def _compare(actual: Any, operator: str, target: Any) -> bool:
    if operator == "not_supports":
        actual_text = str(actual or "").strip()
        target_text = re.escape(str(target or "").strip())
        if not actual_text or not target_text:
            return False
        negative_patterns = (
            rf"(?:不支持|不可(?:用|用于)|不能(?:用|用于)|无法(?:用|使用)|不适用)\s*{target_text}",
            rf"{target_text}\s*(?:不支持|不可(?:用|用于)|不能(?:用|用于)|无法(?:用|使用)|不适用)",
        )
        return any(re.search(pattern, actual_text) for pattern in negative_patterns)
    if operator in {"contains", "supports", "="} and not isinstance(target, (int, float, list)):
        return str(target or "").lower() in str(actual or "").lower()
    try:
        number = float(actual)
    except (TypeError, ValueError):
        return False
    if operator == ">=": return number >= float(target)
    if operator == ">": return number > float(target)
    if operator == "<=": return number <= float(target)
    if operator == "<": return number < float(target)
    if operator == "between": return float(target[0]) <= number <= float(target[1])
    return number == float(target)


def evaluate_structured_row(row: dict[str, Any], contract: StructuredQueryContract) -> dict[str, Any]:
    if len(contract.conditions) > 1:
        condition_proofs = []
        for item in contract.conditions:
            sub_contract = StructuredQueryContract(
                subject_category=contract.subject_category,
                field=item.get("field"), operator=item.get("operator"), value=item.get("value"),
                unit=item.get("unit"), relation=item.get("relation"), status="resolved",
                subject_kind=contract.subject_kind, requested_scope=contract.requested_scope,
                subject_span=contract.subject_span,
            )
            condition_proofs.append(evaluate_structured_row(row, sub_contract))
        matched = all(item.get("matched") for item in condition_proofs)
        return {
            "sku": str(row.get("sku") or "").strip().upper(),
            "subject_match": all(item.get("subject_match") for item in condition_proofs),
            "field_source": "compound",
            "raw_value": {item.get("field"): item.get("raw_value") for item in condition_proofs},
            "normalized_value": {item.get("field"): item.get("normalized_value") for item in condition_proofs},
            "operator": "and",
            "target": {item.get("field"): item.get("target") for item in condition_proofs},
            "matched": matched,
            "condition_proofs": condition_proofs,
            "excluded_reason": None if matched else "condition_not_met",
        }
    subject_decision = resolve_structured_subject_scope(
        row=row,
        subject_category=str(contract.subject_category or ""),
        subject_kind=contract.subject_kind,
        requested_scope=contract.requested_scope,
    )
    if contract.field == "material":
        if contract.requested_scope == "accessory":
            raw_value = str(row.get("body_material") or "").strip()
            field_match = bool(raw_value and _compare(raw_value, str(contract.operator or ""), contract.value))
            matched = bool(subject_decision["matched"] and field_match)
            return {
                "sku": str(row.get("sku") or "").strip().upper(),
                "product_name": str(row.get("product_name_cn") or row.get("product_name_en") or "").strip(),
                "subject_category": contract.subject_category,
                "subject_kind": subject_decision.get("subject_kind"),
                "subject_match": subject_decision["matched"],
                "subject_scope": subject_decision["scope"],
                "subject_matched_by": subject_decision["matched_by"],
                "field": "material",
                "field_source": "body_material",
                "evidence_scope": subject_decision["scope"],
                "raw_value": raw_value,
                "normalized_value": _normalized_material_tokens(raw_value),
                "operator": contract.operator,
                "target": contract.value,
                "matched": matched,
                "excluded_reason": None if matched else subject_decision.get("excluded_reason") or "material_condition_not_met",
            }
        material_scope = {
            "eligible": subject_decision["matched"],
            "subject_scope": subject_decision["scope"],
            "matched_by": subject_decision["matched_by"],
            "excluded_reason": subject_decision["excluded_reason"],
        }
        material_result = match_material_condition(contract=contract, row=row, subject_scope=material_scope)
        return {
            "sku": material_result["sku"],
            "subject_match": subject_decision["matched"],
            "subject_kind": subject_decision.get("subject_kind"),
            "subject_matched_by": subject_decision.get("matched_by"),
            "field_source": material_result["field_source"],
            "raw_value": material_result["raw_value"],
            "normalized_value": material_result["normalized_material_tokens"],
            "operator": contract.operator,
            "target": contract.value,
            "matched": material_result["matched"],
            **material_result,
        }
    subject_match = subject_decision["matched"]
    source_map = {
        "material": ("body_material", row.get("body_material")),
        "capacity": ("capacity", row.get("capacity")),
        "heat_source": ("heat_source", row.get("heat_source")),
        "usage_scene": ("usage_scenarios", row.get("usage_scenarios")),
        "dimensions": ("size", row.get("size") or row.get("size_info")),
        "weight": ("gross_weight_g", row.get("gross_weight_g")),
        "people": ("target_audience", row.get("target_audience")),
        "color": ("color", row.get("color")),
        "waterproof": (
            "waterproof" if row.get("waterproof") is not None else "waterproof_rating",
            row.get("waterproof") if row.get("waterproof") is not None else row.get("waterproof_rating"),
        ),
    }
    source, raw = source_map.get(str(contract.field or ""), ("", None))
    normalized = raw
    if contract.field in {"capacity", "weight", "dimensions", "people"}:
        normalized, _ = normalize_measurement(raw, str(contract.field))
    field_match = normalized is not None and str(normalized).strip() not in {"", "/", "[]"} and _compare(normalized, str(contract.operator or ""), contract.value)
    return {
        "sku": str(row.get("sku") or "").strip().upper(),
        "subject_match": subject_match,
        "subject_kind": subject_decision.get("subject_kind"),
        "subject_scope": subject_decision.get("scope"),
        "subject_matched_by": subject_decision.get("matched_by"),
        "field_source": source,
        "raw_value": raw,
        "normalized_value": normalized,
        "operator": contract.operator,
        "target": contract.value,
        "matched": bool(subject_match and field_match),
        "excluded_reason": None if subject_match and field_match else subject_decision.get("excluded_reason") or "condition_not_met",
    }


def validate_structured_evidence(
    *,
    contract: StructuredQueryContract,
    filtered_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Keep structured evidence bound to rows that satisfy the active contract."""
    filtered_by_sku = {
        str(row.get("sku") or "").strip().upper(): row
        for row in filtered_rows
        if str(row.get("sku") or "").strip()
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for evidence in evidence_rows:
        item = dict(evidence or {})
        sku = str(item.get("sku") or "").strip().upper()
        if not sku or sku not in filtered_by_sku:
            rejected.append({**item, "rejected_reason": "sku_not_in_filtered_rows" if sku else "unscoped_kb_evidence"})
            continue
        evaluation = evaluate_structured_row(filtered_by_sku[sku], contract)
        if not evaluation.get("subject_match"):
            rejected.append({**item, "rejected_reason": "subject_scope_mismatch"})
            continue
        if not evaluation.get("matched"):
            rejected.append({**item, "rejected_reason": "condition_not_met"})
            continue
        expected_sources = {
            str(proof.get("field_source") or "")
            for proof in evaluation.get("condition_proofs") or [evaluation]
            if str(proof.get("field_source") or "")
        }
        evidence_source = str(item.get("field_source") or "")
        if evidence_source and expected_sources and evidence_source not in expected_sources and evidence_source != "compound":
            rejected.append({**item, "rejected_reason": "field_mismatch"})
            continue
        accepted.append(item)
    return {"accepted_evidence": accepted, "rejected_evidence": rejected}


_EMPTY_FIELD_VALUES = {"", "/", "-", "--", "[]", "null", "none", "未知", "暂无", "未标注", "无"}


def _meaningful_field_text(raw: Any) -> str:
    text = str(raw or "").strip()
    return "" if text.lower() in _EMPTY_FIELD_VALUES else text


def _category_field_values(raw: Any, field: str) -> list[str]:
    text = _meaningful_field_text(raw)
    if not text:
        return []
    if field == "capacity":
        values: list[str] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升)\b", text, re.I):
            value, unit = _normalize_numeric(float(match.group(1)), match.group(2), "capacity")
            display = f"{int(value) if value.is_integer() else value:g}{unit}"
            if display not in values:
                values.append(display)
        return values
    if field == "heat_source":
        values = []
        for part in re.split(r"[\n\r,，、;/；]+", text):
            value = part.strip()
            if _meaningful_field_text(value) and value not in values:
                values.append(value)
        return values
    if field == "material":
        value = re.sub(r"[\s,，;；]+", "、", text).strip("、")
        return [value] if value else []
    return [text]


def classify_heat_source_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "other"
    if text.endswith(("炉", "灶")):
        return "appliance"
    if text.endswith("气罐"):
        return "fuel_source"
    if "酒精" in text:
        return "fuel_source"
    if text in {"木柴", "柴火", "竹炭", "木炭"}:
        return "fuel_source"
    if text in {"明火", "明火直烧"} or text.endswith("直烧"):
        return "heating_method"
    return "other"


def aggregate_category_field_rows(
    rows: list[dict[str, Any]],
    contract: StructuredQueryContract,
) -> dict[str, Any]:
    source_map = {
        "heat_source": "heat_source",
        "capacity": "capacity",
        "material": "body_material",
    }
    field_source = source_map.get(str(contract.field or ""))
    values: list[str] = []
    proofs_by_value: dict[str, dict[str, Any]] = {}
    source_rows: list[dict[str, Any]] = []
    supporting_skus: list[str] = []
    if not field_source:
        return {
            "aggregated_values": values,
            "value_proofs": [],
            "source_rows": source_rows,
            "supporting_skus": supporting_skus,
        }

    for row in rows or []:
        if not _subject_matches(row, str(contract.subject_category or "")):
            continue
        sku = str(row.get("sku") or "").strip().upper()
        raw_value = row.get(field_source)
        row_values = _category_field_values(raw_value, str(contract.field or ""))
        if not sku or not row_values:
            continue
        if sku not in supporting_skus:
            supporting_skus.append(sku)
        source_rows.append(
            {
                "sku": sku,
                "field_source": field_source,
                "raw_value": raw_value,
                "normalized_values": row_values,
            }
        )
        for value in row_values:
            if value not in proofs_by_value:
                values.append(value)
                proofs_by_value[value] = {
                    "value": value,
                    "field_source": field_source,
                    "source_skus": [],
                }
            proofs_by_value[value]["source_skus"].append(sku)

    result = {
        "aggregated_values": values,
        "value_proofs": [proofs_by_value[value] for value in values],
        "source_rows": source_rows,
        "supporting_skus": supporting_skus,
    }
    if contract.field == "heat_source":
        value_groups = {
            "appliance": [],
            "fuel_source": [],
            "heating_method": [],
            "other": [],
        }
        for value in values:
            value_type = classify_heat_source_value(value)
            proofs_by_value[value]["value_type"] = value_type
            value_groups[value_type].append(value)
        result["value_groups"] = value_groups
    return result
