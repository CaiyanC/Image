import pytest

from app.models.product import Product
from app.services.customer_entity_resolution_contract import (
    BoundProductIdentityDecision,
    EntityResolutionContract,
    build_entity_resolution_contract,
    can_trust_bound_product_identity,
    can_resolve_single_product,
    choose_effective_entity_contract,
    identity_provenance_from_entity_contract,
)
from app.services.customer_field_contract import (
    normalize_field_adjacent_entity_scope,
    select_entity_subject_for_routing,
)


def _product(sku: str, *, category: str = "锅具") -> Product:
    return Product(
        id=f"id-{sku}",
        sku=sku,
        barcode=f"barcode-{sku}",
        product_name_cn=f"商品{sku}",
        brand="测试品牌",
        category=category,
    )


def _contract(
    *,
    status: str = "resolved",
    resolved_sku: str | None = "SKU-1",
    candidates: list[str] | None = None,
    matched_by: str = "canonical_name_exact",
    confidence: str = "high",
    reason: str = "resolver_unique_exact",
) -> EntityResolutionContract:
    candidate_skus = candidates if candidates is not None else ["SKU-1"]
    return EntityResolutionContract(
        entity_text="测试商品",
        normalized_entity_text="测试商品",
        status=status,
        resolved_sku=resolved_sku,
        resolver_candidate_skus=candidate_skus,
        diagnostic_candidate_skus=[],
        candidate_skus=candidate_skus,
        matched_by=matched_by,
        confidence=confidence,
        is_unique=status == "resolved",
        matched_span=(0, 4),
        field_type="price",
        status_reason=reason,
    )


def test_single_product_resolution_allows_only_center_approved_exact_levels():
    product = _product("SKU-1")
    for match_level in ("sku_exact", "canonical_name_exact", "normalized_alias_exact"):
        decision = can_resolve_single_product(_contract(matched_by=match_level), [product])
        assert decision.allowed is True
        assert decision.resolved_sku == "SKU-1"
        assert decision.resolved_product_id == "id-SKU-1"
        assert decision.reason == "resolved_exact"
        assert decision.match_level == match_level


def test_single_product_resolution_denies_unique_weak_matches():
    product = _product("SKU-1")
    for match_level in ("substring", "fuzzy", "family_alias"):
        decision = can_resolve_single_product(
            _contract(
                status="ambiguous",
                resolved_sku=None,
                matched_by=match_level,
                confidence="medium",
                reason="resolver_weak_single_candidate",
            ),
            [product],
        )
        assert decision.allowed is False
        assert decision.resolved_sku is None
        assert decision.reason in {"weak_single_candidate", "family_or_variant_ambiguous"}


def test_single_product_resolution_denies_multiple_or_missing_candidates():
    multiple = can_resolve_single_product(
        _contract(
            status="ambiguous",
            resolved_sku=None,
            candidates=["SKU-1", "SKU-2"],
            matched_by="none",
            confidence="medium",
            reason="resolver_multiple_candidates",
        ),
        [_product("SKU-1"), _product("SKU-2")],
    )
    missing = can_resolve_single_product(_contract(), [_product("OTHER")])
    assert multiple.reason == "multiple_candidates"
    assert missing.reason == "resolved_candidate_missing"


def test_single_product_resolution_denies_scope_and_subject_conflicts():
    contract = _contract()
    product = _product("SKU-1")
    subject = can_resolve_single_product(contract, [product], subject_compatible=False)
    family = can_resolve_single_product(contract, [product], family_or_variant_ambiguous=True)
    component = can_resolve_single_product(contract, [product], component_scope_unresolved=True)
    assert subject.reason == "subject_type_mismatch"
    assert family.reason == "family_or_variant_ambiguous"
    assert component.reason == "component_scope_unresolved"


def test_entity_contract_preserves_exact_subject_override_for_unknown_field_tail():
    product = _product("SKU-1")
    product.product_name_cn = "瓦片烤盘"

    contract = build_entity_resolution_contract(
        "瓦片烤盘 保修多久？",
        [product],
        resolver_candidates=[product],
        entity_text_override="瓦片烤盘",
    )

    assert contract.status == "resolved"
    assert contract.matched_by == "canonical_name_exact"
    assert contract.resolved_sku == "SKU-1"


def test_field_contract_subject_selection_is_stable_across_unknown_fields():
    expected = {
        "瓦片烤盘 有赠品吗？": "gift",
        "瓦片烤盘 保修多久？": "warranty",
        "瓦片烤盘 今天能发吗？": "shipping",
    }
    for question, field in expected.items():
        selection = select_entity_subject_for_routing(
            raw_question=question,
            fallback_product_like_subject="错误后备主体",
        )
        assert selection.entity_subject == "瓦片烤盘"
        assert selection.source == "field_contract"
        assert selection.field == field
        assert selection.fallback_used is False


@pytest.mark.parametrize(
    ("question", "field", "phrase", "subject"),
    [
        ("瓦片烤盘是什么材质？", "material", "是什么材质", "瓦片烤盘"),
        ("瓦片烤盘能不能明火用？", "heat_source", "能不能明火用", "瓦片烤盘"),
        ("天鹅壶9杯白能明火烧吗？", "heat_source", "能明火烧吗", "天鹅壶9杯白"),
        ("天鹅壶4杯白适合几个人？", "people", "适合几个人", "天鹅壶4杯白"),
        ("瓦片烤盘质保多长时间？", "warranty", "质保多长时间", "瓦片烤盘"),
        ("瓦片烤盘有没有保修？", "warranty", "有没有保修", "瓦片烤盘"),
        ("瓦片烤盘今天能发货吗？", "shipping", "今天能发货吗", "瓦片烤盘"),
        ("瓦片烤盘现在下单什么时候发？", "shipping", "现在下单什么时候发", "瓦片烤盘"),
        ("瓦片烤盘多久可以寄出？", "shipping", "多久可以寄出", "瓦片烤盘"),
    ],
)
def test_natural_field_phrase_selection_removes_the_complete_phrase(
    question,
    field,
    phrase,
    subject,
):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == field
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.core_field_span is not None
    assert selection.entity_subject == subject
    assert selection.raw_subject == subject


@pytest.mark.parametrize("scope_term", ["主体", "本体", "本身"])
def test_scope_and_full_field_phrase_compose_before_entity_resolution(scope_term):
    selection = select_entity_subject_for_routing(
        raw_question=f"瓦片烤盘{scope_term}是什么材质？",
    )

    assert selection.field == "material"
    assert selection.full_field_phrase == "是什么材质"
    assert selection.raw_subject == f"瓦片烤盘{scope_term}"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.requested_scope == "subject"
    assert selection.normalization_reason == "field_adjacent_subject_scope"


def test_component_term_is_not_treated_as_whole_product_scope():
    selection = select_entity_subject_for_routing(
        raw_question="炊墨炒锅锅体是什么材质？",
    )

    assert selection.entity_subject == "炊墨炒锅锅体"
    assert selection.removed_scope_span is None


def test_field_adjacent_subject_scope_flows_into_canonical_entity_subject():
    selection = select_entity_subject_for_routing(
        raw_question="天鹅壶9杯白本身多重？",
        fallback_named_subject="天鹅壶9杯白本身",
    )
    assert selection.raw_subject == "天鹅壶9杯白本身"
    assert selection.entity_subject == "天鹅壶9杯白"
    assert selection.requested_scope == "subject"
    assert selection.normalization_reason == "field_adjacent_subject_scope"
    assert selection.fallback_used is False


def test_field_contract_empty_subject_never_falls_back_to_a_named_candidate():
    selection = select_entity_subject_for_routing(
        raw_question="保修多久？",
        fallback_product_like_subject="某个候选商品",
    )
    assert selection.entity_subject == ""
    assert selection.source == "field_contract"
    assert selection.fallback_used is False
    assert selection.reason == "field_contract_empty_subject"


def test_canonical_exact_match_narrows_a_broad_variant_candidate_pool():
    base = _product("CF-PG19")
    base.product_name_cn = "瓦片烤盘"
    pro = _product("CF-PG19PRO")
    pro.product_name_cn = "瓦片烤盘Pro"

    base_contract = build_entity_resolution_contract(
        "瓦片烤盘 保修多久？",
        [base, pro],
        resolver_candidates=[base, pro],
    )
    pro_contract = build_entity_resolution_contract(
        "瓦片烤盘Pro 保修多久？",
        [base, pro],
        resolver_candidates=[base, pro],
    )

    assert base_contract.status == "resolved"
    assert base_contract.matched_by == "canonical_name_exact"
    assert base_contract.resolved_sku == "CF-PG19"
    assert base_contract.resolver_candidate_skus == ["CF-PG19"]
    assert pro_contract.status == "resolved"
    assert pro_contract.resolved_sku == "CF-PG19PRO"


def test_field_subject_selection_does_not_promote_weak_or_generic_entities():
    weak_product = _product("CW-C47-1")
    weak_product.product_name_cn = "荒野套锅"
    weak = build_entity_resolution_contract(
        "荒野星壶水壶价格",
        [weak_product],
        resolver_candidates=[weak_product],
    )
    generic = select_entity_subject_for_routing(raw_question="烤盘一般保修多久？")

    assert weak.status == "ambiguous"
    assert weak.matched_by in {"fuzzy", "substring"}
    assert weak.resolved_sku is None
    assert generic.entity_subject == "烤盘一般"


def test_effective_contract_keeps_strong_default_over_weaker_override():
    products = [_product("SKU-1")]
    default = _contract()
    for override in (
        _contract(status="unresolved", resolved_sku=None, candidates=[], matched_by="none", confidence="low", reason="no_candidates"),
        _contract(status="ambiguous", resolved_sku=None, matched_by="substring", confidence="medium", reason="resolver_weak_single_candidate"),
    ):
        selection = choose_effective_entity_contract(default, override, products)
        assert selection.contract is default
        assert selection.source == "default"
        assert selection.reason == "default_strong_exact"
        assert selection.override_conflict is False


def test_effective_contract_uses_only_a_strong_override_when_default_is_unresolved():
    products = [_product("SKU-1")]
    default = _contract(status="unresolved", resolved_sku=None, candidates=[], matched_by="none", confidence="low", reason="no_candidates")
    exact_override = _contract()
    weak_override = _contract(status="ambiguous", resolved_sku=None, matched_by="substring", confidence="medium", reason="resolver_weak_single_candidate")

    exact_selection = choose_effective_entity_contract(default, exact_override, products)
    weak_selection = choose_effective_entity_contract(default, weak_override, products)

    assert exact_selection.contract is exact_override
    assert exact_selection.source == "override"
    assert exact_selection.reason == "override_strong_exact"
    assert weak_selection.contract is default
    assert weak_selection.reason == "override_not_strong"


def test_effective_contract_records_conflicting_strong_override_without_replacing_default():
    products = [_product("SKU-1"), _product("SKU-2")]
    default = _contract()
    override = _contract(resolved_sku="SKU-2", candidates=["SKU-2"])

    selection = choose_effective_entity_contract(default, override, products)

    assert selection.contract is default
    assert selection.source == "default"
    assert selection.reason == "strong_override_conflict"
    assert selection.override_conflict is True


def test_bound_product_identity_trusts_explicit_and_context_provenance():
    product = _product("SKU-1")
    for source in (
        "explicit_sku_exact",
        "normalized_sku_exact",
        "named_product_canonical_exact",
        "named_product_alias_exact",
        "recommendation_context_anchor",
        "recommendation_context_ordinal",
        "recommendation_context_pronoun",
        "phase2_resolved_entity",
    ):
        decision = can_trust_bound_product_identity(product=product, sku="SKU-1", identity_source=source)
        assert isinstance(decision, BoundProductIdentityDecision)
        assert decision.allowed is True
        assert decision.sku == "SKU-1"
        assert decision.source == source


def test_bound_product_identity_trusts_matching_exact_contract_only():
    product = _product("SKU-1")
    allowed = can_trust_bound_product_identity(product=product, sku="SKU-1", entity_contract=_contract())
    mismatch = can_trust_bound_product_identity(product=product, sku="OTHER", entity_contract=_contract())

    assert allowed.allowed is True
    assert allowed.source == "entity_contract_resolved_exact"
    assert mismatch.allowed is False
    assert mismatch.reason == "entity_contract_sku_mismatch"


def test_bound_product_identity_rejects_untrusted_or_missing_provenance():
    product = _product("SKU-1")
    for source in (None, "planner_candidate", "planner_single_candidate", "substring", "fuzzy", "family_alias"):
        decision = can_trust_bound_product_identity(product=product, sku="SKU-1", identity_source=source)
        assert decision.allowed is False
        assert decision.sku is None
        assert decision.reason in {"missing_identity_provenance", "weak_identity_source"}


def test_bound_product_identity_reason_precedence_is_stable():
    matching_product = _product("SKU-2")
    other_product = _product("SKU-3")
    contract_for_sku_1 = _contract(resolved_sku="SKU-1", candidates=["SKU-1"])
    contract_for_sku_2 = _contract(resolved_sku="SKU-2", candidates=["SKU-2"])

    assert can_trust_bound_product_identity(
        product=matching_product,
        sku="SKU-2",
        entity_contract=contract_for_sku_1,
    ).reason == "entity_contract_sku_mismatch"
    assert can_trust_bound_product_identity(
        product=other_product,
        sku="SKU-2",
        entity_contract=contract_for_sku_2,
    ).reason == "bound_product_sku_mismatch"
    assert can_trust_bound_product_identity(
        product=other_product,
        sku="SKU-2",
        entity_contract=contract_for_sku_1,
    ).reason == "entity_contract_sku_mismatch"
    assert can_trust_bound_product_identity(
        product=other_product,
        sku="SKU-2",
    ).reason == "missing_identity_provenance"
    assert can_trust_bound_product_identity(
        product=other_product,
        sku="SKU-2",
        identity_source="planner_candidate",
    ).reason == "weak_identity_source"
    assert can_trust_bound_product_identity(
        product=matching_product,
        sku="SKU-2",
        identity_source="explicit_sku_exact",
    ).allowed is True


def test_identity_provenance_is_created_only_from_matching_strong_contract():
    canonical = identity_provenance_from_entity_contract(
        _contract(matched_by="canonical_name_exact"),
        bound_sku="SKU-1",
        origin_stage="named_product_resolver",
    )
    alias = identity_provenance_from_entity_contract(
        _contract(matched_by="normalized_alias_exact"),
        bound_sku="SKU-1",
        origin_stage="named_product_resolver",
    )
    weak = identity_provenance_from_entity_contract(
        _contract(status="ambiguous", resolved_sku=None, matched_by="substring", confidence="medium"),
        bound_sku="SKU-1",
        origin_stage="named_product_resolver",
    )

    assert canonical.source == "named_product_canonical_exact"
    assert canonical.resolved_sku == "SKU-1"
    assert canonical.origin_stage == "named_product_resolver"
    assert alias.source == "named_product_alias_exact"
    assert weak is None


def test_field_adjacent_scope_normalization_separates_entity_and_scope():
    cases = (
        ("晨雾Plus水壶本身多重", "晨雾Plus水壶本身", "weight", "晨雾Plus水壶", "subject"),
        ("晨雾Plus水壶自身重量", "晨雾Plus水壶自身", "weight", "晨雾Plus水壶", "subject"),
        ("星海收纳包的主体尺寸", "星海收纳包的主体", "dimensions", "星海收纳包", "subject"),
        ("星海收纳包的包装尺寸", "星海收纳包的包装", "dimensions", "星海收纳包", "package"),
    )
    for question, raw_subject, field_type, expected_entity, expected_scope in cases:
        result = normalize_field_adjacent_entity_scope(
            question=question,
            raw_subject=raw_subject,
            canonical_field=field_type,
        )
        assert result.entity_subject == expected_entity
        assert result.requested_scope == expected_scope
        assert result.removed_scope_span is not None


def test_field_adjacent_scope_normalization_does_not_trim_nonstandard_or_nonadjacent_terms():
    nonstandard = normalize_field_adjacent_entity_scope(
        question="炊墨炒锅的锅体用的是什么材质",
        raw_subject="炊墨炒锅的锅体用的",
        canonical_field="material",
    )
    product_name_term = normalize_field_adjacent_entity_scope(
        question="主体收纳包尺寸",
        raw_subject="主体收纳包",
        canonical_field="dimensions",
    )
    assert nonstandard.entity_subject == "炊墨炒锅的锅体用的"
    assert product_name_term.entity_subject == "主体收纳包"
