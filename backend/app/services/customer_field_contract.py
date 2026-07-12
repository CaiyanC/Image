from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class FieldContract:
    field_type: str
    aliases: tuple[str, ...]
    semantic_preplan_field_type: str
    full_phrases: tuple[str, ...] = ()


# Field concepts only. This taxonomy does not select products or answer users.
FIELD_CONTRACTS: tuple[FieldContract, ...] = (
    FieldContract("model", ("商品编码", "产品编码", "型号", "SKU", "sku", "货号"), "unknown"),
    FieldContract("dimensions", ("展开后尺寸", "收起后尺寸", "展开尺寸", "收纳尺寸", "长宽高", "大小", "尺寸"), "unknown"),
    FieldContract("specification", ("规格",), "unknown"),
    FieldContract("capacity", ("毫升数", "升数", "容量", "能装多少", "装多少"), "capacity"),
    FieldContract("weight", ("净重", "毛重", "重量", "多重"), "unknown"),
    FieldContract(
        "people",
        ("适用人数", "几个人", "多少人", "几人用", "适用几人", "几人份"),
        "unknown",
        ("适合几个人", "适合多少人", "几个人用", "适用几人", "适用人数", "能供几个人使用", "可供几人", "几人份", "够几个人用"),
    ),
    FieldContract(
        "material",
        ("材质", "材料"),
        "material",
        ("用的是什么材质", "由什么材料制成", "什么材料做的", "是什么材质", "是什么材料", "用什么材料", "材质是什么", "什么材质"),
    ),
    FieldContract("color", ("颜色",), "unknown"),
    FieldContract(
        "heat_source",
        ("电陶炉", "电磁炉", "卡式炉", "酒精炉", "热源", "明火", "直火"),
        "heat_source",
        ("可以直火加热吗", "能放什么炉上用", "能不能明火用", "能不能明火烧", "能不能直火", "可以用酒精炉吗", "能用卡式炉吗", "支持什么热源", "能明火烧吗", "能明火用吗", "可以明火吗", "支持明火吗", "适用什么炉"),
    ),
    FieldContract("dishwasher", ("洗碗机",), "unknown"),
    FieldContract("gift", ("赠品",), "gift"),
    FieldContract("price", ("多少钱", "价格"), "price"),
    FieldContract(
        "warranty",
        ("保修", "质保", "保修期", "质保期"),
        "unknown",
        ("质保多长时间", "保修多长时间", "保修期多久", "质保期多久", "有没有保修", "有没有质保", "保不保修", "有保修吗", "质保多久", "保修多久", "质保几年", "保几年"),
    ),
    FieldContract(
        "shipping",
        ("发货", "寄出", "发出", "发货时效", "配送时效", "送到"),
        "unknown",
        ("现在下单什么时候发", "能不能马上发货", "什么时候能送到", "今天能发货吗", "现在下单多久发", "现在下单几天发", "多久可以寄出", "多久可以发出", "什么时候发货", "多久能发货", "什么时候寄出", "可以当天发吗", "几天能寄出", "什么时候发", "今天能发吗", "发货时效", "配送时效", "多久送到"),
    ),
    FieldContract("accessories", ("套装内容", "包含什么", "配件"), "contents"),
)

DETAIL_FIELD_LABELS = {
    "model": "SKU",
    "dimensions": "尺寸",
    "specification": "规格",
    "capacity": "容量",
    "weight": "重量",
    "people": "适用人数",
    "material": "材质",
    "color": "颜色",
    "heat_source": "heat_source",
    "dishwasher": "洗碗机适配",
    "gift": "赠品",
    "price": "价格",
    "warranty": "保修",
    "shipping": "发货时效",
    "accessories": "配件",
}

# Stable labels emitted by the legacy planner are normalized here before
# Phase 2 consumes them. This maps labels only; it does not detect new text.
LEGACY_DETAIL_FIELD_TYPES = {
    "热源": "heat_source",
}

# Recognized fields may still require an established evidence extractor before
# they are allowed to participate in single-product detail arbitration.
SUPPORTED_DETAIL_FIELDS = frozenset({
    "model",
    "dimensions",
    "specification",
    "capacity",
    "weight",
    "people",
    "material",
    "color",
    "heat_source",
    "dishwasher",
})


@dataclass(frozen=True)
class FieldEvidencePolicy:
    """Allowed evidence for one explicit product-detail field."""

    field_type: str
    aliases: tuple[str, ...]
    structured_fields: tuple[str, ...]
    qa_aliases: tuple[str, ...]
    compatible_field_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class DimensionEvidence:
    value: str
    scope: str


@dataclass(frozen=True)
class EntityScopeNormalization:
    entity_subject: str
    requested_scope: str
    removed_scope_span: tuple[int, int] | None
    normalization_reason: str | None


@dataclass(frozen=True)
class EntitySubjectSelection:
    entity_subject: str
    source: str
    field: str | None
    field_span: tuple[int, int] | None
    raw_subject: str
    requested_scope: str
    removed_scope_span: tuple[int, int] | None
    normalization_reason: str | None
    fallback_used: bool
    reason: str
    core_field_span: tuple[int, int] | None = None
    full_field_phrase_span: tuple[int, int] | None = None
    full_field_phrase: str = ""


def _aliases(field_type: str) -> tuple[str, ...]:
    contract = next((item for item in FIELD_CONTRACTS if item.field_type == field_type), None)
    return contract.aliases if contract else ()


# This policy is field-scoped only. It never chooses a product or generates an answer.
FIELD_EVIDENCE_POLICIES: dict[str, FieldEvidencePolicy] = {
    "model": FieldEvidencePolicy("model", _aliases("model"), ("product.sku", "product.model"), _aliases("model")),
    "dimensions": FieldEvidencePolicy("dimensions", _aliases("dimensions"), ("specs.size_info", "specs.dimensions", "specs.package_size"), _aliases("dimensions")),
    "specification": FieldEvidencePolicy("specification", _aliases("specification"), ("specs.specification",), _aliases("specification")),
    "capacity": FieldEvidencePolicy("capacity", _aliases("capacity"), ("specs.capacity",), _aliases("capacity")),
    "weight": FieldEvidencePolicy("weight", _aliases("weight"), ("specs.gross_weight_g", "specs.net_weight_g", "specs.weight_info"), _aliases("weight")),
    "people": FieldEvidencePolicy("people", _aliases("people"), ("business.target_audience", "specs.capacity"), _aliases("people")),
    "material": FieldEvidencePolicy("material", _aliases("material"), ("specs.body_material",), _aliases("material")),
    "color": FieldEvidencePolicy("color", _aliases("color"), ("specs.color",), _aliases("color")),
    "heat_source": FieldEvidencePolicy("heat_source", _aliases("heat_source"), ("specs.heat_source",), _aliases("heat_source")),
    "dishwasher": FieldEvidencePolicy("dishwasher", _aliases("dishwasher"), ("specs.usage_instruction",), _aliases("dishwasher")),
    "gift": FieldEvidencePolicy("gift", _aliases("gift"), (), _aliases("gift")),
    "price": FieldEvidencePolicy("price", _aliases("price"), (), _aliases("price")),
    "accessories": FieldEvidencePolicy("accessories", _aliases("accessories"), (), _aliases("accessories")),
}


def field_evidence_policy(field_type: str | None) -> FieldEvidencePolicy | None:
    return FIELD_EVIDENCE_POLICIES.get(str(field_type or "").strip())


def is_supported_detail_field(field_type: str | None) -> bool:
    return str(field_type or "").strip() in SUPPORTED_DETAIL_FIELDS


def field_type_from_detail_label(label: str | None) -> str | None:
    value = str(label or "").strip()
    if value in LEGACY_DETAIL_FIELD_TYPES:
        return LEGACY_DETAIL_FIELD_TYPES[value]
    for field_type, detail_label in DETAIL_FIELD_LABELS.items():
        if value == detail_label:
            return field_type
    return None


def qa_evidence_matches_field(question: str, tags: str | None, field_type: str | None) -> bool:
    """Only accept QA whose question or tags explicitly identify the requested field."""
    policy = field_evidence_policy(field_type)
    if not policy:
        return False
    haystack = f"{str(question or '')} {str(tags or '')}".lower()
    return any(alias and alias.lower() in haystack for alias in policy.qa_aliases)


def requested_evidence_scope(question: str, field_type: str | None) -> str:
    if str(field_type or "").strip() != "dimensions":
        return "subject"
    text = str(question or "")
    return "package" if any(term in text for term in ("包装尺寸", "外箱尺寸", "包裹尺寸")) else "subject"


def normalize_field_adjacent_entity_scope(
    *,
    question: str,
    raw_subject: str,
    canonical_field: str | None,
    field_phrase: str = "",
) -> EntityScopeNormalization:
    subject = str(raw_subject or "").strip()
    scope = requested_evidence_scope(question, canonical_field)
    if not subject:
        return EntityScopeNormalization(subject, scope, None, None)
    contract = next((item for item in FIELD_CONTRACTS if item.field_type == canonical_field), None)
    if contract is None:
        return EntityScopeNormalization(subject, scope, None, None)
    remainder = str(question or "")[len(subject):] if str(question or "").startswith(subject) else ""
    expected_field_starts = tuple(
        value
        for value in (str(field_phrase or "").strip(), *contract.aliases)
        if value
    )
    if not any(remainder.startswith(value) for value in expected_field_starts):
        return EntityScopeNormalization(subject, scope, None, None)
    suffixes = (
        (("的包装", "外包装", "包装后", "包装"), "package", "field_adjacent_package_scope"),
        (("商品本身", "本身的", "自身的", "的主体", "本身", "自身", "本体", "主体"), "subject", "field_adjacent_subject_scope"),
    )
    for terms, expected_scope, reason in suffixes:
        for term in sorted(terms, key=len, reverse=True):
            if subject.endswith(term) and scope == expected_scope:
                start = len(subject) - len(term)
                entity_subject = subject[:start].rstrip().removesuffix("的").rstrip()
                if entity_subject:
                    return EntityScopeNormalization(entity_subject, scope, (start, len(subject)), reason)
    return EntityScopeNormalization(subject, scope, None, None)


def _dimension_scope(label: str) -> str:
    value = str(label or "").strip()
    if value in {"", "尺寸", "大小", "长宽高", "展开尺寸", "收纳尺寸", "展开后尺寸", "收起后尺寸"}:
        return "subject"
    if any(term in value for term in ("包装", "外箱", "包裹")):
        return "package"
    return "component"


def select_dimension_evidence(raw_value: Any, *, requested_scope: str) -> DimensionEvidence | None:
    """Return only structured dimensions matching the requested evidence scope."""
    value = str(raw_value or "").strip()
    if not value or value in {"[]", "/"}:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return DimensionEvidence(value=value, scope="subject") if requested_scope == "subject" else None
    if not isinstance(parsed, list):
        return DimensionEvidence(value=value, scope="subject") if requested_scope == "subject" else None
    selected = [
        item
        for item in parsed
        if isinstance(item, dict)
        and str(item.get("value") or "").strip()
        and _dimension_scope(str(item.get("label") or "")) == requested_scope
    ]
    if not selected:
        return None
    return DimensionEvidence(
        value="；".join(str(item.get("value") or "").strip() for item in selected),
        scope=requested_scope,
    )


def iter_field_aliases() -> Iterable[tuple[str, FieldContract]]:
    pairs = [(alias, contract) for contract in FIELD_CONTRACTS for alias in contract.aliases]
    return tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))


def iter_full_field_phrases() -> Iterable[tuple[str, FieldContract]]:
    pairs = [(phrase, contract) for contract in FIELD_CONTRACTS for phrase in contract.full_phrases]
    return tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))


def _field_phrase_match(text: str) -> tuple[FieldContract, str, int, bool] | None:
    value = str(text or "")
    for phrase, contract in iter_full_field_phrases():
        index = value.lower().find(phrase.lower())
        if index >= 0:
            return contract, phrase, index, True
    for alias, contract in iter_field_aliases():
        index = value.lower().find(alias.lower())
        if index >= 0:
            return contract, alias, index, False
    return None


def detect_field_contract(text: str) -> FieldContract | None:
    match = _field_phrase_match(text)
    return match[0] if match else None


def detect_shipping_intent_signal(text: str) -> bool:
    match = _field_phrase_match(text)
    return bool(match and match[0].field_type == "shipping")


def select_entity_subject_for_routing(
    *,
    raw_question: str,
    fallback_product_like_subject: str = "",
    fallback_named_subject: str = "",
) -> EntitySubjectSelection:
    text = str(raw_question or "").strip(" ，。？！；;：:")
    match = _field_phrase_match(text)
    if match is not None:
        contract, phrase, index, is_full_phrase = match
        full_span = (index, index + len(phrase))
        core_match = next(
            (
                (phrase.lower().find(alias.lower()), alias)
                for alias in sorted(contract.aliases, key=len, reverse=True)
                if phrase.lower().find(alias.lower()) >= 0
            ),
            (0, phrase),
        )
        core_index, core_alias = core_match
        core_span = (index + core_index, index + core_index + len(core_alias))
        raw_subject = text[:index].strip(" ，。？！；;：:")
        raw_subject = re.sub(r"(?:的|有)\s*$", "", raw_subject).strip()
        normalized = normalize_field_adjacent_entity_scope(
            question=text,
            raw_subject=raw_subject,
            canonical_field=contract.field_type,
            field_phrase=phrase,
        )
        reason = normalized.normalization_reason or "field_contract_subject"
        return EntitySubjectSelection(
            entity_subject=normalized.entity_subject,
            source="field_contract",
            field=contract.field_type,
            field_span=full_span,
            raw_subject=raw_subject,
            requested_scope=normalized.requested_scope,
            removed_scope_span=normalized.removed_scope_span,
            normalization_reason=normalized.normalization_reason,
            fallback_used=False,
            reason=reason if normalized.entity_subject else "field_contract_empty_subject",
            core_field_span=core_span,
            full_field_phrase_span=full_span,
            full_field_phrase=phrase if is_full_phrase else "",
        )

    fallback = str(fallback_product_like_subject or fallback_named_subject or "").strip()
    return EntitySubjectSelection(
        entity_subject=fallback,
        source="product_like_fallback" if fallback_product_like_subject else "named_fallback",
        field=None,
        field_span=None,
        raw_subject=fallback,
        requested_scope="subject",
        removed_scope_span=None,
        normalization_reason=None,
        fallback_used=bool(fallback),
        reason="field_contract_not_detected" if fallback else "no_entity_subject",
    )


def detect_field_types(text: str) -> tuple[str, ...]:
    value = str(text or "")
    return tuple(
        contract.field_type
        for contract in FIELD_CONTRACTS
        if any(alias in value for alias in contract.aliases)
    )


def semantic_preplan_field_type(field_type: str | None) -> str:
    """Map richer contracts into the current stable planner enum."""
    value = str(field_type or "").strip()
    for contract in FIELD_CONTRACTS:
        if value == contract.field_type:
            return contract.semantic_preplan_field_type
    return value


def field_contract_metadata(text: str) -> dict[str, str | None]:
    contract = detect_field_contract(text)
    field_type = contract.field_type if contract else None
    return {
        "contract_field_type": field_type,
        "planner_compatible_field_type": semantic_preplan_field_type(field_type),
    }


def product_detail_field_label(field_type: str | None) -> str | None:
    return DETAIL_FIELD_LABELS.get(str(field_type or "").strip())


def resolve_requested_field_contract(
    question: str,
    planner_plan: dict[str, Any] | None = None,
    *,
    compatibility_fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Normalize Phase 2 field consumption without replacing legacy extraction."""
    text = str(question or "")
    plan = planner_plan if isinstance(planner_plan, dict) else {}
    requested_fields = list(dict.fromkeys(
        str(field or "").strip()
        for field in compatibility_fields
        if str(field or "").strip()
    ))
    if not requested_fields:
        requested_fields = [
            label
            for field_type in detect_field_types(text)
            if (label := product_detail_field_label(field_type))
        ]

    field_spans: list[dict[str, Any]] = []
    for alias, contract in iter_field_aliases():
        start = text.find(alias)
        if start < 0:
            continue
        field_spans.append({
            "field_type": contract.field_type,
            "alias": alias,
            "start": start,
            "end": start + len(alias),
        })
    field_spans.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))

    canonical_fields = list(dict.fromkeys(
        field_type
        for field in requested_fields
        if (field_type := field_type_from_detail_label(field))
    ))
    for field_type in detect_field_types(text):
        if field_type not in canonical_fields:
            canonical_fields.append(field_type)
    supported_fields = [field for field in canonical_fields if is_supported_detail_field(field)]
    unsupported_fields = [field for field in canonical_fields if not is_supported_detail_field(field)]
    requested_field = str(plan.get("requested_field") or "").strip() or (requested_fields[0] if requested_fields else None)
    return {
        "requested_field": requested_field,
        "requested_fields": requested_fields,
        "field_spans": field_spans,
        "canonical_fields": canonical_fields,
        "supported_fields": supported_fields,
        "unsupported_fields": unsupported_fields,
        "compound": bool(
            plan.get("compound")
            or plan.get("routing_conflict")
            or plan.get("multi_field")
            or len(requested_fields) > 1
        ),
    }
