import json

import pytest

from app.models import Product, ProductSpecs
from app.services import customer_service_service
from app.services.customer_field_contract import (
    field_evidence_policy,
    qa_evidence_matches_field,
    select_dimension_evidence,
)
from test_customer_service_route_level_regression import _add_product, _add_product_qa, route_client_and_db


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
                "size_info": json.dumps(
                    [
                        {"label": "包装尺寸", "value": "42 x 30 x 8", "unit": "cm"},
                        {"label": "收纳袋尺寸", "value": "40 x 28 x 7", "unit": "cm"},
                    ],
                    ensure_ascii=False,
                )
            }
        )
        db.commit()
    return client, headers, Session


@pytest.mark.parametrize("alias", ["型号", "SKU", "货号", "产品编码", "商品编码"])
def test_model_policy_unifies_natural_aliases(alias):
    policy = field_evidence_policy("model")

    assert policy is not None
    assert alias in policy.aliases
    assert "product.sku" in policy.structured_fields
    assert qa_evidence_matches_field("核心卖点是什么", "", "model") is False


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


@pytest.mark.parametrize("alias", ["型号", "货号", "产品编码"])
def test_explicit_model_question_uses_sku_evidence_not_selling_points(field_evidence_client, alias):
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
    assert metadata.get("requested_field") == "model", payload
    assert metadata.get("evidence_field") == "model", payload
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
    assert "420.0g" in payload["answer"], payload
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

    metadata = payload.get("answer_metadata") or {}
    assert payload.get("result_skus") == ["FE-200"], payload
    assert "未标注" in payload["answer"] or "没有找到" in payload["answer"], payload
    assert "核心卖点" not in payload["answer"], payload
    assert metadata.get("field_evidence_missing") is True, payload


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


def test_generic_selling_point_question_keeps_qa_fast_path(field_evidence_client):
    client, headers, _ = field_evidence_client
    payload = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "晨雾Plus水壶有什么核心卖点？"},
        headers=headers,
    ).json()

    assert "核心卖点" in payload["answer"], payload
    assert payload.get("debug", {}).get("agent_mode") == "product_qa_fast_path", payload


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
