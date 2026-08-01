import asyncio
import json

import pytest

from app.models import Product, ProductSpecs
from app.services import customer_agent_intent_service, customer_agent_planner_service, customer_service_service
from app.services.customer_field_contract import is_supported_detail_field
from test_customer_service_route_level_regression import _add_product, route_client_and_db


def _seed_phase2_products(Session):
    with Session() as db:
        rows = (
            ("RT-P2-100", "晨雾Plus水壶", "水具", "1.2L", "铝合金", "明火", "快速加热卖点", "露营", 420),
            ("RT-P2-200", "2.0版本-远行折叠椅", "桌椅", "18L", "铝合金", "", "轻量收纳卖点", "露营", 1800),
            ("RT-P2-300", "山影Pro烤盘", "锅具", "2L", "铝合金", "卡式炉", "均匀导热卖点", "煎烤", 760),
            ("RT-P2-401", "云途水壶", "水具", "1L", "铝合金", "明火", "版本一", "露营", 380),
            ("RT-P2-402", "云途水壶", "水具", "1.5L", "铝合金", "明火", "版本二", "露营", 430),
            ("RT-P2-500", "暮色单人椅", "桌椅", "12L", "铝合金", "", "便携卖点", "露营", 1500),
            ("RT-P2-600", "雾岭组合椅", "桌椅", "9L", "铝合金", "", "组合结构", "露营", 1600),
        )
        for row in rows:
            _add_product(db, *row)
        sizes = {
            "RT-P2-100": "20 x 14 x 18 cm",
            "RT-P2-200": "48 x 38 x 72 cm",
            "RT-P2-300": "32 x 28 x 4 cm",
            "RT-P2-401": "16 x 12 x 15 cm",
            "RT-P2-402": "18 x 14 x 17 cm",
        }
        for sku, size in sizes.items():
            product_id = db.query(Product.id).filter(Product.sku == sku).scalar()
            db.query(ProductSpecs).filter(ProductSpecs.product_id == product_id).update({"size_info": size})
        polluted_id = db.query(Product.id).filter(Product.sku == "RT-P2-600").scalar()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == polluted_id).update(
            {
                "size_info": json.dumps(
                    [
                        {"label": "收纳袋尺寸", "value": "40 x 30 x 8", "unit": "cm"},
                        {"label": "支架展开尺寸", "value": "95 x 5", "unit": "cm"},
                    ],
                    ensure_ascii=False,
                )
            }
        )
        db.commit()


@pytest.fixture()
def phase2_client(route_client_and_db):
    client, headers, Session = route_client_and_db
    _seed_phase2_products(Session)
    return client, headers


@pytest.mark.parametrize(
    ("question", "sku"),
    [
        ("晨雾Plus水壶的货号是多少", "RT-P2-100"),
        ("晨雾Plus水壶商品编码怎么查", "RT-P2-100"),
        ("RT-P2-300 的 SKU 是什么", "RT-P2-300"),
    ],
)
def test_phase2_exact_name_or_sku_record_key_precedes_category_route(phase2_client, question, sku):
    client, headers = phase2_client
    payload = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers).json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == [sku], payload
    assert sku in str(payload.get("answer") or ""), payload
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_detail_contract", payload


def test_phase2_display_prefix_alias_dimensions_precedes_category_route(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "远行折叠椅展开后尺寸是多少"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["RT-P2-200"], payload
    assert "48 x 38 x 72 cm" in payload["answer"], payload
    assert "18L" not in payload["answer"], payload


def test_phase2_exact_version_specification_keeps_single_product(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "山影Pro烤盘的规格是什么"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    # This used to protect the pre-structured-specification missing-value
    # behavior.  The formal field contract now intentionally composes valid
    # same-SKU specification columns, so retain and strengthen the identity,
    # field, evidence, and answer-safety assertions instead of expecting a
    # false missing-data response.
    assert payload["answer_type"] == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-300", payload
    assert entity.get("field_type") == "specification", payload
    assert payload.get("candidate_skus") == ["RT-P2-300"], payload
    assert payload.get("result_skus") == ["RT-P2-300"], payload
    assert metadata.get("contract_field_type") == "specification", payload
    assert metadata.get("evidence_field") == "specification", payload
    assert metadata.get("evidence_source") == "specification.summary", payload
    assert metadata.get("evidence_sku") == "RT-P2-300", payload
    answer = str(payload.get("answer") or "")
    for expected in ("32 x 28 x 4 cm", "2L", "760g", "铝合金", "本色"):
        assert expected in answer, payload
    assert "760.0g" not in answer, payload


def test_phase2_purchase_channel_ignores_field_like_token_inside_product_name(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "山影Pro烤盘在哪里有售卖"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert entity.get("resolved_sku") == "RT-P2-300", payload
    assert entity.get("field_type") == "purchase_channel", payload
    assert payload.get("result_skus") == ["RT-P2-300"], payload
    assert metadata.get("contract_field_type") == "purchase_channel", payload
    assert metadata.get("evidence_status") == "missing", payload
    assert "配件" not in str(payload.get("answer") or ""), payload


def test_phase2_selling_point_consumes_structured_policy_evidence(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "山影Pro烤盘的核心卖点是什么"},
        headers=headers,
    ).json()

    metadata = payload.get("answer_metadata") or {}
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["RT-P2-300"], payload
    assert "均匀导热卖点" in str(payload.get("answer") or ""), payload
    assert metadata.get("evidence_source") == "business.top_selling_points", payload
    assert metadata.get("evidence_sku") == "RT-P2-300", payload


def test_field_evidence_provider_never_re_resolves_a_sealed_identity_from_raw_question(route_client_and_db):
    _client, _headers, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._product_field_followup_result(
            db,
            "RT-P2-100",
            "heat_source",
            "山影Pro烤盘支持什么热源？",
            identity_source="phase2_resolved_entity",
        )

    assert result is not None
    assert result.get("result_skus") == ["RT-P2-100"], result
    assert result.get("candidate_skus") == ["RT-P2-100"], result
    metadata = result.get("answer_metadata") or {}
    assert metadata.get("evidence_sku") == "RT-P2-100", result
    assert "RT-P2-300" not in str(result.get("answer") or ""), result


def test_phase1_catalog_count_accepts_discourse_prefix_but_not_product_capacity():
    count_plan = customer_agent_planner_service.plan_customer_question("我们有多少个锅")
    field_plan = customer_agent_planner_service.plan_customer_question("这口锅容量多少")

    assert count_plan.get("primary_intent") == "catalog_count"
    assert count_plan.get("product_ref") == "锅具"
    assert customer_service_service._looks_like_semantic_catalog_query("我们有多少个锅") is True
    assert field_plan.get("primary_intent") != "catalog_count"


def test_phase2_ambiguous_family_does_not_bind_first_candidate(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "云途水壶的规格怎么选"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("debug", {}).get("agent_mode") == "entity_state_detail_ambiguous", payload
    assert payload.get("result_skus") in ([], None), payload
    assert set(payload.get("candidate_skus") or []) == {"RT-P2-401", "RT-P2-402"}, payload
    assert "云途水壶" in payload["answer"] and "规格怎么选" not in payload["answer"], payload


def test_phase2_unresolved_product_does_not_bind_catalog_sku(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "雾海远征壶的型号是什么"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "clarification", payload
    assert payload.get("debug", {}).get("agent_mode") == "entity_state_detail_unresolved", payload
    assert payload.get("result_skus") in ([], None), payload
    assert payload.get("candidate_skus") in ([], None), payload
    assert "雾海远征壶" in payload["answer"] and "型号" not in payload["answer"].split("”")[0], payload


def test_phase2_generic_category_field_stays_outside_single_product_gate(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "水壶容量怎么看"},
        headers=headers,
    ).json()

    # This protects the category boundary rather than the pre-aggregation
    # single-product clarification used before the structured category
    # contract existed.  The request must remain unbound while consuming only
    # capacity evidence from the water-kettle category.
    metadata = payload.get("answer_metadata") or {}
    contract = metadata.get("structured_query_contract") or {}
    assert payload.get("debug", {}).get("agent_mode") == "category_field_general", payload
    assert payload.get("answer_type") == "product_query", payload
    assert payload.get("result_skus") == [], payload
    assert payload.get("candidate_skus") == [], payload
    assert contract.get("status") == "generic", payload
    assert contract.get("subject_category") == "水壶", payload
    assert contract.get("field") == "capacity", payload
    assert metadata.get("aggregated_values"), payload
    assert all(proof.get("field_source") == "capacity" for proof in metadata.get("value_proofs") or []), payload
    assert payload.get("debug", {}).get("binding_provenance") == "none", payload
    assert payload.get("debug", {}).get("search_top1_promotion_blocked") is True, payload


def test_phase2_second_generic_category_field_blocks_search_top1_promotion(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "椅子重量怎么看"},
        headers=headers,
    ).json()

    assert payload.get("answer_type") != "product_detail", payload
    assert len(payload.get("result_skus") or []) != 1, payload
    assert payload.get("debug", {}).get("binding_provenance") == "none", payload
    assert payload.get("debug", {}).get("search_top1_promotion_blocked") is True, payload


@pytest.mark.parametrize("provenance", ["search_top1", "query_rows_top1", "fallback_rank_top1", "retrieval_top1"])
def test_search_candidate_promotions_share_one_binding_policy(provenance):
    assert customer_agent_intent_service._can_promote_candidate_to_single_product(
        allow_search_top1_promotion=False,
        binding_provenance=provenance,
    ) is False
    assert customer_agent_intent_service._can_promote_candidate_to_single_product(
        allow_search_top1_promotion=True,
        binding_provenance=provenance,
    ) is True


def test_explicit_sku_detail_remains_legal_when_search_promotion_is_disabled(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        payload = asyncio.run(
            customer_agent_intent_service.process_intent_request(
                db,
                user_id="phase2-policy-test",
                question="RT-P2-100 的 SKU 是什么",
                allow_llm_fallback=False,
                allow_search_top1_promotion=False,
            )
        )

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    # Explicit SKU text is resolver evidence, not permission to bypass the
    # central entity contract.  Disabling search promotion must still allow
    # the exact SKU while preserving the sealed-identity provenance.
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("candidate_skus") == ["RT-P2-100"], payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert debug.get("binding_provenance") == "resolved_entity_contract", payload
    assert debug.get("search_top1_promotion_blocked") is False, payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-100", payload
    assert entity.get("matched_by") == "sku_exact", payload
    assert entity.get("field_type") == "sku", payload
    assert metadata.get("contract_field_type") == "sku", payload
    assert metadata.get("evidence_field") == "sku", payload
    assert metadata.get("evidence_source") == "product.sku", payload
    assert metadata.get("evidence_sku") == "RT-P2-100", payload


def test_exact_name_detail_uses_entity_contract_without_search_promotion(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        payload = asyncio.run(
            customer_agent_intent_service.process_intent_request(
                db,
                user_id="phase2-policy-default-test",
                question="晨雾Plus水壶容量是多少",
                allow_llm_fallback=False,
            )
        )

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}

    # A canonical full-name match is deterministic entity evidence.  It must
    # not be represented as search top-1 promotion now that the formal entity
    # contract precedes the compatibility executor.
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("candidate_skus") == ["RT-P2-100"], payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert debug.get("binding_provenance") == "resolved_entity_contract", payload
    assert debug.get("search_top1_promotion_blocked") is False, payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-100", payload
    assert entity.get("matched_by") == "canonical_name_exact", payload
    assert entity.get("field_type") == "capacity", payload
    assert metadata.get("contract_field_type") == "capacity", payload
    assert metadata.get("evidence_field") == "capacity", payload
    assert metadata.get("evidence_source") == "specs.capacity", payload
    assert metadata.get("evidence_sku") == "RT-P2-100", payload


def test_phase2_exact_product_gift_preserves_unknown_field_safety_guard(phase2_client):
    question = "晨雾Plus水壶有赠品记录吗"
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback", payload
    assert (payload.get("debug", {}).get("plan") or {}).get("raw_question") == question, payload
    assert "未标注" in payload["answer"], payload


@pytest.mark.parametrize(
    "question",
    [
        "价格现在如何确认",
        "云途水壶售价有记录吗",
    ],
)
def test_phase2_recognized_unsupported_field_requires_entity_contract_before_safe_missing(route_client_and_db, question):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._phase2_entity_state_arbitration_result(
            db,
            question,
            {"primary_intent": "product_field", "requested_field": "价格"},
            conversation_id=None,
            signals={},
        )

    assert is_supported_detail_field("price") is False
    if result is None:
        # No concrete product subject exists, so no product fact or entity
        # binding is permitted.
        return
    # The old expectation protected a pre-contract bypass. A recognised
    # safety field still forms FieldContract + EntityResolutionContract;
    # ambiguity must be surfaced rather than selecting a product or dropping
    # into a generic commercial answer.
    assert result["answer_type"] == "clarification", result
    assert result["debug"]["agent_mode"] == "entity_state_detail_ambiguous", result
    assert result["candidate_skus"] == ["RT-P2-401", "RT-P2-402"], result
    assert result["result_skus"] == [], result
    entity = result["debug"]["entity_resolution_contract"]
    assert entity["status"] == "ambiguous", result
    assert entity["field_type"] == "price", result


def test_phase2_explicit_sku_unsupported_field_keeps_unknown_field_safety(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "RT-P2-100 当前售价有记录吗"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert payload.get("debug", {}).get("agent_mode") == "resolved_entity_unknown_field_fallback", payload
    # The central safe-missing formatter may use either “未标注” or
    # “暂未找到”; preserve the actual safety invariant instead of pinning a
    # single wording: it must identify the requested price and never invent a
    # current sale price for this exact entity.
    answer = str(payload.get("answer") or "")
    assert "价格" in answer, payload
    assert any(term in answer for term in ("未标注", "暂未找到")), payload
    assert "当前售价：" not in answer, payload


@pytest.mark.parametrize(
    ("question", "expected_field"),
    [
        ("RT-P2-100 当前售价有记录吗", "price"),
        ("RT-P2-100 现在有现货吗", "inventory"),
        ("RT-P2-100 保修多久", "warranty"),
        ("RT-P2-100 下单后几天发出", "shipping"),
        ("RT-P2-100 怎么联系售后", "after_sales_contact"),
    ],
)
def test_high_risk_safe_missing_routes_expose_formal_field_contract(
    phase2_client,
    question,
    expected_field,
):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    field_contract = debug.get("field_contract") or (debug.get("plan") or {}).get("field_contract") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert debug.get("agent_mode") == "resolved_entity_unknown_field_fallback", payload
    assert field_contract.get("field_type") == expected_field, payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-100", payload
    assert entity.get("field_type") == expected_field, payload
    assert payload.get("candidate_skus") == ["RT-P2-100"], payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert metadata.get("contract_field_type") == expected_field, payload
    assert metadata.get("field_evidence_missing") is True, payload


@pytest.mark.parametrize(
    ("question", "expected_field", "expected_status", "expected_source"),
    [
        ("RT-P2-100的条码是什么？", "barcode", "structured", "product.barcode"),
        ("RT-P2-100属于哪个产品系列？", "series", "missing", None),
        ("RT-P2-100是什么时候上市的？", "launch_date", "missing", None),
        ("RT-P2-100的生命周期状态是什么？", "lifecycle_status", "structured", "product.lifecycle_status"),
        ("晨雾Plus水壶的生命周期状态是什么？", "lifecycle_status", "structured", "product.lifecycle_status"),
        ("RT-P2-100表面用了什么处理工艺？", "surface_finish", "structured", "specs.surface_finish"),
        ("RT-P2-100的产品定位是什么？", "positioning", "structured", "business.positioning"),
        ("RT-P2-100属于什么价格定位？", "price_positioning", "structured", "business.price_positioning"),
        ("RT-P2-100强调的情感价值是什么？", "emotional_value", "missing", None),
        ("RT-P2-100目前面向哪些地区销售？", "sales_region", "missing", None),
        ("RT-P2-100有哪些产品认证？", "certification", "missing", None),
    ],
)
def test_customer_relevant_database_fields_use_formal_contract_and_safe_evidence(
    phase2_client,
    question,
    expected_field,
    expected_status,
    expected_source,
):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    field_contract = debug.get("field_contract") or (debug.get("plan") or {}).get("field_contract") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    assert payload.get("answer_type") == "product_detail", payload
    assert debug.get("agent_mode") == "resolved_entity_detail_contract", payload
    assert field_contract.get("field_type") == expected_field, payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-100", payload
    assert entity.get("field_type") == expected_field, payload
    assert payload.get("candidate_skus") == ["RT-P2-100"], payload
    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert metadata.get("contract_field_type") == expected_field, payload
    assert metadata.get("evidence_status") == expected_status, payload
    assert metadata.get("evidence_source") == expected_source, payload
    if expected_status == "structured":
        assert metadata.get("evidence_sku") == "RT-P2-100", payload
    else:
        assert metadata.get("evidence_sku") is None, payload
    if expected_field == "lifecycle_status":
        assert "非实时库存" in str(payload.get("answer") or ""), payload


def test_phase2_supported_ambiguous_and_resolved_fields_keep_entity_arbitration(phase2_client):
    client, headers = phase2_client
    ambiguous = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "云途水壶的尺寸怎么选"},
        headers=headers,
    ).json()
    resolved = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶的产品编码怎么查"},
        headers=headers,
    ).json()

    assert is_supported_detail_field("dimensions") is True
    assert ambiguous["answer_type"] == "clarification", ambiguous
    assert ambiguous.get("debug", {}).get("agent_mode") == "entity_state_detail_ambiguous", ambiguous
    assert resolved["answer_type"] == "product_detail", resolved
    assert resolved.get("debug", {}).get("agent_mode") == "resolved_entity_detail_contract", resolved


def test_unsupported_field_ignores_semantic_product_detail_hint(route_client_and_db):
    _, _, Session = route_client_and_db
    with Session() as db:
        result = customer_service_service._pre_route_high_risk_contract_result(
            db,
            "价格现在多少？",
            {
                "called": True,
                "route_family": "product_bound_qa",
                "route_hint": "product_detail",
                "question_type": "field",
                "field_type": "price",
                "subtype": "known_detail",
                "entity_scope": "generic_scope",
                "entities": [],
            },
        )

    assert is_supported_detail_field("price") is False
    assert result is not None
    assert result["answer_type"] == "product_detail", result
    assert result.get("debug", {}).get("agent_mode") != "entity_scope_ambiguous_clarification", result


def test_phase2_missing_dimension_evidence_preserves_resolved_sku(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "暮色单人椅的收纳尺寸有多大"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    entity = debug.get("entity_resolution_contract") or {}
    metadata = payload.get("answer_metadata") or {}
    answer = str(payload.get("answer") or "")
    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("candidate_skus") == ["RT-P2-500"], payload
    assert payload.get("result_skus") == ["RT-P2-500"], payload
    assert entity.get("status") == "resolved", payload
    assert entity.get("resolved_sku") == "RT-P2-500", payload
    assert entity.get("field_type") == "dimensions", payload
    assert metadata.get("contract_field_type") == "dimensions", payload
    assert metadata.get("evidence_status") == "missing", payload
    assert metadata.get("evidence_sku") is None, payload
    assert "暂未找到" in answer and "收纳尺寸" in answer, payload
    assert "12L" not in answer, payload


def test_phase2_missing_model_number_does_not_substitute_sku_or_selling_points(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶型号是什么"},
        headers=headers,
    ).json()

    assert payload.get("result_skus") == ["RT-P2-100"], payload
    assert "当前资料未标注" in payload["answer"], payload
    assert "SKU：RT-P2-100" not in payload["answer"], payload
    assert "快速加热卖点" not in payload["answer"], payload
    assert payload.get("debug", {}).get("binding_provenance") == "resolved_entity_contract", payload
    # Exact identity is sealed by EntityResolutionContract; this safe-missing
    # route does not invoke search promotion at all.
    assert payload.get("debug", {}).get("search_top1_promotion_blocked") is not True, payload


@pytest.mark.parametrize(
    "question",
    [
        "家庭露营想选容量大的锅具",
        "晨雾Plus水壶的容量和重量分别是多少",
        "晨雾Plus水壶和山影Pro烤盘哪个尺寸大",
    ],
)
def test_phase2_arbitration_exits_recommendation_compound_and_comparison(phase2_client, question):
    client, headers = phase2_client
    payload = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers).json()

    assert payload.get("debug", {}).get("agent_mode") not in {
        "resolved_entity_detail_contract",
        "entity_state_detail_ambiguous",
        "entity_state_detail_unresolved",
        "entity_state_detail_generic_category",
    }, payload
    if "哪个尺寸大" in question:
        assert set(payload.get("result_skus") or []) == {"RT-P2-100", "RT-P2-300"}, payload
        answer = str(payload.get("answer") or "")
        assert "RT-P2-100" in answer and "RT-P2-300" in answer, payload


@pytest.mark.parametrize(
    "question",
    [
        "RT-P2-100容量多大？适合什么场景？",
        "RT-P2-100容量多大？能不能用酒精炉？",
        "RT-P2-100容量多大？保修有记录吗？",
        "晨雾Plus水壶容量多大？适合什么场景？",
    ],
)
def test_phase2_exact_entity_additional_intents_block_single_field_gate(route_client_and_db, question):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    plan = customer_agent_planner_service.plan_customer_question(question)
    requested_fields = customer_agent_intent_service._requested_fields_for_detail_question(question)
    signals = customer_service_service._phase2_entity_arbitration_signals(question, plan, None)

    with Session() as db:
        result = customer_service_service._phase2_entity_state_arbitration_result(
            db,
            question,
            plan,
            conversation_id=None,
            signals=signals,
        )

    assert len(requested_fields) > 1
    assert signals.get("multi_field") is True
    assert signals.get("additional_user_intent") is True
    assert signals.get("compound") is True
    assert result is None


def test_phase2_exact_entity_single_supported_field_still_uses_detail_gate(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    question = "RT-P2-100容量多大？"
    plan = customer_agent_planner_service.plan_customer_question(question)
    signals = customer_service_service._phase2_entity_arbitration_signals(question, plan, None)

    with Session() as db:
        result = customer_service_service._phase2_entity_state_arbitration_result(
            db,
            question,
            plan,
            conversation_id=None,
            signals=signals,
        )

    assert signals.get("additional_user_intent") is False
    assert result is not None
    assert result.get("debug", {}).get("agent_mode") == "resolved_entity_detail_contract"


def test_phase2_compound_http_keeps_existing_route_instead_of_single_field_gate(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "RT-P2-100容量多大？适合什么场景？能不能用酒精炉？"},
        headers=headers,
    ).json()

    debug = payload.get("debug") or {}
    assert debug.get("agent_mode") != "resolved_entity_detail_contract", payload
    assert payload.get("answer"), payload


def test_phase2_arbitration_does_not_intercept_multiturn_followup(phase2_client):
    client, headers = phase2_client
    first = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "推荐几款适合家庭露营的锅具"},
        headers=headers,
    ).json()
    second = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "第一款容量是多少", "conversation_id": first["conversation_id"]},
        headers=headers,
    ).json()

    assert second.get("debug", {}).get("agent_mode") != "entity_state_detail_unresolved", second


def test_phase2_component_dimension_evidence_is_not_used_as_product_dimensions(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "雾岭组合椅展开尺寸是多少"},
        headers=headers,
    ).json()

    assert payload["answer_type"] == "product_detail", payload
    assert payload.get("result_skus") == ["RT-P2-600"], payload
    assert payload.get("answer_metadata", {}).get("evidence_status") == "missing", payload
    assert "40 x 30 x 8" not in payload["answer"] and "95 x 5" not in payload["answer"], payload


def test_compound_orchestrator_resolves_every_requested_field_from_one_sku(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-100",
            requested_fields=["容量", "重量"],
            question="RT-P2-100容量和重量分别有记录吗？",
        )

    fields = result["answer_metadata"]["compound_fields"]
    assert [item["requested_field"] for item in fields] == ["容量", "重量"]
    assert fields[0]["evidence_field"] == "capacity"
    assert fields[0]["missing"] is False
    assert fields[1]["evidence_field"] == "weight"
    assert fields[1]["missing"] is False
    assert result["result_skus"] == ["RT-P2-100"]


def test_compound_orchestrator_keeps_missing_field_without_stopping(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-100",
            requested_fields=["容量", "保修"],
            question="RT-P2-100容量和保修分别有记录吗？",
        )

    fields = result["answer_metadata"]["compound_fields"]
    assert fields[0]["missing"] is False
    assert fields[1]["missing"] is True
    assert "保修" in result["answer"]
    assert result["result_skus"] == ["RT-P2-100"]


def test_compound_orchestrator_uses_same_sku_scene_evidence(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-100",
            requested_fields=["容量", "适用场景"],
            question="晨雾Plus水壶容量多大，通常适合哪些场景？",
        )

    fields = result["answer_metadata"]["compound_fields"]
    assert [item["evidence_sku"] for item in fields] == ["RT-P2-100", "RT-P2-100"]
    assert fields[1]["evidence_field"] == "usage_scene"
    assert fields[1]["evidence_source"] == "business.usage_scenarios"
    assert result["debug"]["agent_mode"] == "resolved_entity_compound_detail"


def test_compound_orchestrator_answers_capacity_heat_source_and_scene(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-100",
            requested_fields=["容量", "适用场景", "热源"],
            question="RT-P2-100容量如何，适用场景有哪些，支持明火吗？",
        )

    fields = result["answer_metadata"]["compound_fields"]
    assert [item["requested_field"] for item in fields] == ["容量", "适用场景", "热源"]
    assert all(item["evidence_sku"] == "RT-P2-100" for item in fields)
    assert len(result["answer"].splitlines()) >= 4


def test_requested_field_phrase_overlap_does_not_expand_dimensions_to_capacity():
    assert customer_service_service._phase2_requested_fields("RT-P2-300尺寸多大？能不能用酒精炉？") == ["尺寸", "热源"]


def test_compound_http_uses_resolved_contract_instead_of_reparsing_product_ref(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶容量多大？适合什么场景？"},
        headers=headers,
    ).json()

    # Compound FieldContracts now use the central multi-field executor.  This
    # preserves the same sealed entity and per-field evidence while avoiding
    # the former route that reparsed the product reference.
    assert payload["debug"]["agent_mode"] == "resolved_entity_multi_field_contract", payload
    assert payload["result_skus"] == ["RT-P2-100"], payload
    assert [item["requested_field"] for item in payload["answer_metadata"]["compound_fields"]] == ["容量", "适用场景"]
    assert "没有找到" not in payload["answer"]


def test_single_field_exact_name_stays_on_existing_detail_contract(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶容量有多少？"},
        headers=headers,
    ).json()

    assert payload["debug"]["agent_mode"] == "resolved_entity_detail_contract", payload
    assert payload["result_skus"] == ["RT-P2-100"], payload


def test_compound_heat_source_reuses_merged_product_detail_evidence(route_client_and_db, monkeypatch):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    original_get_detail = customer_service_service.product_service.get_product_detail

    def merged_detail(db, sku):
        detail = original_get_detail(db, sku)
        if sku == "RT-P2-200":
            detail.setdefault("specs", {})["heat_source"] = "明火、卡式炉"
        return detail

    monkeypatch.setattr(customer_service_service.product_service, "get_product_detail", merged_detail)
    with Session() as db:
        single = customer_service_service._product_field_followup_result(
            db, "RT-P2-200", "heat_source", "RT-P2-200能用明火吗？"
        )
        compound = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-200",
            requested_fields=["适用场景", "热源"],
            question="RT-P2-200适合哪些场景，也能用明火吗？",
        )

    heat = compound["answer_metadata"]["compound_fields"][1]
    assert "明火" in single["answer"]
    assert heat["missing"] is False
    assert "明火" in heat["evidence_value"]
    assert heat["evidence_source"] == "specs.heat_source"


def test_compound_orchestrator_preserves_compatibility_plan(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        result = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-100",
            requested_fields=["适用场景", "热源"],
            question="RT-P2-100适合哪些场景，也支持明火吗？",
            compatibility_plan={"primary_intent": "product_field", "requested_field": "heat_source"},
        )

    plan = result["debug"]["plan"]
    assert plan["product_ref"] == "RT-P2-100"
    assert plan["requested_field"] == "heat_source"
    assert plan["requested_fields"] == ["适用场景", "热源"]


def test_single_and_compound_heat_source_qa_evidence_have_matching_provenance(route_client_and_db):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        product = db.query(Product).filter(Product.sku == "RT-P2-300").first()
        db.query(ProductSpecs).filter(ProductSpecs.product_id == product.id).update({"heat_source": ""})
        db.add(
            customer_service_service.ProductQa(
                product_id=product.id,
                question="这款折叠椅能否使用酒精炉？",
                answer="同 SKU 资料明确说明支持酒精炉。",
                tags="热源,酒精炉",
                priority=200,
                integrity_status="approved",
            )
        )
        db.commit()
        single = customer_service_service._product_field_followup_result(
            db, "RT-P2-300", "heat_source", "RT-P2-300能不能用酒精炉？"
        )
        compound = customer_service_service._build_compound_product_detail_result(
            db,
            resolved_sku="RT-P2-300",
            requested_fields=["适用场景", "热源"],
            question="RT-P2-300适合哪些场景，也能不能用酒精炉？",
        )

    single_meta = single["answer_metadata"]
    compound_heat = compound["answer_metadata"]["compound_fields"][1]
    assert compound_heat["evidence_value"] == single_meta["evidence_value"]
    assert compound_heat["evidence_source"] == single_meta["evidence_source"] == "product_qa"
    assert compound_heat["evidence_sku"] == single_meta["evidence_sku"] == "RT-P2-300"
    assert compound_heat["missing"] is False


def test_attach_phase1_plan_prefers_runtime_effective_fields_and_keeps_timing():
    result = {
        "answer_metadata": {},
        "debug": {
            "plan": {
                "requested_field": "heat_source",
                "requested_fields": ["适用场景", "热源"],
                "product_ref": "RT-P2-100",
                "compound": True,
            }
        },
    }
    attached = customer_service_service._attach_phase1_plan_and_timing(
        result,
        {"requested_field": "scene", "product_ref": "截断实体"},
        {"planner_duration_ms": 12.0},
    )

    assert attached["debug"]["plan"]["requested_field"] == "heat_source"
    assert attached["debug"]["plan"]["requested_fields"] == ["适用场景", "热源"]
    assert attached["debug"]["plan"]["product_ref"] == "RT-P2-100"
    assert attached["debug"]["plan"]["compound"] is True
    assert attached["debug"]["timing"]["planner_duration_ms"] == 12.0


def test_attach_phase1_plan_uses_original_when_runtime_plan_is_absent():
    attached = customer_service_service._attach_phase1_plan_and_timing(
        {"answer_metadata": {}, "debug": {}},
        {"requested_field": "容量", "product_ref": "RT-P2-100"},
        {},
    )
    assert attached["debug"]["plan"] == {"requested_field": "容量", "product_ref": "RT-P2-100"}


def test_public_result_trace_always_preserves_raw_question_without_overwriting_effective_plan():
    result = {
        "answer_metadata": {"timing": {"total_duration_ms": 1}},
        "debug": {
            "timing": {"total_duration_ms": 1},
            "plan": {"requested_field": "manual", "product_ref": "RT-P2-100"},
        },
    }

    traced = customer_service_service._ensure_debug_plan_raw_question(
        result,
        "RT-P2-100有说明书吗？",
    )

    assert traced["debug"]["plan"] == {
        "requested_field": "manual",
        "product_ref": "RT-P2-100",
        "raw_question": "RT-P2-100有说明书吗？",
    }


@pytest.mark.parametrize(
    ("question", "expected_route"),
    [
        ("RT-P2-300第一次使用要注意哪些事项？", "usage_care"),
        ("RT-P2-300有哪些禁止操作和安全提示？", "usage_care"),
        ("RT-P2-300套装内具体包含什么？", "contents_grounding"),
    ],
)
def test_dedicated_semantic_route_excludes_compound_detail(question, expected_route):
    plan = customer_agent_planner_service.plan_customer_question(question)
    signals = customer_service_service._phase2_entity_arbitration_signals(question, plan, None)

    assert customer_service_service._dedicated_semantic_route(question) == expected_route
    assert signals["dedicated_route"] is True


def test_validated_semantic_field_ignores_field_words_inside_product_title():
    question = "旋焰炉芯（作为套装赠品）最大功率多少瓦？"
    semantic_preplan = {
        "called": True,
        "route_family": "product_bound_qa",
        "route_hint": "product_detail",
        "question_type": "field",
        "field_type": "power",
        "field_hint": "power",
        "subtype": "known_detail",
        "canonical_fields": ["power"],
        "confidence": 0.9,
        "confidence_label": "high",
    }
    plan = customer_agent_planner_service.plan_customer_question(question)
    plan["semantic_preplan"] = semantic_preplan
    field_request = customer_service_service.resolve_requested_field_contract(question, plan)

    assert field_request["source"] == "validated_semantic_preplan"
    assert field_request["canonical_fields"] == ["power"]
    signals = customer_service_service._phase2_entity_arbitration_signals(
        question,
        plan,
        semantic_preplan,
        field_request_override=field_request,
    )
    assert signals["multi_field"] is False
    assert signals["compound"] is False
    assert signals["dedicated_route"] is False


def test_semantic_mutually_plausible_fields_fail_closed_with_resolved_entity():
    class _Contract:
        def to_dict(self):
            return {
                "status": "resolved",
                "resolved_sku": "RT-P2-100",
                "candidate_skus": ["RT-P2-100"],
                "field_type": "dimensions",
            }

    result = customer_service_service._semantic_field_ambiguity_clarification_result(
        {
            "called": True,
            "route_hint": "product_detail",
            "canonical_fields": ["capacity", "dimensions"],
            "confidence": 0.9,
            "ambiguity": True,
        },
        {"contract": _Contract()},
    )

    assert result["answer_type"] == "clarification"
    assert result["result_skus"] == []
    assert result["candidate_skus"] == ["RT-P2-100"]
    assert result["debug"]["agent_mode"] == "semantic_field_ambiguity_clarification"
    assert result["debug"]["field_contract"]["canonical_fields"] == ["capacity", "dimensions"]
    assert result["debug"]["entity_resolution_contract"]["resolved_sku"] == "RT-P2-100"
    shaped = customer_service_service._shape_answer_for_output(result)
    assert shaped["answer"] == "这个问法可能对应多个字段。请确认你想查容量还是尺寸。"


def test_true_independent_detail_fields_remain_compound_eligible():
    question = "RT-P2-100容量和重量分别是多少？"
    plan = customer_agent_planner_service.plan_customer_question(question)
    signals = customer_service_service._phase2_entity_arbitration_signals(question, plan, None)

    assert customer_service_service._dedicated_semantic_route(question) == ""
    assert signals["dedicated_route"] is False
    assert signals["compound"] is True
    assert signals["multi_field"] is True


def test_usage_care_mixed_with_detail_field_does_not_enter_compound_orchestrator(phase2_client):
    client, headers = phase2_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "RT-P2-300容量有记录吗，第一次使用要注意什么？"},
        headers=headers,
    ).json()

    assert payload["debug"]["agent_mode"] != "resolved_entity_compound_detail", payload
    assert payload["result_skus"] == ["RT-P2-300"], payload


@pytest.mark.parametrize(
    ("question", "expected_fields", "expected_supported", "expected_unsupported"),
    [
        ("RT-P2-100 的型号是什么", ["型号"], [], ["model"]),
        ("RT-P2-100 容量和重量分别多少", ["容量", "重量"], ["capacity", "weight"], []),
        ("RT-P2-300 尺寸多大", ["尺寸"], ["dimensions"], []),
        ("RT-P2-100 价格现在多少", ["价格"], [], ["price"]),
        # U-S12 promotes accessories into the formal field/evidence contract;
        # gift remains safely unsupported and must not borrow accessories data.
        ("RT-P2-100 有赠品和配件吗", ["配件"], ["accessories"], ["gift"]),
        ("RT-P2-100 使用时有哪些注意事项", ["使用限制", "禁止操作"], [], []),
        ("RT-P2-100 容量多大，适合什么场景，能用酒精炉吗", ["容量", "适用场景", "热源"], ["capacity", "usage_scene", "heat_source"], []),
    ],
)
def test_requested_field_contract_adapter_preserves_phase2_field_parity(
    question,
    expected_fields,
    expected_supported,
    expected_unsupported,
):
    contract = customer_service_service.resolve_requested_field_contract(question, {})

    assert contract["requested_fields"] == expected_fields
    assert contract["supported_fields"] == expected_supported
    assert contract["unsupported_fields"] == expected_unsupported
    assert contract["compound"] is (len(expected_fields) > 1)


@pytest.mark.parametrize(
    ("question", "expected_mode", "expected_skus"),
    [
        ("晨雾Plus水壶的型号是什么", "resolved_entity_unknown_field_fallback", ["RT-P2-100"]),
        ("云途水壶的规格怎么选", "entity_state_detail_ambiguous", []),
        ("雾海远征壶的型号是什么", "entity_state_detail_unresolved", []),
        ("水壶容量怎么看", None, []),
        ("晨雾Plus水壶容量和重量分别多少", "resolved_entity_multi_field_contract", ["RT-P2-100"]),
    ],
)
def test_phase2_request_reuses_one_entity_contract_build(
    phase2_client,
    monkeypatch,
    question,
    expected_mode,
    expected_skus,
):
    client, headers = phase2_client
    original = customer_service_service.customer_entity_resolution_contract.build_entity_resolution_contract
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(
        customer_service_service.customer_entity_resolution_contract,
        "build_entity_resolution_contract",
        counted,
    )
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    ).json()
    assert len(calls) == 1, payload
    if expected_mode:
        assert payload.get("debug", {}).get("agent_mode") == expected_mode, payload
    else:
        assert payload.get("debug", {}).get("agent_mode") not in {
            "resolved_entity_detail_contract",
            "entity_state_detail_ambiguous",
            "entity_state_detail_unresolved",
            "resolved_entity_compound_detail",
        }, payload
    assert payload.get("result_skus") or [] == expected_skus


@pytest.mark.parametrize(
    ("question", "plan", "expected_action"),
    [
        ("晨雾Plus水壶的型号是什么", {"primary_intent": "product_field"}, "resolved_detail"),
        ("云途水壶的规格怎么选", {"primary_intent": "product_field"}, "ambiguous_clarification"),
        ("雾海远征壶的型号是什么", {"primary_intent": "product_field"}, "unresolved_clarification"),
        ("水壶容量怎么看", {"primary_intent": "product_field"}, "generic_clarification"),
        # A safety-bound commercial field still seals an exact entity before
        # the formatter returns its field-specific safe-missing answer.
        ("晨雾Plus水壶价格是多少", {"primary_intent": "product_field"}, "resolved_detail"),
        ("推荐晨雾Plus水壶的容量", {"primary_intent": "recommendation"}, "pass_through"),
    ],
)
def test_phase2_arbitration_decision_is_separate_from_response_formatting(
    route_client_and_db,
    question,
    plan,
    expected_action,
):
    _, _, Session = route_client_and_db
    _seed_phase2_products(Session)
    with Session() as db:
        context = customer_service_service._build_phase2_entity_resolution_context(db, question)
        signals = customer_service_service._phase2_entity_arbitration_signals(question, plan, None)
        decision = customer_service_service._classify_phase2_entity_state_action(
            question,
            plan,
            signals=signals,
            entity_resolution_context=context,
        )
        response = customer_service_service._build_phase2_entity_state_response(db, question, decision)

    assert decision["action"] == expected_action
    assert (response is not None) is (expected_action != "pass_through")


def test_attach_phase1_plan_is_the_effective_runtime_merge_boundary():
    original = {"requested_field": "适用场景", "requested_fields": ["适用场景"]}
    result = {
        "debug": {
            "plan": {
                "requested_field": "热源",
                "requested_fields": ["适用场景", "热源"],
                "compound": True,
                "resolved_sku": "RT-P2-300",
            }
        }
    }

    attached = customer_service_service._attach_phase1_plan_and_timing(
        result,
        original,
        {"planner_duration_ms": 3},
    )

    effective = attached["debug"]["plan"]
    assert effective["requested_field"] == "热源"
    assert effective["requested_fields"] == ["适用场景", "热源"]
    assert effective["compound"] is True
    assert effective["resolved_sku"] == "RT-P2-300"
    assert attached["debug"]["timing"]["planner_duration_ms"] == 3
