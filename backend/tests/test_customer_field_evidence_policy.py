import json
from types import SimpleNamespace

import pytest

from app.models import Product, ProductBusiness, ProductSpecs
from app.models.product_associations import (
    Certification,
    ListingChannel,
    ProductCertification,
    ProductListingChannel,
    ProductSalesRegion,
    SalesRegion,
)
from app.services import customer_agent_planner_service, customer_field_contract, customer_service_service
from app.services.customer_field_contract import (
    field_evidence_policy,
    qa_evidence_matches_field,
    select_dimension_evidence,
)
from customer_service_test_support import _add_product, _add_product_qa


@pytest.fixture()
def field_evidence_client(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(
            db,
            "FE-100",
            "晨雾Plus水壶",
            "水具",
            "1.2L",
            "铝合金",
            "明火",
            "核心卖点：快速加热",
            "露营",
            420,
        )
        _add_product_qa(db, "FE-100", "晨雾Plus水壶有什么核心卖点？", "核心卖点：快速加热。", priority=200)
        _add_product(
            db,
            "FE-200",
            "星海收纳包",
            "配件",
            "",
            "尼龙",
            "",
            "核心卖点：轻便收纳",
            "露营",
            0,
        )
        _add_product_qa(db, "FE-200", "星海收纳包有什么核心卖点？", "核心卖点：轻便收纳。", priority=200)
        product_id = db.query(Product.id).filter(Product.sku == "FE-200").scalar()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == product_id).update(
            {
                "capacity": json.dumps(
                    [
                        {"label": "", "value": "材", "unit": ""},
                        {"label": "质", "value": "食品级塑料", "unit": ""},
                    ],
                    ensure_ascii=False,
                ),
                "size_info": json.dumps(
                    [
                        {"label": "包装尺寸", "value": "42 x 30 x 8", "unit": "cm"},
                        {"label": "收纳袋尺寸", "value": "40 x 28 x 7", "unit": "cm"},
                    ],
                    ensure_ascii=False,
                )
            }
        )
        water_product_id = db.query(Product.id).filter(Product.sku == "FE-100").scalar()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == water_product_id).update(
            {"usage_instruction": "首次使用前用清水冲洗，使用后擦干并通风存放。"}
        )
        db.commit()
    return client, headers, Session


@pytest.mark.parametrize("alias", ["SKU", "货号", "产品编码", "商品编码"])
def test_sku_policy_uses_only_the_record_key_aliases(alias):
    policy = field_evidence_policy("sku")

    assert policy is not None
    assert alias in policy.aliases
    assert "product.sku" in policy.structured_fields
    assert qa_evidence_matches_field("核心卖点是什么", "", "sku") is False


def test_model_policy_does_not_substitute_sku_for_missing_model_number():
    policy = field_evidence_policy("model")

    assert policy is not None
    assert "型号" in policy.aliases
    assert "product.sku" not in policy.structured_fields


def test_safely_missing_model_uses_field_specific_non_realtime_copy():
    answer = customer_service_service._resolved_entity_unknown_fact_answer(
        "示例商品（DEMO-1）",
        "型号",
    )

    assert "型号" in answer
    assert "实时" not in answer
    assert "SKU" not in answer


def test_safely_missing_shipping_covers_carrier_without_claiming_delivery_timing():
    """A carrier question and an ETA question share a field, not a false premise."""
    answer = customer_service_service._resolved_entity_unknown_fact_answer(
        "示例旅行筷（DEMO-1）",
        "发货时效",
    )

    assert "承运" in answer
    assert "配送时效" in answer
    assert "按你说的时间送达" not in answer


def test_weight_policy_rejects_selling_point_qa():
    assert qa_evidence_matches_field("某商品有什么核心卖点", "", "weight") is False
    assert qa_evidence_matches_field("某商品净重是多少", "", "weight") is True


def test_dimension_policy_keeps_package_scope_separate_from_subject_scope():
    value = json.dumps(
        [
            {"label": "包装尺寸", "value": "42 x 30 x 8", "unit": "cm"},
            {"label": "收纳袋尺寸", "value": "40 x 28 x 7", "unit": "cm"},
        ],
        ensure_ascii=False,
    )

    assert select_dimension_evidence(value, requested_scope="subject") is None
    package = select_dimension_evidence(value, requested_scope="package")
    assert package is not None
    assert package.value == "42 x 30 x 8"
    assert package.scope == "package"


def test_generic_subject_dimension_includes_all_non_package_product_measurements():
    value = json.dumps(
        [
            {"label": "展开尺寸", "value": "36x25x20", "unit": "cm"},
            {"label": "收纳尺寸", "value": "36x25x10", "unit": "cm"},
            {"label": "包装尺寸", "value": "40x30x25", "unit": "cm"},
        ],
        ensure_ascii=False,
    )

    evidence = select_dimension_evidence(value, requested_scope="subject")

    assert evidence is not None
    assert evidence.value == "展开尺寸：36x25x20cm；收纳尺寸：36x25x10cm"
    assert evidence.is_generic_fallback is False


def test_generic_subject_dimension_recovers_a_label_only_row_and_component_measurement():
    split_storage = json.dumps(
        [
            {"label": "展开尺寸", "value": "15.2x11.7", "unit": "cm"},
            {"label": "", "value": "收纳尺寸", "unit": ""},
            {"label": "", "value": ":9.5x6.7mm（炉体）", "unit": ""},
        ],
        ensure_ascii=False,
    )
    component_only = json.dumps(
        [{"label": "炉体", "value": "9.5x6.7", "unit": "cm"}],
        ensure_ascii=False,
    )

    recovered = select_dimension_evidence(split_storage, requested_scope="subject")
    component = select_dimension_evidence(component_only, requested_scope="subject")

    assert recovered is not None
    assert recovered.value == "展开尺寸：15.2x11.7cm；收纳尺寸：9.5x6.7mm（炉体）"
    assert component is not None
    assert component.value == "9.5x6.7"


def test_dimension_policy_rejects_label_without_measurement():
    assert select_dimension_evidence(
        json.dumps([{"label": "收纳尺寸", "value": "收纳尺寸", "unit": ""}], ensure_ascii=False),
        requested_scope="subject",
    ) is None


def test_dimension_policy_removes_source_label_delimiter_before_formatting():
    evidence = select_dimension_evidence(":9.5x6.7mm", requested_scope="subject")

    assert evidence is not None
    assert evidence.value == "9.5x6.7mm"


def test_capacity_name_and_structured_value_conflict_fails_closed():
    assert customer_service_service._capacity_evidence_conflict(
        "1.4L示例水壶",
        '[{"label": "容量", "value": "4L"}]',
    ) == ("1.4L", "4L")
    assert customer_service_service._capacity_evidence_conflict(
        "1400ml示例水壶",
        '[{"label": "容量", "value": "1.4L"}]',
    ) is None


def test_product_row_keeps_uncorroborated_marketing_capacity_conflict_closed():
    product = SimpleNamespace(
        sku="FIELD-CAPACITY-1",
        barcode="",
        product_name_cn="示例水壶",
        product_name_en="Example Kettle",
        brand="",
        series="",
        category="水具",
        sub_category="水壶",
        product_level="",
        launch_date=None,
        lifecycle_status="active",
    )
    specs = SimpleNamespace(
        capacity="水壶：800ml",
        technical_advantages="",
        heat_source="",
        size_info="",
        power="",
        body_material="",
        surface_finish="",
        color="",
        usage_instruction="",
        gross_weight_g=183,
    )
    stale_content = SimpleNamespace(long_description_cn="旧版文案写成 1.4L 双人容量")

    row = customer_service_service._product_row_from_model(
        product,
        specs,
        None,
        stale_content,
    )

    assert row["capacity"] == ""
    assert row["capacity_evidence_conflict"] is True
    assert "capacity" in row["conflicted_formal_fields"]


def test_product_row_closes_capacity_conflict_against_same_sku_size_info():
    product = SimpleNamespace(
        sku="FIELD-CAPACITY-SIZE-1",
        barcode="",
        product_name_cn="示例套锅",
        product_name_en="Example Cookware Set",
        brand="",
        series="",
        category="锅具",
        sub_category="套锅",
        product_level="",
        launch_date=None,
        lifecycle_status="active",
    )
    specs = SimpleNamespace(
        capacity=[
            {"label": "", "value": "7L锅", "unit": ""},
            {"label": "", "value": "4L浅锅", "unit": ""},
        ],
        size_info=[
            {"label": "展开尺寸", "value": "1.7L锅 17*17*7.5", "unit": "cm"},
            {"label": "", "value": "1.4L浅锅 16*16*7.5", "unit": "cm"},
        ],
        technical_advantages="户外锅具套装",
        heat_source="",
        power="",
        body_material="",
        surface_finish="",
        color="",
        usage_instruction="",
        gross_weight_g=1030,
    )

    row = customer_service_service._product_row_from_model(
        product,
        specs,
        None,
        None,
    )

    assert row["capacity"] == ""
    assert row["capacity_evidence_conflict"] is True
    assert "capacity" in row["conflicted_formal_fields"]


def test_approved_direct_capacity_qa_can_corroborate_complete_structured_value():
    approved = [SimpleNamespace(
        question="示例水壶的容量多大？",
        answer="水壶：800ml。",
        tags=None,
    )]
    stale_or_unrelated = [
        SimpleNamespace(
            question="示例水壶有什么核心卖点？",
            answer="1.4L 双人容量。",
            tags=None,
        ),
        SimpleNamespace(
            question="示例水壶的容量多大？",
            answer="1.4L。",
            tags=None,
        ),
    ]

    assert customer_service_service._approved_capacity_qa_corroborates_structured_value(
        approved,
        "水壶：800ml",
    ) is True
    assert customer_service_service._approved_capacity_qa_corroborates_structured_value(
        stale_or_unrelated,
        "水壶：800ml",
    ) is False


def test_product_row_still_fails_closed_on_capacity_in_canonical_identity():
    product = SimpleNamespace(
        sku="FIELD-CAPACITY-2",
        barcode="",
        product_name_cn="1.4L 示例水壶",
        product_name_en="",
        brand="",
        series="",
        category="水具",
        sub_category="水壶",
        product_level="",
        launch_date=None,
        lifecycle_status="active",
    )
    specs = SimpleNamespace(
        capacity="水壶：800ml",
        technical_advantages="",
        heat_source="",
        size_info="",
        power="",
        body_material="",
        surface_finish="",
        color="",
        usage_instruction="",
        gross_weight_g=183,
    )

    row = customer_service_service._product_row_from_model(product, specs, None, None)

    assert row["capacity"] == ""
    assert row["capacity_evidence_conflict"] is True
    assert "capacity" in row["conflicted_formal_fields"]


def test_explicit_name_color_and_structured_color_conflict_fails_closed():
    assert customer_service_service._color_evidence_conflict(
        "示例水壶(电光绿)",
        "锖色",
    ) == ("电光绿", "锖色")
    assert customer_service_service._color_evidence_conflict(
        "示例水壶-竹灰绿",
        "绿色",
    ) is None


def test_color_provider_drops_cross_field_tokens():
    assert customer_service_service._color_field_evidence("铝、黑色") == "黑色"
    assert customer_service_service._color_field_evidence("锖色、牛油果绿") == "锖色、牛油果绿"


def test_liquid_temperature_capability_requires_liquid_specific_same_sku_evidence():
    """High-temperature food is not evidence that a vessel can hold hot water."""
    product = SimpleNamespace(
        product_name_cn="示例搪瓷餐具",
        product_name_en="",
        category="餐具",
        sub_category="",
    )
    specs = SimpleNamespace(
        usage_instruction="适用于户外用餐场景，可接触高温食物。"
    )

    value, source = customer_service_service._structured_product_field_evidence(
        "usage_instruction",
        db=None,
        product=product,
        specs=specs,
        business=None,
        content=None,
        requested_subtype="liquid_temperature_capability",
    )

    assert value == ""
    assert source is None


def test_liquid_temperature_capability_rejects_warm_water_cleaning_instructions():
    product = SimpleNamespace(
        product_name_cn="示例搪瓷餐具",
        product_name_en="",
        category="餐具",
        sub_category="",
    )
    specs = SimpleNamespace(
        usage_instruction="首次使用前用温水清洗。使用后用温水冲洗并擦干。"
    )

    value, source = customer_service_service._structured_product_field_evidence(
        "usage_instruction",
        db=None,
        product=product,
        specs=specs,
        business=None,
        content=None,
        requested_subtype="liquid_temperature_capability",
    )

    assert value == ""
    assert source is None


def test_material_answer_normalizer_removes_source_tabs_without_repeating_handle_material():
    answer = customer_service_service._normalize_handle_material_phrase(
        "示例产品的材质：腕带材质：\t尼龙\n手柄材质：\tEVA发泡海绵。"
    )

    assert answer == "示例产品的材质：腕带材质：尼龙\n手柄材质：EVA发泡海绵。"


def test_catalog_subject_override_keeps_field_word_inside_product_name():
    contract = customer_service_service.resolve_requested_field_contract(
        "示例酒精炉PRO的型号是什么？",
        subject_override="示例酒精炉PRO",
    )

    assert contract["field_type"] == "model"
    assert contract["canonical_fields"] == ["model"]
    assert contract["subject"] == "示例酒精炉PRO"


def test_catalog_exact_subject_can_correct_semantic_entity_scope_without_trusting_semantic_identity():
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "contents",
            "subtype": "known_detail",
            "entity_scope": "category_scope",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷原装开箱会附带哪些东西？",
        plan,
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "accessories"
    assert contract["source"] == "validated_semantic_preplan"
    assert contract["subject"] == "示例旅行筷"


def test_supported_semantic_field_is_adapted_to_the_existing_field_contract():
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "series",
            "field_hint": "series",
            "subtype": "known_detail",
            "entity_scope": "resolved_product",
            "confidence": 0.95,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷是哪个产品线的？",
        plan,
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "series"
    assert contract["source"] == "validated_semantic_preplan"
    assert contract["canonical_fields"] == ["series"]


def test_high_confidence_semantic_field_is_not_overridden_by_legacy_usage_care_classifier():
    """Usage/care is evidence routing, not a second field-intent authority."""
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "cleaning",
            "field_hint": "cleaning",
            "canonical_fields": ["cleaning"],
            "subtype": "known_detail",
            "entity_scope": "product_like",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例锅怎么清洁？",
        plan,
        subject_override="示例锅",
    )

    assert contract["field_type"] == "cleaning"
    assert contract["source"] == "validated_semantic_preplan"


def test_high_confidence_target_audience_semantic_is_not_overridden_by_generic_suitable_for_phrase():
    """"Suitable for whom" is semantic audience intent, not a scenario predicate."""
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "target_audience",
            "field_hint": "target_audience",
            "canonical_fields": ["target_audience"],
            "subtype": "known_detail",
            "entity_scope": "product_like",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例收纳包更适合谁用？",
        plan,
        subject_override="示例收纳包",
    )

    assert contract["field_type"] == "target_audience"
    assert contract["source"] == "validated_semantic_preplan"


def test_explicit_people_contract_outranks_conflicting_semantic_target_audience_label():
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(
        "示例旅行筷通常供几人使用？"
    )
    assert semantic is not None
    assert semantic["field_type"] == "people"
    plan = {"semantic_preplan": semantic}

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷通常供几人使用？",
        plan,
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "people"


def test_explicit_technical_advantages_contract_rejects_conflicting_semantic_selling_point_label():
    # A high-confidence semantic plan owns natural-language interpretation,
    # but a direct canonical FieldContract span is a deterministic contract
    # constraint.  It must reject a contradictory label rather than letting a
    # generic selling-point route consume technical evidence.
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "selling_point",
            "field_hint": "selling_point",
            "canonical_fields": ["selling_point"],
            "subtype": "known_detail",
            "entity_scope": "product_like",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷的技术优势是什么？",
        plan,
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "technical_advantages"
    assert contract["canonical_fields"] == ["technical_advantages"]
    assert contract["source"] == "explicit_contract_semantic_conflict"


def test_people_structured_evidence_rejects_capacity_and_requires_headcount():
    policy = field_evidence_policy("people")
    # target_audience and selling points are both admissible only after the
    # central value validator finds an explicit headcount; capacity and generic
    # marketing text remain invalid people evidence.
    assert policy.structured_fields == ("business.target_audience", "business.top_selling_points")
    assert customer_service_service._is_valid_structured_field_value("people", "8L") is False
    assert customer_service_service._is_valid_structured_field_value("people", "户外露营者") is False
    assert customer_service_service._is_valid_structured_field_value("people", "适合2-3人使用") is True


def test_compositional_price_tier_adapter_outranks_incidental_brand_alias():
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(
        "示例旅行筷在品牌的价位梯度中处于哪一档？"
    )
    assert semantic is not None
    assert semantic["field_type"] == "price_positioning"

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷在品牌的价位梯度中处于哪一档？",
        {"semantic_preplan": semantic},
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "price_positioning"
    assert contract["source"] == "validated_semantic_preplan"


def test_semantic_price_positioning_keeps_its_compositionally_confirmed_field_over_incidental_brand_label():
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "price_positioning",
            "field_hint": "price_positioning",
            "canonical_fields": ["price_positioning"],
            "subtype": "known_detail",
            "entity_scope": "product_like",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例旅行筷在品牌的价位梯度中处于哪一档？",
        plan,
        subject_override="示例旅行筷",
    )

    assert contract["field_type"] == "price_positioning"
    assert contract["source"] == "validated_semantic_preplan"


def test_semantic_preplan_prompt_distinguishes_product_need_from_user_persona():
    """Natural wording about a product's role must not collapse into audience.

    This is a taxonomy contract for the semantic planner, not an alias for a
    product or a particular customer question.  Entity and evidence contracts
    remain downstream of the selected canonical field.
    """
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="示例折叠箱面向哪类需求？",
        deterministic_plan={},
        context={},
    )
    prompt = str(messages[0]["content"])

    assert "positioning=target customer/problem, intended role, or brand strategy" in prompt
    assert "need, use case, problem, role, or job-to-be-done" in prompt
    assert "user persona, customer type, or user group" in prompt


def test_semantic_preplan_prompt_keeps_named_product_safety_as_product_fact():
    """A document may supply evidence without becoming the customer's subject."""
    messages = customer_agent_planner_service._semantic_preplan_messages(
        question="\u793a\u4f8b\u7089\u5177\u6709\u4ec0\u4e48\u7981\u6b62\u64cd\u4f5c\uff1f",
        deterministic_plan={},
        context={},
    )
    prompt = str(messages[0]["content"])

    assert "named-product question about operating steps, safety rules, prohibited actions" in prompt
    assert "is product_bound_qa even if its answer may later use a manual or knowledge-base document as evidence" in prompt




def test_semantic_safe_field_forms_the_only_field_contract_without_a_phrase_alias():
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "manual",
            "field_hint": "manual",
            "canonical_fields": ["manual"],
            "subtype": "known_detail",
            "entity_scope": "product_like",
            "confidence": 0.9,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "示例野炊锅的官方操作文档在哪儿看？",
        plan,
        subject_override="示例野炊锅",
    )

    assert contract["field_type"] == "manual"
    assert contract["canonical_fields"] == ["manual"]
    assert contract["supported_fields"] == []
    assert contract["unsupported_fields"] == ["manual"]
    assert contract["source"] == "validated_semantic_preplan"


@pytest.mark.parametrize(("question", "field_type"), [
    ("示例烤炉是否适配常见炉具？", "heat_source"),
    ("示例收纳包能否机洗？", "cleaning"),
    ("示例水袋属于A类还是B类？", "product_level"),
    ("示例炉具最大功率多少瓦？", "power"),
    ("示例折叠箱操作步骤怎么走？", "usage_instruction"),
    ("示例折叠箱日常清洗怎么做？", "cleaning"),
    ("示例折叠箱长期不用怎么维护？", "care"),
])
def test_compositional_field_adapter_handles_unseen_supported_field_wording(question, field_type):
    semantic = customer_agent_planner_service._deterministic_semantic_field_fallback(question)
    assert semantic is not None
    assert semantic["field_type"] == field_type
    contract = customer_service_service.resolve_requested_field_contract(question, {"semantic_preplan": semantic})
    assert contract["field_type"] == field_type


def test_contents_composition_fallback_forms_contract_when_semantic_is_unavailable():
    question = "示例野炊套锅包含哪些？"
    contract = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": {"called": True, "fallback_reason": "semantic_unavailable"}},
        subject_override="示例野炊套锅",
    )

    assert contract["field_type"] == "accessories"
    # Semantic planning is explicitly unavailable here. The formal contract
    # remains valid, but its source must truthfully record the conservative
    # deterministic fallback rather than impersonate an AI decision.
    assert contract["source"] == "legacy_requested_fields"


def test_purchase_predicate_fallback_beats_product_name_heat_source_alias():
    question = "示例酒精炉在哪里可以买到？"
    contract = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": {"called": True, "fallback_reason": "semantic_unavailable"}},
        subject_override="示例酒精炉",
    )

    assert contract["field_type"] == "purchase_channel"
    assert contract["source"] == "deterministic_full_predicate"


def test_semantic_outage_fallback_keeps_an_independent_audience_field_in_a_compound_request():
    # This is deliberately not a production title or a historical failed
    # sentence.  When semantic planning is unavailable, an explicit material
    # field must not hide the independent customer-audience intent.
    question = "示例野炊锅的锅盖材质是什么，更适合哪类用户？"
    contract = customer_service_service.resolve_requested_field_contract(
        question,
        {"semantic_preplan": {"called": True, "fallback_reason": "semantic_unavailable"}},
        subject_override="示例野炊锅",
    )

    assert contract["canonical_fields"] == ["material", "target_audience"]
    assert contract["compound"] is True


def test_semantic_field_keeps_a_full_explicit_sku_when_legacy_extraction_emits_a_suffix():
    plan = {
        "semantic_preplan": {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "series",
            "field_hint": "series",
            "subtype": "known_detail",
            "entity_scope": "resolved_product",
            "confidence": 0.95,
        }
    }

    contract = customer_service_service.resolve_requested_field_contract(
        "CW-C95属于什么系列？",
        plan,
    )

    assert contract["subject"] == "CW-C95"
    assert contract["field_type"] == "series"




def test_validated_semantic_field_is_not_blocked_by_legacy_product_refs():
    # A planner reference is only an identity hint.  Once the semantic layer
    # has formed a supported FieldContract, Phase 2 must seal that identity
    # rather than fall back to the planner's broad lexical field label.
    field_request = {
        "field_type": "price_positioning",
        "requested_field": "价格定位",
        "requested_fields": ["价格定位"],
        "canonical_fields": ["price_positioning"],
        "source": "validated_semantic_preplan",
    }
    assert customer_service_service._phase2_single_field_arbitration_eligible(
        "example travel box price tier?",
        {"primary_intent": "product_field", "product_refs": ["FE-100"]},
        conversation_id=None,
        field_request_override=field_request,
    ) is True


def test_validated_semantic_detail_field_precedes_legacy_unknown_fact_guard():
    # The semantic plan supplies only a validated canonical field.  It does
    # not supply entity identity or evidence; Phase 2 must still create the
    # EntityResolutionContract and obtain same-SKU evidence.
    result = customer_service_service._pre_route_high_risk_contract_result(
        None,
        "示例旅行筷拿到过什么合规认证？",
        {
            "called": True,
            "route_family": "product_bound_qa",
            "route_hint": "product_detail",
            "question_type": "field",
            "field_type": "certification",
            "field_hint": "certification",
            "subtype": "known_detail",
            "entity_scope": "resolved_product",
            "confidence": 0.95,
        },
    )

    assert result is None


@pytest.mark.parametrize(
    ("field_type", "expected_value", "expected_source"),
    [
        ("purchase_channel", "字段验收渠道", "product_listing_channels->listing_channels"),
        ("sales_region", "字段验收区域", "product_sales_regions->sales_regions"),
        ("certification", "字段验收认证", "product_certifications->certifications"),
    ],
)
def test_association_evidence_uses_the_sealed_product_only(
    field_evidence_client,
    field_type,
    expected_value,
    expected_source,
):
    _client, _headers, Session = field_evidence_client
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "FE-100").one()
        if field_type == "purchase_channel":
            item = ListingChannel(channel_name=expected_value, channel_code="field-check")
            db.add(item)
            db.flush()
            db.add(ProductListingChannel(product_id=product.id, channel_id=item.id))
        elif field_type == "sales_region":
            item = SalesRegion(region_name=expected_value, region_code="field-check")
            db.add(item)
            db.flush()
            db.add(ProductSalesRegion(product_id=product.id, region_id=item.id))
        else:
            item = Certification(certification_name=expected_value, certification_code="field-check")
            db.add(item)
            db.flush()
            db.add(ProductCertification(product_id=product.id, certification_id=item.id))
        db.commit()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
        value, source = customer_service_service._structured_product_field_evidence(
            field_type,
            db=db,
            product=product,
            specs=specs,
            business=None,
            content=None,
        )

    assert value == expected_value
    assert source == expected_source


def test_certification_association_preserves_its_database_explanation(
    field_evidence_client,
):
    """A standard label must not lose its DB meaning and become a bare certification claim."""
    _client, _headers, Session = field_evidence_client
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "FE-100").one()
        item = Certification(
            certification_name="GB",
            certification_code="GB",
            description="中国国家标准",
        )
        db.add(item)
        db.flush()
        db.add(ProductCertification(product_id=product.id, certification_id=item.id))
        db.commit()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).first()
        value, source = customer_service_service._structured_product_field_evidence(
            "certification",
            db=db,
            product=product,
            specs=specs,
            business=None,
            content=None,
        )

    assert value == "GB（中国国家标准）"
    assert source == "product_certifications->certifications"


def test_usage_provider_rejects_instruction_from_another_product_domain():
    cup = Product(product_name_cn="示例随行杯", category="水杯")
    kettle_copy = "烹饪前将水壶置于灶具上小火预热，洗净后确保壶底干燥，严禁干烧。"
    kettle = Product(product_name_cn="示例咖啡壶", category="咖啡器具")
    grinder_copy = "按冲煮方式调节研磨粗细，定期清理研磨器刀盘。"

    assert customer_service_service._usage_instruction_matches_product(cup, kettle_copy) is False
    assert customer_service_service._usage_instruction_matches_product(kettle, grinder_copy) is False
    assert customer_service_service._color_evidence_conflict(
        "金波系列示例水杯",
        "橙色",
    ) is None


@pytest.mark.parametrize(
    "raw_value",
    [
        '[{"label": "", "value": "/", "unit": ""}]',
        '[{"label": "", "value": "材"}, {"label": "质", "value": "食品级塑料"}]',
        '[{"label": "", "value": "13*8.5", "unit": "cm"}]',
    ],
)
def test_capacity_evidence_rejects_placeholders_and_cross_field_values(raw_value):
    assert customer_service_service._capacity_field_evidence(raw_value) == ""


def test_capacity_evidence_keeps_capacity_units_and_labeled_component_sizes():
    raw_value = json.dumps(
        [
            {"label": "大锅", "value": "3L", "unit": ""},
            {"label": "煎盘", "value": "8寸", "unit": ""},
            {"label": "水壶", "value": "800ml", "unit": ""},
        ],
        ensure_ascii=False,
    )

    assert customer_service_service._capacity_field_evidence(raw_value) == "大锅 3L，煎盘 8寸，水壶 800ml"


def test_usage_field_evidence_keeps_complete_numbered_items():
    instruction = """【使用步骤】
1.展开产品并检查锁扣。
【日常养护】
1.使用后清洁杖身泥土，保持锁扣洁净。
2.长期不用时松开锁扣，放在干燥处。
【禁止事项】
1.避免用冷水清洗高温部件。"""

    cleaning = customer_service_service._usage_instruction_field_evidence(instruction, "cleaning")
    care = customer_service_service._usage_instruction_field_evidence(instruction, "care")

    assert "保持锁扣洁净" in cleaning
    assert "避免用冷水清洗高温部件" in cleaning
    assert "长期不用时松开锁扣，放在干燥处" in care
    assert "展开产品" not in cleaning


def test_usage_instruction_first_use_subtype_keeps_only_first_use_step():
    instruction = (
        "\u3010\u4f7f\u7528\u6b65\u9aa4\u3011\n"
        "1.\u5f00\u7bb1\u521d\u6d17\uff1a\u9996\u6b21\u4f7f\u7528\u524d\uff0c\u7528\u6e29\u6c34\u548c\u8f6f\u5e03\u8f7b\u67d4\u51b2\u6d17\u9505\u8eab\uff0c\u65e0\u9700\u4f7f\u7528\u6d17\u6d01\u7cbe\u3002\n"
        "2.\u53ca\u65f6\u6e05\u6d01\uff1a\u6bcf\u6b21\u4f7f\u7528\u540e\u7528\u6e29\u6c34\u51b2\u6d17\u5e72\u51c0\u3002\n"
        "\u3010\u65e5\u5e38\u517b\u62a4\u3011\n"
        "1.\u6d17\u51c0\u540e\u7528\u62b9\u5e03\u64e6\u5e72\uff0c\u907f\u514d\u6e7f\u6c34\u4e45\u653e\u3002"
    )

    assert customer_field_contract.requested_usage_instruction_subtype("\u7b2c\u4e00\u6b21\u4f7f\u7528\u524d\u600e\u4e48\u6e05\u6d01\uff1f") == "first_use"
    assert customer_field_contract.requested_cleaning_subtype("\u7b2c\u4e00\u6b21\u4f7f\u7528\u524d\u600e\u4e48\u6e05\u6d01\uff1f") == "first_use"
    evidence = customer_service_service._usage_instruction_field_evidence(
        instruction,
        "cleaning",
        requested_subtype="first_use",
    )

    assert "\u5f00\u7bb1\u521d\u6d17" in evidence
    assert "\u6bcf\u6b21\u4f7f\u7528\u540e" not in evidence
    assert "\u907f\u514d\u6e7f\u6c34\u4e45\u653e" not in evidence


def test_machine_wash_evidence_requires_an_explicit_laundry_machine_wash_clause():
    generic_cleaning = "首次使用前用湿布擦拭表面。使用后用湿布擦拭干净。"
    explicit_machine_wash = "本产品不可放入洗衣机机洗，请使用湿布擦拭。"

    assert customer_service_service._machine_wash_specific_evidence(generic_cleaning) == ""
    assert customer_service_service._machine_wash_specific_evidence(explicit_machine_wash) == explicit_machine_wash


def test_requested_cleaning_subtype_distinguishes_laundry_machine_wash_from_dishwasher():
    assert customer_field_contract.requested_cleaning_subtype("示例收纳包能否机洗？") == "machine_wash"
    assert customer_field_contract.requested_cleaning_subtype("示例收纳包能放洗衣机吗？") == "machine_wash"
    assert customer_field_contract.requested_cleaning_subtype("示例餐盘能放洗碗机吗？") is None


def test_usage_field_evidence_removes_stray_terminal_ascii_fragment():
    instruction = "4.酒精存放：密封后远离火源，放在儿童接触不到的地方，常温存放aLocs"

    result = customer_service_service._usage_instruction_field_evidence(instruction, "care")

    assert "酒精存放" in result
    assert "远离火源" in result
    assert "aLocs" not in result
    assert "aLocs" not in customer_service_service._usage_instruction_field_evidence(
        instruction,
        "usage_instruction",
    )


def test_usage_field_evidence_normalizes_whitespace_and_filtered_section_numbering():
    instruction = """【首次使用】
1.用温水冲洗。\n\n【日常清洁】
1.使用后擦洗干净。\n\n【禁止事项】
1.不要使用钢丝球刷洗。"""

    full = customer_service_service._usage_instruction_field_evidence(instruction, "usage_instruction")
    cleaning = customer_service_service._usage_instruction_field_evidence(instruction, "cleaning")

    assert "\n" not in full
    assert cleaning == "用温水冲洗。 使用后擦洗干净。 不要使用钢丝球刷洗。"


def test_heat_source_evidence_normalizes_multiline_and_duplicate_separators():
    result = customer_service_service._heat_source_field_evidence(
        "明火直烧\n燃气炉、卡式炉\n\n燃气炉"
    )

    assert result == "明火直烧、燃气炉、卡式炉"


def test_heat_source_evidence_discards_catalogue_placeholders():
    assert customer_service_service._heat_source_field_evidence("/") == ""
    assert customer_service_service._heat_source_field_evidence("暂无") == ""


def test_heat_source_answer_consumes_the_normalized_structured_value():
    metadata = {}
    answer, status = customer_service_service._phase1_heat_source_capability_answer(
        None,
        {
            "sku": "DEMO-HEAT",
            "product_name_cn": "示例炉具",
            "heat_source": "明火直烧\n燃气炉、卡式炉\n\n燃气炉",
        },
        "支持什么热源？",
        evidence_metadata=metadata,
    )

    assert status == "structured"
    assert "明火直烧、燃气炉、卡式炉" in answer
    assert "\n" not in answer
    assert metadata["evidence_value"] == "明火直烧、燃气炉、卡式炉"


def test_heat_source_answer_uses_explicit_same_sku_usage_instruction_boundary():
    metadata = {}
    answer, status = customer_service_service._phase1_heat_source_capability_answer(
        None,
        {
            "sku": "DEMO-CUP",
            "product_name_cn": "示例水杯",
            "heat_source": "",
            "usage_instruction": "日常使用：可用于盛装冷/热饮品，不可直接置于明火上加热（除非产品明确支持）。",
        },
        "示例水杯能直接放明火上吗？",
        evidence_metadata=metadata,
    )

    assert status == "unsupported"
    assert "不可直接置于明火上加热" in answer
    assert metadata["evidence_source"] == "specs.usage_instruction"
    assert metadata["evidence_value"] == "不可直接置于明火上加热（除非产品明确支持）"


def test_usage_field_evidence_keeps_unmarked_continuation_after_matched_clause():
    instruction = (
        "2.彻底烘干：洗净后务必用抹布擦干，"
        "或置于灶具上小火加热1分钟，确保锅身和锅底水分完全蒸发。"
    )

    result = customer_service_service._usage_instruction_field_evidence(instruction, "care")

    assert "用抹布擦干" in result
    assert "小火加热1分钟" in result
    assert "水分完全蒸发" in result


def test_care_evidence_does_not_treat_take_from_storage_bag_as_maintenance():
    instruction = "1.从收纳包取出炉具，放置在稳固水平面上。"

    assert customer_service_service._usage_instruction_field_evidence(instruction, "care") == ""


def test_field_only_output_keeps_all_valid_evidence_sentences():
    answer = "示例产品（DEMO-1）的清洁：先冲洗。再擦拭干净。"

    assert customer_service_service._shape_product_detail_output(
        answer,
        [],
        answer_metadata={"answer_policy": "field_only"},
    ) == answer


def test_same_sku_rag_product_qa_output_keeps_complete_grounded_body():
    """A post-RAG formatter must not discard verified facts after sentence one."""
    answer = "Verified benefit one. Verified benefit two."

    assert customer_service_service._shape_product_detail_output(
        answer,
        [],
        answer_metadata={
            "contract_field_type": "product_qa",
            "evidence_status": "matched",
            "evidence_source": "same_sku_knowledge",
        },
    ) == answer


def test_same_sku_rag_coverage_treats_broad_decision_prompt_as_one_request():
    """Coverage must not invent an omitted sub-capability from a broad overview ask."""
    messages = customer_service_service._same_sku_knowledge_coverage_messages(
        "现有资料能帮我判断哪些实际取舍？",
        "它折叠便携、重量轻，且易清洁。",
        "支持折叠收纳，折后体积小巧。\n净重约9g。\n易清洁。",
    )

    instruction = messages[0]["content"]

    assert "broad overview or decision question" in instruction
    assert "Do not invent" in instruction
    assert "Only state that evidence does not directly confirm" in instruction
    assert "both resolves a condition and says that same condition is not confirmed" in instruction
    assert "internally_consistent:boolean" in instruction


def test_same_sku_rag_coverage_rejects_an_internally_contradictory_draft(monkeypatch):
    async def fake_completion(*_args, **_kwargs):
        return '{"complete":true,"internally_consistent":false}'

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_completion,
    )

    import asyncio

    assert not asyncio.run(
        customer_service_service._same_sku_rag_answer_covers_question(
            SimpleNamespace(),
            "\u80fd\u5426\u76f4\u63a5\u704c\u6cb8\u6c34\uff1f",
            "\u8010\u6e29\u4e0a\u9650\u4e3a140\u00b0F\uff0c\u4e0d\u5efa\u8bae\u704c\u6cb8\u6c34\u3002\u4f46\u8d44\u6599\u672a\u786e\u8ba4\u80fd\u5426\u704c\u6cb8\u6c34\u3002",
            "\u8010\u6e29\u8303\u56f4\u4e3a32\u00b0F\u81f3140\u00b0F\u3002",
        )
    )


def test_same_sku_rag_selector_allows_partial_direct_evidence_only_for_semantic_compound_turn():
    """A semantic multi-intent contract may retain a verified first part.

    The selector still cannot use related evidence as an answer to another
    independent part; the downstream generator must state that gap safely.
    """
    messages = customer_service_service._same_sku_knowledge_evidence_selection_messages(
        "Can it perform one capability and remain in a separate condition?",
        "RAG-COMPOUND-100",
        [{"index": 0, "content": "Verified capability: compact storage."}],
        allow_partial_compound=True,
    )

    assert "one independently requested part" in messages[0]["content"]


def test_strict_same_sku_entailment_allows_a_safe_compound_evidence_gap():
    """A non-negative evidence gap is not an unsupported product conclusion."""
    messages = customer_service_service._same_sku_knowledge_strict_entailment_messages(
        "Can it perform one capability and remain in a separate condition?",
        "It supports the recorded capability. The supplied evidence does not directly confirm the separate condition.",
        "Recorded capability: compact storage.",
    )

    assert "does not directly confirm" in messages[0]["content"]
    assert "not a negative product fact" in messages[0]["content"]


def test_same_sku_coverage_treats_a_named_compound_evidence_gap_as_complete():
    """Coverage must keep a verified part instead of demanding an invented second fact."""
    messages = customer_service_service._same_sku_knowledge_coverage_messages(
        "Can it perform one capability and remain in a separate condition?",
        "It supports the recorded capability. The supplied evidence does not directly confirm the separate condition.",
        "Recorded capability: compact storage.",
    )

    assert "complete evidence-boundary answer" in messages[0]["content"]
    assert "do not return false merely because" in messages[0]["content"]


def test_semantic_product_qa_missing_clause_requires_semantic_compound_intent():
    """A broad one-intent QA plan cannot invent an additional missing capability."""
    assert not customer_service_service._semantic_product_qa_allows_explicit_missing_clause(
        {"semantic_preplan": {"compound": False, "additional_user_intent": False}}
    )
    assert customer_service_service._semantic_product_qa_allows_explicit_missing_clause(
        {"semantic_preplan": {"compound": True, "additional_user_intent": False}}
    )


def test_same_sku_rag_payload_excludes_internal_catalog_fields():
    """Open RAG may use customer evidence but must never see internal labels."""
    content = (
        "SKU: DEMO-1\n"
        "生命周期: old catalog status\n"
        "负责人: Internal Owner\n"
        "业务信息:\n"
        "- 核心卖点: verified customer benefit\n"
        "关联信息:\n"
        "- 关键词: internal search phrase\n"
        "- 认证: verified certification"
    )

    filtered = customer_service_service._customer_safe_same_sku_knowledge_content(content)

    assert "old catalog status" not in filtered
    assert "Internal Owner" not in filtered
    assert "internal search phrase" not in filtered
    assert "verified customer benefit" in filtered
    assert "verified certification" in filtered


def test_same_sku_knowledge_evidence_units_keep_independent_listing_paragraphs_separate():
    """Long imported Listings must not turn unrelated facts into one claim."""
    content = (
        "- 中文 Listing: 这套炊具采用硬质阳极氧化铝合金。\n\n"
        "这套全面的炊具包含一个容量为 3700 毫升的主锅和一个容量为 2300 毫升的煎锅。\n\n"
        "请在锅具仍有余温时用温水清洗。"
    )

    units = customer_service_service._same_sku_knowledge_evidence_units(content)

    assert units == [
        "- 中文 Listing: 这套炊具采用硬质阳极氧化铝合金。",
        "这套全面的炊具包含一个容量为 3700 毫升的主锅和一个容量为 2300 毫升的煎锅。",
        "请在锅具仍有余温时用温水清洗。",
    ]


def test_same_sku_knowledge_evidence_units_atomize_english_listing_sentences():
    content = (
        "The kettle passed a food-contact standard. "
        "Hard anodized aluminum resists corrosion. "
        "The upgraded lid stays in place while pouring hot water."
    )

    units = customer_service_service._same_sku_knowledge_evidence_units(content)

    assert units == [
        "The kettle passed a food-contact standard.",
        "Hard anodized aluminum resists corrosion.",
        "The upgraded lid stays in place while pouring hot water.",
    ]


def test_same_sku_knowledge_evidence_units_keep_indented_list_continuation_together():
    """Blank lines inside one imported list item must not drop its safety details."""
    content = (
        "4. 燃料存放：未使用完的燃料要及时密封，以防挥发。\n\n"
        "    同时存放在儿童不易接触的地方，远离火源，常温存放。"
    )

    units = customer_service_service._same_sku_knowledge_evidence_units(content)

    assert units == [
        "4. 燃料存放：未使用完的燃料要及时密封，以防挥发。\n"
        "同时存放在儿童不易接触的地方，远离火源，常温存放。"
    ]


def test_same_sku_knowledge_evidence_units_split_labelled_profile_fields():
    """A labelled product profile must not remain one multi-field RAG unit."""
    content = (
        "使用场景: 轻量徒步, 背包旅行\n"
        "目标人群: 1-2 人露营者\n"
        "容量: 大锅约3.0L, 小锅约1.7L\n"
        "尺寸: 收纳尺寸约22x21x13.5cm\n"
        "重量: 1150g\n"
        "材质: 铝合金"
    )

    units = customer_service_service._same_sku_knowledge_evidence_units(content)

    assert units == [
        "使用场景: 轻量徒步, 背包旅行",
        "目标人群: 1-2 人露营者",
        "容量: 大锅约3.0L, 小锅约1.7L",
        "尺寸: 收纳尺寸约22x21x13.5cm",
        "重量: 1150g",
        "材质: 铝合金",
    ]


def test_same_sku_comparison_selector_separates_storage_from_carrying_burden():
    """Storage RAG must not treat weight/portability marketing as storage evidence."""
    messages = customer_service_service._same_sku_knowledge_evidence_selection_messages(
        "收纳负担和打包空间怎么比？",
        "RAG-STORAGE-100",
        [
            {"index": 0, "content": "重量: 1150g"},
            {"index": 1, "content": "套娃式收纳不占空间。"},
        ],
        comparison_supplemental=True,
        comparison_excluded_fields=["weight"],
    )

    instruction = messages[0]["content"]
    assert "携带负担" in instruction
    assert "轻量化" in instruction
    assert "smallest directly useful unit" in instruction


def test_semantic_recommendation_context_keeps_meaning_without_literal_phrase_gate():
    """Semantic context is bounded by schema, not by substring matching."""
    constraints = customer_agent_planner_service._validated_recommendation_constraints(
        {"heat_sources": ["gas_stove"]}
    )
    evidence_requirements = customer_agent_planner_service._validated_recommendation_evidence_requirements(
        ["希望用气炉做饭"]
    )

    assert constraints == {"heat_sources": ["gas_stove"]}
    assert evidence_requirements == ["希望用气炉做饭"]


def test_semantic_recommendation_context_does_not_translate_one_heat_source_into_another():
    """The semantic provider's enum remains explicit; no alias gate rewrites it."""
    assert customer_agent_planner_service._validated_recommendation_constraints(
        {"heat_sources": ["card_stove"]}
    ) == {"heat_sources": ["card_stove"]}
    assert customer_agent_planner_service._validated_recommendation_constraints(
        {"heat_sources": ["unknown_stove"]}
    ) is None


def test_dishwasher_constraint_is_schema_valid_without_literal_provenance():
    """A typed preference is not discarded just because wording was paraphrased."""
    assert customer_agent_planner_service._validated_recommendation_constraints(
        {"dishwasher_safe": True}
    ) == {"dishwasher_safe": True}
    assert customer_agent_planner_service._validated_recommendation_soft_preferences(
        ["优先推荐好清洁的"]
    ) == ["优先推荐好清洁的"]


def test_weight_evidence_fails_closed_for_physically_conflicting_high_capacity_value():
    """A gram-column value must not be unit-guessed when it conflicts with scale."""
    high_capacity = '[{"label":"capacity","value":"30L","unit":""}]'

    assert customer_service_service._weight_field_evidence(1.74, capacity=high_capacity) == ""
    assert customer_service_service._weight_field_evidence(1.74, capacity='[{"value":"1.2L"}]') == "1.74g"


def test_output_evidence_includes_same_sku_field_qa_that_supports_answer():
    """Visible evidence must include the same-SKU QA actually used for a field answer."""
    result = {
        "answer_type": "product_detail",
        "answer": "灵巧包（AC-Z14）的重量约为1.74kg。",
        "results": [{"sku": "AC-Z14", "capacity": "30L"}],
        "evidence": [{"sku": "AC-Z14", "field_label": "容量", "value": "30L"}],
        "answer_metadata": {
            "answer_policy": "field_only",
            "evidence_field": "weight",
            "evidence_value": "灵巧包重量约为1.74kg。",
            "evidence_sku": "AC-Z14",
            "evidence_source": "product_qa:qa-weight-1",
        },
    }

    shaped = customer_service_service._shape_answer_for_output(result)

    assert any(
        item.get("sku") == "AC-Z14"
        and item.get("source_type") == "product_qa"
        and item.get("field_label") == "重量"
        and "1.74kg" in item.get("evidence_text", "")
        for item in shaped["evidence"]
    ), shaped["evidence"]
    assert all(item.get("field_label") != "容量" for item in shaped["evidence"]), shaped["evidence"]


def test_same_sku_rag_output_hides_unrelated_product_row_evidence():
    """A RAG answer must display its selected knowledge evidence, not a generic row summary."""
    result = {
        "answer_type": "product_detail",
        "answer": "A grounded overview.",
        "results": [{"sku": "RAG-100", "category": "tableware"}],
        "evidence": [
            {"sku": "RAG-100", "source_type": "knowledge_chunks", "content": "Verified portable benefit."},
            {"sku": "RAG-100", "field_label": "category", "value": "tableware"},
        ],
        "answer_metadata": {
            "contract_field_type": "product_qa",
            "evidence_status": "matched",
            "evidence_sku": "RAG-100",
            "evidence_source": "same_sku_knowledge",
        },
    }

    shaped = customer_service_service._shape_answer_for_output(result)

    assert [item.get("source_type") for item in shaped["evidence"]] == ["knowledge_chunks"], shaped["evidence"]


def test_product_qa_output_keeps_one_same_sku_qa_and_hides_generic_row_evidence():
    """A direct product-QA answer must not duplicate QA or expose an unrelated category row."""
    qa_value = "Verified durability guidance."
    result = {
        "answer_type": "product_detail",
        "answer": qa_value,
        "results": [{"sku": "QA-100", "category": "accessory"}],
        "evidence": [
            {"sku": "QA-100", "source_type": "product_qa", "field_label": "product_qa", "value": qa_value},
            {"sku": "QA-100", "source_type": "product_qa", "field_label": "产品 QA", "value": qa_value},
            {"sku": "QA-100", "field_label": "category", "value": "accessory"},
        ],
        "answer_metadata": {
            "contract_field_type": "product_qa",
            "evidence_status": "matched",
            "evidence_sku": "QA-100",
            "evidence_source": "product_qa:qa-100",
        },
    }

    shaped = customer_service_service._shape_answer_for_output(result)

    assert len(shaped["evidence"]) == 1, shaped["evidence"]
    assert shaped["evidence"][0].get("source_type") == "product_qa", shaped["evidence"]
    assert shaped["evidence"][0].get("sku") == "QA-100", shaped["evidence"]


def test_safe_missing_formal_field_hides_unrelated_product_row_evidence():
    """A safe missing shipping answer must not display the product category as proof."""
    result = {
        "answer_type": "product_detail",
        "answer": "Shipping details are not recorded.",
        "results": [{"sku": "SHIP-100", "category": "cookware"}],
        "evidence": [{"sku": "SHIP-100", "field_label": "category", "value": "cookware"}],
        "answer_metadata": {
            "contract_field_type": "shipping",
            "evidence_status": "missing",
            "evidence_value": "",
            "evidence_sku": None,
        },
    }

    shaped = customer_service_service._shape_answer_for_output(result)

    assert shaped["evidence"] == []


def test_same_sku_rag_accessories_uses_semantic_component_evidence_without_package_keyword(monkeypatch):
    """A natural component description must not be blocked by a package-word gate."""
    safe_missing = {
        "sku": "RAG-ACCESSORIES-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [{
        "sku": "RAG-ACCESSORIES-100",
        "content": "组件：锅、碗、勺、铲等10件配件。",
    }]
    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        return '{"answer":"资料记录包含锅、碗、勺、铲等10件配件。","evidence_quotes":["锅、碗、勺、铲等10件配件"]}'

    async def grounded(*_args, **_kwargs):
        return True

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "How many cups are included?",
            {"semantic_preplan": {"canonical_fields": ["accessories"]}},
        )
    )

    assert result is not None
    assert result["answer"] == "资料记录包含锅、碗、勺、铲等10件配件。"
    assert result["answer_metadata"]["evidence_status"] == "matched"
    assert result["answer_metadata"].get("retrieval_missing_reason") != "package_evidence_incomplete"


def test_same_sku_rag_broad_product_question_merges_multiple_selected_evidence(monkeypatch):
    """A broad product-QA question must not be reduced to one related chunk."""
    safe_missing = {
        "sku": "RAG-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": "RAG-100", "content": "Core benefit: compact and safe."},
        {"sku": "RAG-100", "content": "Usage scene: camping and travel."},
        {"sku": "RAG-100", "content": "Weight: 280g."},
    ]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        prompt = messages[-1]["content"]
        if '"candidates"' in prompt:
            return '{"indexes":[0,1],"confidence":"high","identity_consistent":true}'
        return '{"answer":"Compact and safe for camping and travel.","evidence_quotes":["compact and safe","camping and travel"]}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I know before taking this product camping?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    selected_values = "\n".join(item["value"] for item in result["evidence"])
    assert "Core benefit" in selected_values
    assert "Usage scene" in selected_values
    assert "Weight" not in selected_values
    assert result["debug"]["knowledge_evidence_selector"]["selected_count"] == 2


def test_same_sku_rag_semantic_selection_is_not_repeated_for_a_large_narrow_packet(monkeypatch):
    """A semantic selector owns packet breadth; a local item-count retry is unnecessary."""
    safe_missing = {
        "sku": "RAG-LARGE-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": "RAG-LARGE-100", "content": f"Direct fact {index}."}
        for index in range(7)
    ]
    selection_calls = 0

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal selection_calls
        prompt = messages[-1]["content"]
        if '"candidates"' in prompt:
            selection_calls += 1
            return json.dumps({
                "indexes": list(range(7)),
                "confidence": "high",
                "identity_consistent": True,
                "coverage": "full",
            })
        return json.dumps({
            "answer": "资料记录了这七项事实。",
            "evidence_quotes": ["Direct fact 0."],
        })

    async def grounded(*_args, **_kwargs):
        return True

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I know about this product?",
            {"semantic_preplan": {"qa_evidence_query": "What direct facts are recorded?"}},
        )
    )

    assert result is not None
    assert selection_calls == 1
    assert result["debug"]["knowledge_evidence_selector"]["selected_count"] == 7


def test_same_sku_selector_exposes_source_provenance_for_conflicting_numeric_values():
    """Flash must see provenance when same-SKU records disagree numerically."""
    messages = customer_service_service._same_sku_knowledge_evidence_selection_messages(
        "CW-S10-1 容量是多少？",
        "CW-S10-1",
        [
            {
                "index": 0,
                "content": "锅：1400ML",
                "source_type": "knowledge_chunk",
                "source_section": "profile",
            },
            {
                "index": 1,
                "content": "1.1.4L大容量满足双人需求",
                "source_type": "product_qa",
                "source_section": "qa:technical_advantage",
            },
        ],
        product_identity={"sku": "CW-S10-1", "canonical_name": "激川单锅", "category": "锅具"},
    )

    payload = json.loads(messages[1]["content"])

    assert payload["candidates"][0]["source_type"] == "knowledge_chunk"
    assert payload["candidates"][0]["source_section"] == "profile"
    assert payload["candidates"][1]["source_type"] == "product_qa"
    assert payload["candidates"][1]["source_section"] == "qa:technical_advantage"
    assert "incompatible numeric values" in messages[0]["content"]
    assert "direct specification or direct field QA" in messages[0]["content"]


def test_conflicted_formal_field_keeps_explicit_same_sku_rag_evidence_available():
    instruction = customer_service_service._same_sku_conflicted_formal_fields_instruction(
        ["heat_source"]
    )

    assert "not a ban on every same-SKU RAG statement" in instruction
    assert "usage instruction" in instruction
    assert "do not silently choose one" in instruction
    assert "Reject a candidate that only implies" in instruction


def test_same_sku_rag_repairs_conflicting_capacity_without_repeating_secondary_number(monkeypatch):
    """A conflicting QA rendering must be repaired semantically, not dropped."""
    sku = "CW-S10-1"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "results": [{"sku": sku, "product_name_cn": "激川单锅", "category": "锅具"}],
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {
            "sku": sku,
            "content": "锅：1400ML",
            "metadata": {"section": "profile"},
        },
        {
            "sku": sku,
            "content": "1.1.4L大容量满足双人需求",
            "metadata": {"section": "qa:technical_advantage"},
        },
    ]
    captured: dict[str, dict] = {}

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, purpose, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if purpose == "semantic_product_knowledge_evidence_selection":
            return '{"indexes":[0,1],"confidence":"high","identity_consistent":true}'
        captured[purpose] = payload
        if purpose == "sealed_same_sku_knowledge_answer":
            return json.dumps({
                "answer": "容量为1400ML，1.1.4L大容量满足双人需求。",
                "evidence_quotes": ["锅：1400ML", "满足双人需求"],
            }, ensure_ascii=False)
        if purpose == "sealed_same_sku_knowledge_answer_repair":
            return json.dumps({
                "answer": "容量为1400ML，资料描述满足双人需求。",
                "evidence_quotes": ["锅：1400ML", "满足双人需求"],
            }, ensure_ascii=False)
        raise AssertionError(f"unexpected LLM purpose: {purpose}")

    async def grounded(_db, _question, answer, _payload, _evidence):
        return "1.1.4L" not in answer

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(
        customer_service_service.knowledge_service,
        "same_sku_customer_context",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "CW-S10-1 容量是多少？",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer"] == "容量为1400ML，资料描述满足双人需求。"
    assert "1.1.4L" not in result["answer"]
    provenance = captured["sealed_same_sku_knowledge_answer"]["evidence_provenance"]
    repair_provenance = captured["sealed_same_sku_knowledge_answer_repair"]["evidence_provenance"]
    assert [(item["source_type"], item["source_section"]) for item in provenance] == [
        ("knowledge_chunk", "profile"),
        ("product_qa", "qa:technical_advantage"),
    ]
    assert repair_provenance == provenance
    assert result["answer_metadata"]["evidence_status"] == "matched"


def test_same_sku_rag_marketing_claim_is_downgraded_to_safe_missing(monkeypatch):
    """A grounded same-SKU chunk cannot authorize unsupported gifting claims."""
    sku = "RAG-GIFT-100"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "evidence": [],
        "sources": [],
        "answer_metadata": {
            "contract_field_type": "product_qa",
            "evidence_status": "missing",
            "field_evidence_missing": True,
            "evidence_skus": [],
        },
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
        "skip_polish": True,
    }
    rows = [{
        "sku": sku,
        "content": "产品资料：包装精美、品质出众，是送给户外露营爱好者的绝佳礼物。",
    }]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **kwargs):
        if kwargs.get("purpose") == "semantic_product_knowledge_evidence_selection":
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        return json.dumps({
            "answer": "品质出众、包装精美，非常适合作为礼物。",
            "evidence_quotes": ["包装精美、品质出众，是送给户外露营爱好者的绝佳礼物"],
        }, ensure_ascii=False)

    async def grounded(*_args, **_kwargs):
        return True

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_is_grounded_after_quote_validation", grounded)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "饭盒（黑色盖子+硬质氧化铝身）品质出众吗？",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert "品质出众" not in result["answer"]
    assert "包装精美" not in result["answer"]
    assert "适合作为礼物" not in result["answer"]
    assert result["evidence"] == []
    assert result["sources"] == []
    assert result["answer_metadata"]["evidence_status"] == "missing"
    assert result["answer_metadata"]["field_evidence_missing"] is True
    assert result["debug"]["agent_mode"] == "sealed_product_qa_safe_missing"
    assert result["skip_polish"] is True


def test_same_sku_rag_uses_medium_semantic_selection_only_after_grounding(monkeypatch):
    """A cautious semantic selector must not turn relevant same-SKU evidence
    into a false missing answer when the downstream grounding gate approves it.

    The selector still chooses the evidence semantically; this only permits a
    medium-confidence, nonempty selection to proceed to generation and the
    independent grounding verifier rather than treating it as a product fact.
    """
    safe_missing = {
        "sku": "RAG-MEDIUM-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": "RAG-MEDIUM-100", "content": "Core trait: compact and easy to carry."},
        {"sku": "RAG-MEDIUM-100", "content": "Use scene: camping and self-drive trips."},
    ]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0,1],"confidence":"medium","identity_consistent":true}'
        return '{"answer":"Compact and convenient for camping trips.","evidence_quotes":["compact and easy to carry","camping and self-drive trips"]}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I consider before taking this product camping?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer"] == "Compact and convenient for camping trips."
    assert result["debug"]["knowledge_evidence_selector"]["selected_count"] == 2


def test_same_sku_rag_generation_uses_semantically_selected_broad_evidence(monkeypatch):
    """A selected same-SKU overview must not become missing merely by wording mismatch."""
    safe_missing = {
        "sku": "RAG-OVERVIEW-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": "RAG-OVERVIEW-100", "content": "Core traits: portable and simple to operate."},
        {"sku": "RAG-OVERVIEW-100", "content": "Usage scenes: camping and outdoor heating."},
    ]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0,1],"confidence":"high","identity_consistent":true}'
        if "upstream semantic selector has already accepted" in messages[0]["content"]:
            assert "decision-support factors" in messages[0]["content"]
            assert "A listed target audience never excludes an unlisted audience" in messages[0]["content"]
            return '{"answer":"It is portable, simple to operate, and suited to camping and outdoor heating.","evidence_quotes":["portable and simple to operate","camping and outdoor heating"]}'
        return '{"answer":"NO_EVIDENCE"}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I keep in mind when preparing this product for an outing?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer_metadata"]["evidence_status"] == "matched"
    assert result["answer_metadata"]["evidence_bundle_skus"] == ["RAG-OVERVIEW-100"]
    assert result["evidence"][0]["evidence_id"].startswith("knowledge:")
    assert result["evidence"][0]["sku"] == "RAG-OVERVIEW-100"
    assert result["debug"]["agent_mode"] == "sealed_same_sku_knowledge_rag"


def test_same_sku_rag_retrieval_keeps_semantically_relevant_lower_ranked_evidence(monkeypatch):
    """Same-SKU retrieval should leave enough candidates for the semantic
    selector when a natural paraphrase ranks the useful file chunk below five.
    """
    sku = "RAG-RECALL-100"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": sku, "content": f"Unrelated same-SKU fact {index}."}
        for index in range(10)
    ]
    rows.append({
        "sku": sku,
        "content": "Withstands 32\u00b0F to 140\u00b0F temperatures.",
    })
    observed_limits = []

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **kwargs):
        limit = int(kwargs["limit"])
        observed_limits.append(limit)
        return rows[:limit]

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            assert "explicit numeric operating boundary" in messages[0]["content"]
            selected = [
                candidate["index"]
                for candidate in payload["candidates"]
                if "140\u00b0F" in candidate["content"]
            ]
            return json.dumps({
                "indexes": selected,
                "identity_consistent": True,
                "confidence": "high" if selected else "low",
            })
        assert "transparent conservative reasoning from an explicit numeric boundary" in messages[0]["content"]
        assert "never answer with cannot, impossible, or unsafe" in messages[0]["content"]
        return json.dumps({
            "answer": "\u8be5\u6c34\u888b\u8010\u6e29\u4e0a\u9650\u4e3a140\u00b0F\uff0c\u4e0d\u80fd\u76f4\u63a5\u704c\u6cb8\u6c34\u3002",
            "evidence_quotes": ["32\u00b0F to 140\u00b0F"],
        }, ensure_ascii=False)

    async def grounded(*_args, **_kwargs):
        return True

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "\u8fd9\u4e2a\u6c34\u888b\u80fd\u4e0d\u80fd\u76f4\u63a5\u704c\u521a\u716e\u5f00\u7684\u6c34\uff1f",
            {"semantic_preplan": {"qa_evidence_query": "\u80fd\u5426\u76f4\u63a5\u704c\u6cb8\u6c34"}},
        )
    )

    assert observed_limits == [12]
    assert result is not None
    assert "140\u00b0F" in result["answer"]
    assert result["answer_metadata"]["semantic_answer_coverage_complete"] is True
    assert result["debug"]["agent_mode"] == "sealed_same_sku_knowledge_rag"


def test_strict_rag_grounding_allows_standard_threshold_normalization_for_numeric_boundaries():
    messages = customer_service_service._same_sku_knowledge_strict_entailment_messages(
        "这个容器能直接装刚煮开的水吗？",
        "资料记录的耐温上限为140°F（60°C），刚煮开的水超出该上限，因此不建议直接灌入。",
        "Withstands 32°F to 140°F temperatures.",
    )

    system = messages[0]["content"]
    assert "universally defined physical threshold" in system
    assert "standard measurement needed for that boundary comparison" in system
    assert "beyond this narrow threshold normalization" in system
    assert "Example that must return grounded=true" in system


def test_same_sku_rag_does_not_retry_a_low_confidence_evidence_selection(monkeypatch):
    sku = "RAG-SELECT-RETRY"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    selector_calls = 0

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return [
            {"sku": sku, "content": "Unrelated same-SKU fact."},
            {"sku": sku, "content": "Recorded operating range: 32\u00b0F to 140\u00b0F."},
        ]

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal selector_calls
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            selector_calls += 1
            if selector_calls == 1:
                return '{"indexes":[],"confidence":"low","identity_consistent":false}'
            return '{"indexes":[1],"confidence":"high","identity_consistent":true}'
        return json.dumps({
            "answer": "\u8bb0\u5f55\u8010\u6e29\u4e0a\u9650\u4e3a140\u00b0F\uff0c\u6cb8\u6c34\u8d85\u51fa\u8be5\u8303\u56f4\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u704c\u88c5\u3002",
            "evidence_quotes": ["32\u00b0F to 140\u00b0F"],
        }, ensure_ascii=False)

    async def approved(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", approved)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", approved)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "\u80fd\u4e0d\u80fd\u76f4\u63a5\u704c\u6cb8\u6c34\uff1f",
            {"semantic_preplan": {"qa_evidence_query": "\u76f4\u63a5\u704c\u6cb8\u6c34"}},
        )
    )

    assert selector_calls == 1
    assert result is not None
    assert result["answer_metadata"]["retrieval_missing_reason"] == "evidence_selection_not_usable"


def test_same_sku_structured_best_effort_answers_only_from_selected_evidence(monkeypatch):
    product = SimpleNamespace(
        sku="BEST-100",
        product_name_cn="测试套锅",
        product_name_en="",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda *_args, **_kwargs: (product, None, None, None),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **_kwargs: (
            ("1-2人露营者", "business.target_audience")
            if field == "target_audience"
            else ("", None)
        ),
    )
    evidence_id = customer_service_service.customer_evidence_bundle.stable_customer_evidence_id(
        namespace="structured",
        sku="BEST-100",
        value="target_audience|1-2人露营者",
    )

    async def fake_completion(*_args, **_kwargs):
        return json.dumps({
            "answer": "这款适合两人出行。",
            "evidence_ids": [evidence_id],
            "evidence_quotes": ["1-2人露营者"],
        }, ensure_ascii=False)

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_same_sku_structured_best_effort_answer(
            SimpleNamespace(),
            question="这款两个人出行够用吗？",
            safe_missing={
                "result_skus": ["BEST-100"],
                "results": [{"sku": "BEST-100", "product_name_cn": "测试套锅"}],
                "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
            },
            semantic_preplan={"evidence_kind": "product_qa"},
        )
    )

    assert result is not None
    assert result["answer"] == "这款适合两人出行。"
    assert result["result_skus"] == ["BEST-100"]
    assert result["evidence"][0]["sku"] == "BEST-100"
    assert result["debug"]["agent_mode"] == "sealed_same_sku_structured_best_effort"


def test_same_sku_structured_best_effort_accepts_labelled_literal_quote(monkeypatch):
    product = SimpleNamespace(
        sku="BEST-101",
        product_name_cn="测试单锅",
        product_name_en="",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda *_args, **_kwargs: (product, None, None, None),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **_kwargs: (
            ("锅：1400ML", "specs.capacity")
            if field == "capacity"
            else ("", None)
        ),
    )
    evidence_id = customer_service_service.customer_evidence_bundle.stable_customer_evidence_id(
        namespace="structured",
        sku="BEST-101",
        value="capacity|锅：1400ML",
    )

    async def fake_completion(*_args, **_kwargs):
        return json.dumps({
            "answer": "容量为1400ML。",
            "evidence_ids": [evidence_id],
            "evidence_quotes": ["容量：锅：1400ML"],
        }, ensure_ascii=False)

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_completion,
    )
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_same_sku_structured_best_effort_answer(
            SimpleNamespace(),
            question="这款容量多少？",
            safe_missing={
                "result_skus": ["BEST-101"],
                "results": [{"sku": "BEST-101", "product_name_cn": "测试单锅"}],
                "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
            },
            semantic_preplan={"evidence_kind": "product_qa"},
        )
    )

    assert result is not None
    assert result["answer"] == "容量为1400ML。"


def test_same_sku_structured_best_effort_accepts_natural_answer_without_quote(monkeypatch):
    product = SimpleNamespace(
        sku="BEST-102",
        product_name_cn="测试单锅",
        product_name_en="",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda *_args, **_kwargs: (product, None, None, None),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **_kwargs: (
            ("1400ML", "specs.capacity")
            if field == "capacity"
            else ("", None)
        ),
    )
    evidence_id = customer_service_service.customer_evidence_bundle.stable_customer_evidence_id(
        namespace="structured",
        sku="BEST-102",
        value="capacity|1400ML",
    )

    async def fake_completion(*_args, **_kwargs):
        return json.dumps({
            "answer": "这款容量是1400ML。",
            "evidence_ids": [evidence_id],
            "evidence_quotes": [],
        }, ensure_ascii=False)

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_same_sku_structured_best_effort_answer(
            SimpleNamespace(),
            question="这款容量多少？",
            safe_missing={
                "result_skus": ["BEST-102"],
                "results": [{"sku": "BEST-102", "product_name_cn": "测试单锅"}],
                "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
            },
            semantic_preplan={"evidence_kind": "product_qa"},
        )
    )

    assert result is not None
    assert result["answer"] == "这款容量是1400ML。"


def test_same_sku_structured_best_effort_rejects_adjacent_evidence(monkeypatch):
    product = SimpleNamespace(
        sku="BEST-200",
        product_name_cn="测试磨豆器",
        product_name_en="",
    )
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_product_bundle_by_ref",
        lambda *_args, **_kwargs: (product, None, None, None),
    )
    monkeypatch.setattr(
        customer_service_service,
        "_structured_product_field_evidence",
        lambda field, **_kwargs: (
            ("不锈钢", "specs.material")
            if field == "material"
            else ("", None)
        ),
    )

    async def fake_completion(*_args, **_kwargs):
        return json.dumps({
            "answer": "NO_EVIDENCE",
            "evidence_ids": [],
            "evidence_quotes": [],
        })

    monkeypatch.setattr(
        customer_service_service.customer_llm_service,
        "chat_completion",
        fake_completion,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_same_sku_structured_best_effort_answer(
            SimpleNamespace(),
            question="这款手摇起来费力吗？",
            safe_missing={
                "sku": "BEST-200",
                "result_skus": ["BEST-200"],
                "results": [{"sku": "BEST-200", "product_name_cn": "测试磨豆器"}],
                "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
            },
            semantic_preplan={"evidence_kind": "product_qa"},
        )
    )

    assert result is None


def test_same_sku_rag_keeps_supported_part_of_a_compound_question(monkeypatch):
    """One unverified sub-question must not erase another sealed product fact."""
    safe_missing = {
        "sku": "RAG-PARTIAL-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [{"sku": "RAG-PARTIAL-100", "content": "Grinding coarseness can be adjusted."}]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        if "Answer only the parts directly supported" in messages[0]["content"]:
            return '{"answer":"Grinding coarseness can be adjusted.","evidence_quotes":["Grinding coarseness can be adjusted"]}'
        return '{"answer":"NO_EVIDENCE"}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
            customer_service_service._try_sealed_same_sku_knowledge_answer(
                SimpleNamespace(),
                "Can it adjust grinding coarseness, and can it heat a drink?",
                {"semantic_preplan": {"compound": True, "additional_user_intent": False}},
            )
        )

    assert result is not None
    assert "Grinding coarseness can be adjusted" in result["answer"]
    assert "does not directly confirm heating" not in result["answer"]


def test_same_sku_rag_repairs_grounded_draft_that_omits_a_compound_part(monkeypatch):
    """A factual RAG draft still fails when it silently drops an independent question part."""
    safe_missing = {
        "sku": "RAG-COVERAGE-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [{"sku": "RAG-COVERAGE-100", "content": "Avoid rapid hot/cold changes."}]
    coverage_calls = 0

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal coverage_calls
        payload = json.loads(messages[-1]["content"])
        instruction = messages[0]["content"]
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        if "coverage auditor" in instruction:
            coverage_calls += 1
            return '{"complete":false}' if coverage_calls == 1 else '{"complete":true}'
        if "complete every independently requested part" in instruction.lower():
            return json.dumps({
                "answer": (
                    "Avoid rapid hot/cold changes. The supplied evidence does not directly confirm "
                    "whether it can sterilize baby bottles."
                ),
                "evidence_quotes": ["Avoid rapid hot/cold changes."],
            })
        return json.dumps({
            "answer": "Avoid rapid hot/cold changes.",
            "evidence_quotes": ["Avoid rapid hot/cold changes."],
        })

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "Which operations should I avoid, and can it sterilize baby bottles?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert "Avoid rapid hot/cold changes" in result["answer"]
    assert "does not directly confirm whether it can sterilize baby bottles" in result["answer"]
    assert coverage_calls == 2


def test_same_sku_qa_selector_rejects_single_property_for_broad_product_decision(monkeypatch):
    """One narrow QA cannot claim full coverage of a product-overview decision question."""
    qa = SimpleNamespace(
        id="qa-scene",
        question="Which scenarios is it suitable for?",
        answer="Camping and travel.",
        tags="",
        priority=1,
        updated_at=None,
    )

    class Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return [qa]

    class Db:
        def query(self, *_args):
            return Query()

    async def fake_completion(_db, *, messages, **_kwargs):
        instruction = messages[0]["content"]
        if "single-property QA cannot have full coverage" in instruction:
            return '{"qa_id":null,"coverage":"none","confidence":"high"}'
        return '{"qa_id":"qa-scene","coverage":"full","confidence":"high"}'

    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)

    import asyncio

    selected = asyncio.run(
        customer_service_service._select_same_sku_product_qa_with_semantic_selection(
            Db(),
            SimpleNamespace(id="product-1", product_name_cn="Example cookware", product_name_en=""),
            "What information should I consider before deciding whether this product suits a weekend trip?",
            semantic_query="product weekend trip decision-support overview",
            subject_text="Example cookware",
        )
    )

    assert selected is None


def test_same_sku_knowledge_selection_messages_require_direct_semantic_relevance():
    """Same-SKU identity must not make off-question knowledge admissible for RAG."""
    messages = customer_service_service._same_sku_knowledge_evidence_selection_messages(
        "What product facts matter when deciding whether this item suits a camping trip?",
        "RAG-100",
        [{"index": 0, "content": "Product feature: compact."}],
        product_identity={"sku": "RAG-100", "canonical_name": "Camping kettle", "category": "cookware"},
    )

    system_instruction = messages[0]["content"]
    payload = json.loads(messages[1]["content"])

    assert "Same-SKU identity alone is insufficient" in system_instruction
    assert "directly respond to the customer's intended question" in system_instruction
    assert "first-use" in system_instruction
    assert "comparison" in system_instruction
    assert "product_identity" in system_instruction
    assert "different device" in system_instruction
    assert payload["sku"] == "RAG-100"
    assert payload["product_identity"]["canonical_name"] == "Camping kettle"
    assert payload["candidates"] == [{"index": 0, "content": "Product feature: compact."}]


def test_same_sku_knowledge_grounding_messages_validate_faithfulness_without_redeciding_selection():
    """The semantic selector owns question relevance; grounding owns whether
    the drafted customer facts remain faithful to selected same-SKU evidence."""
    messages = customer_service_service._same_sku_knowledge_grounding_messages(
        "What should I consider before taking this product camping?",
        "Compact and easy to store for camping.",
        "Core benefit: compact for camping.",
    )

    system_instruction = messages[0]["content"]
    payload = json.loads(messages[1]["content"])

    assert "do not override the upstream semantic evidence selection" in system_instruction.lower()
    assert "do not require the answer to exhaust every possible product consideration" in system_instruction.lower()
    assert payload["answer"] == "Compact and easy to store for camping."


def test_same_sku_knowledge_grounding_treats_subject_descriptors_as_identity_not_unmet_conditions():
    """A product title can contain compatibility/version text without making it
    an additional capability the broad current question must re-prove.

    The semantic selector already chooses the same-SKU evidence for the actual
    question. Grounding must validate the generated facts, not reject a useful
    overview merely because an identity descriptor appears in the subject span.
    """
    messages = customer_service_service._same_sku_knowledge_grounding_messages(
        "Before taking the long-canister adapter on an outing, what should I know?",
        "It converts the gas-canister interface, works with cassette canisters, and is simple to install.",
        "Core points: converts the gas-canister interface; compatible with cassette canisters; simple installation.",
    )

    system_instruction = messages[0]["content"].lower()

    assert "identity context" in system_instruction
    assert "not independent unanswered customer conditions" in system_instruction


def test_same_sku_knowledge_grounding_payload_keeps_question_for_claim_entailment_only():
    """Grounding needs the customer condition to reject an adjacent-evidence inference.

    The question cannot reopen route selection, identity, or evidence selection,
    but it is required to tell whether a generated conclusion (such as a
    duration or exposure claim) was actually requested and directly supported.
    """
    messages = customer_service_service._same_sku_knowledge_grounding_messages(
        "Before taking the long-canister adapter on an outing, what should I know?",
        "It converts the gas-canister interface and is simple to install.",
        "Core points: converts the gas-canister interface; simple installation.",
    )

    payload = json.loads(messages[1]["content"])

    assert "approve a claimed condition only" in messages[0]["content"].lower()
    assert payload["question"] == "Before taking the long-canister adapter on an outing, what should I know?"
    assert "semantic_focus" not in payload
    assert payload["answer"] == "It converts the gas-canister interface and is simple to install."
    assert payload["evidence"] == "Core points: converts the gas-canister interface; simple installation."


def test_same_sku_entailment_keeps_group_fit_separate_from_task_sufficiency():
    messages = customer_service_service._same_sku_knowledge_strict_entailment_messages(
        "CW-S10-1 容量够不够两个人煮面？",
        "容量为1400ML，适用1-2人，因此足够两人煮面；但具体水量仍未直接确认。",
        "容量：锅：1400ML\n目标人群：1-2 人露营者",
    )

    system_instruction = messages[0]["content"].lower()

    assert "particular food" in system_instruction
    assert "task-specific outcome" in system_instruction
    assert "grounded=false" in system_instruction
    assert "caveat cannot cancel" in system_instruction


def test_same_sku_knowledge_grounding_requires_explicit_support_for_negative_claims():
    """A missing capability is not proof that the product cannot do it."""
    messages = customer_service_service._same_sku_knowledge_grounding_messages(
        "Can this hand-operated product heat a drink?",
        "No, it cannot heat a drink.",
        "The product is hand-operated and does not need electricity.",
    )

    system_instruction = messages[0]["content"]

    assert "absence of evidence never proves a negative claim" in system_instruction.lower()


def test_same_sku_rag_reports_optional_verbatim_selected_evidence_quotes():
    """Exact excerpts remain useful provenance, but are not answer gating."""
    evidence = "Core points: vintage enamel is durable; easy to clean."

    assert customer_service_service._same_sku_rag_answer_has_selected_quotes(
        {
            "answer": "The vintage enamel is durable and easy to clean.",
            "evidence_quotes": ["vintage enamel is durable", "easy to clean"],
        },
        evidence,
    ) is True
    assert customer_service_service._same_sku_rag_answer_has_selected_quotes(
        {
            "answer": "It weighs 578g and folds for storage.",
            "evidence_quotes": ["weighs 578g", "folds for storage"],
        },
        evidence,
    ) is False


def test_same_sku_rag_delivers_a_grounded_citationless_draft(monkeypatch):
    """Natural paraphrase does not need an exact source substring to ship."""
    safe_missing = {
        "sku": "RAG-QUOTE-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    row = {"sku": "RAG-QUOTE-100", "content": "Core trait: compact for camping."}

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return [row]

    calls = 0

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal calls
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        calls += 1
        if calls == 1:
            return '{"answer":"Compact for camping."}'
        return '{"answer":"Compact for camping.","evidence_quotes":["compact for camping"]}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I consider before camping with this product?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer"] == "Compact for camping."
    assert calls == 1


def test_same_sku_rag_repairs_group_fit_upgrade_to_task_bound_answer(monkeypatch):
    """A group-fit fact must not be upgraded into a dish-specific guarantee."""
    sku = "RAG-TASK-BOUND-100"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    row = {
        "sku": sku,
        "content": "Capacity: 1400ML\nTarget audience: 1-2 campers",
    }
    repair_seen = False

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return [row]

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal repair_seen
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        if "previous_draft" in payload:
            repair_seen = True
            return json.dumps({
                "answer": (
                    "The record lists 1400ML and a 1-2-person target audience; "
                    "it does not directly confirm the water amount for two-person noodles."
                ),
                "evidence_quotes": ["Capacity: 1400ML", "Target audience: 1-2 campers"],
            })
        return json.dumps({
            "answer": (
                "The 1400ML capacity is enough for two people cooking noodles, "
                "but the exact water amount is not directly confirmed."
            ),
            "evidence_quotes": ["Capacity: 1400ML"],
        })

    async def grounded(_db, _question, answer, _payload, _evidence, **_kwargs):
        return "enough for two people cooking noodles" not in answer.lower()

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        grounded,
    )
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "CW-S10-1 capacity enough for two people cooking noodles?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert repair_seen is True
    assert "does not directly confirm" in result["answer"]
    assert "enough for two people cooking noodles" not in result["answer"].lower()


def test_same_sku_rag_does_not_repair_a_grounded_natural_paraphrase_for_quote_shape(monkeypatch):
    """A paraphrase with an imperfect receipt is still judged by grounding."""
    safe_missing = {
        "sku": "RAG-QUOTE-EXACT-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    row = {
        "sku": "RAG-QUOTE-EXACT-100",
        "content": "Core traits: folds small for travel; reusable for camping and hiking.",
    }
    repair_system_prompt = ""

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return [row]

    async def fake_completion(_db, *, messages, **_kwargs):
        nonlocal repair_system_prompt
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        if "previous_draft" not in payload:
            return (
                '{"answer":"It folds small for travel and is reusable for camping and hiking.",'
                '"evidence_quotes":["folds small for travel","camping and hiking trips"]}'
            )
        repair_system_prompt = messages[0]["content"]
        return (
            '{"answer":"It folds small for travel and is reusable for camping and hiking.",'
            '"evidence_quotes":["folds small for travel","reusable for camping and hiking"]}'
        )

    async def grounded(*_args, **_kwargs):
        return True

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)
    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I consider for travel?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer"] == "It folds small for travel and is reusable for camping and hiking."
    assert repair_system_prompt == ""


def test_same_sku_rag_rejects_one_false_grounding_verdict_after_quote_validation(monkeypatch):
    """One grounding rejection must fail closed instead of becoming a chance
    for a second stochastic verifier to approve an unsupported inference."""
    calls = 0

    async def alternating_verifier(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return calls == 2

    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_evidence_answer_is_grounded",
        alternating_verifier,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._same_sku_rag_answer_is_grounded_after_quote_validation(
            SimpleNamespace(),
            "What should I consider?",
            "Compact for camping.",
            {"evidence_quotes": ["compact for camping"]},
            "Core trait: compact for camping.",
        )
    )

    assert result is False
    assert calls == 1


def test_same_sku_rag_fails_closed_when_grounded_delivery_cannot_cover_question(monkeypatch):
    sku = "RAG-BOUNDED-REFERENCE"
    safe_missing = {
        "sku": sku,
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    rows = [
        {"sku": sku, "content": "Target audience: experienced campers."},
        {"sku": sku, "content": "Folding design for compact storage."},
    ]

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return rows

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0,1],"confidence":"high","identity_consistent":true}'
        return json.dumps({
            "answer": "It is definitely ideal for every beginner.",
            "evidence_quotes": [
                "Target audience: experienced campers.",
                "Folding design for compact storage.",
            ],
        })

    async def rejected(*_args, **_kwargs):
        return False

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.knowledge_service, "same_sku_customer_context", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(
        customer_service_service,
        "_same_sku_rag_answer_is_grounded_after_quote_validation",
        rejected,
    )

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "Is it suitable for a beginner?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["answer"] == "safe missing"
    # Delivery still fails closed, but the selected same-SKU packet remains
    # available as provenance for the semantic recovery layer instead of being
    # erased by the post-selection failure.
    assert [item["value"] for item in result.get("evidence", [])] == [
        "Target audience: experienced campers.",
        "Folding design for compact storage.",
    ]
    assert result["answer_metadata"]["evidence_status"] == "partial"
    assert result["answer_metadata"]["semantic_selected_evidence_available"] is True
    assert result["answer_metadata"]["retrieval_missing_reason"] == "answer_grounding_failed"


def test_same_sku_rag_uses_strict_entailment_as_the_claim_delivery_gate(monkeypatch):
    """The delivery gate is strict entailment, not a second relevance vote."""
    seen_kwargs: list[dict] = []

    async def grounded(*_args, **_kwargs):
        seen_kwargs.append(_kwargs)
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    import asyncio

    result = asyncio.run(
        customer_service_service._same_sku_rag_answer_is_grounded_after_quote_validation(
            SimpleNamespace(),
            "Can it remain in one environment for a full day?",
            "Yes, it can remain there for a full day.",
            {"evidence_quotes": ["operates from 32 to 140 degrees"]},
            "The product operates from 32 to 140 degrees.",
        )
    )

    assert result is True
    assert seen_kwargs == [{"strict_entailment": True}]


def test_same_sku_rag_grounding_does_not_require_an_exact_quote(monkeypatch):
    """Strict entailment, not substring shape, decides answer delivery."""
    seen: list[tuple[str, str]] = []

    async def grounded(_db, question, answer, evidence, **_kwargs):
        seen.append((question, evidence))
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    import asyncio

    result = asyncio.run(
        customer_service_service._same_sku_rag_answer_is_grounded_after_quote_validation(
            SimpleNamespace(),
            "这款适合露营吗？",
            "资料显示它便于露营携带。",
            {},
            "记录：适合露营，便于携带。",
        )
    )

    assert result is True
    assert seen == [("这款适合露营吗？", "记录：适合露营，便于携带。")]


def test_same_sku_rag_grounding_receives_the_complete_sealed_selection(monkeypatch):
    """Quotes prove provenance; strict entailment sees every selected fact."""
    seen_evidence: list[str] = []

    async def verifier(_db, _question, _answer, evidence, **_kwargs):
        seen_evidence.append(evidence)
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", verifier)

    import asyncio

    result = asyncio.run(
        customer_service_service._same_sku_rag_answer_is_grounded_after_quote_validation(
            SimpleNamespace(),
            "What should I consider?",
            "Compact for camping.",
            {"evidence_quotes": ["compact for camping"]},
            "Internal unrelated context. Core trait: compact for camping.",
        )
    )

    assert result is True
    assert seen_evidence == ["Internal unrelated context. Core trait: compact for camping."]


def test_same_sku_rag_generation_contract_bounds_provenance_output(monkeypatch):
    """The evidence provenance JSON needs a bounded shape so a useful broad
    RAG answer cannot be truncated merely by echoing every long evidence line."""
    safe_missing = {
        "sku": "RAG-BOUND-100",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    row = {"sku": "RAG-BOUND-100", "content": "Core trait: compact for camping."}
    generator_request: dict = {}

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return [row]

    async def fake_completion(_db, *, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            return '{"indexes":[0],"confidence":"high","identity_consistent":true}'
        generator_request["system"] = messages[0]["content"]
        generator_request["max_tokens"] = kwargs["max_tokens"]
        return '{"answer":"Compact for camping.","evidence_quotes":["compact for camping"]}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I consider before camping with this product?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert "at most 3" in generator_request["system"].lower()
    assert "60 characters" in generator_request["system"].lower()
    assert generator_request["max_tokens"] >= 360


def test_same_sku_rag_adds_authoritative_product_context_when_vector_top_results_are_off_question(monkeypatch):
    """A broad product turn may need the same-SKU listing beyond top vector QA hits."""
    safe_missing = {
        "sku": "RAG-200",
        "answer": "safe missing",
        "debug": {"agent_mode": "sealed_product_qa_safe_missing"},
    }
    retrieved = [
        {"sku": "RAG-200", "content": "Q: Is it authentic? A: Check the barcode."},
        {"sku": "RAG-200", "content": "Q: Does it have a warranty? A: Contact support."},
    ]
    profile = {"sku": "RAG-200", "content": "Core benefit: compact for camping."}

    monkeypatch.setattr(
        customer_service_service,
        "_sealed_semantic_product_qa_entity_guard",
        lambda *_args, **_kwargs: safe_missing.copy(),
    )

    async def fake_retrieve(*_args, **_kwargs):
        return retrieved

    def fake_profile_context(*_args, **_kwargs):
        return [profile]

    async def fake_completion(_db, *, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "candidates" in payload:
            selected = next(item for item in payload["candidates"] if item["content"] == profile["content"])
            return json.dumps({"indexes": [selected["index"]], "confidence": "high", "identity_consistent": True})
        return '{"answer":"Compact for camping.","evidence_quotes":["compact for camping"]}'

    async def grounded(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service.knowledge_service, "semantic_retrieve", fake_retrieve)
    monkeypatch.setattr(
        customer_service_service.knowledge_service,
        "same_sku_customer_context",
        fake_profile_context,
        raising=True,
    )
    monkeypatch.setattr(customer_service_service.customer_llm_service, "chat_completion", fake_completion)
    monkeypatch.setattr(customer_service_service, "_same_sku_evidence_answer_is_grounded", grounded)

    async def covered(*_args, **_kwargs):
        return True

    monkeypatch.setattr(customer_service_service, "_same_sku_rag_answer_covers_question", covered)

    import asyncio

    result = asyncio.run(
        customer_service_service._try_sealed_same_sku_knowledge_answer(
            SimpleNamespace(),
            "What should I consider before camping with this product?",
            {"semantic_preplan": {}},
        )
    )

    assert result is not None
    assert result["evidence"][0]["value"] == profile["content"]
    assert result["debug"]["knowledge_evidence_selector"]["selected_count"] == 1


def test_invalid_capacity_column_fails_closed_without_cross_field_answer(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包的容量是多少？"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    answer = str(payload.get("answer") or "")
    assert payload.get("candidate_skus") == ["FE-200"], payload
    assert payload.get("result_skus") == ["FE-200"], payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "FE-200", payload
    assert entity.get("field_type") == "capacity", payload
    assert "食品级塑料" not in answer, payload
    assert "暂未找到" in answer and "容量" in answer, payload
    assert metadata.get("contract_field_type") == "capacity", payload
    assert metadata.get("evidence_status") == "missing", payload
    assert metadata.get("evidence_sku") is None, payload


def test_specification_uses_only_valid_same_sku_components(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包的规格是什么？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["FE-200"], payload
    assert "规格" in payload["answer"], payload
    assert "尼龙" in payload["answer"], payload
    assert "食品级塑料" not in payload["answer"], payload
    assert metadata.get("evidence_status") == "structured", payload
    assert metadata.get("evidence_source") == "specification.summary", payload
    assert metadata.get("evidence_sku") == "FE-200", payload


@pytest.mark.parametrize(
    ("question", "field_type", "expected_fragment", "metadata_fragment"),
    [
        ("晨雾Plus水壶的技术优势是什么？", "technical_advantages", "快速加热", "specs.technical_advantages"),
        ("晨雾Plus水壶的竞品对标是什么？", "competitor_benchmark", "双层隔热", "business.competitor_benchmark"),
        ("晨雾Plus水壶的生命周期状态是什么？", "lifecycle_status", "常规品", "product.lifecycle_status"),
        ("晨雾Plus水壶的规格是什么？", "specification", "容量", "specification.summary"),
    ],
)
def test_customer_business_fields_use_formal_same_sku_evidence(
    field_evidence_client,
    question,
    field_type,
    expected_fragment,
    metadata_fragment,
):
    client, headers, Session = field_evidence_client
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "FE-100").one()
        specs = db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).one()
        business = db.query(ProductBusiness).filter(ProductBusiness.product_id == product.id).one()
        specs.size_info = "12 x 10 cm"
        specs.technical_advantages = "快速加热，双层隔热结构"
        business.competitor_benchmark = "相较同类单层水壶，双层隔热结构更利于握持。"
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    entity = (payload.get("debug") or {}).get("entity_resolution_contract") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert payload.get("result_skus") == ["FE-100"], payload
    assert expected_fragment in payload["answer"], payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "FE-100", payload
    assert entity.get("field_type") == field_type, payload
    assert metadata.get("contract_field_type") == field_type, payload
    assert metadata.get("evidence_field") == field_type, payload
    assert metadata.get("evidence_sku") == "FE-100", payload
    assert metadata.get("evidence_source") == metadata_fragment, payload


def test_lifecycle_status_never_claims_realtime_inventory(field_evidence_client):
    client, headers, _ = field_evidence_client

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶的生命周期状态是什么？"},
        headers=headers,
    ).json()

    assert "非实时库存" in payload["answer"], payload
    assert "是否有现货" not in payload["answer"], payload


@pytest.mark.parametrize("alias", ["SKU", "货号", "产品编码"])
def test_explicit_sku_question_uses_sku_evidence_not_selling_points(field_evidence_client, alias):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": f"晨雾Plus水壶的{alias}怎么查？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["FE-100"], payload
    assert "FE-100" in payload["answer"], payload
    assert "核心卖点" not in payload["answer"], payload
    assert metadata.get("requested_field") == "sku", payload
    assert metadata.get("evidence_field") == "sku", payload
    assert metadata.get("field_evidence_match") is True, payload


def test_weight_question_uses_weight_evidence_not_selling_points(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶本身多重，资料里有记录吗？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["FE-100"], payload
    assert "420g" in payload["answer"], payload
    assert "420.0g" not in payload["answer"], payload
    assert "核心卖点" not in payload["answer"], payload
    assert metadata.get("requested_field") == "weight", payload
    assert metadata.get("evidence_field") == "weight", payload


def test_missing_weight_rejects_selling_point_qa_and_keeps_resolved_sku(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包的重量是多少？"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    answer = str(payload.get("answer") or "")
    assert payload.get("candidate_skus") == ["FE-200"], payload
    assert payload.get("result_skus") == ["FE-200"], payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "FE-200", payload
    assert entity.get("field_type") == "weight", payload
    assert "暂未找到" in answer and "重量" in answer, payload
    assert "核心卖点" not in answer, payload
    assert metadata.get("contract_field_type") == "weight", payload
    assert metadata.get("evidence_status") == "missing", payload
    assert metadata.get("evidence_sku") is None, payload
    assert metadata.get("field_evidence_missing") is True, payload


def test_dishwasher_question_rejects_generic_usage_instruction(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶可以放洗碗机吗？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["FE-100"], payload
    assert "未标注" in payload["answer"], payload
    assert "首次使用" not in payload["answer"], payload
    assert metadata.get("contract_field_type") == "dishwasher", payload
    assert metadata.get("field_evidence_missing") is True, payload


def test_structured_dishwasher_provider_requires_explicit_dishwasher_evidence():
    product = SimpleNamespace()
    specs = SimpleNamespace(usage_instruction="首次使用前用清水冲洗，使用后擦干并通风存放。")

    value, source = customer_service_service._structured_product_field_evidence(
        "dishwasher",
        db=None,
        product=product,
        specs=specs,
        business=None,
        content=None,
    )

    assert value == ""
    assert source is None


def test_heat_source_fallback_rejects_unrelated_selling_points():
    product = SimpleNamespace()
    specs = SimpleNamespace(heat_source="/")
    business = SimpleNamespace(top_selling_points="大容量储水，双水龙头设计，便携易收纳")

    value, source = customer_service_service._structured_product_field_evidence(
        "heat_source",
        db=None,
        product=product,
        specs=specs,
        business=business,
        content=None,
    )

    assert value == ""
    assert source is None


def test_field_display_value_removes_only_a_repeated_leading_field_label():
    assert customer_service_service._field_display_value("材质", "材质：磨毛春亚纺，铝膜") == "磨毛春亚纺，铝膜"
    assert customer_service_service._field_display_value("材质", "铝膜材质，耐磨") == "铝膜材质，耐磨"


def test_cleaning_question_rejects_unrelated_usage_instruction(field_evidence_client):
    client, headers, Session = field_evidence_client
    with Session() as db:
        product_id = db.query(Product.id).filter(Product.sku == "FE-200").scalar()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == product_id).update(
            {"usage_instruction": "避免明火直烧，远离高温物体。"}
        )
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包怎么清洁？"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    answer = str(payload.get("answer") or "")
    assert payload.get("candidate_skus") == ["FE-200"], payload
    assert payload.get("result_skus") == ["FE-200"], payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "FE-200", payload
    assert entity.get("field_type") == "cleaning", payload
    assert "暂未找到" in answer and "清洁" in answer, payload
    assert "明火直烧" not in answer, payload
    assert metadata.get("contract_field_type") == "cleaning", payload
    assert metadata.get("evidence_status") == "missing", payload
    assert metadata.get("evidence_sku") is None, payload
    assert metadata.get("field_evidence_missing") is True, payload


def test_cleaning_and_care_select_distinct_clauses_from_shared_instruction(field_evidence_client):
    client, headers, _ = field_evidence_client

    cleaning = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶怎么清洁？"},
        headers=headers,
    ).json()
    care = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶怎么保养？"},
        headers=headers,
    ).json()

    assert "清水冲洗" in cleaning["answer"], cleaning
    assert "通风存放" not in cleaning["answer"], cleaning
    assert "擦干" in care["answer"], care
    assert "通风存放" in care["answer"], care
    assert "清水冲洗" not in care["answer"], care
    for payload, field in ((cleaning, "cleaning"), (care, "care")):
        metadata = payload.get("answer_metadata") or {}
        assert payload.get("result_skus") == ["FE-100"], payload
        assert metadata.get("contract_field_type") == field, payload
        assert metadata.get("evidence_sku") == "FE-100", payload


def test_subject_dimension_rejects_component_and_package_evidence(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包的主体尺寸是多少？"},
        headers=headers,
    ).json()

    assert payload.get("result_skus") == ["FE-200"], payload
    assert "42 x 30 x 8" not in payload["answer"], payload
    assert "40 x 28 x 7" not in payload["answer"], payload
    assert (payload.get("answer_metadata") or {}).get("field_evidence_missing") is True, payload


def test_package_dimension_allows_package_evidence(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "星海收纳包的包装尺寸是多少？"},
        headers=headers,
    ).json()

    assert payload.get("result_skus") == ["FE-200"], payload
    assert "42 x 30 x 8" in payload["answer"], payload
    assert (payload.get("answer_metadata") or {}).get("evidence_scope") == "package", payload


def test_expanded_dimension_rejects_generic_dimension_qa(field_evidence_client):
    client, headers, Session = field_evidence_client
    with Session() as db:
        _add_product_qa(
            db,
            "FE-100",
            "晨雾Plus水壶的尺寸是多少？",
            "12 x 10 cm。",
            priority=300,
        )
        product_id = db.query(Product.id).filter(Product.sku == "FE-100").scalar()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == product_id).update({"size_info": ""})
        db.commit()

    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶的展开尺寸是多少？"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["FE-100"], payload
    assert "12 x 10" not in payload["answer"], payload
    assert metadata.get("contract_field_type") == "dimensions", payload
    assert metadata.get("field_evidence_missing") is True, payload


def test_generic_selling_point_question_uses_resolved_detail_contract(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶有什么核心卖点？"},
        headers=headers,
    ).json()

    assert "核心卖点" in payload["answer"], payload
    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "FE-100", payload
    assert entity.get("field_type") == "selling_point", payload
    assert payload.get("candidate_skus") == ["FE-100"], payload
    assert payload.get("result_skus") == ["FE-100"], payload
    metadata = payload.get("answer_metadata") or {}
    assert metadata.get("contract_field_type") == "selling_point", payload
    # Selling points have a formal structured evidence policy.  Do not force
    # this resolved detail path back through the legacy QA shortcut merely to
    # satisfy an obsolete source label expectation.
    assert metadata.get("evidence_source") == "business.top_selling_points", payload
    assert metadata.get("evidence_sku") == "FE-100", payload


def test_final_guard_replaces_mismatched_evidence_with_missing_field_result(field_evidence_client):
    _, _, Session = field_evidence_client
    with Session() as db:
        result = customer_service_service._enforce_field_evidence_policy(
            db,
            "晨雾Plus水壶的尺寸是多少？",
            {
                "intent": "product_detail",
                "answer_type": "product_detail",
                "answer": "晨雾Plus水壶的核心卖点是快速加热。",
                "result_skus": ["FE-100"],
                "candidate_skus": ["FE-100"],
                "results": [{"sku": "FE-100"}],
                "evidence": [{"sku": "FE-100", "field_label": "核心卖点", "value": "快速加热"}],
                "answer_metadata": {"requested_field": "dimensions", "evidence_field": "selling_points"},
                "debug": {},
            },
        )

    assert "核心卖点" not in result["answer"]
    assert result.get("result_skus") == ["FE-100"]
    assert result.get("answer_metadata", {}).get("field_evidence_missing") is True


def test_final_guard_preserves_same_sku_shipping_qa_evidence(field_evidence_client):
    _, _, Session = field_evidence_client
    with Session() as db:
        original = {
            "intent": "product_detail",
            "answer_type": "product_detail",
            "answer": "Default carrier is verified by the order page.",
            "result_skus": ["FE-100"],
            "candidate_skus": ["FE-100"],
            "results": [{"sku": "FE-100"}],
            "answer_metadata": {
                "contract_field_type": "shipping",
                "evidence_status": "matched",
                "evidence_field": "product_qa",
                "evidence_source": "product_qa:shipping-qa-id",
                "evidence_sku": "FE-100",
                "field_evidence_match": True,
            },
            "debug": {
                "field_contract": {
                    "field_type": "shipping",
                    "source": "validated_semantic_preplan",
                },
            },
        }
        result = customer_service_service._enforce_field_evidence_policy(
            db,
            "FE-100 shipping method?",
            original,
        )

    assert result is original
    assert result["answer_metadata"]["evidence_source"] == "product_qa:shipping-qa-id"


def test_final_guard_preserves_attached_semantic_field_contract_over_incidental_raw_alias(field_evidence_client):
    _, _, Session = field_evidence_client
    with Session() as db:
        result = customer_service_service._enforce_field_evidence_policy(
            db,
            "FE-100\u54c1\u724c\u7684\u4ef7\u4f4d\u5982\u4f55\uff1f",
            {
                "intent": "product_detail",
                "answer_type": "product_detail",
                "answer": "\u54c1\u724c\u8bc1\u636e\u3002",
                "result_skus": ["FE-100"],
                "candidate_skus": ["FE-100"],
                "results": [{"sku": "FE-100"}],
                "answer_metadata": {
                    "evidence_field": "brand",
                    "evidence_sku": "FE-100",
                    "evidence_value": "example brand",
                },
                "debug": {
                    "field_contract": {
                        "field_type": "capacity",
                        "source": "validated_semantic_preplan",
                    },
                },
            },
        )

    metadata = result.get("answer_metadata") or {}
    assert metadata.get("evidence_field") == "capacity", result


def test_final_guard_uses_attached_contract_when_product_descriptor_contains_another_field_word(field_evidence_client, monkeypatch):
    client, headers, Session = field_evidence_client
    with Session() as db:
        original = {
            "answer_type": "product_detail",
            "result_skus": ["FE-100"],
            "answer_metadata": {"evidence_field": "gift", "evidence_sku": "FE-100", "evidence_value": "无关赠品资料"},
            "debug": {
                "field_contract": {"field_type": "power", "source": "validated_semantic_preplan"},
                "entity_resolution_contract": {"status": "resolved", "resolved_sku": "FE-100"},
            },
        }
        replacement = {
            "answer_type": "product_detail", "result_skus": ["FE-100"],
            "answer_metadata": {"evidence_field": "power", "evidence_sku": "FE-100", "evidence_value": "2400W"},
            "debug": {},
        }
        monkeypatch.setattr(customer_service_service, "_explicit_product_from_question", lambda *_: db.query(Product).filter(Product.sku == "FE-100").one())
        monkeypatch.setattr(customer_service_service, "_phase1_product_field_result", lambda *_args, **_kwargs: dict(replacement))
        result = customer_service_service._enforce_field_evidence_policy(db, "示例赠品功率是多少？", original)

    assert result["answer_metadata"]["evidence_field"] == "power"
    assert result["answer_metadata"]["evidence_sku"] == "FE-100"
    assert result["answer_metadata"]["evidence_value"] == "2400W"
    assert result["debug"]["field_evidence_guard_applied"] is True


def test_heat_source_product_name_does_not_become_requested_compatibility():
    product_name = "\u9152\u7cbe\u7089\u5957\u88c5"
    heat_source = "95%\u6db2\u4f53\u5de5\u4e1a\u9152\u7cbe"

    answer, status = customer_service_service._phase1_heat_source_capability_answer(
        None,
        {
            "sku": "DEMO-ALCOHOL",
            "product_name_cn": product_name,
            "heat_source": heat_source,
        },
        f"{product_name}\u652f\u6301\u4ec0\u4e48\u70ed\u6e90\uff1f",
    )

    assert status == "structured"
    assert f"\u9002\u7528\u70ed\u6e90\u4e3a{heat_source}" in answer
    assert "\u652f\u6301\u9152\u7cbe\u7089" not in answer


def test_specification_summary_does_not_repeat_embedded_field_label():
    product = Product(sku="DEMO-SPEC", product_name_cn="Demo")
    specs = ProductSpecs(body_material="\u6750\u8d28\uff1a\u78e8\u6bdb\u6625\u4e9a\u7eba")

    summary = customer_service_service._specification_field_evidence(
        product=product,
        specs=specs,
    )

    assert summary == "\u6750\u8d28\uff1a\u78e8\u6bdb\u6625\u4e9a\u7eba"


def test_people_field_accepts_explicit_single_person_audience_word():
    assert customer_service_service._people_count_field_evidence("适合单人背包客") == "单人"
