import json
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.permission_constants import MANAGEMENT_GROUP_NAME
from app.core.security import create_access_token
from app.main import app
from app.models.group import Group
from app.models.user import User
from app.models.user_group import UserGroup


Q04 = "\u516c\u53f8\u56e2\u5efa\u5341\u6765\u4e2a\u4eba\u6237\u5916\u70e7\u70e4\uff0c\u6709\u6ca1\u6709\u9002\u5408\u7684\u7089\u5b50\u6216\u8005\u70e4\u76d8\uff1f"
Q19 = "\u6211\u4e0d\u8981\u592a\u8d35\uff0c\u4e5f\u4e0d\u8981\u592a\u91cd\uff0c\u8fd8\u8981\u597d\u6536\u7eb3\uff0c\u4e70\u54ea\u4e2a\u6700\u7a33\uff1f"
Q06 = "\u8f7b\u9014\u5957\u9505\u662f\u4ec0\u4e48\u6750\u8d28\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u7c98\u9505\uff1f"
Q08 = "\u4f60\u4eec\u90a3\u4e2a\u4eab\u91ce\u6c34\u58f6\u53ef\u4ee5\u88c5\u51b7\u6c34\u5417\uff1f\u5bb9\u91cf\u662f\u591a\u5c11\uff1f"
Q15_1 = "\u6211\u4e00\u4e2a\u4eba\u5f92\u6b65\uff0c\u60f3\u8f7b\u4e00\u70b9\uff0c\u63a8\u8350\u4e00\u4e2a\u9505\u3002"
Q15_2 = "\u5b83\u80fd\u4e0d\u80fd\u7528\u9152\u7cbe\u7089\uff1f"
Q15_3 = "\u6709\u6ca1\u6709\u66f4\u4fbf\u5b9c\u4e00\u70b9\u7684\u66ff\u4ee3\uff1f"


def _parse_sse(payload: str) -> dict:
    current = {}
    meta = {}
    answer_parts = []
    trace = {}
    for raw_line in payload.splitlines():
        line = raw_line.strip("\r")
        if not line:
            event = current.get("event")
            data = current.get("data") or {}
            if event in {"content", "answer_delta"}:
                answer_parts.append(str(data.get("content") or data.get("text") or ""))
            elif event == "meta" and isinstance(data, dict):
                meta = data
            elif event == "trace" and isinstance(data, dict):
                trace = data
            current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line.split(":", 1)[1].strip())
    return {
        "answer": "".join(answer_parts).strip() or str(meta.get("answer") or ""),
        "meta": meta,
        "trace": trace,
    }


@pytest.fixture()
def client_and_token(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Group.__table__,
            UserGroup.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)

    db = Session()
    db.add(
        User(
            id="customer-service-api-user",
            username="customer-service-api-user",
            email="customer-service-api@example.com",
            password_hash="unused",
            user_type="human",
            display_name="Customer Service API User",
            is_active=True,
        )
    )
    db.add(Group(id="customer-service-api-management", group_name=MANAGEMENT_GROUP_NAME, description="management"))
    db.add(
        UserGroup(
            user_id="customer-service-api-user",
            group_id="customer-service-api-management",
            group_role="admin",
        )
    )
    db.commit()
    db.close()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    from app.api import customer_service as customer_service_api

    customer_service_api.customer_cache_service.recommendation_response_cache.clear()
    customer_service_api.customer_cache_service.parity_result_snapshot_cache.clear()
    monkeypatch.setattr(customer_service_api, "enforce_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(customer_service_api.operation_log_service, "log_operation", lambda *args, **kwargs: None)

    token = create_access_token({"sub": "customer-service-api-user"})
    headers = {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app) as test_client:
            yield test_client, headers
    finally:
        app.dependency_overrides.clear()
        tmpdir.cleanup()


def test_customer_service_ask_and_stream_share_single_turn_public_shape(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api

    responses = {
        Q04: {
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": "炉具方向：CS-G26HM。烤盘方向：CF-PG19。",
            "result_skus": ["CS-G26HM", "CF-PG19", "CS-G26CS"],
        },
        Q19: {
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": "优先推荐 CW-C01-37，也可以看 CW-S10-1。",
            "result_skus": ["CW-C01-37", "CW-S10-1", "CW-C93"],
        },
        Q06: {
            "intent": "product_detail",
            "answer_type": "product_detail",
            "answer": "轻途套锅（CW-C06PRO）\n主体材质：3003铝合金、硅胶、不锈钢、PP\n粘锅/不粘：当前资料未找到不粘或涂层说明，无法保证不粘。",
            "result_skus": ["CW-C06PRO"],
        },
        Q08: {
            "intent": "product_detail",
            "answer_type": "product_detail",
            "answer": "享野水壶（CW-C76）\n容量：8L\n冷水/水温：当前资料未明确标注装冷水限制或适用水温。",
            "result_skus": ["CW-C76"],
        },
    }

    calls = []

    async def fake_ask_customer_service(db, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append(question)
        payload = responses[question]
        return {
            "conversation_id": f"conv-{abs(hash(question))}",
            "message_id": f"msg-{abs(hash(question))}",
            "intent": payload["intent"],
            "answer_type": payload["answer_type"],
            "confidence": "high",
            "uncertainty": "low",
            "needs_clarification": False,
            "anomalies": [],
            "suggested_followups": [],
            "followups": [],
            "warnings": [],
            "evidence": [],
            "agent_quality": {"score": 1.0, "passed": True, "risks": []},
            "answer_metadata": {"timing": {"llm_call_count": 0}},
            "debug": {
                "plan": {"primary_intent": payload["intent"]},
                "trace": {"routing_stage": "process_agent_request"},
            },
            "sku": payload["result_skus"][0],
            "answer": payload["answer"],
            "sources": [],
            "actions": [],
            "results": [{"sku": sku} for sku in payload["result_skus"]],
            "steps": [],
            "result_skus": payload["result_skus"],
            "candidate_skus": payload["result_skus"],
            "agent_mode": None,
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    for question, expected in responses.items():
        ask_response = client.post("/api/customer-service/ask?debug=true", json={"question": question}, headers=headers)
        assert ask_response.status_code == 200, ask_response.text
        ask_payload = ask_response.json()

        stream_response = client.post("/api/customer-service/ask-stream", json={"question": question}, headers=headers)
        assert stream_response.status_code == 200, stream_response.text
        assert stream_response.headers.get("connection", "").lower() == "close"
        stream_payload = _parse_sse(stream_response.text)
        stream_meta = stream_payload["meta"]

        assert ask_payload["answer_type"] == expected["answer_type"]
        assert ((ask_payload.get("debug") or {}).get("plan") or {}).get("primary_intent") == expected["intent"]
        assert ask_payload["result_skus"] == expected["result_skus"]
        assert ask_payload["answer_type"] != "knowledge_base_answer"

        assert stream_meta["answer_type"] == expected["answer_type"]
        assert ((stream_meta.get("debug") or {}).get("plan") or {}).get("primary_intent") == expected["intent"]
        assert stream_meta["result_skus"] == expected["result_skus"]
        assert stream_meta["answer_type"] != "knowledge_base_answer"

    assert calls.count(Q04) == 1
    assert calls.count(Q19) == 1
    assert calls.count(Q06) == 2
    assert calls.count(Q08) == 2


def test_customer_service_ask_and_stream_share_multiturn_conversation_context(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api

    def response_for(question: str, conversation_id: str | None) -> dict:
        if question == Q15_1:
            return {
                "conversation_id": conversation_id or "conv-q15",
                "intent": "recommendation",
                "answer_type": "recommendation",
                "answer": "优先推荐 CW-C01-37。",
                "result_skus": ["CW-C01-37", "CW-C93"],
                "primary_intent": "recommendation",
            }
        if question == Q15_2:
            assert conversation_id == "conv-q15"
            return {
                "conversation_id": conversation_id,
                "intent": "product_detail",
                "answer_type": "product_detail",
                "answer": "CW-C01-37 当前资料未显示支持酒精炉。",
                "result_skus": ["CW-C01-37"],
                "primary_intent": "",
            }
        assert conversation_id == "conv-q15"
        return {
            "conversation_id": conversation_id,
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": "更便宜一点可以看 CW-C65-5。",
            "result_skus": ["CW-C65-5", "CW-C93"],
            "primary_intent": "",
        }

    async def fake_ask_customer_service(db, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        payload = response_for(question, conversation_id)
        return {
            "conversation_id": payload["conversation_id"],
            "message_id": f"msg-{question[-1]}",
            "intent": payload["intent"],
            "answer_type": payload["answer_type"],
            "confidence": "high",
            "uncertainty": "low",
            "needs_clarification": False,
            "anomalies": [],
            "suggested_followups": [],
            "followups": [],
            "warnings": [],
            "evidence": [],
            "agent_quality": {"score": 1.0, "passed": True, "risks": []},
            "answer_metadata": {"timing": {"llm_call_count": 0}},
            "debug": {
                "plan": {"primary_intent": payload["primary_intent"]},
                "trace": {"routing_stage": "process_agent_request_followup" if conversation_id else "process_agent_request"},
            },
            "sku": payload["result_skus"][0],
            "answer": payload["answer"],
            "sources": [],
            "actions": [],
            "results": [{"sku": sku} for sku in payload["result_skus"]],
            "steps": [],
            "result_skus": payload["result_skus"],
            "candidate_skus": payload["result_skus"],
            "agent_mode": "recommendation_context_product_compatibility" if question == Q15_2 else None,
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    ask_conversation_id = None
    for question, expected_answer_type in ((Q15_1, "recommendation"), (Q15_2, "product_detail"), (Q15_3, "recommendation")):
        response = client.post(
            "/api/customer-service/ask?debug=true",
            json={"question": question, "conversation_id": ask_conversation_id},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        ask_conversation_id = payload["conversation_id"]
        assert payload["conversation_id"] == "conv-q15"
        assert payload["answer_type"] == expected_answer_type
        assert payload["answer_type"] != "knowledge_base_answer"

    stream_conversation_id = None
    for question, expected_answer_type in ((Q15_1, "recommendation"), (Q15_2, "product_detail"), (Q15_3, "recommendation")):
        response = client.post(
            "/api/customer-service/ask-stream",
            json={"question": question, "conversation_id": stream_conversation_id},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = _parse_sse(response.text)
        meta = payload["meta"]
        stream_conversation_id = meta["conversation_id"]
        assert meta["conversation_id"] == "conv-q15"
        assert meta["answer_type"] == expected_answer_type
        assert meta["answer_type"] != "knowledge_base_answer"
        assert meta["result_skus"]


def test_repeated_stateless_recommendation_reuses_the_approved_result_for_stream(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api
    from app.services import customer_cache_service

    customer_cache_service.recommendation_response_cache.clear()
    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append((question, conversation_id, answer_delta_callback is not None))
        return {
            "conversation_id": "recommendation-parity",
            "message_id": "recommendation-parity-message",
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": "推荐 CW-C69-1。",
            "result_skus": ["CW-C69-1", "CW-C06PRO"],
            "candidate_skus": ["CW-C69-1", "CW-C06PRO"],
            "results": [], "sources": [], "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    normal = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)
    stream = client.post("/api/customer-service/ask-stream", json={"question": Q15_1}, headers=headers)

    assert normal.status_code == 200
    assert stream.status_code == 200
    assert len(calls) == 1
    assert _parse_sse(stream.text)["meta"]["result_skus"] == normal.json()["result_skus"]


def test_parity_isolation_header_bypasses_stateless_recommendation_cache(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api
    from app.services import customer_cache_service

    customer_cache_service.recommendation_response_cache.clear()
    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append((question, conversation_id, answer_delta_callback is not None))
        sequence = len(calls)
        return {
            "conversation_id": f"isolated-conversation-{sequence}",
            "message_id": f"isolated-message-{sequence}",
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": "推荐 CW-C69-1。",
            "result_skus": ["CW-C69-1"],
            "candidate_skus": ["CW-C69-1"],
            "results": [], "sources": [], "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)
    parity_headers = {**headers, "X-Customer-Service-Parity-Isolation": "true"}
    parity_checks = []
    original_parity_isolation_enabled = customer_service_api._parity_isolation_enabled
    monkeypatch.setattr(
        customer_service_api,
        "_parity_isolation_enabled",
        lambda request: parity_checks.append(request.headers.get("X-Customer-Service-Parity-Isolation"))
        or original_parity_isolation_enabled(request),
    )

    normal = client.post(
        "/api/customer-service/ask",
        json={"question": Q15_1},
        headers=parity_headers,
    )
    stream = client.post(
        "/api/customer-service/ask-stream",
        json={"question": Q15_1},
        headers=parity_headers,
    )

    assert normal.status_code == 200
    assert stream.status_code == 200
    assert parity_checks == ["true", "true"]
    assert len(calls) == 2
    assert normal.json()["conversation_id"] != _parse_sse(stream.text)["meta"]["conversation_id"]


def test_parity_isolation_canonicalizes_independent_recommendation_decisions(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api

    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append((question, conversation_id, answer_delta_callback is not None))
        selected_sku = "SKU-A" if len(calls) == 1 else "SKU-B"
        if answer_delta_callback is not None:
            await answer_delta_callback(f"推荐 {selected_sku}。")
        return {
            "conversation_id": f"canonical-conversation-{len(calls)}",
            "message_id": f"canonical-message-{len(calls)}",
            "intent": "recommendation",
            "answer_type": "recommendation",
            "answer": f"推荐 {selected_sku}。",
            "result_skus": [selected_sku],
            "candidate_skus": [selected_sku],
            "results": [], "sources": [], "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)
    parity_headers = {**headers, "X-Customer-Service-Parity-Isolation": "true"}

    normal = client.post(
        "/api/customer-service/ask",
        json={"question": Q15_1},
        headers=parity_headers,
    )
    stream = client.post(
        "/api/customer-service/ask-stream",
        json={"question": Q15_1},
        headers=parity_headers,
    )

    assert normal.status_code == 200
    assert stream.status_code == 200
    assert len(calls) == 2
    stream_payload = _parse_sse(stream.text)
    assert stream_payload["meta"]["result_skus"] == normal.json()["result_skus"] == ["SKU-A"]
    assert "SKU-A" in stream_payload["answer"]
    assert "SKU-B" not in stream_payload["answer"]


def test_parity_isolation_serializes_runtime_only_nested_values(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api

    async def fake_ask_customer_service(_db, **_kwargs):
        return {
            "conversation_id": "runtime-value-conversation",
            "message_id": "runtime-value-message",
            "intent": "product_detail",
            "answer_type": "product_detail",
            "answer": "同一份可序列化的商品事实。",
            "result_skus": ["SKU-RUNTIME"],
            "candidate_skus": ["SKU-RUNTIME"],
            "results": [{"sku": "SKU-RUNTIME", "runtime_module": customer_service_api}],
            "sources": [], "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)
    parity_headers = {**headers, "X-Customer-Service-Parity-Isolation": "true"}

    normal = client.post(
        "/api/customer-service/ask",
        json={"question": "SKU-RUNTIME 的资料是什么？"},
        headers=parity_headers,
    )
    stream = client.post(
        "/api/customer-service/ask-stream",
        json={"question": "SKU-RUNTIME 的资料是什么？"},
        headers=parity_headers,
    )

    assert normal.status_code == 200, normal.text
    assert stream.status_code == 200, stream.text
    stream_payload = _parse_sse(stream.text)
    assert stream_payload["meta"]["results"] == normal.json()["results"]
    assert isinstance(normal.json()["results"][0]["runtime_module"], str)


def test_repeated_normal_recommendation_creates_a_fresh_conversation(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api
    from app.services import customer_cache_service

    customer_cache_service.recommendation_response_cache.clear()
    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append((question, conversation_id))
        sequence = len(calls)
        return {
            "conversation_id": f"fresh-conversation-{sequence}",
            "message_id": f"fresh-message-{sequence}",
            "intent": "recommendation", "answer_type": "recommendation",
            "answer": "推荐 CW-C69-1。", "result_skus": ["CW-C69-1"],
            "candidate_skus": ["CW-C69-1"], "results": [], "sources": [],
            "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    first = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)
    second = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 2
    assert first.json()["conversation_id"] != second.json()["conversation_id"]


def test_normal_non_recommendation_invalidates_a_stale_stream_recommendation_cache(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api
    from app.services import customer_cache_service

    customer_cache_service.recommendation_response_cache.clear()
    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append(question)
        if len(calls) == 1:
            return {
                "conversation_id": "old-recommendation", "message_id": "old-message",
                "intent": "recommendation", "answer_type": "recommendation",
                "answer": "推荐 CW-C69-1。", "result_skus": ["CW-C69-1"],
                "candidate_skus": ["CW-C69-1"], "results": [], "sources": [],
                "actions": [], "steps": [], "warnings": [], "evidence": [],
            }
        return {
            "conversation_id": "fresh-clarification", "message_id": "fresh-message",
            "intent": "clarify", "answer_type": "clarification",
            "answer": "请补充具体容量或重量偏好。", "result_skus": [],
            "candidate_skus": [], "results": [], "sources": [],
            "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    first = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)
    second = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)
    stream = client.post("/api/customer-service/ask-stream", json={"question": Q15_1}, headers=headers)

    assert first.json()["answer_type"] == "recommendation"
    assert second.json()["answer_type"] == "clarification"
    assert _parse_sse(stream.text)["meta"]["answer_type"] == "clarification"
    assert len(calls) == 3


def test_stateless_comparison_reuses_the_normal_result_for_stream(client_and_token, monkeypatch):
    client, headers = client_and_token
    from app.api import customer_service as customer_service_api
    from app.services import customer_cache_service

    customer_cache_service.recommendation_response_cache.clear()
    calls = []

    async def fake_ask_customer_service(_db, *, user_id, question, sku=None, conversation_id=None, answer_delta_callback=None):
        calls.append(question)
        return {
            "conversation_id": "comparison-parity", "message_id": "comparison-message",
            "intent": "compare_products", "answer_type": "comparison",
            "answer": "CW-C93 更适合两人徒步。", "result_skus": ["CW-C93", "CW-C83"],
            "candidate_skus": ["CW-C93", "CW-C83"], "results": [], "sources": [],
            "actions": [], "steps": [], "warnings": [], "evidence": [],
        }

    monkeypatch.setattr(customer_service_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)

    normal = client.post("/api/customer-service/ask", json={"question": Q15_1}, headers=headers)
    stream = client.post("/api/customer-service/ask-stream", json={"question": Q15_1}, headers=headers)

    assert normal.status_code == 200
    assert stream.status_code == 200
    assert len(calls) == 1
    assert _parse_sse(stream.text)["meta"]["result_skus"] == normal.json()["result_skus"]
