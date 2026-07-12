from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..models.product import Product
from . import customer_agent_service
from .customer_field_contract import detect_field_contract, select_entity_subject_for_routing


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


@dataclass(frozen=True)
class SingleProductResolutionDecision:
    allowed: bool
    resolved_sku: str | None
    resolved_product_id: str | None
    reason: str
    match_level: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BoundProductIdentityDecision:
    allowed: bool
    sku: str | None
    source: str | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BoundProductIdentityProvenance:
    source: str
    resolved_sku: str
    match_level: str
    confidence: str
    origin_stage: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EntityContractSelection:
    contract: EntityResolutionContract
    source: str
    reason: str
    override_conflict: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "reason": self.reason,
            "override_conflict": self.override_conflict,
            "contract": self.contract.to_dict(),
        }


_STRONG_SINGLE_PRODUCT_MATCH_LEVELS = {
    "sku_exact",
    "canonical_name_exact",
    "normalized_alias_exact",
}

_TRUSTED_BOUND_PRODUCT_IDENTITY_SOURCES = {
    "explicit_sku_exact",
    "normalized_sku_exact",
    "entity_contract_resolved_exact",
    "named_product_canonical_exact",
    "named_product_alias_exact",
    "recommendation_context_anchor",
    "recommendation_context_ordinal",
    "recommendation_context_pronoun",
    "phase2_resolved_entity",
    "field_evidence_repair",
}


def _candidate_identity(candidate: Product | dict) -> tuple[str, str | None]:
    if isinstance(candidate, dict):
        sku = str(candidate.get("sku") or "").strip().upper()
        product_id = candidate.get("id") or candidate.get("product_id")
    else:
        sku = str(getattr(candidate, "sku", "") or "").strip().upper()
        product_id = getattr(candidate, "id", None)
    return sku, str(product_id) if product_id is not None else None


def can_trust_bound_product_identity(
    *,
    product: Product | dict | None,
    sku: str | None,
    entity_contract: EntityResolutionContract | None = None,
    identity_source: str | None = None,
) -> BoundProductIdentityDecision:
    bound_sku = str(sku or "").strip().upper()
    product_sku, _ = _candidate_identity(product) if product is not None else ("", None)
    if entity_contract is not None:
        contract_sku = str(entity_contract.resolved_sku or "").strip().upper()
        if (
            entity_contract.status != "resolved"
            or entity_contract.confidence != "high"
            or entity_contract.matched_by not in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS
        ):
            return BoundProductIdentityDecision(False, None, identity_source, "entity_contract_not_resolved")
        if contract_sku != bound_sku:
            return BoundProductIdentityDecision(False, None, identity_source, "entity_contract_sku_mismatch")
        if not bound_sku or not product_sku or bound_sku != product_sku:
            return BoundProductIdentityDecision(False, None, identity_source, "bound_product_sku_mismatch")
        return BoundProductIdentityDecision(True, bound_sku, "entity_contract_resolved_exact", "trusted_identity")
    source = str(identity_source or "").strip() or None
    if source is None:
        return BoundProductIdentityDecision(False, None, None, "missing_identity_provenance")
    if source not in _TRUSTED_BOUND_PRODUCT_IDENTITY_SOURCES:
        return BoundProductIdentityDecision(False, None, source, "weak_identity_source")
    if not bound_sku or not product_sku or bound_sku != product_sku:
        return BoundProductIdentityDecision(False, None, source, "bound_product_sku_mismatch")
    return BoundProductIdentityDecision(True, bound_sku, source, "trusted_identity")


def identity_provenance_from_entity_contract(
    entity_contract: EntityResolutionContract | None,
    *,
    bound_sku: str,
    origin_stage: str,
) -> BoundProductIdentityProvenance | None:
    if entity_contract is None:
        return None
    resolved_sku = str(entity_contract.resolved_sku or "").strip().upper()
    expected_sku = str(bound_sku or "").strip().upper()
    if (
        entity_contract.status != "resolved"
        or entity_contract.confidence != "high"
        or entity_contract.matched_by not in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS
        or not resolved_sku
        or resolved_sku != expected_sku
    ):
        return None
    source_by_match = {
        "sku_exact": "explicit_sku_exact",
        "canonical_name_exact": "named_product_canonical_exact",
        "normalized_alias_exact": "named_product_alias_exact",
    }
    return BoundProductIdentityProvenance(
        source=source_by_match[entity_contract.matched_by],
        resolved_sku=resolved_sku,
        match_level=entity_contract.matched_by,
        confidence=entity_contract.confidence,
        origin_stage=str(origin_stage or "").strip(),
    )


def can_resolve_single_product(
    entity_contract: EntityResolutionContract | None,
    candidates: list[Product | dict],
    *,
    subject_compatible: bool = True,
    family_or_variant_ambiguous: bool = False,
    component_scope_unresolved: bool = False,
) -> SingleProductResolutionDecision:
    match_level = str(getattr(entity_contract, "matched_by", "") or "") or None

    def denied(reason: str) -> SingleProductResolutionDecision:
        return SingleProductResolutionDecision(False, None, None, reason, match_level)

    if component_scope_unresolved:
        return denied("component_scope_unresolved")
    if family_or_variant_ambiguous or match_level == "family_alias" or (
        entity_contract and entity_contract.status_reason == "diagnostic_family_overlap"
    ):
        return denied("family_or_variant_ambiguous")
    if entity_contract is None:
        return denied("entity_not_resolved")
    if entity_contract.status != "resolved":
        if len(entity_contract.resolver_candidate_skus) > 1:
            return denied("multiple_candidates")
        if entity_contract.status_reason == "resolver_weak_single_candidate" or match_level in {
            "substring",
            "contains",
            "fuzzy",
            "semantic",
            "token_overlap",
        }:
            return denied("weak_single_candidate")
        return denied("entity_not_resolved")
    if entity_contract.confidence != "high" or match_level not in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS:
        return denied("match_level_not_strong")
    resolved_sku = str(entity_contract.resolved_sku or "").strip().upper()
    if not resolved_sku:
        return denied("resolved_candidate_missing")
    if entity_contract.resolver_candidate_skus != [resolved_sku]:
        reason = "multiple_candidates" if len(entity_contract.resolver_candidate_skus) > 1 else "resolved_candidate_missing"
        return denied(reason)
    candidate_map: dict[str, str | None] = {}
    for candidate in candidates:
        sku, product_id = _candidate_identity(candidate)
        if sku:
            candidate_map[sku] = product_id
    if resolved_sku not in candidate_map:
        return denied("resolved_candidate_missing")
    if not subject_compatible:
        return denied("subject_type_mismatch")
    return SingleProductResolutionDecision(True, resolved_sku, candidate_map[resolved_sku], "resolved_exact", match_level)


def choose_effective_entity_contract(
    default_contract: EntityResolutionContract,
    override_contract: EntityResolutionContract | None,
    candidates: list[Product | dict],
) -> EntityContractSelection:
    default_decision = can_resolve_single_product(default_contract, candidates)
    override_decision = can_resolve_single_product(override_contract, candidates)
    if default_decision.allowed:
        if (
            override_decision.allowed
            and override_decision.resolved_sku != default_decision.resolved_sku
        ):
            return EntityContractSelection(default_contract, "default", "strong_override_conflict", True)
        return EntityContractSelection(default_contract, "default", "default_strong_exact")
    if override_contract is not None and override_decision.allowed:
        return EntityContractSelection(override_contract, "override", "override_strong_exact")
    return EntityContractSelection(default_contract, "default", "override_not_strong")


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
    return select_entity_subject_for_routing(
        raw_question=value,
        fallback_named_subject=value,
    ).entity_subject


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
    entity_text_override: str | None = None,
) -> EntityResolutionContract:
    field = detect_field_contract(question)
    entity_text = str(entity_text_override or "").strip() or _entity_text_from_question(question)
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
    exact_candidates = [
        product
        for product in formal_candidates
        if _matched_by(entity_text, product) in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS
    ]
    if len(exact_candidates) == 1:
        formal_candidates = exact_candidates
        resolver_candidate_skus = _skus(formal_candidates)
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
