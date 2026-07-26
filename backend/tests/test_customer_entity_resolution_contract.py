import pytest

from app.models.product import Product
from app.services import customer_field_contract
from app.services.customer_entity_resolution_contract import (
    BoundProductIdentityDecision,
    EntityResolutionContract,
    build_entity_resolution_contract,
    can_trust_bound_product_identity,
    can_resolve_single_product,
    choose_effective_entity_contract,
    identity_provenance_from_entity_contract,
    recover_explicit_versioned_subject,
    unique_canonical_subject_in_question,
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


def test_unique_canonical_subject_prefers_longest_variant_and_fails_closed_on_duplicates():
    base = _product("SUBJECT-BASE")
    base.product_name_cn = "远行炉"
    variant = _product("SUBJECT-PRO")
    variant.product_name_cn = "远行炉Pro-组合版"
    duplicate = _product("SUBJECT-DUP")
    duplicate.product_name_cn = "远行炉Pro-组合版"

    question = "远行炉Pro-组合版收到货拆开会配些什么"
    assert unique_canonical_subject_in_question(question, [base, variant]) == "远行炉Pro-组合版"
    assert unique_canonical_subject_in_question(question, [base, variant, duplicate]) == ""
    assert unique_canonical_subject_in_question("另一款商品收到货拆开会配些什么", [base, variant]) == ""


def test_canonical_base_name_remains_exact_beside_longer_variant():
    base = _product("SUBJECT-BASE")
    base.product_name_cn = "远行杯"
    variant = _product("SUBJECT-PRO")
    variant.product_name_cn = "远行杯Pro"

    assert unique_canonical_subject_in_question(
        "远行杯原装开箱会附带哪些东西？",
        [base, variant],
    ) == "远行杯"


def test_unique_catalog_display_alias_recovers_semantic_field_subject_but_shared_alias_fails_closed():
    boxed = _product("SUBJECT-BOXED")
    boxed.product_name_cn = "云岭水壶（经典款）"
    unrelated = _product("SUBJECT-OTHER")
    unrelated.product_name_cn = "远山水壶"

    assert unique_canonical_subject_in_question(
        "云岭水壶收到以后盒内都能看到什么",
        [boxed, unrelated],
    ) == "云岭水壶"

    sibling = _product("SUBJECT-SIBLING")
    sibling.product_name_cn = "云岭水壶（轻量款）"
    assert unique_canonical_subject_in_question(
        "云岭水壶收到以后盒内都能看到什么",
        [boxed, sibling, unrelated],
    ) == ""


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


def test_pairwise_entity_override_seals_its_own_explicit_sku_not_every_question_sku():
    """Each semantic comparison participant must keep an independent exact identity."""
    first = _product("CW-C74")
    second = _product("CW-C69-1")
    first.product_name_cn = "甲产品"
    second.product_name_cn = "乙产品"
    question = "CW-C74 and CW-C69-1: which is lighter?"

    first_contract = build_entity_resolution_contract(
        question,
        [first, second],
        entity_text_override="CW-C74",
        field_type_override="weight",
    )
    second_contract = build_entity_resolution_contract(
        question,
        [first, second],
        entity_text_override="CW-C69-1",
        field_type_override="weight",
    )

    assert first_contract.status == "resolved"
    assert first_contract.resolved_sku == "CW-C74"
    assert first_contract.matched_by == "sku_exact"
    assert second_contract.status == "resolved"
    assert second_contract.resolved_sku == "CW-C69-1"
    assert second_contract.matched_by == "sku_exact"


def test_catalog_unique_parenthesized_sku_serialization_is_a_strong_exact_identity():
    """A catalogue-unique external SKU serialization remains an exact identity."""
    product = _product("AA-12(X)")

    contract = build_entity_resolution_contract(
        "AA-12-X的材质是什么？",
        [product],
        field_type_override="material",
    )
    decision = can_resolve_single_product(contract, [product])
    provenance = identity_provenance_from_entity_contract(
        contract,
        bound_sku="AA-12(X)",
        origin_stage="field_contract",
    )

    assert contract.status == "resolved"
    assert contract.resolved_sku == "AA-12(X)"
    assert contract.matched_by == "normalized_sku_exact"
    assert decision.allowed is True
    assert provenance is not None
    assert provenance.source == "normalized_sku_exact"


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
        ("天鹅9杯能明火吗？", "heat_source", "能明火吗", "天鹅9杯"),
        ("天鹅壶4杯白适合几个人？", "people", "适合几个人", "天鹅壶4杯白"),
        ("瓦片烤盘质保多长时间？", "warranty", "质保多长时间", "瓦片烤盘"),
        ("瓦片烤盘有没有保修？", "warranty", "有没有保修", "瓦片烤盘"),
        ("瓦片烤盘今天能发货吗？", "shipping", "今天能发货吗", "瓦片烤盘"),
        ("瓦片烤盘现在下单什么时候发？", "shipping", "现在下单什么时候发", "瓦片烤盘"),
        ("瓦片烤盘多久可以寄出？", "shipping", "多久可以寄出", "瓦片烤盘"),
        ("天鹅壶4杯白本周能送到吗？", "shipping", "本周能送到", "天鹅壶4杯白"),
        ("天鹅壶4杯白自身有多重？", "weight", "自身有多重", "天鹅壶4杯白"),
        ("瓦片烤盘怎么查看产品手册？", "manual", "怎么查看产品手册", "瓦片烤盘"),
        ("瓦片烤盘的客服联系方式是什么？", "after_sales_contact", "客服联系方式是什么", "瓦片烤盘"),
        ("天鹅壶9杯黑当前售价是多少？", "price", "当前售价是多少", "天鹅壶9杯黑"),
        ("瓦片烤盘Pro当前还有库存吗？", "inventory", "当前还有库存吗", "瓦片烤盘Pro"),
        ("天鹅壶9杯黑有没有用户手册？", "manual", "有没有用户手册", "天鹅壶9杯黑"),
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


@pytest.mark.parametrize(
    "phrase",
    [
        "是用什么做的",
        "由什么做成",
        "是什么做的",
        "用什么制成",
        "由什么制成",
        "用哪种材料制作",
        "拿什么材料做的",
    ],
)
def test_material_predicate_grammar_extracts_complete_phrase_and_subject(phrase):
    question = f"瓦片烤盘{phrase}？"
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "material"
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.raw_subject == "瓦片烤盘"


@pytest.mark.parametrize(
    "question",
    [
        "瓦片烤盘怎么使用？",
        "瓦片烤盘用起来怎么样？",
        "瓦片烤盘做饭怎么样？",
        "瓦片烤盘有什么卖点？",
        "瓦片烤盘有什么特点？",
        "这个东西是怎么做出来的？",
    ],
)
def test_material_predicate_grammar_rejects_non_material_actions(question):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field != "material"


@pytest.mark.parametrize(
    "phrase",
    [
        "支持哪些炉子",
        "支持什么炉子",
        "支持哪种炉具",
        "可以用哪些炉子",
        "能用什么炉具",
        "支持哪些热源",
        "适配什么炉子",
    ],
)
def test_heat_source_predicate_grammar_extracts_product_subject(phrase):
    question = f"远山锅{phrase}？"
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "heat_source"
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.entity_subject == "远山锅"
    assert selection.requested_scope == "subject"
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "可以放电磁炉上吗",
        "能放电磁炉上吗",
        "可以在电磁炉上用吗",
        "能用卡式炉吗",
        "可以直接明火烧吗",
    ],
)
def test_heat_source_yes_no_predicate_consumes_complete_phrase(phrase):
    question = f"远山锅{phrase}？"
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "heat_source"
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.raw_subject == "远山锅"
    assert selection.entity_subject == "远山锅"
    assert selection.requested_scope == "subject"
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


@pytest.mark.parametrize(
    "question",
    [
        "有哪些适合卡式炉的烤盘？",
        "推荐几款能用电磁炉的烤盘",
        "烤盘和炉子怎么搭配？",
        "哪些烤盘支持卡式炉？",
        "哪些烤盘可以放电磁炉上？",
        "有哪些锅能用卡式炉？",
        "推荐几款可以明火烧的烤盘",
    ],
)
def test_heat_source_category_queries_do_not_create_product_detail_predicate(question):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert customer_field_contract.is_field_contract_predicate_signal(selection) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "下单后几天发出",
        "下单后多久发货",
        "什么时候发货",
        "几天内能发出",
        "什么时候寄出",
    ],
)
def test_shipping_predicate_consumes_complete_phrase(phrase):
    question = f"瓦片烤盘{phrase}？"
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "shipping"
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.raw_subject == "瓦片烤盘"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.requested_scope == "subject"
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "多大尺寸",
        "尺寸多大",
        "是什么尺寸",
        "具体尺寸是多少",
        "长宽高是多少",
        "本身有多大",
    ],
)
def test_dimensions_predicate_consumes_complete_phrase(phrase):
    question = f"瓦片烤盘{phrase}？"
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "dimensions"
    assert selection.full_field_phrase == phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == phrase
    assert selection.raw_subject == "瓦片烤盘"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.requested_scope == "subject"
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


def test_packaging_dimensions_keep_package_scope_separate_from_body_dimensions():
    selection = select_entity_subject_for_routing(raw_question="瓦片烤盘的包装尺寸是多少？")

    assert selection.field == "dimensions"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.requested_scope == "package"


@pytest.mark.parametrize(
    ("question", "expected_phrase", "expected_subject", "expected_scope"),
    [
        ("暮色单人椅的收纳尺寸有多大", "收纳尺寸有多大", "暮色单人椅", "subject"),
        ("某商品包装尺寸有多大？", "包装尺寸有多大", "某商品", "package"),
        ("某商品展开尺寸是多少？", "展开尺寸是多少", "某商品", "subject"),
        ("某商品有多大？", "有多大", "某商品", "subject"),
    ],
)
def test_dimensions_same_field_arbitration_prefers_specific_complete_span(
    question,
    expected_phrase,
    expected_subject,
    expected_scope,
):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "dimensions"
    assert selection.full_field_phrase == expected_phrase
    assert selection.full_field_phrase_span is not None
    assert question[slice(*selection.full_field_phrase_span)] == expected_phrase
    assert selection.raw_subject == expected_subject
    assert selection.entity_subject == expected_subject
    assert selection.requested_scope == expected_scope


def test_dimension_evidence_keeps_storage_expanded_and_body_subtypes_separate():
    raw_value = (
        '[{"label":"尺寸","value":"50 x 40 x 70"},'
        '{"label":"收纳尺寸","value":"50 x 15 x 12"},'
        '{"label":"展开尺寸","value":"50 x 40 x 72"},'
        '{"label":"包装尺寸","value":"55 x 20 x 15"}]'
    )

    storage = customer_field_contract.select_dimension_evidence(
        raw_value,
        requested_scope="subject",
        requested_subtype="storage",
    )
    expanded = customer_field_contract.select_dimension_evidence(
        raw_value,
        requested_scope="subject",
        requested_subtype="expanded",
    )
    body = customer_field_contract.select_dimension_evidence(raw_value, requested_scope="subject")

    assert storage is not None and storage.value == "50 x 15 x 12"
    assert storage.label == "收纳尺寸"
    assert storage.unit == ""
    assert storage.subtype == "storage"
    assert expanded is not None and expanded.value == "50 x 40 x 72"
    assert expanded.label == "展开尺寸"
    assert expanded.subtype == "expanded"
    assert body is not None and body.value == "50 x 40 x 70"
    assert body.label == "尺寸"
    assert body.subtype == "product"


def test_generic_dimension_evidence_falls_back_to_expanded_with_full_provenance():
    evidence = customer_field_contract.select_dimension_evidence(
        '[{"label":"展开尺寸","value":"32*32*3.9","unit":"cm"}]',
        requested_scope="subject",
    )

    assert evidence is not None
    assert evidence.label == "展开尺寸"
    assert evidence.value == "32*32*3.9"
    assert evidence.unit == "cm"
    assert evidence.subtype == "expanded"
    assert evidence.is_generic_fallback is True


@pytest.mark.parametrize(
    ("request_type", "evidence_type", "overlap", "expected"),
    [
        ("material", "material", False, True),
        ("material", "selling_point", True, False),
        ("material", "usage_care", True, False),
        ("shipping", "selling_point", True, False),
        ("warranty", "usage_scene", True, False),
        ("people", "usage_scene", True, False),
        ("selling_point", "selling_point", False, True),
        ("usage_care", "usage_care", False, True),
        ("unknown", "selling_point", False, False),
    ],
)
def test_qa_evidence_compatibility_matrix(request_type, evidence_type, overlap, expected):
    assert customer_field_contract.is_qa_evidence_compatible(
        request_type,
        evidence_type,
        has_semantic_overlap=overlap,
    ) is expected


def test_qa_evidence_compatibility_classifies_request_and_qa_semantics():
    assert customer_field_contract.classify_product_qa_request_type("瓦片烤盘是用什么做的？") == "material"
    assert customer_field_contract.classify_product_qa_request_type("瓦片烤盘有什么特点？") == "selling_point"
    assert customer_field_contract.classify_product_qa_request_type("瓦片烤盘怎么使用？") == "usage_care"
    assert customer_field_contract.classify_product_qa_evidence_type("瓦片烤盘有什么核心卖点？", "") == "selling_point"
    assert customer_field_contract.classify_product_qa_evidence_type("瓦片烤盘是什么材质？", "材质") == "material"


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
    # “主体” is an explicit material component; 本体/本身 only remove a
    # field-adjacent subject modifier.  Entity normalization stays identical.
    expected_reason = (
        "material_component_scope"
        if scope_term == "主体"
        else "field_adjacent_subject_scope"
    )
    assert selection.normalization_reason == expected_reason


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


@pytest.mark.parametrize(
    ("question", "fallback_subject", "expected_subject"),
    [
        ("天鹅壶9杯白今天适合露营吗？", "天鹅壶9杯白今天", "天鹅壶9杯白"),
        ("瓦片烤盘现在适合户外吗？", "瓦片烤盘现在", "瓦片烤盘"),
        ("晨雾水壶本周适合露营吗？", "晨雾水壶本周", "晨雾水壶"),
    ],
)
def test_fallback_subject_separates_trailing_temporal_modifier(
    question,
    fallback_subject,
    expected_subject,
):
    selection = select_entity_subject_for_routing(
        raw_question=question,
        fallback_product_like_subject=fallback_subject,
    )

    assert selection.entity_subject == expected_subject
    assert selection.normalization_reason == "trailing_temporal_modifier"
    assert selection.removed_scope_span is not None


def test_temporal_only_scenario_does_not_create_product_subject():
    selection = select_entity_subject_for_routing(
        raw_question="今天适合露营吗？",
        fallback_product_like_subject="今天",
    )

    assert selection.entity_subject == "今天"
    assert selection.normalization_reason is None


@pytest.mark.parametrize(
    "question",
    [
        "瓦片烤盘有没有说明书？",
        "瓦片烤盘有说明书吗？",
        "瓦片烤盘说明书在哪里？",
        "瓦片烤盘电子说明书在哪里？",
        "瓦片烤盘怎么查看说明书？",
        "瓦片烤盘有使用手册吗？",
    ],
)
def test_manual_predicate_builds_independent_subject_field_contract(question):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.field == "manual"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.requested_scope == "subject"
    assert selection.full_field_phrase
    assert selection.full_field_phrase_span is not None


def test_manual_field_is_distinct_from_usage_and_contents():
    manual = select_entity_subject_for_routing(raw_question="瓦片烤盘有没有说明书？")
    usage = select_entity_subject_for_routing(
        raw_question="瓦片烤盘怎么使用？",
        fallback_named_subject="瓦片烤盘",
    )
    contents = select_entity_subject_for_routing(
        raw_question="瓦片烤盘包装里有什么？",
        fallback_named_subject="瓦片烤盘",
    )

    assert manual.field == "manual"
    assert usage.field != "manual"
    assert contents.field != "manual"


@pytest.mark.parametrize(
    "question",
    [
        "瓦片烤盘售后电话是多少？",
        "瓦片烤盘售后联系电话是多少？",
        "瓦片烤盘客服电话是多少？",
        "瓦片烤盘怎么联系售后？",
    ],
)
def test_after_sales_contact_predicate_keeps_exact_product_subject(question):
    selection = select_entity_subject_for_routing(raw_question=question)
    assert selection.field == "after_sales_contact"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.full_field_phrase


def test_temporal_modifier_before_price_predicate_does_not_pollute_subject():
    selection = select_entity_subject_for_routing(raw_question="天鹅壶9杯白现在多少钱？")
    assert selection.field == "price"
    assert selection.entity_subject == "天鹅壶9杯白"
    assert selection.normalization_reason == "trailing_temporal_modifier"


@pytest.mark.parametrize(
    "question",
    ["瓦片烤盘当前有现货吗？", "瓦片烤盘库存还有多少？", "瓦片烤盘现在有现货吗？"],
)
def test_inventory_predicate_keeps_exact_product_subject(question):
    selection = select_entity_subject_for_routing(raw_question=question)
    assert selection.field == "inventory"
    assert selection.entity_subject == "瓦片烤盘"
    assert selection.full_field_phrase


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


def test_unique_parenthesized_display_alias_resolves_but_shared_alias_clarifies():
    unique = _product("ALIAS-UNIQUE")
    unique.product_name_cn = "远行点火器（深色）"

    unique_contract = build_entity_resolution_contract(
        "远行点火器的型号是什么？",
        [unique],
        entity_text_override="远行点火器",
    )

    other = _product("ALIAS-OTHER")
    other.product_name_cn = "远行点火器（浅色）"
    ambiguous_contract = build_entity_resolution_contract(
        "远行点火器的型号是什么？",
        [unique, other],
        entity_text_override="远行点火器",
    )

    assert unique_contract.status == "resolved"
    assert unique_contract.resolved_sku == "ALIAS-UNIQUE"
    assert unique_contract.matched_by == "normalized_alias_exact"
    assert ambiguous_contract.status == "ambiguous"
    assert ambiguous_contract.resolved_sku is None
    assert set(ambiguous_contract.resolver_candidate_skus) == {"ALIAS-UNIQUE", "ALIAS-OTHER"}


def test_exact_display_alias_does_not_hide_an_omitted_variant_candidate():
    hyphen_variant = _product("VARIANT-DARK")
    hyphen_variant.product_name_cn = "远行壶4杯-深色"
    direct_variant = _product("VARIANT-LIGHT")
    direct_variant.product_name_cn = "远行壶4杯浅色"

    contract = build_entity_resolution_contract(
        "远行壶4杯有哪些颜色？",
        [hyphen_variant, direct_variant],
        entity_text_override="远行壶4杯",
    )

    assert contract.status == "ambiguous"
    assert contract.resolved_sku is None
    assert set(contract.resolver_candidate_skus) == {"VARIANT-DARK", "VARIANT-LIGHT"}


def test_unique_specific_display_alias_outranks_generic_substring_recall():
    specific = _product("SPECIFIC")
    specific.product_name_cn = "城市远行饭盒（含配件）-电光绿版本"
    generic = _product("GENERIC")
    generic.product_name_cn = "饭盒（深色盖子）"

    contract = build_entity_resolution_contract(
        "城市远行饭盒-电光绿版本下单后几天发出？",
        [specific, generic],
        entity_text_override="城市远行饭盒-电光绿版本",
    )

    assert contract.status == "resolved"
    assert contract.resolved_sku == "SPECIFIC"
    assert contract.resolver_candidate_skus == ["SPECIFIC"]
    assert contract.matched_by == "normalized_alias_exact"


def test_explicit_color_suffix_ignores_non_color_label_characters():
    orange = _product("COLOR-ORANGE")
    orange.product_name_cn = "（联名专属）示例杯-橙色"
    unlabeled_color = _product("COLOR-GENERIC")
    unlabeled_color.product_name_cn = "（金波专属）示例杯"

    contract = build_entity_resolution_contract(
        "示例杯-橙色有哪些颜色？",
        [orange, unlabeled_color],
        entity_text_override="示例杯-橙色",
    )

    assert contract.status == "resolved"
    assert contract.resolved_sku == "COLOR-ORANGE"
    assert contract.resolver_candidate_skus == ["COLOR-ORANGE"]


@pytest.mark.parametrize(
    ("entity_text", "expected_sku"),
    [
        ("天鹅壶4杯白", "KW-K31-白"),
        ("天鹅壶9杯白", "KW-K32-白"),
        ("天鹅壶4杯黑", "KW-K31-黑"),
        ("天鹅壶9杯黑", "KW-K32-黑"),
    ],
)
def test_explicit_cup_and_color_constraints_resolve_only_matching_variant(
    entity_text,
    expected_sku,
):
    products = []
    for sku, name in (
        ("KW-K31-白", "天鹅壶4杯-白色"),
        ("KW-K32-白", "天鹅壶9杯-白色"),
        ("KW-K31-黑", "天鹅壶4杯-黑色"),
        ("KW-K32-黑", "天鹅壶9杯-黑色"),
    ):
        product = _product(sku)
        product.product_name_cn = name
        products.append(product)

    contract = build_entity_resolution_contract(
        f"{entity_text}是什么材质？",
        products,
        resolver_candidates=products,
        entity_text_override=entity_text,
    )

    assert contract.status == "resolved"
    assert contract.resolved_sku == expected_sku
    assert contract.resolver_candidate_skus == [expected_sku]
    assert contract.matched_by == "normalized_alias_exact"
    assert contract.status_reason == "resolver_unique_exact"


def test_variant_constraints_keep_missing_or_nonexistent_cup_safe():
    four = _product("KW-K31-黑")
    four.product_name_cn = "天鹅壶4杯-黑色"
    nine = _product("KW-K32-黑")
    nine.product_name_cn = "天鹅壶9杯-黑色"

    missing_cup = build_entity_resolution_contract(
        "天鹅壶黑色是什么材质？",
        [four, nine],
        resolver_candidates=[four, nine],
        entity_text_override="天鹅壶黑色",
    )
    nonexistent_cup = build_entity_resolution_contract(
        "天鹅壶6杯黑是什么材质？",
        [four, nine],
        resolver_candidates=[four, nine],
        entity_text_override="天鹅壶6杯黑",
    )

    assert missing_cup.status == "ambiguous"
    assert missing_cup.resolver_candidate_skus == ["KW-K31-黑", "KW-K32-黑"]
    assert missing_cup.resolved_sku is None
    assert nonexistent_cup.status == "unresolved"
    assert nonexistent_cup.resolver_candidate_skus == []
    assert nonexistent_cup.resolved_sku is None
    assert nonexistent_cup.status_reason == "explicit_attribute_conflict"


def test_explicit_numeric_version_never_binds_a_different_catalog_version():
    """A shared family alias must not erase a version the customer actually named."""
    current = _product("CHAIR-1-1")
    current.product_name_cn = "1.1版本-行川包包椅"

    question = "1.0版本-行川包包椅怎么调长度？"
    assert unique_canonical_subject_in_question(question, [current]) == ""

    contract = build_entity_resolution_contract(
        question,
        [current],
        resolver_candidates=[current],
        entity_text_override="1.0版本-行川包包椅",
        field_type_override="product_qa",
    )

    assert contract.status != "resolved"
    assert contract.resolved_sku is None
    assert contract.resolver_candidate_skus == []
    assert contract.status_reason == "explicit_attribute_conflict"


def test_recover_explicit_versioned_subject_uses_only_the_current_turn_span():
    assert recover_explicit_versioned_subject(
        "1.0版本-行川包包椅怎么调长度？", "行川包包椅"
    ) == "1.0版本-行川包包椅"
    assert recover_explicit_versioned_subject("行川包包椅怎么调长度？", "行川包包椅") == ""


def test_variant_constraints_do_not_promote_a_weak_single_candidate():
    weak = _product("WEAK-4-BLACK")
    weak.product_name_cn = "旅行咖啡壶4杯-黑色"

    contract = build_entity_resolution_contract(
        "天鹅壶4杯黑是什么材质？",
        [weak],
        resolver_candidates=[weak],
        entity_text_override="天鹅壶4杯黑",
    )

    assert contract.status == "ambiguous"
    assert contract.resolved_sku is None
    assert contract.resolver_candidate_skus == ["WEAK-4-BLACK"]
    assert contract.status_reason == "resolver_weak_single_candidate"


def test_conflicting_explicit_variant_attributes_do_not_bind_a_product():
    white = _product("KW-K31-白")
    white.product_name_cn = "天鹅壶4杯-白色"
    black = _product("KW-K31-黑")
    black.product_name_cn = "天鹅壶4杯-黑色"

    contract = build_entity_resolution_contract(
        "天鹅壶4杯白但我要黑色是什么材质？",
        [white, black],
        resolver_candidates=[white, black],
        entity_text_override="天鹅壶4杯白但我要黑色",
    )

    assert contract.status == "unresolved"
    assert contract.resolved_sku is None
    assert contract.resolver_candidate_skus == []
    assert contract.status_reason == "explicit_attribute_conflict"


def test_adjacent_explicit_color_constraints_do_not_bind_a_product():
    white = _product("COLOR-WHITE")
    white.product_name_cn = "示例杯4杯-白色"
    black = _product("COLOR-BLACK")
    black.product_name_cn = "示例杯4杯-黑色"

    contract = build_entity_resolution_contract(
        "示例杯4杯白黑色支持什么热源？",
        [white, black],
        resolver_candidates=[white, black],
        entity_text_override="示例杯4杯白黑色",
        field_type_override="heat_source",
    )

    assert contract.status == "unresolved"
    assert contract.resolved_sku is None
    assert contract.resolver_candidate_skus == []
    assert contract.status_reason == "explicit_attribute_conflict"


def test_catalog_family_shorthand_keeps_missing_variant_attributes_ambiguous():
    products = []
    for sku, name in (
        ("KW-K31-白", "天鹅壶4杯-白色"),
        ("KW-K32-白", "天鹅壶9杯-白色"),
        ("KW-K31-黑", "天鹅壶4杯-黑色"),
        ("KW-K32-黑", "天鹅壶9杯-黑色"),
    ):
        product = _product(sku)
        product.product_name_cn = name
        products.append(product)

    nine_cup = build_entity_resolution_contract(
        "天鹅9杯能明火吗？",
        products,
        entity_text_override="天鹅9杯",
    )
    black = build_entity_resolution_contract(
        "天鹅黑色能明火吗？",
        products,
        entity_text_override="天鹅黑色",
    )
    all_variants = build_entity_resolution_contract(
        "天鹅能明火吗？",
        products,
        entity_text_override="天鹅",
    )

    assert nine_cup.status == "ambiguous"
    assert nine_cup.resolver_candidate_skus == ["KW-K32-白", "KW-K32-黑"]
    assert nine_cup.resolved_sku is None
    assert black.status == "ambiguous"
    assert black.resolver_candidate_skus == ["KW-K31-黑", "KW-K32-黑"]
    assert all_variants.status == "ambiguous"
    assert all_variants.resolver_candidate_skus == []
    assert set(all_variants.diagnostic_candidate_skus) == {sku for sku, _name in (
        ("KW-K31-白", ""), ("KW-K32-白", ""), ("KW-K31-黑", ""), ("KW-K32-黑", "")
    )}
    assert set(all_variants.candidate_skus) == set(all_variants.diagnostic_candidate_skus)


def test_catalog_family_shorthand_never_promotes_a_single_diagnostic_candidate():
    product = _product("KW-K32-白")
    product.product_name_cn = "天鹅壶9杯-白色"

    contract = build_entity_resolution_contract(
        "天鹅9杯能明火吗？",
        [product],
        entity_text_override="天鹅9杯",
    )

    assert contract.status == "ambiguous"
    assert contract.resolved_sku is None
    assert contract.resolver_candidate_skus == []
    assert contract.diagnostic_candidate_skus == ["KW-K32-白"]
    assert contract.candidate_skus == []


def test_catalog_family_shorthand_resolves_complete_variant_but_not_unrelated_or_missing_spec():
    products = []
    for sku, name in (
        ("KW-K31-白", "天鹅壶4杯-白色"),
        ("KW-K32-白", "天鹅壶9杯-白色"),
        ("KW-K31-黑", "天鹅壶4杯-黑色"),
        ("KW-K32-黑", "天鹅壶9杯-黑色"),
    ):
        product = _product(sku)
        product.product_name_cn = name
        products.append(product)

    exact = build_entity_resolution_contract(
        "天鹅9杯黑能明火吗？",
        products,
        entity_text_override="天鹅9杯黑",
    )
    nonexistent = build_entity_resolution_contract(
        "天鹅6杯能明火吗？",
        products,
        entity_text_override="天鹅6杯",
    )
    unrelated = build_entity_resolution_contract(
        "不存在的天鹅杯能明火吗？",
        products,
        entity_text_override="不存在的天鹅杯",
    )

    assert exact.status == "resolved"
    assert exact.resolved_sku == "KW-K32-黑"
    assert exact.matched_by == "normalized_alias_exact"
    assert nonexistent.status == "unresolved"
    assert nonexistent.candidate_skus == []
    assert unrelated.status == "unresolved"
    assert unrelated.candidate_skus == []


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


@pytest.mark.parametrize(
    "raw_subject",
    [
        "我想买可放",
        "想挑一套可以直接放进",
        "准备买一个能进",
    ],
)
def test_field_scope_normalization_rejects_shopping_predicates_as_product_entities(raw_subject):
    result = normalize_field_adjacent_entity_scope(
        question="想挑一套可以直接放进洗碗机清洁的户外餐具，资料里有确认过的吗？",
        raw_subject=raw_subject,
        canonical_field="dishwasher",
    )

    assert result.entity_subject == ""
    assert result.normalization_reason == "request_predicate_not_entity"


@pytest.mark.parametrize(
    ("question", "expected_field"),
    [
        ("示例商品的主体主要用什么材质？", "material"),
        ("示例商品的锅体用的是什么材质？", "material"),
        ("示例商品有哪些颜色？", "color"),
        ("示例商品可以放洗碗机吗？", "dishwasher"),
        ("示例商品最核心的产品卖点是什么？", "selling_point"),
        ("示例商品有什么主要特点？", "selling_point"),
    ],
)
def test_grammatical_field_predicate_is_removed_before_entity_resolution(question, expected_field):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.entity_subject == "示例商品"
    assert selection.field == expected_field
    assert selection.source == "field_contract"
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


@pytest.mark.parametrize(
    ("question", "expected_field"),
    [
        ("示例商品的条码是什么？", "barcode"),
        ("示例商品属于哪个产品系列？", "series"),
        ("示例商品是什么时候上市的？", "launch_date"),
        # “当前是否在售”是实时商业事实，不能借内部生命周期标签
        # 对客户作出承诺；它必须走 inventory 的安全实时边界。
        ("示例商品现在还在售吗？", "inventory"),
        ("示例商品的生命周期状态是什么？", "lifecycle_status"),
        ("示例商品表面用了什么处理工艺？", "surface_finish"),
        ("示例商品的产品定位是什么？", "positioning"),
        ("示例商品属于什么价格定位？", "price_positioning"),
        ("示例商品强调的情感价值是什么？", "emotional_value"),
        ("示例商品目前面向哪些地区销售？", "sales_region"),
        ("示例商品有哪些产品认证？", "certification"),
    ],
)
def test_customer_relevant_database_fields_form_one_contract_and_clean_subject(question, expected_field):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.entity_subject == "示例商品"
    assert selection.field == expected_field
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


def test_field_like_text_inside_selected_product_subject_is_not_a_second_contract():
    question = "示例桌面炉（不含炉配件-烤盘）有哪些颜色？"
    selection = select_entity_subject_for_routing(raw_question=question)
    result = customer_field_contract.resolve_requested_field_contract(
        question,
        {},
        subject=selection.entity_subject,
    )

    assert selection.entity_subject == "示例桌面炉（不含炉配件-烤盘）"
    assert result["canonical_fields"] == ["color"]
    assert result["supported_fields"] == ["color"]
    assert all(item["field_type"] != "accessories" for item in result["field_spans"])


@pytest.mark.parametrize(
    ("question", "expected_subject", "expected_field"),
    [
        ("示例炉配件自身有多重？", "示例炉配件", "weight"),
        ("示例酒精炉有没有官方说明书？", "示例酒精炉", "manual"),
        ("示例酒精炉套装下单后几天发出？", "示例酒精炉套装", "shipping"),
        ("示例酒精炉套装怎么保养？", "示例酒精炉套装", "care"),
        ("示例气罐从正式销售渠道购买，应该去哪里？", "示例气罐", "purchase_channel"),
    ],
)
def test_full_field_predicate_wins_over_field_like_terms_inside_product_name(
    question,
    expected_subject,
    expected_field,
):
    selection = select_entity_subject_for_routing(raw_question=question)

    assert selection.entity_subject == expected_subject
    assert selection.field == expected_field
    assert customer_field_contract.is_field_contract_predicate_signal(selection) is True


def test_material_predicate_field_contract_wins_over_empty_planner_field():
    result = customer_field_contract.resolve_requested_field_contract(
        "瓦片烤盘是用什么做的？",
        {"requested_field": ""},
        compatibility_fields=(),
    )

    assert result["requested_field"] == "材质"
    assert result["requested_fields"] == ["材质"]
    assert result["canonical_fields"] == ["material"]
    assert result["supported_fields"] == ["material"]


def test_explicit_dishwasher_predicate_keeps_formal_contract_when_semantic_calls_it_product_qa():
    """A provider may call a capability question product QA, but an existing
    full FieldContract predicate remains a high-precision formal request.

    This is a contract adapter test, not a new wording rule: the dishwasher
    predicate is already registered in the canonical field ontology.
    """
    result = customer_field_contract.resolve_requested_field_contract(
        "它可以放进洗碗机洗吗？",
        {
            "semantic_preplan": {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "evidence_kind": "product_qa",
                "canonical_fields": [],
                "confidence": 0.9,
            }
        },
    )

    assert result["field_type"] == "dishwasher"
    assert result["canonical_fields"] == ["dishwasher"]
    assert result["supported_fields"] == ["dishwasher"]


@pytest.mark.parametrize(
    ("question", "compatibility_fields", "expected_requested_fields"),
    [
        ("RT-P2-300尺寸多大？能不能用酒精炉？", ("尺寸", "热源"), ["尺寸", "热源"]),
        ("RT-P2-100 有赠品和配件吗", ("配件",), ["配件"]),
    ],
)
def test_field_phrase_semantics_do_not_expand_existing_legacy_requested_fields(
    question,
    compatibility_fields,
    expected_requested_fields,
):
    result = customer_field_contract.resolve_requested_field_contract(
        question,
        {},
        compatibility_fields=compatibility_fields,
    )

    assert result["requested_fields"] == expected_requested_fields


def test_full_phrase_predicate_signal_is_distinct_from_legacy_alias_signal():
    material = select_entity_subject_for_routing(raw_question="瓦片烤盘是用什么做的？")
    legacy_capacity = select_entity_subject_for_routing(raw_question="水壶容量怎么看")

    assert customer_field_contract.is_field_contract_predicate_signal(material) is True
    assert customer_field_contract.is_field_contract_predicate_signal(legacy_capacity) is False
