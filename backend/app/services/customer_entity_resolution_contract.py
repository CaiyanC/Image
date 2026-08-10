from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from ..models.product import Product
from . import customer_agent_service
from .customer_field_contract import detect_field_contract, select_entity_subject_for_routing


_DISPLAY_VERSION_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*(?:版本|版)[\s\-_]*", re.IGNORECASE)
_DISPLAY_LABEL_PREFIX_RE = re.compile(r"^[\[(（【][^\])）】]+[\])）】]\s*", re.IGNORECASE)
_NUMERIC_VERSION_VARIANT_RE = re.compile(
    r"(?:(?:\bv\s*)(\d+(?:\.\d+)+)|(\d+(?:\.\d+)+)\s*(?:版本|版))",
    re.IGNORECASE,
)
_VERSION_TOKEN_RE = re.compile(r"(?:pro|plus|max|lite|mini|ultra)", re.IGNORECASE)
_FAMILY_CATEGORY_SUFFIX_RE = re.compile(r"(?:水壶|保温杯|水杯|套锅|单锅|炒锅|煎锅|烤盘|盘|椅子|桌椅|炉具|炉子)$")
_GENERIC_CATEGORY_TERMS = {"水壶", "水杯", "杯", "杯子", "锅", "锅具", "炉", "炉具", "炉子", "椅子", "桌椅", "配件", "产品", "商品", "水具"}
_CUP_COUNT_RE = re.compile(r"(?<!\d)(\d{1,3})\s*杯")
_COLOR_ALIASES = {
    "黑": "黑",
    "黑色": "黑",
    "白": "白",
    "白色": "白",
    "蓝": "蓝",
    "蓝色": "蓝",
    "绿": "绿",
    "绿色": "绿",
    "粉": "粉",
    "粉色": "粉",
    "红": "红",
    "红色": "红",
    "灰": "灰",
    "灰色": "灰",
    "银": "银",
    "银色": "银",
    "金": "金",
    "金色": "金",
    "橙": "橙",
    "橙色": "橙",
    "黄": "黄",
    "黄色": "黄",
    "紫": "紫",
    "紫色": "紫",
    "棕": "棕",
    "棕色": "棕",
    "咖色": "棕",
    "米色": "米",
    "卡其色": "卡其",
}


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
    "normalized_sku_exact",
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
        "normalized_sku_exact": "normalized_sku_exact",
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


def _raw_sku_identity_key(value: str) -> str:
    """Normalize casing/separators without expanding parenthesized variants."""
    raw = str(value or "").strip().upper().replace("_", "-")
    return _normalized(raw).upper() if raw else ""


def _explicit_sku_identity_keys(value: str) -> set[str]:
    """Return catalog-verifiable equivalents for an explicit SKU token.

    Some upstream systems serialize a parenthesized variant segment with a
    hyphen (``CT-T04(BM)`` → ``CT-T04-BM``). This is not fuzzy matching: the
    alternate key is usable only when exactly one real catalog SKU owns it.
    """
    raw = str(value or "").strip().upper().replace("_", "-")
    normalized = _raw_sku_identity_key(raw)
    if not normalized:
        return set()
    parenthetical = re.sub(r"[（(]\s*([A-Z0-9]+)\s*[）)]", r"-\1", raw)
    return {
        key
        for key in (normalized, _normalized(parenthetical).upper())
        if key
    }


def _catalog_unique_exact_alias_product(
    entity: str,
    products: list[Product],
) -> Product | None:
    """Return the sole catalog product owned by an exact display alias.

    Alias ownership is deliberately stricter than an exact match on one row:
    the alias must not occur inside any other product's canonical/display name.
    This keeps omitted colour, size, and version variants fail-closed while
    allowing a specific normalized display name to outrank generic substring
    recall.
    """
    normalized_entity = _normalized(entity)
    if not normalized_entity:
        return None

    exact_owners: dict[str, Product] = {}
    containing_owner_skus: set[str] = set()
    for product in products:
        sku = str(getattr(product, "sku", "") or "").strip().upper()
        if not sku:
            continue
        aliases = {
            alias
            for raw_name in (
                str(getattr(product, "product_name_cn", "") or "").strip(),
                str(getattr(product, "product_name_en", "") or "").strip(),
            )
            for alias in _display_aliases(raw_name)
            if alias
        }
        if normalized_entity in aliases:
            exact_owners[sku] = product
        if any(normalized_entity in alias for alias in aliases):
            containing_owner_skus.add(sku)

    if len(exact_owners) != 1:
        return None
    sku, product = next(iter(exact_owners.items()))
    return product if containing_owner_skus == {sku} else None


def recover_explicit_versioned_subject(question: str, subject: str) -> str:
    """Recover only a version-bearing current-turn identity span for validation."""
    raw_question = str(question or "")
    raw_subject = str(subject or "").strip()
    if not raw_question or not raw_subject:
        return ""
    version = r"(?:(?:v\s*)\d+(?:\.\d+)+|\d+(?:\.\d+)+\s*(?:版本|版))"
    match = re.search(rf"({version}\s*[-—–_]?\s*{re.escape(raw_subject)})", raw_question, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def unique_canonical_subject_in_question(question: str, products: list[Product]) -> str:
    """Return a unique longest catalog display alias explicitly present.

    This supplies deterministic identity input when a validated semantic field
    has no predicate span. Semantic entities are ignored: only current catalog
    names/aliases qualify, a longer variant beats its overlapping base name,
    and aliases shared with another catalog row fail closed.
    """
    normalized_question = _normalized(question)
    if not normalized_question:
        return ""
    question_versions = _numeric_version_variants(question)
    canonical_matches: dict[str, set[str]] = {}
    for product in products:
        sku = str(getattr(product, "sku", "") or "").strip().upper()
        product_versions = set().union(
            _numeric_version_variants(str(getattr(product, "product_name_cn", "") or "")),
            _numeric_version_variants(str(getattr(product, "product_name_en", "") or "")),
        )
        # A display alias can intentionally omit a version prefix, but an
        # explicit version in the current turn is identity-bearing. Do not let
        # that derived alias revive a different catalog version.
        if question_versions and product_versions and question_versions != product_versions:
            continue
        for raw_name in (
            str(getattr(product, "product_name_cn", "") or "").strip(),
            str(getattr(product, "product_name_en", "") or "").strip(),
        ):
            normalized_name = _normalized(raw_name)
            if sku and normalized_name and normalized_name in normalized_question:
                canonical_matches.setdefault(normalized_name, set()).add(sku)
    if canonical_matches:
        longest_canonical = max(map(len, canonical_matches))
        strongest_canonical = [
            owners for alias, owners in canonical_matches.items() if len(alias) == longest_canonical
        ]
        if any(len(owners) != 1 for owners in strongest_canonical):
            return ""
    matches: list[tuple[int, int, str, str]] = []
    for product in products:
        sku = str(getattr(product, "sku", "") or "").strip().upper()
        product_versions = set().union(
            _numeric_version_variants(str(getattr(product, "product_name_cn", "") or "")),
            _numeric_version_variants(str(getattr(product, "product_name_en", "") or "")),
        )
        if question_versions and product_versions and question_versions != product_versions:
            continue
        for raw_name in (
            str(getattr(product, "product_name_cn", "") or "").strip(),
            str(getattr(product, "product_name_en", "") or "").strip(),
        ):
            for alias in _display_aliases(raw_name):
                if not sku or not alias or alias not in normalized_question:
                    continue
                canonical_owner_skus = {
                    str(getattr(candidate, "sku", "") or "").strip().upper()
                    for candidate in products
                    if any(
                        _normalized(candidate_name) == alias
                        for candidate_name in (
                            str(getattr(candidate, "product_name_cn", "") or "").strip(),
                            str(getattr(candidate, "product_name_en", "") or "").strip(),
                        )
                        if candidate_name
                    )
                }
                owner = _catalog_unique_exact_alias_product(alias, products)
                alias_owner_sku = str(getattr(owner, "sku", "") or "").strip().upper() if owner else ""
                # A canonical full name remains exact even when a longer
                # variant derives the same family alias. If no canonical row
                # owns the alias, derived aliases must still have one owner.
                if canonical_owner_skus:
                    if canonical_owner_skus != {sku}:
                        continue
                elif alias_owner_sku != sku:
                    continue
                display_alias = next(
                    (
                        candidate
                        for candidate in customer_agent_service.product_name_aliases(raw_name)
                        if _normalized(candidate) == alias
                    ),
                    raw_name if _normalized(raw_name) == alias else alias,
                )
                matches.append((len(alias), normalized_question.index(alias), sku, display_alias))
    if not matches:
        return ""
    longest = max(item[0] for item in matches)
    strongest = [item for item in matches if item[0] == longest]
    if len({item[2] for item in strongest}) != 1:
        return ""
    strongest.sort(key=lambda item: (item[1], item[3]))
    return strongest[0][3]


def _display_aliases(value: str) -> set[str]:
    normalized = _normalized(value)
    aliases = {normalized} if normalized else set()
    # Canonical display aliases (notably names with a parenthesized
    # colour/label removed) are strong only when unique across the candidate
    # set. Shared aliases still produce the normal ambiguity contract.
    aliases.update(
        _normalized(alias)
        for alias in customer_agent_service.product_name_aliases(value)
        if _normalized(alias)
    )
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
    for alias in list(aliases):
        compact = re.sub(r"[\s\-_]+", "", alias)
        if compact:
            aliases.add(compact)
        for color_alias, canonical_color in _COLOR_ALIASES.items():
            if compact.endswith(color_alias):
                aliases.add(f"{compact[:-len(color_alias)]}{canonical_color}")
    return aliases


def _numeric_version_variants(value: str) -> set[str]:
    """Extract explicit version labels without treating dimensions as variants."""
    return {
        str(match.group(1) or match.group(2) or "").strip().lower()
        for match in _NUMERIC_VERSION_VARIANT_RE.finditer(str(value or ""))
        if str(match.group(1) or match.group(2) or "").strip()
    }


def _explicit_variant_attributes(value: str) -> dict[str, set[str]]:
    normalized = _normalized(value)
    cups = {match.group(1) for match in _CUP_COUNT_RE.finditer(normalized)}
    versions = _numeric_version_variants(value)
    colors: set[str] = set()
    complete_color_words = tuple(
        sorted(
            (
                alias
                for alias in _COLOR_ALIASES
                if len(alias) > 1 and alias.endswith("色")
            ),
            key=len,
            reverse=True,
        )
    )
    complete_color_pattern = "|".join(re.escape(alias) for alias in complete_color_words)
    for alias, canonical in sorted(_COLOR_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        # Full color words are safe lexical attributes. Single-character
        # colors are only variant attributes at the end of the extracted
        # entity (optionally followed by “款”); otherwise labels such as
        # “金波专属” would be misread as a gold-color constraint.
        if len(alias) > 1:
            if alias in normalized:
                colors.add(canonical)
        elif re.search(
            rf"{re.escape(alias)}(?:款)?(?=$|但|可是|不过|和|与|、|/)",
            normalized,
        ) or (
            complete_color_pattern
            and re.search(rf"{re.escape(alias)}(?=(?:{complete_color_pattern}))", normalized)
        ):
            colors.add(canonical)
    return {"cup_count": cups, "color": colors, "version": versions}


def _product_variant_attributes(product: Product) -> dict[str, set[str]]:
    combined = {"cup_count": set(), "color": set(), "version": set()}
    for value in (
        getattr(product, "product_name_cn", ""),
        getattr(product, "product_name_en", ""),
    ):
        attributes = _explicit_variant_attributes(str(value or ""))
        for key in combined:
            combined[key].update(attributes[key])
    return combined


def _candidate_satisfies_explicit_variant_attributes(entity: str, product: Product) -> bool:
    explicit = _explicit_variant_attributes(entity)
    if any(len(values) > 1 for values in explicit.values()):
        return False
    candidate = _product_variant_attributes(product)
    for key, expected in explicit.items():
        if expected and candidate[key] != expected:
            return False
    return True


def _can_promote_diagnostic_variant_ambiguity(entity: str, candidates: list[Product]) -> bool:
    explicit = _explicit_variant_attributes(entity)
    if not any(explicit.values()) or len(candidates) < 2:
        return False
    if not all(_candidate_satisfies_explicit_variant_attributes(entity, product) for product in candidates):
        return False

    candidate_attributes = [_product_variant_attributes(product) for product in candidates]
    for key, expected in explicit.items():
        if expected:
            continue
        values = {tuple(sorted(attributes[key])) for attributes in candidate_attributes}
        if () not in values and len(values) >= 2:
            return True
    return False


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
    normalized = _CUP_COUNT_RE.sub("", normalized)
    for color_alias in sorted(_COLOR_ALIASES, key=len, reverse=True):
        normalized = normalized.replace(color_alias, "")
    normalized = re.sub(r"[\s\-_]+", "", normalized)
    normalized = re.sub(r"(?:水壶|保温杯|水杯|咖啡壶|壶|杯)$", "", normalized)
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
    entity_attributes = _explicit_variant_attributes(entity)
    candidate_attributes = _product_variant_attributes(product)
    has_complete_variant_identity = bool(any(entity_attributes.values())) and all(
        not candidate_values or entity_attributes[key] == candidate_values
        for key, candidate_values in candidate_attributes.items()
    )
    if (
        has_complete_variant_identity
        and _family_key(normalized_entity)
        and _family_key(normalized_entity) in {_family_key(name) for name in names if name}
    ):
        return "normalized_alias_exact"
    families = {alias for name in names for alias in _contract_family_aliases(name)}
    if _family_key(normalized_entity) and _family_key(normalized_entity) in families:
        return "family_alias"
    if any(normalized_entity in candidate or candidate in normalized_entity for candidate in canonical if candidate):
        return "substring"
    return "fuzzy"


def _skus(products: list[Product]) -> list[str]:
    return list(dict.fromkeys(str(getattr(product, "sku", "") or "").strip().upper() for product in products if str(getattr(product, "sku", "") or "").strip()))


def _clarification_candidate_skus(
    resolver_candidate_skus: list[str],
    diagnostic_candidate_skus: list[str],
) -> list[str]:
    if resolver_candidate_skus:
        return list(dict.fromkeys(resolver_candidate_skus))
    deduplicated_diagnostics = list(dict.fromkeys(diagnostic_candidate_skus))
    return deduplicated_diagnostics if len(deduplicated_diagnostics) >= 2 else []


def build_entity_resolution_contract(
    question: str,
    products: list[Product],
    *,
    resolver_candidates: list[Product] | None = None,
    entity_text_override: str | None = None,
    field_type_override: str | None = None,
    participant_local_identity: bool = False,
) -> EntityResolutionContract:
    field = detect_field_contract(question)
    entity_text = str(entity_text_override or "").strip() or _entity_text_from_question(question)
    normalized_entity = _normalized(entity_text)
    matched_span = None
    if entity_text:
        start = str(question or "").find(entity_text)
        if start >= 0:
            matched_span = (start, start + len(entity_text))
    field_type = str(field_type_override or "").strip() or (field.field_type if field else None)
    if normalized_entity in _GENERIC_CATEGORY_TERMS:
        return EntityResolutionContract(entity_text, normalized_entity, "generic", None, [], [], [], "none", "low", False, matched_span, field_type, "generic_or_missing_entity")
    sku_identity_owners: dict[str, list[Product]] = {}
    raw_sku_identity_owners: dict[str, list[Product]] = {}
    for product in products:
        raw_key = _raw_sku_identity_key(getattr(product, "sku", ""))
        if raw_key:
            raw_sku_identity_owners.setdefault(raw_key, []).append(product)
        for key in _explicit_sku_identity_keys(getattr(product, "sku", "")):
            sku_identity_owners.setdefault(key, []).append(product)
    # The field-subject extractor may intentionally replace an explicit SKU
    # with its resolved display name.  Preserve an unambiguous SKU stated in
    # the complete question as stronger identity provenance even for that
    # semantic override.  For a multi-SKU question, keep the participant-local
    # source only: importing every question-level SKU would collapse distinct
    # comparison participants into one product.
    question_sku_products: set[str] = set()
    for raw_sku in customer_agent_service._extract_skus(question):
        raw_owners = raw_sku_identity_owners.get(_raw_sku_identity_key(raw_sku)) or []
        owners = raw_owners if len(raw_owners) == 1 else [
            product
            for key in _explicit_sku_identity_keys(raw_sku)
            for product in sku_identity_owners.get(key) or []
        ]
        for product in owners:
            sku = str(getattr(product, "sku", "") or "").strip().upper()
            if sku:
                question_sku_products.add(sku)
    identity_sources = (
        (entity_text,)
        if participant_local_identity
        else (
            (entity_text, question)
            if not entity_text_override or len(question_sku_products) == 1
            else (entity_text,)
        )
    )
    extracted_sku_tokens = [
        str(sku or "").strip().upper().replace("_", "-")
        for raw in identity_sources
        for sku in customer_agent_service._extract_skus(raw)
        if str(sku or "").strip()
    ]
    # External systems may prepend a routing/source segment to a real SKU
    # (for example ``SOURCE-CW-C83``).  Treat it as identity only when a
    # complete hyphen-delimited suffix exactly names one catalogue SKU; this
    # is catalogue-validated normalization, never fuzzy prefix stripping.
    explicit_sku_candidates: list[str] = []
    for token in extracted_sku_tokens:
        explicit_sku_candidates.append(token)
        parts = token.split("-")
        for index in range(1, len(parts) - 1):
            suffix = "-".join(parts[index:])
            if suffix:
                explicit_sku_candidates.append(suffix)
    raw_explicit_products_by_sku: dict[str, Product] = {}
    for token in explicit_sku_candidates:
        raw_owners = raw_sku_identity_owners.get(_raw_sku_identity_key(token)) or []
        if len(raw_owners) == 1:
            product = raw_owners[0]
            sku = str(getattr(product, "sku", "") or "").strip().upper()
            if sku:
                raw_explicit_products_by_sku[sku] = product

    explicit_products_by_sku: dict[str, Product] = {}
    if len(raw_explicit_products_by_sku) == 1:
        explicit_products_by_sku.update(raw_explicit_products_by_sku)

    normalized_token_keys = {
        key
        for token in explicit_sku_candidates
        for key in _explicit_sku_identity_keys(token)
    }
    if not explicit_products_by_sku:
        for key in normalized_token_keys:
            owners = sku_identity_owners.get(key) or []
            if len(owners) == 1:
                product = owners[0]
                sku = str(getattr(product, "sku", "") or "").strip().upper()
                if sku:
                    explicit_products_by_sku[sku] = product
    if len(explicit_products_by_sku) == 1:
        resolved_sku, product = next(iter(explicit_products_by_sku.items()))
        raw_sku_key = _normalized(str(getattr(product, "sku", "") or "")).upper()
        matched_by = "sku_exact" if raw_sku_key in normalized_token_keys else "normalized_sku_exact"
        return EntityResolutionContract(entity_text, normalized_entity, "resolved", resolved_sku, [resolved_sku], [], [resolved_sku], matched_by, "high", True, matched_span, field_type, "resolver_sku_exact")
    formal_candidates = resolver_candidates if resolver_candidates is not None else customer_agent_service.resolve_named_product_candidates(question, products, subject=entity_text or question)
    # Catalog recall may return typo-near products, but fuzzy-only recall is
    # diagnostic search output, not resolver evidence.  Do not turn it into
    # either a resolved identity or a displayable ambiguity contract.
    if (
        resolver_candidates is None
        and formal_candidates
        and all(_matched_by(entity_text, product) == "fuzzy" for product in formal_candidates)
    ):
        formal_candidates = []
    explicit_variant_attributes = _explicit_variant_attributes(entity_text)
    has_explicit_variant_attributes = any(explicit_variant_attributes.values())
    if has_explicit_variant_attributes:
        formal_candidates = [
            product
            for product in formal_candidates
            if _candidate_satisfies_explicit_variant_attributes(entity_text, product)
        ]
    diagnostic_candidates: list[Product] = []
    promoted_ambiguity_candidates: list[Product] = []
    entity_family = _family_key(normalized_entity)
    default_family_recall_only = (
        resolver_candidates is None
        and bool(formal_candidates)
        and bool(entity_family)
        and not any(
            _matched_by(entity_text, product) in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS
            for product in formal_candidates
        )
        and all(
            entity_family in {
                _family_key(str(getattr(product, "product_name_cn", "") or "")),
                _family_key(str(getattr(product, "product_name_en", "") or "")),
            }
            for product in formal_candidates
        )
    )
    if default_family_recall_only:
        diagnostic_candidates = formal_candidates
        formal_candidates = []
    if not formal_candidates:
        if len(entity_family) >= 2 and not diagnostic_candidates:
            diagnostic_candidates = [
                product
                for product in products
                if entity_family in {
                    _family_key(str(getattr(product, "product_name_cn", "") or "")),
                    _family_key(str(getattr(product, "product_name_en", "") or "")),
                }
            ]
        if diagnostic_candidates and has_explicit_variant_attributes:
            filtered_diagnostic_candidates = [
                product
                for product in diagnostic_candidates
                if _candidate_satisfies_explicit_variant_attributes(entity_text, product)
            ]
            if not filtered_diagnostic_candidates:
                return EntityResolutionContract(
                    entity_text, normalized_entity, "unresolved", None, [], [], [], "none", "low",
                    False, matched_span, field_type, "explicit_attribute_conflict",
                )
            exact_diagnostic_candidates = [
                product
                for product in filtered_diagnostic_candidates
                if _matched_by(entity_text, product) in _STRONG_SINGLE_PRODUCT_MATCH_LEVELS
            ]
            if len(exact_diagnostic_candidates) == 1:
                formal_candidates = exact_diagnostic_candidates
            elif _can_promote_diagnostic_variant_ambiguity(entity_text, filtered_diagnostic_candidates):
                promoted_ambiguity_candidates = filtered_diagnostic_candidates
    if not formal_candidates and not diagnostic_candidates and has_explicit_variant_attributes:
        return EntityResolutionContract(
            entity_text,
            normalized_entity,
            "unresolved",
            None,
            [],
            [],
            [],
            "none",
            "low",
            False,
            matched_span,
            field_type,
            "explicit_attribute_conflict",
        )
    if promoted_ambiguity_candidates:
        resolver_candidate_skus = _skus(promoted_ambiguity_candidates)
        return EntityResolutionContract(
            entity_text, normalized_entity, "ambiguous", None, resolver_candidate_skus,
            _skus(diagnostic_candidates), resolver_candidate_skus, "none", "medium", False,
            matched_span, field_type, "explicit_variant_attribute_missing",
        )
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
    # When the default named-product resolver deliberately returns a family of
    # candidates, one candidate's display alias must not erase another
    # candidate that differs only by an omitted variant (for example color).
    # Caller-supplied recall pools may still be narrowed by a canonical exact
    # identity; the default resolver's ambiguity is authoritative.
    exact_match_level = (
        _matched_by(entity_text, exact_candidates[0])
        if len(exact_candidates) == 1
        else "none"
    )
    unique_alias_product = (
        _catalog_unique_exact_alias_product(entity_text, products)
        if exact_match_level == "normalized_alias_exact"
        else None
    )
    unique_alias_sku = (
        str(getattr(unique_alias_product, "sku", "") or "").strip().upper()
        if unique_alias_product is not None
        else ""
    )
    if len(exact_candidates) == 1 and (
        exact_match_level == "canonical_name_exact"
        or unique_alias_sku == str(getattr(exact_candidates[0], "sku", "") or "").strip().upper()
        or resolver_candidates is not None
        or len(formal_candidates) == 1
    ):
        formal_candidates = exact_candidates
        resolver_candidate_skus = _skus(formal_candidates)
    if not resolver_candidate_skus and not diagnostic_candidates:
        diagnostic_candidates = [
            product
            for product in products
            if _family_key(normalized_entity) in _contract_family_aliases(str(getattr(product, "product_name_cn", "") or ""))
            or _family_key(normalized_entity) in _contract_family_aliases(str(getattr(product, "product_name_en", "") or ""))
        ]
    diagnostic_candidate_skus = _skus(diagnostic_candidates)
    candidate_skus = _clarification_candidate_skus(
        resolver_candidate_skus,
        diagnostic_candidate_skus,
    )
    if not resolver_candidate_skus and not diagnostic_candidate_skus:
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
