import inspect

import pytest

from app.models.product import Product
from app.services import customer_entity_resolution_contract, customer_service_service
from app.services.customer_entity_resolution_contract import build_entity_resolution_contract, build_entity_resolution_contract_observation
from app.services.customer_field_contract import (
    detect_field_contract,
    field_contract_metadata,
    is_supported_detail_field,
    semantic_preplan_field_type,
)


def _product(sku: str, name: str, category: str = "锅具") -> Product:
    return Product(id=f"id-{sku}", sku=sku, product_name_cn=name, product_name_en=name, category=category)


@pytest.mark.parametrize(
    ("question", "field_type"),
    [
        ("某商品的货号是多少", "model"),
        ("某商品的SKU是什么", "model"),
        ("某商品大小是多少", "dimensions"),
        ("某商品收纳尺寸是多少", "dimensions"),
        ("某商品规格是什么", "specification"),
        ("某商品容量是多少", "capacity"),
        ("某商品净重是多少", "weight"),
        ("某商品几个人用", "people"),
        ("某商品材质是什么", "material"),
        ("某商品颜色是什么", "color"),
        ("某商品适用热源是什么", "heat_source"),
        ("某商品能进洗碗机吗", "dishwasher"),
        ("某商品有赠品吗", "gift"),
        ("某商品多少钱", "price"),
        ("某商品包含什么", "accessories"),
    ],
)
def test_field_contract_classifies_shared_aliases(question, field_type):
    assert detect_field_contract(question).field_type == field_type


def test_field_contract_maps_only_existing_planner_enum_values():
    assert semantic_preplan_field_type("model") == "unknown"
    assert semantic_preplan_field_type("capacity") == "capacity"
    assert field_contract_metadata("某商品型号是什么") == {
        "contract_field_type": "model",
        "planner_compatible_field_type": "unknown",
    }


def test_field_contract_separates_recognized_from_supported_detail_fields():
    assert detect_field_contract("某商品价格是多少").field_type == "price"
    assert is_supported_detail_field("price") is False
    assert is_supported_detail_field("gift") is False
    assert is_supported_detail_field("dimensions") is True
    assert is_supported_detail_field("model") is True


def test_entity_contract_resolves_unique_canonical_name_with_model_field():
    product = _product("AA-100", "晨曦Pro水壶")
    result = build_entity_resolution_contract("晨曦Pro水壶的商品编码是什么", [product])
    assert result.status == "resolved"
    assert result.resolved_sku == "AA-100"
    assert result.matched_by == "canonical_name_exact"
    assert result.field_type == "model"


def test_entity_contract_keeps_version_tokens_distinct_for_exact_variants():
    products = [_product("AA-100", "晨曦Pro水壶"), _product("AA-200", "晨曦Plus水壶")]
    result = build_entity_resolution_contract("晨曦Plus水壶的容量", products)
    assert result.status == "resolved"
    assert result.resolved_sku == "AA-200"


def test_entity_contract_resolves_display_prefix_alias_without_changing_resolver_behavior():
    product = _product("CH-200", "2.0版本-远行折叠椅", "桌椅")
    result = build_entity_resolution_contract("远行折叠椅尺寸是多少", [product])
    assert result.status == "resolved"
    assert result.matched_by == "normalized_alias_exact"
    assert result.field_type == "dimensions"


def test_entity_contract_parses_dimension_state_modifier_as_part_of_field_tail():
    product = _product("CH-201", "1.1版本-远行包包椅", "桌椅")
    result = build_entity_resolution_contract("远行包包椅展开后尺寸是多少", [product])
    assert result.status == "resolved"
    assert result.entity_text == "远行包包椅"
    assert result.resolved_sku == "CH-201"
    assert result.field_type == "dimensions"


def test_entity_contract_resolves_leading_display_label_alias_with_formal_candidate():
    product = _product("CP-201", "（渠道专属）晨光户外杯", "水具")
    result = build_entity_resolution_contract("晨光户外杯的大小是多少", [product], resolver_candidates=[product])
    assert result.status == "resolved"
    assert result.matched_by == "normalized_alias_exact"


def test_entity_contract_keeps_family_and_weak_matches_ambiguous():
    products = [_product("KT-1", "远野Max水壶"), _product("KT-2", "远野Pro水壶")]
    result = build_entity_resolution_contract("远野水壶的规格", products)
    assert result.status == "ambiguous"
    assert result.resolved_sku is None
    assert set(result.candidate_skus) == {"KT-1", "KT-2"}


def test_entity_contract_rejects_generic_and_unresolved_inputs():
    generic = build_entity_resolution_contract("水壶容量是多少", [_product("KT-1", "远野水壶")])
    unresolved = build_entity_resolution_contract("不存在名称的型号", [_product("KT-1", "远野水壶")])
    assert generic.status == "generic"
    assert generic.resolved_sku is None
    assert unresolved.status == "unresolved"
    assert unresolved.resolved_sku is None


def test_entity_contract_preserves_explicit_sku_evidence():
    product = _product("AB-123", "晨曦水壶")
    result = build_entity_resolution_contract("AB-123 的型号", [product])
    assert result.status == "resolved"
    assert result.matched_by == "sku_exact"
    assert result.confidence == "high"


def test_entity_contract_keeps_formal_unique_candidate_when_tail_span_is_imperfect():
    product = _product("AA-100", "晨曦Pro水壶")
    result = build_entity_resolution_contract(
        "晨曦Pro水壶，型号怎么查",
        [product],
        resolver_candidates=[product],
    )
    assert result.status != "generic"
    assert result.resolver_candidate_skus == ["AA-100"]
    assert result.candidate_skus == ["AA-100"]


def test_entity_contract_keeps_formal_multiple_candidates_when_tail_contains_how_to_choose():
    products = [_product("AA-100", "晨曦Pro水壶"), _product("AA-200", "晨曦Plus水壶")]
    result = build_entity_resolution_contract(
        "晨曦水壶的规格怎么选",
        products,
        resolver_candidates=products,
    )
    assert result.status == "ambiguous"
    assert result.resolver_candidate_skus == ["AA-100", "AA-200"]
    assert result.diagnostic_candidate_skus == []


def test_entity_contract_separates_diagnostic_family_candidates():
    products = [_product("KT-1", "远野Max水壶"), _product("KT-2", "远野Pro水壶")]
    result = build_entity_resolution_contract("远野水壶的规格", products, resolver_candidates=[])
    assert result.status == "ambiguous"
    assert result.resolver_candidate_skus == []
    assert set(result.diagnostic_candidate_skus) == {"KT-1", "KT-2"}
    assert result.status_reason == "diagnostic_family_overlap"


def test_diagnostic_only_candidate_never_becomes_resolved():
    product = _product("KT-1", "远野Max水壶")
    result = build_entity_resolution_contract("远野水壶的规格", [product], resolver_candidates=[])
    assert result.status == "ambiguous"
    assert result.resolved_sku is None
    assert result.resolver_candidate_skus == []
    assert result.diagnostic_candidate_skus == ["KT-1"]


def test_contract_observation_isolates_contract_exceptions(monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("contract-only failure")

    monkeypatch.setattr(customer_entity_resolution_contract, "build_entity_resolution_contract", boom)
    observation = build_entity_resolution_contract_observation("某商品型号", [])
    assert "entity_resolution_contract" not in observation
    assert observation["entity_resolution_contract_error"].startswith("ValueError:")


def test_contract_is_not_injected_into_semantic_preplan_input_or_global_product_query():
    source = inspect.getsource(customer_service_service.ask_customer_service)
    assert "db.query(Product).all()" not in source
    preplan_call = source.index("_maybe_run_semantic_preplan")
    arbitration_call = source.index("_phase2_entity_state_arbitration_result")
    assert preplan_call < arbitration_call
