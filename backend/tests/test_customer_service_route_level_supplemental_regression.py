import re

import pytest

from app.models import Product
from test_customer_service_route_level_regression import route_client_and_db


@pytest.mark.parametrize(
    "question",
    [
        "\u56e2\u5efa\u9732\u8425\u60f3\u517c\u987e\u70e4\u4e1c\u897f\u548c\u716e\u70ed\u6c34\uff0c\u7089\u5177\u8be5\u600e\u4e48\u9009\uff1f",
        "\u591a\u4eba\u9732\u8425\u4ee5\u70e7\u70e4\u4e3a\u4e3b\uff0c\u4f46\u8fd8\u9700\u8981\u70e7\u6c34\u6ce1\u9762\uff0c\u7089\u5177\u5148\u9009\u4ec0\u4e48\uff1f",
        "\u56e2\u5efa\u9732\u8425\u60f3\u517c\u987e\u70e4\u4e1c\u897f\u548c\u716e\u70ed\u6c34\uff0c\u7089\u5177\u8be5\u600e\u4e48\u914d\uff1f",
        "\u591a\u4eba\u9732\u8425\u4ee5\u70e7\u70e4\u4e3a\u4e3b\uff0c\u4f46\u8fd8\u9700\u8981\u70e7\u6c34\u6ce1\u9762\uff0c\u7089\u5177\u8be5\u5148\u4e70\u4ec0\u4e48\uff1f",
    ],
)
def test_route_level_stove_combo_variant_generalization_stays_off_accessories(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["result_skus"][0] not in {"AC-Z13", "CB253", "CB254"}, payload["result_skus"]
    assert payload["answer"], payload

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert categories, payload
    assert all(category == "炉具" for category in categories.values()), categories


@pytest.mark.parametrize(
    "question",
    [
        "\u8425\u5730\u505a\u65e9\u9910\u504f\u714e\u70e4\uff0c\u9505\u5177\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u5b9e\u7528\uff1f",
        "\u65e9\u4e0a\u60f3\u5728\u8425\u5730\u505a\u714e\u70e4\u98df\u7269\uff0c\u4f18\u5148\u9009\u70e4\u76d8\u8fd8\u662f\u9505\u66f4\u597d\uff1f",
    ],
)
def test_route_level_grill_vs_pot_variant_explicitly_compares_tradeoffs(
    route_client_and_db,
    question,
):
    client, headers, Session = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert "\u70e4\u76d8" in payload["answer"], payload["answer"]
    assert ("\u9505\u5177" in payload["answer"] or "\u9505" in payload["answer"]), payload["answer"]
    assert re.search(r"(\u66f4\u5408\u9002|\u66f4\u901a\u7528|\u4f18\u5148)", payload["answer"]), payload["answer"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:3])).all()
        }

    assert categories, payload
    assert all(category in {"锅具", "炉具"} for category in categories.values()), categories


def test_route_level_multiturn_variant_constraint_followup_keeps_same_domain(route_client_and_db):
    client, headers, _ = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_skus = payload1["result_skus"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert first_skus, payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e0d\u8981\u521a\u624d\u90a3\u4e2a\uff0c\u6362\u4e00\u4e2a\u66f4\u8f7b\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_skus[0], (payload1, payload2)

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u518d\u7ed9\u6211\u4e00\u4e2a\u7a0d\u5fae\u4fbf\u5b9c\u70b9\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254"}, payload3["result_skus"]


def test_route_level_single_turn_lightweight_two_person_cookware_stays_in_cookware_domain(route_client_and_db):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in {"CW-C84", "CW-K32", "CB253", "CB254"}, payload["result_skus"]
    assert "不先把水壶当主推" in payload["answer"], payload["answer"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert top_products, payload
    assert all("锅" in category for category in top_products.values()), top_products
    assert re.search(r"(\u53cc\u4eba|\u9732\u8425).*(\u8f7b|\u4fbf|\u5957\u9505|\u9505\u5177)", payload["answer"]), payload["answer"]


def test_route_level_multiturn_variant_lightweight_cookware_followups_stay_out_of_waterware(route_client_and_db):
    client, headers, Session = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert payload1["answer_type"] != "knowledge_base_answer"
    assert payload1["result_skus"], payload1
    assert payload1["result_skus"][0] not in {"CW-C84", "CW-K32", "CB253", "CB254"}, payload1["result_skus"]

    with Session() as db:
        top_products = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload1["result_skus"][:2])).all()
        }

    assert top_products, payload1
    assert all(category == "锅具" for category in top_products.values()), top_products

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e0d\u8981\u521a\u624d\u90a3\u4e2a\uff0c\u6362\u4e00\u4e2a\u66f4\u8f7b\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] not in {"CB253", "CB254"}, payload2["result_skus"]

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u518d\u7ed9\u6211\u4e00\u4e2a\u7a0d\u5fae\u4fbf\u5b9c\u70b9\u7684\u3002", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254"}, payload3["result_skus"]


def test_route_level_multiturn_variant_ordinal_compare_followup_keeps_second_choice(route_client_and_db):
    client, headers, _ = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u4e24\u4e2a\u4eba\u9732\u8425\u63a8\u8350\u5957\u9505\u3002"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    ordered = payload1["result_skus"]
    assert payload1["answer_type"] == "recommendation", payload1
    assert len(ordered) >= 2, payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u7b2c\u4e00\u4e2a\u592a\u8d35\u5c31\u7b97\u4e86\uff0c\u7b2c\u4e8c\u4e2a\u66f4\u5408\u9002\u65b0\u624b\u5417\uff1f", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] in {"comparison", "recommendation"}, payload2
    assert payload2["answer_type"] != "clarification"
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert ordered[1] in payload2["result_skus"], (ordered, payload2)

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "\u90a3\u5b83\u80fd\u7528\u9152\u7cbe\u7089\u5417\uff1f", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "product_detail", payload3
    assert payload3["answer_type"] != "clarification"
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["result_skus"] == [ordered[1]], (ordered, payload2, payload3)
