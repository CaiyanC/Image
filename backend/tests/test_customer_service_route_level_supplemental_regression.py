import asyncio
import json
import re

import pytest

from app.models import Product
from app.services import customer_agent_planner_service
from test_customer_service_route_level_regression import route_client_and_db


def _semantic_preplan_debug(payload: dict) -> dict:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    return debug.get("semantic_preplan") if isinstance(debug.get("semantic_preplan"), dict) else {}


def test_semantic_preplan_parser_accepts_code_fence_and_tracks_llm_calls(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append(purpose)
        return """```json
{"route_hint":"comparison","question_type":"comparison","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.84,"reason":"pan vs cookware"}
```"""

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u4e3b\u8981\u505a\u714e\u70e4\u65e9\u9910\uff0c\u9505\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u503c\u5f97\u5148\u4e70\uff1f",
            deterministic_plan={"primary_intent": "comparison", "answer_type": "comparison"},
            context={},
        )
    )

    assert calls == ["semantic_preplan"]
    assert result["called"] is True
    assert result["route_hint"] == "comparison"
    assert result["confidence"] > 0
    assert result["fallback_reason"] == ""
    assert result["llm_call_count"] == 1
    assert result["llm_call_count_delta"] == 1


def test_semantic_preplan_repair_recovers_truncated_json(monkeypatch):
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append(purpose)
        if purpose == "semantic_preplan":
            return '{\n  "route_hint": "query_products",\n  "question_type": "filter",\n  "entities": [],\n'
        return '{"route_hint":"query_products","question_type":"filter","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.77,"reason":"waterware capability"}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u6709\u54ea\u4e9b\u6c34\u5177\u66f4\u504f\u51b7\u6c34\u968f\u8eab\u8865\u6c34\uff1f",
            deterministic_plan={"primary_intent": "", "answer_type": ""},
            context={},
        )
    )

    assert calls == ["semantic_preplan", "semantic_preplan_repair"]
    assert result["called"] is True
    assert result["route_hint"] == "query_products"
    assert result["confidence"] == pytest.approx(0.77)
    assert result["fallback_reason"] == ""
    assert result["llm_call_count"] == 2
    assert result["llm_call_count_delta"] == 2


def test_semantic_preplan_forbidden_keys_still_fallback(monkeypatch):
    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        return '{"route_hint":"comparison","question_type":"comparison","entities":[],"field_hint":null,"qa_or_usage_care":false,"unknown_field":false,"confidence":0.9,"reason":"x","candidate_skus":["BAD-1"]}'

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    result = asyncio.run(
        customer_agent_planner_service.plan_customer_question_semantic(
            db=None,
            question="\u4e3b\u8981\u505a\u714e\u70e4\u65e9\u9910\uff0c\u9505\u548c\u70e4\u76d8\u54ea\u4e2a\u66f4\u503c\u5f97\u5148\u4e70\uff1f",
            deterministic_plan={"primary_intent": "comparison", "answer_type": "comparison"},
            context={},
        )
    )

    assert result["called"] is True
    assert result["route_hint"] == ""
    assert result["fallback_reason"].startswith("forbidden_keys:")


@pytest.mark.parametrize(
    ("question", "route_hint"),
    [
        ("主要做煎烤早餐，锅和烤盘哪个更值得先买？", "comparison"),
        ("有哪些水具更偏冷水随身补水？", "query_products"),
        ("有哪些咖啡器具适合手冲？", "query_products"),
        ("CT-T04(BM) 有什么使用限制？", "product_detail"),
    ],
)
def test_route_level_semantic_preplan_triggers_only_for_ambiguous_routes(
    route_client_and_db,
    monkeypatch,
    question,
    route_hint,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append({"purpose": purpose, "messages": messages})
        return json.dumps(
            {
                "route_hint": route_hint,
                "question_type": "comparison" if route_hint == "comparison" else "filter",
                "entities": [],
                "field_hint": None,
                "qa_or_usage_care": route_hint == "usage_care",
                "unknown_field": route_hint == "unknown_field",
                "confidence": 0.88,
                "reason": "ambiguous route smoke",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert calls and calls[0]["purpose"] == "semantic_preplan"
    semantic_debug = _semantic_preplan_debug(payload)
    assert semantic_debug.get("called") is True, payload.get("debug")
    assert semantic_debug.get("route_hint") == route_hint, semantic_debug
    assert semantic_debug.get("accepted_or_overridden") in {"accepted", "overridden"}, semantic_debug
    assert int(semantic_debug.get("llm_call_count_delta") or 0) >= 1, semantic_debug
    assert payload["answer"], payload
    assert "candidate_skus" not in semantic_debug
    assert "recommended_skus" not in semantic_debug


def test_route_level_semantic_preplan_triggers_for_alternative_followup(route_client_and_db, monkeypatch):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        calls.append({"purpose": purpose, "messages": messages})
        return json.dumps(
            {
                "route_hint": "recommendation",
                "question_type": "followup",
                "entities": [],
                "field_hint": None,
                "qa_or_usage_care": False,
                "unknown_field": False,
                "confidence": 0.86,
                "reason": "negative alternative follow-up",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "双人露营想买套轻便锅具。"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_top = payload1["result_skus"][0]

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "不要刚才那个，换个更轻的", "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert calls and calls[-1]["purpose"] == "semantic_preplan"
    semantic_debug = _semantic_preplan_debug(payload2)
    assert semantic_debug.get("called") is True, payload2.get("debug")
    assert semantic_debug.get("route_hint") == "recommendation", semantic_debug
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_top, (payload1, payload2)


@pytest.mark.parametrize(
    "question",
    [
        "CS-B14（LX）能不能用酒精炉？",
        "CW-C83 容量是多少？",
        "现在有多少款水具？",
        "CW-C83有库存吗？",
        "炉具点不着怎么办？",
    ],
)
def test_route_level_semantic_preplan_skips_clear_deterministic_routes(
    route_client_and_db,
    monkeypatch,
    question,
):
    client, headers, _ = route_client_and_db
    calls = []

    async def fake_chat_completion(db, messages, model=None, temperature=0.2, max_tokens=1200, *, purpose="chat"):
        if purpose == "semantic_preplan":
            calls.append({"purpose": purpose, "messages": messages})
            raise AssertionError("semantic_preplan should not run for clear deterministic routes")
        return "{}"

    monkeypatch.setattr(customer_agent_planner_service.customer_llm_service, "chat_completion", fake_chat_completion)

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert not calls, payload.get("debug")
    assert not _semantic_preplan_debug(payload), payload.get("debug")
    assert payload["answer"], payload


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


@pytest.mark.parametrize(
    "question",
    [
        "\u60c5\u4fa3\u9732\u8425\u4e3b\u8981\u559d\u70ed\u6c34\uff0c\u6c34\u58f6\u600e\u4e48\u9009\uff1f",
        "\u4e24\u4e2a\u4eba\u9732\u8425\u4e3b\u8981\u6ce1\u8336\uff0c\u63a8\u8350\u4e2a\u8f7b\u4fbf\u6c34\u58f6\u3002",
        "\u53cc\u4eba\u9732\u8425\uff0c\u60f3\u4e70\u4e2a\u80fd\u70e7\u6c34\u7684\u58f6\u3002",
        "\u4e24\u4e2a\u4eba\u9732\u8425\uff0c\u6c34\u5177\u8981\u8f7b\u4fbf\u4e00\u70b9\u3002",
        "\u6237\u5916\u559d\u70ed\u6c34\u6bd4\u8f83\u591a\uff0c\u6c34\u58f6\u600e\u4e48\u9009\uff1f",
    ],
)
def test_route_level_water_kettle_selection_prefers_waterware_domain(route_client_and_db, question):
    client, headers, Session = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] != "AC-Z13", payload["result_skus"]

    with Session() as db:
        categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload["result_skus"][:2])).all()
        }

    assert categories, payload
    assert all(category in {"\u6c34\u5177", "\u6c34\u58f6"} for category in categories.values()), categories


@pytest.mark.parametrize(
    ("question", "forbidden_top"),
    [
        ("\u53cc\u4eba\u9732\u8425\u60f3\u4e70\u5957\u8f7b\u4fbf\u9505\u5177\u3002", {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"}),
        (
            "\u4e24\u4e2a\u4eba\u5468\u672b\u9732\u8425\uff0c\u60f3\u4e70\u8f7b\u4e00\u70b9\u53c8\u522b\u592a\u8d35\u7684\u9505\u5177\u5957\u88c5\uff0c\u600e\u4e48\u9009\uff1f",
            {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"},
        ),
        (
            "\u516c\u53f8\u5341\u51e0\u4e2a\u4eba\u9732\u8425\u70e7\u70e4\uff0c\u8fd8\u8981\u70e7\u6c34\u6ce1\u8336\uff0c\u7089\u5177\u600e\u4e48\u914d\uff1f",
            {"CW-K03-37", "CW-K04PRO-37", "CB253", "CB254", "AC-Z13"},
        ),
        (
            "\u9732\u8425\u70e7\u70e4\u52a0\u716e\u6c34\uff0c\u5148\u4e70\u7089\u5177\u8fd8\u662f\u6c34\u58f6\uff1f",
            {"AC-Z13"},
        ),
        (
            "\u4e24\u4e2a\u4eba\u6237\u5916\u6ce1\u8336\uff0c\u63a8\u8350\u8f7b\u4e00\u70b9\u7684\u6c34\u58f6\u3002",
            {"AC-Z13"},
        ),
    ],
)
def test_route_level_water_kettle_guard_does_not_break_cookware_or_stove_domains(
    route_client_and_db,
    question,
    forbidden_top,
):
    client, headers, _ = route_client_and_db

    response = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": question},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] in {"recommendation", "product_query"}, payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"], payload
    assert payload["answer"], payload
    assert payload["result_skus"][0] not in forbidden_top, payload["result_skus"]


@pytest.mark.parametrize(
    ("question", "expected_sku", "required_terms"),
    [
        ("KW-K31-白适合冷水还是热水？", "KW-K31-白", ("冷水", "热水")),
        ("KW-K31-黑是烧水还是补水？", "KW-K31-黑", ("烧水", "补水")),
        ("KW-K32-白适合冷水还是热水？", "KW-K32-白", ("冷水", "热水")),
        ("KW-K32-黑是烧水还是补水？", "KW-K32-黑", ("烧水", "补水")),
        ("TW-422-蓝能不能装热水？", "TW-422-蓝", ("热水",)),
        ("TW-422-绿适合冷水还是热水？", "TW-422-绿", ("冷水", "热水")),
        ("TW-422-粉能不能补水用？", "TW-422-粉", ("补水",)),
    ],
)
def test_route_level_waterware_capability_questions_keep_exact_sku_and_answer_capability(
    route_client_and_db,
    question,
    expected_sku,
    required_terms,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    debug_plan = ((payload.get("debug") or {}).get("plan") or {})

    assert payload["answer_type"] == "product_detail", payload
    assert payload["answer_type"] != "knowledge_base_answer"
    assert payload["result_skus"] == [expected_sku], payload
    assert payload["answer"], payload
    assert debug_plan.get("product_ref") == expected_sku, debug_plan
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "required_answer_type", "required_terms", "forbidden_terms"),
    [
        ("现在有多少款水具？", "query_products", ("当前匹配到", "水具"), ("天气", "实时", "unsupported")),
        ("水壶有多少款？", "query_products", ("当前匹配到", "水壶"), ("天气", "实时", "unsupported")),
        ("有哪些咖啡器具适合手冲？", "product_query", ("咖啡器具",), ("knowledge_base_answer",)),
        ("有哪些水具更偏冷水随身补水？", "product_query", ("补水", "水具"), ("清洗", "冷水冲")),
        ("有哪些烤盘能配露营炉具？", "product_query", ("烤盘",), ()),
        ("露营烧烤用，能配炉具的烤盘有哪些？", "product_query", ("烤盘", "炉具"), ()),
        ("CW-C83有库存吗？", "product_detail", ("未标注", "库存"), ("Product not found", "天气")),
        ("销量最高的是哪个锅？", "product_detail", ("未标注", "销量"), ("推荐", "天气")),
        ("客户评价最好的水壶是哪款？", "product_detail", ("未标注", "评价"), ("推荐", "天气")),
        ("价格现在多少？", "product_detail", ("未标注", "价格"), ("天气", "实时天气")),
    ],
)
def test_route_level_structured_and_unknown_field_questions_route_conservatively(
    route_client_and_db,
    question,
    required_answer_type,
    required_terms,
    forbidden_terms,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == required_answer_type, payload
    assert payload["answer"], payload
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]
    for term in forbidden_terms:
        assert term not in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    ("question", "expected_answer_type", "expected_sku", "required_terms"),
    [
        ("炉具点不着怎么办？", "product_usage_care", None, ("关闭阀门", "检查")),
        ("气罐和炉具连接要注意什么？", "product_usage_care", None, ("连接", "注意")),
        ("炉具使用安全吗？", "product_usage_care", None, ("安全", "明火")),
        ("户外使用炉具有什么安全注意事项？", "product_usage_care", None, ("安全", "气罐")),
        ("气罐怎么存放？", "product_usage_care", None, ("阴凉通风", "火源")),
        ("CT-T04(BM) 有什么使用限制？", "product_detail", "CT-T04(BM)", ("茶具", "未标注适用酒精炉")),
        ("CW-C83 有没有官方说明书？", "product_detail", "CW-C83", ("未维护", "说明书")),
        ("DV01有没有保修？", "product_detail", "DV01", ("未标注", "保修")),
        ("KD20HM有没有安装视频？", "product_detail", "KD20HM", ("未维护", "安装视频")),
    ],
)
def test_route_level_qa_usage_care_and_sku_knowledge_boundary(
    route_client_and_db,
    question,
    expected_answer_type,
    expected_sku,
    required_terms,
):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == expected_answer_type, payload
    assert payload["answer"], payload
    if expected_sku:
        assert payload["result_skus"] == [expected_sku], payload
    for term in required_terms:
        assert term in payload["answer"], payload["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "主要做煎烤早餐，锅和烤盘哪个更值得先买？",
        "如果早餐主要煎蛋煎培根，先买锅还是烤盘更合适？",
    ],
)
def test_route_level_pan_vs_cookware_comparison_answers_tradeoff_not_plain_list(route_client_and_db, question):
    client, headers, _ = route_client_and_db

    response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer_type"] == "recommendation", payload
    assert payload["answer"], payload
    assert "烤盘" in payload["answer"], payload["answer"]
    assert ("锅具" in payload["answer"] or "锅" in payload["answer"]), payload["answer"]
    assert re.search(r"(更值得先买|更合适|更通用|优先)", payload["answer"]), payload["answer"]


@pytest.mark.parametrize(
    "followups",
    [
        ("不要刚才那个，换个更轻的。", "再给我一个稍微便宜点的。"),
        ("换个更轻一点的。", "还有别的吗？"),
        ("不要这个了，换一个。", "再来一个更适合新手的。"),
        ("这个太重了，换个轻便点的。", "更便宜点还有吗？"),
    ],
)
def test_route_level_alternative_followups_stay_in_same_recommendation_domain(route_client_and_db, followups):
    client, headers, Session = route_client_and_db

    response1 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": "双人露营想买套轻便锅具。"},
        headers=headers,
    )
    assert response1.status_code == 200, response1.text
    payload1 = response1.json()
    conversation_id = payload1["conversation_id"]
    first_top = payload1["result_skus"][0]
    assert payload1["answer_type"] == "recommendation", payload1

    response2 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": followups[0], "conversation_id": conversation_id},
        headers=headers,
    )
    assert response2.status_code == 200, response2.text
    payload2 = response2.json()
    assert payload2["answer_type"] == "recommendation", payload2
    assert payload2["answer_type"] != "knowledge_base_answer"
    assert payload2["answer_type"] != "clarification"
    assert payload2["result_skus"], payload2
    assert payload2["result_skus"][0] != first_top, (payload1, payload2)

    with Session() as db:
        top_categories = {
            product.sku: product.category
            for product in db.query(Product).filter(Product.sku.in_(payload2["result_skus"][:2])).all()
        }
    assert top_categories and all(category == "锅具" for category in top_categories.values()), top_categories

    response3 = client.post(
        "/api/customer-service/ask?debug=true",
        json={"question": followups[1], "conversation_id": conversation_id},
        headers=headers,
    )
    assert response3.status_code == 200, response3.text
    payload3 = response3.json()
    assert payload3["answer_type"] == "recommendation", payload3
    assert payload3["answer_type"] != "knowledge_base_answer"
    assert payload3["answer_type"] != "clarification"
    assert payload3["result_skus"], payload3
    assert payload3["result_skus"][0] not in {"CB253", "CB254", "AC-Z13", "CW-C84", "CW-K32"}, payload3["result_skus"]
