import pytest
from types import SimpleNamespace

from app.services import customer_agent_planner_service, customer_service_service
from app.services.customer_structured_query_contract import (
    StructuredQueryContract,
    adapt_semantic_structured_query_contract,
    classify_heat_source_value,
    build_structured_query_contract,
    evaluate_structured_row,
    format_structured_condition_summary,
    match_material_condition,
    normalize_measurement,
    resolve_waterware_subject_kind,
    resolve_structured_subject_scope,
    validate_structured_evidence,
)
from customer_service_test_support import _add_product


@pytest.fixture(autouse=True)
def _semantic_preplan_out_of_scope_for_structured_executor_regressions(monkeypatch):
    """Keep executor tests independent of provider configuration.

    These tests validate the deterministic structured-query contract after a
    route has been selected. Tests that validate semantic adaptation install
    their own explicit preplan response, which overrides this isolation stub.
    """
    async def no_semantic_preplan(*_args, **_kwargs):
        return {"called": False}

    monkeypatch.setattr(
        customer_agent_planner_service,
        "plan_customer_question_semantic",
        no_semantic_preplan,
    )


@pytest.mark.parametrize(
    ("question", "subject", "field", "operator", "value", "unit"),
    [
        ("哪些锅具适配燃气炉", "锅具", "heat_source", "supports", "燃气炉", None),
        ("有没有适合酒精炉的锅？", "锅具", "heat_source", "supports", "酒精炉", None),
        ("有哪些杯子容量在600ml以上", "水杯", "capacity", ">=", 600, "ml"),
        ("哪些锅具的材质是铝合金", "锅具", "material", "contains", "铝合金", None),
        ("哪些锅是硬氧材质", "锅具", "material", "contains", "硬质氧化铝", None),
        ("哪些炉具资料写了可以烧酒精", "炉具", "heat_source", "supports", "酒精", None),
    ],
)
def test_structured_contract_parses_subject_condition_and_relation(question, subject, field, operator, value, unit):
    contract = build_structured_query_contract(question)

    assert contract.status == "resolved"
    assert (contract.subject_category, contract.field, contract.operator) == (subject, field, operator)
    assert contract.value == value
    assert contract.unit == unit
    assert "subject" in contract.source_spans and "value" in contract.source_spans
    if question == "有没有适合酒精炉的锅？":
        assert contract.source_spans["value"][0] < contract.source_spans["subject"][0]
    else:
        assert contract.source_spans["subject"][0] < contract.source_spans["value"][0]


def test_structured_measurement_normalizes_ml_and_l_to_same_unit():
    assert normalize_measurement("600ml", "capacity") == (600.0, "ml")
    assert normalize_measurement("0.6L", "capacity") == (600.0, "ml")


@pytest.mark.parametrize(
    "question",
    [
        "容量不超过1升的水壶有哪些？",
        "容量不高于1升的水壶有哪些？",
    ],
)
def test_structured_contract_preserves_negated_upper_bound_phrases(question):
    contract = build_structured_query_contract(question)

    assert contract.status == "resolved"
    assert contract.field == "capacity"
    assert contract.operator == "<="
    assert contract.value == 1000
    assert contract.unit == "ml"


def test_condition_object_does_not_replace_subject_category():
    contract = build_structured_query_contract("现有锅具里哪些可以配燃气炉使用")

    assert contract.subject_category == "锅具"
    assert contract.value == "燃气炉"
    assert contract.subject_category != "炉具"


def test_structured_contract_preserves_material_and_compatible_stove_in_selection_wording():
    contract = build_structured_query_contract(
        "想买硬质氧化铝套锅，有哪些适合卡式炉的选择？"
    )

    assert contract.status == "resolved"
    assert contract.subject_category == "锅具"
    assert contract.conditions == [
        {"field": "material", "operator": "contains", "value": "硬质氧化铝", "unit": None, "relation": None},
        {"field": "heat_source", "operator": "supports", "value": "卡式炉", "unit": None, "relation": "compatible_with"},
    ]


@pytest.mark.parametrize(
    "question",
    [
        "户外水壶的容量通常怎么看",
        "露营椅一般会有哪些尺寸",
        "户外锅常见会用哪些材质",
    ],
)
def test_generic_category_field_has_no_filter_condition(question):
    contract = build_structured_query_contract(question)

    assert contract.status == "generic"
    assert contract.subject_category
    assert contract.field
    assert contract.operator is None
    assert contract.value is None


def test_recommendation_does_not_become_structured_filter():
    contract = build_structured_query_contract("推荐适合燃气炉的轻量锅具")
    assert contract.status == "not_applicable"


def test_semantic_structured_multi_condition_contract_requires_each_literal_condition():
    """Semantic fields may add an allowlisted literal predicate, never a product fact."""
    question = "列出锅具中支持明火并适合露营使用的款式"
    base = build_structured_query_contract(question)
    preplan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "confidence": 0.9,
        "canonical_fields": ["heat_source", "usage_scene"],
        "structured_query_constraints": [
            {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "明火"},
            {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营"},
        ],
    }

    contract = adapt_semantic_structured_query_contract(
        question=question,
        base_contract=base,
        semantic_preplan=preplan,
    )

    assert contract.status == "resolved"
    assert contract.subject_category == "锅具"
    assert [item["field"] for item in contract.conditions] == ["heat_source", "usage_scene"]
    assert evaluate_structured_row(
        {"sku": "MATCH", "category": "锅具", "heat_source": "明火直烧", "usage_scenarios": "露营"},
        contract,
    )["matched"] is True
    assert evaluate_structured_row(
        {"sku": "HEAT-ONLY", "category": "锅具", "heat_source": "明火直烧", "usage_scenarios": "家庭厨房"},
        contract,
    )["matched"] is False


def test_semantic_structured_contract_validates_subject_span_when_legacy_parser_cannot_order_it():
    """Semantic subject meaning may be validated against the category taxonomy, not guessed from rows."""
    question = "筛出支持明火并且使用场景写有露营的锅具"
    base = build_structured_query_contract(question)
    preplan = {
        "called": True,
        "route_family": "structured_query",
        "route_hint": "query_products",
        "question_type": "filter",
        "subtype": "structured_query",
        "subject_text": "锅具",
        "confidence": 0.9,
        "canonical_fields": ["heat_source", "usage_scene"],
        "structured_query_constraints": [
            {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "支持明火"},
            {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "使用场景写有露营"},
        ],
    }

    assert base.subject_category is None
    contract = adapt_semantic_structured_query_contract(
        question=question,
        base_contract=base,
        semantic_preplan=preplan,
    )

    assert contract is not None
    assert contract.subject_category == "锅具"
    assert contract.source_spans["subject"] == (len(question) - 2, len(question))
    assert [item["field"] for item in contract.conditions] == ["heat_source", "usage_scene"]


def test_route_uses_validated_semantic_multi_condition_contract_before_legacy_single_filter(
    structured_client,
    monkeypatch,
):
    async def fake_preplan(db, question, deterministic_plan, context):
        return {
            "called": True,
            "route_family": "structured_query",
            "route_hint": "query_products",
            "question_type": "filter",
            "subtype": "structured_query",
            "subject_text": "锅具",
            "canonical_fields": ["heat_source", "usage_scene"],
            "confidence": 0.9,
            "confidence_label": "high",
            "ambiguity": False,
            "structured_query_constraints": [
                {"field": "heat_source", "operator": "supports", "value": "明火", "evidence_span": "明火", "unit": None},
                {"field": "usage_scene", "operator": "contains", "value": "露营", "evidence_span": "露营", "unit": None},
            ],
        }

    monkeypatch.setattr(customer_agent_planner_service, "plan_customer_question_semantic", fake_preplan)
    monkeypatch.setattr(
        customer_service_service,
        "_phase1_catalog_rows",
        lambda db, ref: [
            {"sku": "SQ-MATCH", "product_name_cn": "露营锅", "category": "锅具", "heat_source": "明火直烧", "usage_scenarios": "露营"},
            {"sku": "SQ-HEAT-ONLY", "product_name_cn": "家庭锅", "category": "锅具", "heat_source": "明火直烧", "usage_scenarios": "家庭厨房"},
        ],
    )
    payload = _ask(structured_client, "哪些锅具能用明火并适合露营？")

    contract = payload["answer_metadata"]["structured_query_contract"]
    assert payload["debug"]["agent_mode"] == "structured_query_contract", payload
    assert [item["field"] for item in contract["conditions"]] == ["heat_source", "usage_scene"]
    assert payload["result_skus"] == ["SQ-MATCH"], payload
    assert all(
        all(proof["matched"] for proof in evidence["condition_proofs"])
        for evidence in payload["answer_metadata"]["structured_match_evidence"]
    )


@pytest.mark.parametrize("question", [
    "这个锅能不能用酒精炉？",
    "那款水壶容量有多大？",
    "该产品材质是什么？",
])
def test_deictic_subject_does_not_become_catalog_category_filter(question):
    contract = build_structured_query_contract(question)

    assert contract.status != "resolved"
    assert contract.subject_category is None


@pytest.mark.parametrize(
    ("row", "question", "matched"),
    [
        ({"sku": "SQ-1", "category": "锅具", "product_name_cn": "远山锅", "body_material": "硬质氧化铝合金"}, "哪些锅是硬氧材质", True),
        ({"sku": "SQ-2", "category": "水具", "product_name_cn": "远山杯", "capacity": "650ml"}, "哪些杯子容量在600ml以上", True),
        ({"sku": "SQ-3", "category": "锅具", "product_name_cn": "远山锅", "heat_source": "燃气炉、卡式炉"}, "哪些锅具适配燃气炉", True),
        ({"sku": "SQ-4", "category": "锅具", "product_name_cn": "远山锅", "capacity": ""}, "哪些锅具容量在600ml以上", False),
        ({"sku": "SQ-5", "category": "炉具", "product_name_cn": "远山炉", "body_material": "铝合金"}, "哪些锅具是铝合金材质", False),
    ],
)
def test_structured_filter_requires_subject_and_field_evidence(row, question, matched):
    evidence = evaluate_structured_row(row, build_structured_query_contract(question))
    assert evidence["matched"] is matched
    assert evidence["sku"] == row["sku"]


@pytest.fixture()
def structured_client(route_client_and_db):
    client, headers, Session = route_client_and_db
    with Session() as db:
        _add_product(db, "SQ-POT-1", "远山铝锅", "锅具", "800ml", "硬质氧化铝合金", "燃气炉、卡式炉", "测试锅", "露营", 480)
        _add_product(db, "SQ-POT-2", "远山钢锅", "锅具", "500ml", "304不锈钢", "电磁炉", "测试锅", "露营", 700)
        _add_product(db, "SQ-CUP-1", "远山大杯", "水具", "650ml", "304不锈钢", "", "测试杯", "饮水", 220)
        _add_product(db, "SQ-CUP-2", "远山小杯", "水具", "350ml", "PP", "", "测试杯", "饮水", 90)
        _add_product(db, "SQ-STOVE-1", "远山酒精炉", "炉具", "/", "不锈钢", "95%液体工业酒精", "测试炉", "露营", 160)
        db.commit()
    return client, headers


def _ask(structured_client, question):
    client, headers = structured_client
    return client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers).json()


def _synthetic_structured_rows():
    return [
        {
            "sku": "SQ-POT-1", "product_name_cn": "远山铝锅", "product_name_en": "synthetic pot one",
            "category": "锅具", "sub_category": "锅具", "capacity": "800ml",
            "body_material": "硬质氧化铝合金", "heat_source": "燃气炉、卡式炉",
            "gross_weight_g": 480, "color": "本色", "target_audience": "户外用户",
        },
        {
            "sku": "SQ-POT-2", "product_name_cn": "远山钢锅", "product_name_en": "synthetic pot two",
            "category": "锅具", "sub_category": "锅具", "capacity": "500ml",
            "body_material": "304不锈钢", "heat_source": "电磁炉",
            "gross_weight_g": 700, "color": "黑色", "target_audience": "户外用户",
        },
        {
            "sku": "SQ-CUP-1", "product_name_cn": "远山大杯", "product_name_en": "synthetic cup one",
            "category": "水具", "sub_category": "水杯", "capacity": "650ml",
            "body_material": "304不锈钢", "heat_source": "",
            "gross_weight_g": 220, "color": "本色", "target_audience": "户外用户",
        },
        {
            "sku": "SQ-CUP-2", "product_name_cn": "远山小杯", "product_name_en": "synthetic cup two",
            "category": "水具", "sub_category": "水杯", "capacity": "350ml",
            "body_material": "PP", "heat_source": "",
            "gross_weight_g": 90, "color": "橙色", "target_audience": "户外用户",
        },
    ]


def test_structured_route_precedes_entity_clarification(structured_client, monkeypatch):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: _synthetic_structured_rows())
    payload = _ask(structured_client, "哪些锅具适配燃气炉")
    assert payload["debug"]["agent_mode"] == "structured_query_contract", payload
    assert payload["answer_type"] == "product_query"
    assert payload["result_skus"] == ["SQ-POT-1"]
    assert all(item["subject_match"] and item["matched"] for item in payload["answer_metadata"]["structured_match_evidence"])


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        (StructuredQueryContract(field="heat_source", operator="supports", value="酒精炉"), "支持酒精炉"),
        (StructuredQueryContract(field="material", operator="contains", value="不锈钢"), "材质包含不锈钢"),
        (StructuredQueryContract(field="capacity", operator=">=", value=600, unit="ml"), "容量不低于600ml"),
    ],
)
def test_structured_condition_summary_preserves_requested_condition(contract, expected):
    assert format_structured_condition_summary(contract) == expected


def test_structured_result_rendering_keeps_condition_and_legacy_source(structured_client, monkeypatch):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: _synthetic_structured_rows())

    payload = _ask(structured_client, "哪些锅具适配燃气炉")

    assert "燃气炉" in payload["answer"]
    assert payload["answer_metadata"]["source"] == "structured_category_field_filter_query"
    assert payload["result_skus"] == payload["candidate_skus"] == ["SQ-POT-1"]
    assert [item["sku"] for item in payload["answer_metadata"]["structured_match_evidence"]] == ["SQ-POT-1"]


@pytest.mark.parametrize(
    "question",
    [
        "有哪些水具材质是不锈钢的？",
        "哪些锅具适配燃气炉？",
        "哪些杯子容量在600ml以上？",
    ],
)
def test_structured_effective_plan_uses_normalized_contract_subject(structured_client, question):
    payload = _ask(structured_client, question)
    contract = payload["answer_metadata"]["structured_query_contract"]

    assert payload["debug"]["agent_mode"] == "structured_query_contract"
    assert payload["debug"]["plan"]["product_ref"] == contract["subject_category"]


def test_non_structured_effective_plan_keeps_original_product_ref():
    result = {"answer_metadata": {}, "debug": {}}
    original_plan = {"primary_intent": "product_field", "product_ref": "SYN-PRODUCT"}

    merged = customer_service_service._attach_phase1_plan_and_timing(result, original_plan, {})

    assert merged["debug"]["plan"]["product_ref"] == "SYN-PRODUCT"
    assert "contract_source" not in merged["answer_metadata"]


@pytest.mark.parametrize(
    ("row", "matched", "reason"),
    [
        ({"sku": "MAT-1", "category": "锅具", "product_name_cn": "野营锅", "body_material": "硬质氧化铝"}, True, None),
        ({"sku": "MAT-2", "category": "锅具", "product_name_cn": "复合锅", "body_material": "硬质氧化铝合金、不锈钢"}, True, None),
        ({"sku": "MAT-3", "category": "锅具", "product_name_cn": "铝锅", "body_material": "3003铝合金", "long_description_cn": "采用硬氧工艺卖点"}, False, "material_condition_not_met"),
        ({"sku": "MAT-4", "category": "锅具", "product_name_cn": "硬氧概念锅", "body_material": "不锈钢", "features": "硬氧卖点"}, False, "material_condition_not_met"),
        ({"sku": "MAT-5", "category": "配件", "product_name_cn": "野营锅配件", "body_material": "硬质氧化铝"}, False, "accessory_scope"),
        ({"sku": "MAT-6", "category": "餐具", "product_name_cn": "折叠锅铲", "body_material": "硬质氧化铝"}, False, "subject_category_mismatch"),
        ({"sku": "MAT-7", "category": "", "sub_category": "", "product_name_cn": "轻量野营锅", "body_material": "硬质氧化铝"}, True, None),
        ({"sku": "MAT-8", "category": "", "sub_category": "", "product_name_cn": "野营锅盖配件", "body_material": "硬质氧化铝"}, False, "accessory_scope"),
        ({"sku": "MAT-9", "category": "锅具", "product_name_cn": "复合套锅", "body_material": "锅体材质：不锈钢\n手柄材质：硬质氧化铝"}, False, "material_condition_not_met"),
        ({"sku": "MAT-10", "category": "锅具", "product_name_cn": "复合套锅", "body_material": "锅体材质：硬质氧化铝\n手柄材质：木材"}, True, None),
        ({"sku": "MAT-11", "category": "锅具", "product_name_cn": "未知范围锅", "body_material": "硬质氧化铝", "material_scope": "unknown"}, False, "non_subject_evidence_only"),
    ],
)
def test_material_matcher_enforces_subject_and_evidence_scope(row, matched, reason):
    contract = StructuredQueryContract(
        subject_category="锅具", field="material", operator="contains", value="硬质氧化铝", status="resolved"
    )

    result = match_material_condition(contract=contract, row=row)

    assert result["matched"] is matched
    assert result["excluded_reason"] == reason
    assert result["field_source"] == "body_material"
    if matched:
        assert result["raw_value"] == row["body_material"]
        assert result["matched_term"]
        assert result["subject_scope"] == "subject"


def test_legacy_and_contract_material_matchers_share_one_decision():
    rows = [
        {"sku": "MAT-PARITY-1", "category": "锅具", "product_name_cn": "主体锅", "body_material": "硬质氧化铝合金"},
        {"sku": "MAT-PARITY-2", "category": "锅具", "product_name_cn": "普通锅", "body_material": "3003铝合金", "features": "硬氧卖点"},
        {"sku": "MAT-PARITY-3", "category": "配件", "product_name_cn": "锅具配件", "body_material": "硬质氧化铝"},
    ]
    contract = StructuredQueryContract(
        subject_category="锅具", field="material", operator="contains", value="硬质氧化铝", status="resolved"
    )
    legacy_contract = {"filters": {"product.category": "锅具", "specs.body_material": "硬质氧化铝"}, "negative_filters": {}}

    new_matches = [row["sku"] for row in rows if match_material_condition(contract=contract, row=row)["matched"]]
    legacy_matches = [row["sku"] for row in rows if customer_service_service._structured_row_matches_contract(row, legacy_contract)]

    assert legacy_matches == new_matches == ["MAT-PARITY-1"]


@pytest.mark.parametrize("subject", ["水壶", "水具"])
def test_structured_subject_scope_reuses_canonical_waterware_compatibility(subject):
    row = {
        "sku": "WATER-1", "category": "水壶", "sub_category": "户外水壶",
        "product_name_cn": "明火小方壶", "body_material": "304不锈钢",
    }

    decision = resolve_structured_subject_scope(row=row, subject_category=subject)

    assert decision["matched"] is True
    assert decision["scope"] == "subject"
    assert decision["matched_by"] == "canonical_category"


def test_structured_subject_scope_allows_existing_strict_coffee_kettle_compatibility():
    row = {"sku": "WATER-2", "category": "咖啡器具", "product_name_cn": "细口手冲壶", "body_material": "不锈钢"}

    decision = resolve_structured_subject_scope(row=row, subject_category="水壶")

    assert decision["matched"] is True
    assert decision["matched_by"] == "strict_water_kettle_compatibility"


@pytest.mark.parametrize(
    ("requested_subject", "row", "expected", "expected_kind"),
    [
        ("水具", {"category": "水杯", "product_name_cn": "户外水杯"}, True, "cup"),
        ("水具", {"category": "水壶", "product_name_cn": "户外水壶"}, True, "kettle"),
        ("水壶", {"category": "水壶", "product_name_cn": "户外水壶"}, True, "kettle"),
        ("水壶", {"category": "水具", "product_name_cn": "户外水杯"}, False, "cup"),
        ("水杯", {"category": "水杯", "product_name_cn": "户外水杯"}, True, "cup"),
        ("水杯", {"category": "水壶", "product_name_cn": "户外水壶"}, False, "kettle"),
        ("水具", {"category": "咖啡器具", "product_name_cn": "手冲细口壶"}, True, "coffee_kettle"),
        ("水壶", {"category": "咖啡器具", "product_name_cn": "手冲细口壶"}, True, "coffee_kettle"),
        ("水壶", {"category": "咖啡器具", "product_name_cn": "咖啡滤杯"}, False, "other"),
        ("水壶", {"category": "配件", "product_name_cn": "水壶替换壶盖"}, False, "accessory"),
        ("水壶", {"category": "", "product_name_cn": "户外烧水壶"}, True, "kettle"),
        ("水壶", {"category": "水杯", "product_name_cn": "壶形随行杯"}, False, "cup"),
    ],
)
def test_directional_waterware_subject_hierarchy(requested_subject, row, expected, expected_kind):
    row = {"sku": "SYN-WATER", "body_material": "304不锈钢", **row}

    kind = resolve_waterware_subject_kind(row)
    decision = resolve_structured_subject_scope(row=row, subject_category=requested_subject)

    assert kind["kind"] == expected_kind
    assert decision["matched"] is expected
    if expected:
        assert decision["scope"] == "subject"
    elif expected_kind == "accessory":
        assert decision["excluded_reason"] == "accessory_scope"
    else:
        assert decision["excluded_reason"] == "subject_specificity_mismatch"


@pytest.mark.parametrize(
    ("question", "field"),
    [
        ("哪些咖啡壶是不锈钢的？", "material"),
        ("哪些咖啡壶容量大于500ml？", "capacity"),
        ("哪些咖啡壶支持明火？", "heat_source"),
    ],
)
def test_coffee_kettle_composite_subject_contract_consumes_full_span(question, field):
    contract = build_structured_query_contract(question)

    assert contract.status == "resolved"
    assert contract.subject_category == "咖啡器具"
    assert contract.subject_kind == "coffee_kettle"
    assert contract.requested_scope == "subject"
    assert question[slice(*contract.subject_span)] == "咖啡壶"
    assert contract.field == field


def test_water_kettle_accessory_contract_consumes_accessory_as_scope():
    question = "哪些水壶配件是不锈钢的？"
    contract = build_structured_query_contract(question)

    assert contract.status == "resolved"
    assert contract.subject_category == "水壶"
    assert contract.subject_kind == "kettle"
    assert contract.requested_scope == "accessory"
    assert question[slice(*contract.subject_span)] == "水壶配件"
    assert contract.field == "material"


def test_composite_subject_evaluator_keeps_coffee_kettles_and_accessories_directional():
    coffee_contract = build_structured_query_contract("哪些咖啡壶是不锈钢的？")
    accessory_contract = build_structured_query_contract("哪些水壶配件是不锈钢的？")
    rows = [
        {"sku": "COFFEE-KETTLE", "category": "咖啡器具", "product_name_cn": "手冲细口壶", "body_material": "不锈钢"},
        {"sku": "COFFEE-GRINDER", "category": "咖啡器具", "product_name_cn": "手摇磨豆器", "body_material": "不锈钢"},
        {"sku": "PLAIN-KETTLE", "category": "水壶", "product_name_cn": "烧水壶", "body_material": "不锈钢"},
        {"sku": "KETTLE-ACCESSORY", "category": "配件", "product_name_cn": "替换件", "compatible_category": "水壶", "body_material": "不锈钢"},
        {"sku": "UNKNOWN-ACCESSORY", "category": "配件", "product_name_cn": "通用替换件", "body_material": "不锈钢"},
        {"sku": "CUP-ACCESSORY", "category": "配件", "product_name_cn": "杯盖替换件", "compatible_category": "水杯", "body_material": "不锈钢"},
    ]

    coffee = {row["sku"]: evaluate_structured_row(row, coffee_contract) for row in rows}
    accessory = {row["sku"]: evaluate_structured_row(row, accessory_contract) for row in rows}

    assert coffee["COFFEE-KETTLE"]["matched"] is True
    assert coffee["COFFEE-KETTLE"]["subject_kind"] == "coffee_kettle"
    assert coffee["COFFEE-GRINDER"]["excluded_reason"] == "subject_specificity_mismatch"
    assert coffee["PLAIN-KETTLE"]["excluded_reason"] == "subject_specificity_mismatch"
    assert accessory["KETTLE-ACCESSORY"]["matched"] is True
    assert accessory["KETTLE-ACCESSORY"]["subject_scope"] == "accessory"
    assert accessory["KETTLE-ACCESSORY"]["field_source"] == "body_material"
    assert accessory["PLAIN-KETTLE"]["matched"] is False
    assert accessory["UNKNOWN-ACCESSORY"]["excluded_reason"] == "accessory_subject_compatibility_unknown"
    assert accessory["CUP-ACCESSORY"]["matched"] is False


@pytest.mark.parametrize(
    ("row", "matched", "excluded_reason"),
    [
        ({"sku": "UNKNOWN", "category": "配件", "product_name_cn": "通用替换件", "body_material": "不锈钢"}, False, "accessory_subject_compatibility_unknown"),
        ({"sku": "CUP", "category": "配件", "product_name_cn": "杯盖替换件", "compatible_category": "水杯", "body_material": "不锈钢"}, False, "subject_specificity_mismatch"),
        ({"sku": "SUBJECT", "category": "水壶", "product_name_cn": "烧水壶", "body_material": "不锈钢"}, False, "accessory_scope_mismatch"),
        ({"sku": "WRONG-MATERIAL", "category": "配件", "product_name_cn": "替换件", "compatible_category": "水壶", "body_material": "铝合金"}, False, "material_condition_not_met"),
        ({"sku": "MATCH", "category": "配件", "product_name_cn": "替换件", "compatible_category": "水壶", "body_material": "不锈钢"}, True, None),
    ],
)
def test_accessory_exclusion_reason_provenance(row, matched, excluded_reason):
    evidence = evaluate_structured_row(row, build_structured_query_contract("哪些水壶配件是不锈钢的？"))

    assert evidence["matched"] is matched
    assert evidence["excluded_reason"] == excluded_reason


def test_waterproof_category_question_resolves_to_structured_empty_result_without_kb(structured_client, monkeypatch):
    rows = [
        {"sku": "OTHER-1", "product_name_cn": "不相关水壶", "category": "水壶", "waterproof": True},
        {"sku": "TENT-UNKNOWN", "product_name_cn": "资料缺失帐篷", "category": "帐篷"},
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "帐篷防水吗？")
    contract = payload["answer_metadata"]["structured_query_contract"]

    assert contract["status"] == "resolved"
    assert contract["subject_category"] == "帐篷"
    assert contract["field"] == "waterproof"
    assert payload["debug"]["agent_mode"] == "structured_query_contract"
    assert payload["answer_type"] == "product_query"
    assert payload["result_skus"] == payload["candidate_skus"] == []
    assert payload["answer_metadata"]["structured_match_evidence"] == []
    assert payload["answer_metadata"]["total_match_count"] == 0
    assert any(
        phrase in payload["answer"]
        for phrase in ("当前结构化商品库未找到符合条件的商品", "当前已核对资料未找到符合条件的商品")
    )


def test_structured_evidence_guard_rejects_cross_scope_field_condition_and_unscoped_evidence():
    contract = build_structured_query_contract("哪些帐篷防水？")
    matched = {"sku": "TENT-YES", "category": "帐篷", "product_name_cn": "合成帐篷", "waterproof": True}
    wrong_subject = {"sku": "CUP-YES", "category": "水杯", "product_name_cn": "防水杯", "waterproof": True}
    wrong_condition = {"sku": "TENT-NO", "category": "帐篷", "product_name_cn": "普通帐篷", "waterproof": False}
    evidence = [
        {**evaluate_structured_row(matched, contract)},
        {"sku": "CUP-YES", "field_source": "waterproof"},
        {"sku": "TENT-NO", "field_source": "waterproof"},
        {"sku": "TENT-YES", "field_source": "body_material"},
        {"sku": "OUTSIDE", "field_source": "waterproof"},
        {"source_kind": "qa", "content": "unscoped note"},
    ]

    guarded = validate_structured_evidence(
        contract=contract,
        filtered_rows=[matched, wrong_subject, wrong_condition],
        evidence_rows=evidence,
    )

    assert [item["sku"] for item in guarded["accepted_evidence"]] == ["TENT-YES"]
    assert [item["rejected_reason"] for item in guarded["rejected_evidence"]] == [
        "subject_scope_mismatch",
        "condition_not_met",
        "field_mismatch",
        "sku_not_in_filtered_rows",
        "unscoped_kb_evidence",
    ]


def test_structured_evidence_guard_requires_all_compound_conditions():
    contract = build_structured_query_contract("可以明火直烧的不锈钢水壶有哪些？")
    full_match = {"sku": "BOTH", "category": "水壶", "product_name_cn": "合成水壶", "body_material": "不锈钢", "heat_source": "明火直烧"}
    partial = {"sku": "ONE", "category": "水壶", "product_name_cn": "部分水壶", "body_material": "不锈钢", "heat_source": "电磁炉"}

    guarded = validate_structured_evidence(
        contract=contract,
        filtered_rows=[full_match, partial],
        evidence_rows=[evaluate_structured_row(full_match, contract), {"sku": "ONE", "field_source": "compound"}],
    )

    assert [item["sku"] for item in guarded["accepted_evidence"]] == ["BOTH"]
    assert guarded["rejected_evidence"][0]["rejected_reason"] == "condition_not_met"


@pytest.mark.parametrize(
    ("question", "expected_skus"),
    [
        ("哪些咖啡壶是不锈钢的？", ["COFFEE-KETTLE"]),
        ("哪些水壶配件是不锈钢的？", ["KETTLE-ACCESSORY"]),
    ],
)
def test_composite_subject_routes_through_structured_contract(structured_client, monkeypatch, question, expected_skus):
    rows = [
        {"sku": "COFFEE-KETTLE", "product_name_cn": "手冲细口壶", "category": "咖啡器具", "body_material": "不锈钢"},
        {"sku": "COFFEE-GRINDER", "product_name_cn": "磨豆器", "category": "咖啡器具", "body_material": "不锈钢"},
        {"sku": "KETTLE-ACCESSORY", "product_name_cn": "替换件", "category": "配件", "compatible_category": "水壶", "body_material": "不锈钢"},
        {"sku": "PLAIN-KETTLE", "product_name_cn": "烧水壶", "category": "水壶", "body_material": "不锈钢"},
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, question)

    assert payload["debug"]["agent_mode"] == "structured_query_contract"
    assert payload["answer_metadata"]["source"] == "structured_category_field_filter_query"
    assert payload["answer_metadata"]["contract_source"] == "structured_query_contract"
    assert payload["result_skus"] == expected_skus


def test_structured_subject_scope_rejects_kettle_named_accessory():
    row = {"sku": "WATER-3", "category": "配件", "product_name_cn": "水壶替换壶嘴", "body_material": "不锈钢"}

    decision = resolve_structured_subject_scope(row=row, subject_category="水壶")

    assert decision["matched"] is False
    assert decision["excluded_reason"] == "accessory_scope"


def test_legacy_compound_waterware_filter_requires_subject_material_and_heat_source():
    contract = {
        "filters": {
            "product.category": "水壶",
            "specs.body_material": "不锈钢",
            "specs.heat_source": "明火直烧",
        },
        "negative_filters": {},
    }
    qualified = {
        "sku": "WATER-4", "category": "水壶", "product_name_cn": "明火壶",
        "body_material": "304不锈钢", "heat_source": "明火直烧、卡式炉",
    }
    wrong_material = {**qualified, "sku": "WATER-5", "body_material": "铝合金", "long_description_cn": "不锈钢卖点"}
    wrong_heat = {**qualified, "sku": "WATER-6", "heat_source": "电磁炉"}

    assert customer_service_service._structured_row_matches_contract(qualified, contract) is True
    assert customer_service_service._structured_row_matches_contract(wrong_material, contract) is False
    assert customer_service_service._structured_row_matches_contract(wrong_heat, contract) is False


def test_generic_category_field_uses_general_route_without_sku(structured_client):
    payload = _ask(structured_client, "户外锅常见会用哪些材质")
    assert payload["debug"]["agent_mode"] == "category_field_general", payload
    assert payload["result_skus"] == []
    assert payload["candidate_skus"] == []


def test_exact_single_product_detail_keeps_phase2_precedence(structured_client):
    payload = _ask(structured_client, "SQ-POT-1 的容量是多少")
    assert payload["debug"]["agent_mode"] == "resolved_entity_detail_contract", payload
    assert payload["result_skus"] == ["SQ-POT-1"]


def test_structured_output_and_skus_share_filtered_rows(structured_client, monkeypatch):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: _synthetic_structured_rows())
    payload = _ask(structured_client, "有哪些杯子容量在600ml以上")
    assert payload["result_skus"] == payload["candidate_skus"] == ["SQ-CUP-1"]
    assert "SQ-CUP-1" in payload["answer"]
    assert "SQ-CUP-2" not in payload["answer"]
    evidence = payload["answer_metadata"]["structured_match_evidence"]
    assert [item["sku"] for item in evidence] == payload["result_skus"]
    assert all(item["matched"] for item in evidence)
    assert all(item["normalized_value"] >= item["target"] for item in evidence)


def test_structured_empty_result_has_no_residual_skus(structured_client):
    payload = _ask(structured_client, "有哪些杯子容量在900ml以上")
    assert payload["result_skus"] == []
    assert payload["candidate_skus"] == []
    assert payload["results"] == []
    assert any(
        phrase in payload["answer"]
        for phrase in ("当前结构化商品库未找到符合条件的商品", "当前已核对资料未找到符合条件的商品")
    )
    assert "水杯" in payload["answer"]
    assert "容量不低于900ml" in payload["answer"]


def test_structured_subject_and_heat_source_must_both_match(structured_client):
    payload = _ask(structured_client, "哪些炉具资料里明确写了可以烧酒精")
    assert payload["result_skus"] == ["SQ-STOVE-1"]
    assert "SQ-POT-1" not in payload["result_skus"]


def test_structured_multiple_results_have_stable_order_and_proof(structured_client, monkeypatch):
    rows = [
        {**_synthetic_structured_rows()[0], "sku": "SQ-Z-POT", "product_name_cn": "远山乙锅"},
        {**_synthetic_structured_rows()[0], "sku": "SQ-A-POT", "product_name_cn": "远山甲锅"},
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    first = _ask(structured_client, "哪些锅具是铝合金材质")
    second = _ask(structured_client, "哪些锅具是铝合金材质")

    assert first["result_skus"] == second["result_skus"] == ["SQ-Z-POT", "SQ-A-POT"]
    assert first["candidate_skus"] == first["result_skus"]
    proof = first["answer_metadata"]["structured_match_evidence"]
    assert [item["sku"] for item in proof] == first["result_skus"]
    assert all(item["matched"] and "铝合金" in str(item["raw_value"]) for item in proof)


def test_normalization_cannot_restore_prefilter_candidates(structured_client):
    payload = _ask(structured_client, "有哪些杯子容量在900ml以上")
    assert payload["debug"].get("candidate_skus") == []
    assert payload.get("result_skus") == []


@pytest.mark.parametrize(
    ("question", "subject", "field", "operator", "value", "unit"),
    [
        ("帮我找容量不低于600毫升的水杯", "水杯", "capacity", ">=", 600, "ml"),
        ("容量不小于1升的水壶有哪些？", "水壶", "capacity", ">=", 1000, "ml"),
        ("找一下容量在500到1000毫升之间的杯子", "水杯", "capacity", "between", [500, 1000], "ml"),
        ("找出容量大于300毫升的杯子", "水杯", "capacity", ">", 300, "ml"),
        ("哪些产品的重量小于1千克", "all_products", "weight", "<", 1000, "g"),
        ("有哪些重量小于2千克的产品", "all_products", "weight", "<", 2000, "g"),
    ],
)
def test_structured_contract_parses_search_prefixes_and_broad_product_scope(
    question, subject, field, operator, value, unit
):
    contract = build_structured_query_contract(question)

    assert contract.status == "resolved"
    assert (contract.subject_category, contract.field, contract.operator) == (subject, field, operator)
    assert contract.value == value
    assert contract.unit == unit


def test_structured_contract_keeps_subject_separate_from_heat_source_value():
    contract = build_structured_query_contract("有哪些锅具可以在燃气炉上使用")

    assert contract.status == "resolved"
    assert contract.subject_category == "锅具"
    assert contract.field == "heat_source"
    assert contract.operator == "supports"
    assert contract.value == "燃气炉"


def test_structured_contract_preserves_negative_heat_source_operator():
    contract = build_structured_query_contract("有哪些锅具不能用于电磁炉")

    assert contract.status == "resolved"
    assert contract.subject_category == "锅具"
    assert contract.field == "heat_source"
    assert contract.operator == "not_supports"
    assert contract.value == "电磁炉"


@pytest.mark.parametrize(
    ("heat_source", "matched"),
    [
        ("明确不支持电磁炉", True),
        ("燃气炉、卡式炉", False),
        ("", False),
        (None, False),
    ],
)
def test_negative_heat_source_requires_explicit_negative_evidence(heat_source, matched):
    row = {
        "sku": "SYN-POT-NEG",
        "category": "锅具",
        "product_name_cn": "合成测试锅",
        "heat_source": heat_source,
    }
    evidence = evaluate_structured_row(row, build_structured_query_contract("哪些锅具不能用于电磁炉"))

    assert evidence["matched"] is matched


def test_all_products_scope_still_requires_comparable_weight_evidence():
    contract = build_structured_query_contract("哪些产品的重量小于1千克")
    light = evaluate_structured_row(
        {"sku": "SYN-LIGHT", "category": "配件", "gross_weight_g": 900}, contract
    )
    missing = evaluate_structured_row(
        {"sku": "SYN-MISSING", "category": "锅具", "gross_weight_g": None}, contract
    )

    assert light["subject_match"] is True
    assert light["matched"] is True
    assert missing["subject_match"] is True
    assert missing["matched"] is False


@pytest.mark.parametrize(
    "question",
    [
        "帮我找容量不低于600毫升的水杯",
        "找一下容量在500到1000毫升之间的杯子",
        "找出容量大于300毫升的杯子",
        "哪些产品的重量小于1千克",
        "有哪些重量小于2千克的产品",
    ],
)
def test_complete_structured_contract_precedes_entity_and_kb_fallback(
    structured_client, monkeypatch, question
):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: _synthetic_structured_rows())

    payload = _ask(structured_client, question)

    assert payload["debug"]["agent_mode"] == "structured_query_contract", payload
    assert payload["answer_type"] == "product_query"
    assert payload["answer_metadata"]["source"] == "structured_category_field_filter_query"
    assert payload["answer_metadata"]["contract_source"] == "structured_query_contract"
    assert payload["answer_metadata"]["structured_query_contract"]["status"] == "resolved"
    assert all(item["matched"] for item in payload["answer_metadata"]["structured_match_evidence"])


@pytest.mark.parametrize(
    "question",
    [
        "哪些锅具是铝合金材质？",
        "哪些锅具适配燃气炉？",
        "帮我找容量不低于600毫升的水杯",
        "哪些产品的重量小于1千克",
        "有哪些杯子容量在900ml以上",
    ],
)
def test_structured_metadata_contract_has_stable_source_and_explicit_contract_source(
    structured_client, monkeypatch, question
):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: _synthetic_structured_rows())

    payload = _ask(structured_client, question)

    assert payload["answer_metadata"]["source"] == "structured_category_field_filter_query"
    assert payload["answer_metadata"]["contract_source"] == "structured_query_contract"
    assert payload["debug"]["agent_mode"] == "structured_query_contract"


def test_compound_structured_contract_routes_through_center_and_requires_all_conditions(structured_client, monkeypatch):
    rows = [
        {"sku": "CMP-1", "product_name_cn": "合格壶", "category": "水壶", "body_material": "304不锈钢", "heat_source": "明火直烧"},
        {"sku": "CMP-2", "product_name_cn": "仅材质壶", "category": "水壶", "body_material": "304不锈钢", "heat_source": "电磁炉"},
        {"sku": "CMP-3", "product_name_cn": "仅热源壶", "category": "水壶", "body_material": "铝合金", "heat_source": "明火直烧"},
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "可以明火直烧的不锈钢水壶有哪些")
    contract = payload["answer_metadata"]["structured_query_contract"]

    assert [item["field"] for item in contract["conditions"]] == ["material", "heat_source"]
    assert payload["debug"]["agent_mode"] == "structured_query_contract"
    assert payload["result_skus"] == payload["candidate_skus"] == ["CMP-1"]
    assert all(item["matched"] for item in payload["answer_metadata"]["structured_match_evidence"])
    assert len(payload["answer_metadata"]["structured_match_evidence"][0]["condition_proofs"]) == 2
    assert payload["sources"]
    structured_sources = [item for item in payload["sources"] if item.get("type") == "structured_query_contract"]
    assert {item["sku"] for item in structured_sources} == {"CMP-1"}
    assert "missing_sources" not in payload["warnings"]


def test_structured_result_metadata_distinguishes_total_and_returned_rows(structured_client, monkeypatch):
    rows = [
        {"sku": f"TRUNC-{index:02d}", "product_name_cn": f"合成杯{index}", "category": "水杯", "capacity": "800ml"}
        for index in range(12)
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "哪些杯子容量在600ml以上")
    metadata = payload["answer_metadata"]

    assert metadata["total_match_count"] == 12
    assert metadata["returned_count"] == 10
    assert metadata["is_truncated"] is True
    assert len(payload["result_skus"]) == len(payload["candidate_skus"]) == len(payload["results"]) == 10
    assert "共找到 12 款" in payload["answer"] and "前 10 款" in payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "有哪些杯子容量在9000ml以上",
        "哪些锅具是钛材质？",
        "哪些锅具容量在999999ml以上？",
        "可以明火直烧的不锈钢水壶有哪些？",
        "哪些产品重量小于1克？",
    ],
)
def test_structured_empty_result_keeps_legacy_anchor_and_condition_metadata(structured_client, monkeypatch, question):
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: [])

    payload = _ask(structured_client, question)
    metadata = payload["answer_metadata"]

    assert any(
        phrase in payload["answer"]
        for phrase in ("当前结构化商品库未找到符合条件的商品", "当前已核对资料未找到符合条件的商品")
    )
    assert any(
        phrase in payload["answer"]
        for phrase in ("筛选条件：", "按你的条件：")
    )
    assert payload["result_skus"] == payload["candidate_skus"] == payload["results"] == []
    assert metadata["structured_match_evidence"] == []
    assert metadata["total_match_count"] == metadata["returned_count"] == 0
    assert metadata["is_truncated"] is False






@pytest.mark.parametrize(
    "question",
    [
        "我想买可放洗碗机的户外餐具，库里有可确认的选择吗？",
        "能进洗碗机的露营餐具有哪些？",
        "给我找资料明确写能放洗碗机的餐具。",
    ],
)
def test_generic_dishwasher_catalog_selection_builds_evidence_backed_filter(question):
    contract = customer_service_service._structured_hard_filter_contract(question)

    assert contract["product_ref"] == "餐具"
    assert contract["filters"]["product.category"] == "餐具"
    assert contract["filters"]["_contract.dishwasher"] == "洗碗机"
    assert customer_service_service._looks_like_structured_field_filter_query(question)


def test_named_dishwasher_question_does_not_become_catalog_selection_contract():
    assert customer_service_service._structured_hard_filter_contract("CW-C95 能放洗碗机吗？") == {}




def test_all_products_scope_uses_user_facing_label_without_changing_contract_or_rows(
    structured_client, monkeypatch
):
    rows = _synthetic_structured_rows()
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "哪些产品重量低于1千克")

    contract = payload["answer_metadata"]["structured_query_contract"]
    evidence = payload["answer_metadata"]["structured_match_evidence"]
    expected_skus = [row["sku"] for row in rows]
    assert contract["subject_category"] == "all_products"
    assert "all_products" not in payload["answer"]
    assert "全部产品" in payload["answer"]
    assert payload["result_skus"] == payload["candidate_skus"] == expected_skus
    assert [item["sku"] for item in evidence] == expected_skus
    assert all(item["matched"] and item["field_source"] == "gross_weight_g" for item in evidence)


@pytest.mark.parametrize("subject", ["锅具", "水杯"])
def test_regular_structured_subject_display_label_is_unchanged(subject):
    assert customer_service_service._phase1_catalog_display_label(subject) == subject


def _synthetic_category_aggregation_rows():
    return [
        {
            "sku": "AGG-POT-1", "product_name_cn": "合成锅一", "category": "锅具",
            "heat_source": "燃气炉\n电磁炉\n高山气罐\n明火直烧\n酒精炉", "capacity": "900ml", "body_material": "硬质氧化铝合金",
            "gross_weight_g": 700, "size_info": "30cm",
        },
        {
            "sku": "AGG-POT-2", "product_name_cn": "合成锅二", "category": "锅具",
            "heat_source": "燃气炉、卡式炉、卡式气罐、液体酒精", "capacity": "1L", "body_material": "304不锈钢",
            "gross_weight_g": 850, "size_info": "28cm",
        },
        {
            "sku": "AGG-CUP-1", "product_name_cn": "合成杯一", "category": "水具", "sub_category": "水杯",
            "heat_source": "", "capacity": '[{"label":"","value":"350ml","unit":""}]',
            "body_material": "PP", "gross_weight_g": 90, "size_info": "8cm",
        },
        {
            "sku": "AGG-CUP-2", "product_name_cn": "合成杯二", "category": "水具", "sub_category": "水杯",
            "heat_source": "/", "capacity": '[{"label":"","value":"0.35L","unit":""}]',
            "body_material": "不锈钢", "gross_weight_g": 120, "size_info": "9cm",
        },
        {
            "sku": "AGG-CUP-X", "product_name_cn": "合成杯缺失", "category": "水具", "sub_category": "水杯",
            "heat_source": "暂无", "capacity": "/", "body_material": "", "gross_weight_g": 150,
            "size_info": "999cm",
        },
        {
            "sku": "AGG-TENT-1", "product_name_cn": "合成帐篷一", "category": "帐篷",
            "heat_source": "", "capacity": "", "body_material": "涤纶布", "gross_weight_g": 1800,
        },
        {
            "sku": "AGG-STOVE-1", "product_name_cn": "合成炉", "category": "炉具",
            "heat_source": "异丁烷气罐", "capacity": "", "body_material": "铝合金", "gross_weight_g": 400,
        },
    ]


@pytest.mark.parametrize("question", ["水杯都有哪些容量", "杯子的容量是多少"])
def test_category_capacity_aggregation_uses_only_capacity_and_has_stable_proof(
    structured_client, monkeypatch, question
):
    rows = _synthetic_category_aggregation_rows()
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, question)

    metadata = payload["answer_metadata"]
    assert payload["debug"]["agent_mode"] == "category_field_general"
    assert metadata["aggregated_values"] == ["350ml"]
    assert "350ml" in payload["answer"]
    assert "999" not in payload["answer"]
    assert metadata["value_proofs"] == [
        {
            "value": "350ml",
            "field_source": "capacity",
            "source_skus": ["AGG-CUP-1", "AGG-CUP-2"],
        }
    ]
    assert payload["result_skus"] == payload["candidate_skus"] == []
    assert payload["debug"]["binding_provenance"] == "none"
    assert payload["debug"]["search_top1_promotion_blocked"] is True


def test_category_heat_source_aggregation_excludes_other_categories_and_internal_labels(
    structured_client, monkeypatch
):
    rows = _synthetic_category_aggregation_rows()
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "锅具都支持什么炉具")

    metadata = payload["answer_metadata"]
    assert metadata["aggregated_values"] == [
        "燃气炉", "电磁炉", "高山气罐", "明火直烧", "酒精炉", "卡式炉", "卡式气罐", "液体酒精"
    ]
    assert metadata["value_groups"] == {
        "appliance": ["燃气炉", "电磁炉", "酒精炉", "卡式炉"],
        "fuel_source": ["高山气罐", "卡式气罐", "液体酒精"],
        "heating_method": ["明火直烧"],
        "other": [],
    }
    proof_by_value = {proof["value"]: proof for proof in metadata["value_proofs"]}
    assert proof_by_value["燃气炉"]["source_skus"] == ["AGG-POT-1", "AGG-POT-2"]
    assert proof_by_value["高山气罐"]["source_skus"] == ["AGG-POT-1"]
    assert proof_by_value["卡式气罐"]["source_skus"] == ["AGG-POT-2"]
    assert proof_by_value["液体酒精"]["source_skus"] == ["AGG-POT-2"]
    assert {value: proof["value_type"] for value, proof in proof_by_value.items()} == {
        "燃气炉": "appliance", "电磁炉": "appliance", "高山气罐": "fuel_source",
        "明火直烧": "heating_method", "酒精炉": "appliance", "卡式炉": "appliance",
        "卡式气罐": "fuel_source", "液体酒精": "fuel_source",
    }
    assert "异丁烷气罐" not in payload["answer"]
    appliance_text, remainder = payload["answer"].split("另外", 1)
    assert all(value in appliance_text for value in ("燃气炉", "电磁炉", "酒精炉", "卡式炉"))
    assert all(value not in appliance_text for value in ("高山气罐", "卡式气罐", "液体酒精", "明火直烧"))
    assert all(value in remainder for value in ("高山气罐", "卡式气罐", "液体酒精", "明火直烧"))
    assert all(token not in payload["answer"] for token in ("heat_source", "subject_category", "filtered_rows"))
    assert payload["result_skus"] == payload["candidate_skus"] == []
    assert payload["debug"]["binding_provenance"] == "none"
    assert payload["debug"]["search_top1_promotion_blocked"] is True


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        ("燃气炉", "appliance"),
        ("卡式炉", "appliance"),
        ("电磁炉", "appliance"),
        ("酒精炉", "appliance"),
        ("燃气灶", "appliance"),
        ("高山气罐", "fuel_source"),
        ("卡式气罐", "fuel_source"),
        ("液体酒精", "fuel_source"),
        ("95%液体工业酒精", "fuel_source"),
        ("木柴", "fuel_source"),
        ("竹炭", "fuel_source"),
        ("明火直烧", "heating_method"),
        ("未分类热能", "other"),
    ],
)
def test_heat_source_value_typing_uses_specific_suffixes_before_fuel_terms(value, value_type):
    assert classify_heat_source_value(value) == value_type


def test_non_heat_source_aggregations_do_not_receive_heat_source_value_groups():
    rows = _synthetic_category_aggregation_rows()
    capacity = customer_service_service.customer_structured_query_contract.aggregate_category_field_rows(
        rows, build_structured_query_contract("水杯都有哪些容量")
    )
    material = customer_service_service.customer_structured_query_contract.aggregate_category_field_rows(
        rows, build_structured_query_contract("锅具有哪些材质")
    )

    assert "value_groups" not in capacity
    assert "value_groups" not in material
    assert all("value_type" not in proof for proof in capacity["value_proofs"] + material["value_proofs"])


def _entity_state(status="generic", *, resolved_sku=None, candidates=None, confidence="low", matched_by="none"):
    return SimpleNamespace(
        status=status,
        resolved_sku=resolved_sku,
        resolver_candidate_skus=list(candidates or []),
        confidence=confidence,
        matched_by=matched_by,
        is_unique=bool(resolved_sku),
    )




def test_category_general_precedes_single_product_generic_clarification():
    decision = customer_service_service._classify_phase2_entity_state_action(
        "杯子的容量是多少",
        {"primary_intent": "product_field"},
        signals={"category_general": True},
        entity_resolution_context={
            "entity_subject_selection": SimpleNamespace(entity_subject="杯子"),
            "contract": _entity_state(),
            "products_snapshot": [],
        },
    )

    assert decision == {"action": "pass_through", "reason": "category_field_general"}






@pytest.mark.parametrize(
    ("question", "subject", "expected_values", "expected_skus"),
    [
        ("锅具有哪些材质", "锅具", ["硬质氧化铝合金", "304不锈钢"], [["AGG-POT-1"], ["AGG-POT-2"]]),
        ("帐篷一般是什么材质", "帐篷", ["涤纶布"], [["AGG-TENT-1"]]),
        ("帐篷通常是什么材质", "帐篷", ["涤纶布"], [["AGG-TENT-1"]]),
    ],
)
def test_category_material_aggregation_recognizes_general_syntax_without_entity_binding(
    structured_client, monkeypatch, question, subject, expected_values, expected_skus
):
    rows = _synthetic_category_aggregation_rows()
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, question)

    contract = payload["answer_metadata"]["structured_query_contract"]
    assert contract["status"] == "generic"
    assert (contract["subject_category"], contract["field"]) == (subject, "material")
    assert payload["debug"]["agent_mode"] == "category_field_general"
    assert payload["answer_metadata"]["aggregated_values"] == expected_values
    assert [proof["source_skus"] for proof in payload["answer_metadata"]["value_proofs"]] == expected_skus
    assert payload["result_skus"] == payload["candidate_skus"] == []


def test_category_aggregation_with_no_field_data_is_honest_and_keeps_no_binding(
    structured_client, monkeypatch
):
    rows = [
        {"sku": "AGG-TENT-X", "product_name_cn": "缺失材质帐篷", "category": "帐篷", "body_material": "/"}
    ]
    monkeypatch.setattr(customer_service_service, "_phase1_catalog_rows", lambda db, ref: list(rows))

    payload = _ask(structured_client, "帐篷有哪些材质")

    assert payload["answer_metadata"]["aggregated_values"] == []
    assert payload["answer_metadata"]["value_proofs"] == []
    assert "当前已标注的商品资料中没有找到明确的材质信息" in payload["answer"]
    assert payload["result_skus"] == payload["candidate_skus"] == []
    assert payload["debug"]["binding_provenance"] == "none"
    assert payload["debug"]["search_top1_promotion_blocked"] is True
def test_structured_contract_keeps_exact_316l_material_grade():
    contract = build_structured_query_contract("\u6709\u6ca1\u6709316L\u4e0d\u9508\u94a2\u7684\u6237\u5916\u5957\u9505?")

    assert contract.status == "resolved"
    assert contract.field == "material"
    assert contract.value == "316L\u4e0d\u9508\u94a2"
    assert evaluate_structured_row(
        {"sku": "GRADE-316L", "category": "\u9505\u5177", "product_name_cn": "316L\u5957\u9505", "body_material": "316L\u4e0d\u9508\u94a2"},
        contract,
    )["matched"] is True
    assert evaluate_structured_row(
        {"sku": "GRADE-304", "category": "\u9505\u5177", "product_name_cn": "304\u5957\u9505", "body_material": "304\u4e0d\u9508\u94a2"},
        contract,
    )["matched"] is False
