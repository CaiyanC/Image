from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..models.product import Product
from . import customer_agent_service
from .customer_field_contract import detect_field_contract


_DISPLAY_VERSION_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*(?:版本|版)[\s\-_]*", re.IGNORECASE)
_DISPLAY_LABEL_PREFIX_RE = re.compile(r"^[\[(（【][^\])）】]+[\])）】]\s*", re.IGNORECASE)
_VERSION_TOKEN_RE = re.compile(r"(?:pro|plus|max|lite|mini|ultra)", re.IGNORECASE)
_FAMILY_CATEGORY_SUFFIX_RE = re.compile(r"(?:水壶|保温杯|水杯|套锅|单锅|炒锅|煎锅|烤盘|椅子|桌椅|炉具|炉子)$")
_GENERIC_CATEGORY_TERMS = {"水壶", "水杯", "杯", "杯子", "锅", "锅具", "炉", "炉具", "炉子", "椅子", "桌椅", "配件", "产品", "商品", "水具"}


@dataclass(frozen=True)
class EntityResolutionContract:
    entity_text: str
    normalized_entity_text: str
    status: str
    resolved_sku: str | None
    resolver_candidate_skus: list[str]
    diagnostic_candidate_skus: list[str]
    candidate_skus: list[str]
    matched_by: str
    confidence: str
    is_unique: bool
    matched_span: tuple[int, int] | None
    field_type: str | None
    status_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _normalized(value: str) -> str:
    return customer_agent_service.normalize_search_text(value).lower().strip()


def _display_aliases(value: str) -> set[str]:
    normalized = _normalized(value)
    aliases = {normalized} if normalized else set()
    pending = [normalized]
    while pending:
        candidate = pending.pop()
        for pattern in (_DISPLAY_VERSION_PREFIX_RE, _DISPLAY_LABEL_PREFIX_RE):
            trimmed = pattern.sub("", candidate).strip(" -_")
            if trimmed and trimmed not in aliases:
                aliases.add(trimmed)
                pending.append(trimmed)
        if "-" in candidate:
            _, suffix = candidate.split("-", 1)
            suffix = suffix.strip(" -_")
            if len(suffix) >= 4 and re.search(r"\d", suffix) and suffix not in aliases:
                aliases.add(suffix)
                pending.append(suffix)
    return aliases


def _contract_family_aliases(value: str) -> set[str]:
    aliases = set(customer_agent_service.product_name_family_aliases(value))
    for alias in _display_aliases(value):
        stripped = _FAMILY_CATEGORY_SUFFIX_RE.sub("", alias).strip(" -_")
        stripped = _VERSION_TOKEN_RE.sub("", stripped).strip(" -_")
        if len(stripped) >= 2:
            aliases.add(stripped)
    return {_normalized(alias) for alias in aliases if _normalized(alias)}


def _family_key(value: str) -> str:
    normalized = _normalized(value)
    normalized = _FAMILY_CATEGORY_SUFFIX_RE.sub("", normalized).strip(" -_")
    return _VERSION_TOKEN_RE.sub("", normalized).strip(" -_")


def _entity_text_from_question(question: str) -> str:
    value = str(question or "").strip(" ，。？！；;：:")
    field = detect_field_contract(value)
    if not field:
        return value
    for alias in sorted(field.aliases, key=len, reverse=True):
        match = re.match(rf"^(?P<entity>.+?)(?:的|有)?{re.escape(alias)}(?:是|为|有|是多少|多少|吗|呢|？|。|$).*", value, flags=re.IGNORECASE)
        if match:
            entity = str(match.group("entity") or "").strip(" ，。？！；;：:")
            return re.sub(r"(?:的|有)$", "", entity).strip()
        index = value.lower().find(alias.lower())
        if index > 0:
            entity = value[:index].strip(" ，。？！；;：:")
            return re.sub(r"(?:的|有)$", "", entity).strip()
    return ""


def _matched_by(entity: str, product: Product) -> str:
    normalized_entity = _normalized(entity)
    if not normalized_entity:
        return "none"
    sku = str(getattr(product, "sku", "") or "").strip().upper()
    if normalized_entity.upper() == sku:
        return "sku_exact"
    names = (str(getattr(product, "product_name_cn", "") or ""), str(getattr(product, "product_name_en", "") or ""))
    canonical = {_normalized(name) for name in names if name}
    if normalized_entity in canonical:
        return "canonical_name_exact"
    aliases = {alias for name in names for alias in _display_aliases(name)}
    if normalized_entity in aliases:
        return "normalized_alias_exact"
    families = {alias for name in names for alias in _contract_family_aliases(name)}
    if _family_key(normalized_entity) and _family_key(normalized_entity) in families:
        return "family_alias"
    if any(normalized_entity in candidate or candidate in normalized_entity for candidate in canonical if candidate):
        return "substring"
    return "fuzzy"


def _skus(products: list[Product]) -> list[str]:
    return list(dict.fromkeys(str(getattr(product, "sku", "") or "").strip().upper() for product in products if str(getattr(product, "sku", "") or "").strip()))


def build_entity_resolution_contract(
    question: str,
    products: list[Product],
    *,
    resolver_candidates: list[Product] | None = None,
) -> EntityResolutionContract:
    field = detect_field_contract(question)
    entity_text = _entity_text_from_question(question)
    normalized_entity = _normalized(entity_text)
    matched_span = None
    if entity_text:
        start = str(question or "").find(entity_text)
        if start >= 0:
            matched_span = (start, start + len(entity_text))
    field_type = field.field_type if field else None
    if normalized_entity in _GENERIC_CATEGORY_TERMS:
        return EntityResolutionContract(entity_text, normalized_entity, "generic", None, [], [], [], "none", "low", False, matched_span, field_type, "generic_or_missing_entity")
    sku_map = {_normalized(str(getattr(product, "sku", "") or "")).upper(): product for product in products}
    explicit_skus = [sku for sku in customer_agent_service._extract_skus(entity_text) if sku in sku_map]
    if len(explicit_skus) == 1:
        resolved_sku = str(getattr(sku_map[explicit_skus[0]], "sku", "") or "").strip().upper()
        return EntityResolutionContract(entity_text, normalized_entity, "resolved", resolved_sku, [resolved_sku], [], [resolved_sku], "sku_exact", "high", True, matched_span, field_type, "resolver_sku_exact")
    formal_candidates = resolver_candidates if resolver_candidates is not None else customer_agent_service.resolve_named_product_candidates(question, products, subject=entity_text or question)
    resolver_candidate_skus = _skus(formal_candidates)
    if not normalized_entity:
        if len(resolver_candidate_skus) == 1:
            recovered = str(getattr(formal_candidates[0], "product_name_cn", "") or getattr(formal_candidates[0], "product_name_en", "") or "").strip()
            if recovered and recovered in str(question or ""):
                entity_text = recovered
                normalized_entity = _normalized(recovered)
                start = str(question).find(recovered)
                matched_span = (start, start + len(recovered)) if start >= 0 else None
            else:
                return EntityResolutionContract(entity_text, normalized_entity, "ambiguous", None, resolver_candidate_skus, [], resolver_candidate_skus, "none", "medium", False, matched_span, field_type, "resolver_candidate_without_entity_span")
        elif len(resolver_candidate_skus) > 1:
            return EntityResolutionContract(entity_text, normalized_entity, "ambiguous", None, resolver_candidate_skus, [], resolver_candidate_skus, "none", "medium", False, matched_span, field_type, "resolver_multiple_candidates_without_entity_span")
        else:
            return EntityResolutionContract(entity_text, normalized_entity, "generic", None, [], [], [], "none", "low", False, matched_span, field_type, "generic_or_missing_entity")
    diagnostic_candidates: list[Product] = []
    if not resolver_candidate_skus:
        diagnostic_candidates = [
            product
            for product in products
            if _family_key(normalized_entity) in _contract_family_aliases(str(getattr(product, "product_name_cn", "") or ""))
            or _family_key(normalized_entity) in _contract_family_aliases(str(getattr(product, "product_name_en", "") or ""))
        ]
    diagnostic_candidate_skus = _skus(diagnostic_candidates)
    candidate_skus = list(dict.fromkeys(resolver_candidate_skus + diagnostic_candidate_skus))
    if not candidate_skus:
        return EntityResolutionContract(entity_text, normalized_entity, "unresolved", None, [], [], [], "none", "low", False, matched_span, field_type, "no_candidates")
    if len(resolver_candidate_skus) != 1:
        reason = "diagnostic_family_overlap" if diagnostic_candidate_skus else "resolver_multiple_candidates"
        return EntityResolutionContract(entity_text, normalized_entity, "ambiguous", None, resolver_candidate_skus, diagnostic_candidate_skus, candidate_skus, "none", "medium", False, matched_span, field_type, reason)
    matched_by = _matched_by(entity_text, formal_candidates[0])
    if matched_by in {"sku_exact", "canonical_name_exact", "normalized_alias_exact"}:
        return EntityResolutionContract(entity_text, normalized_entity, "resolved", resolver_candidate_skus[0], resolver_candidate_skus, diagnostic_candidate_skus, candidate_skus, matched_by, "high", True, matched_span, field_type, "resolver_unique_exact")
    return EntityResolutionContract(entity_text, normalized_entity, "ambiguous", None, resolver_candidate_skus, diagnostic_candidate_skus, candidate_skus, matched_by, "medium", False, matched_span, field_type, "resolver_weak_single_candidate")


def build_entity_resolution_contract_observation(question: str, products: list[Product], *, resolver_candidates: list[Product] | None = None) -> dict:
    """Observation-only wrapper for callers that already have product rows."""
    try:
        return {"entity_resolution_contract": build_entity_resolution_contract(question, products, resolver_candidates=resolver_candidates).to_dict()}
    except Exception as exc:
        return {"entity_resolution_contract_error": f"{type(exc).__name__}: {exc}"[:240]}
