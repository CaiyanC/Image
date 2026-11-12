import json
import sys
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import Base, get_db  # noqa: E402
from app.core.permission_constants import MANAGEMENT_GROUP_NAME  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    CustomerProductLink, CustomerServiceConversation, CustomerServiceMessage, Group,
    OperationLog, Product, ProductQa, User, UserGroup, WorkBuddyCustomerServiceToken,
)


CONNECTOR_PATH = "/api/workbuddy/customer-service"


def _connector_headers(client, user_headers, *, write=False):
    response = client.post(
        CONNECTOR_PATH + "/tokens", headers=user_headers, json={"allow_qa_write": write},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.fixture()
def connector_client(monkeypatch):
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
            WorkBuddyCustomerServiceToken.__table__,
            Product.__table__,
            ProductQa.__table__,
            CustomerProductLink.__table__,
            CustomerServiceConversation.__table__,
            CustomerServiceMessage.__table__,
            OperationLog.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        db.add_all([
            Product(id="product-a", sku="TEST-SKU-A", product_name_cn="测试炉", barcode="1", brand="测试"),
            Product(id="product-b", sku="TEST-SKU-B", product_name_cn="测试炉组合装", barcode="2", brand="测试"),
        ])
        db.add(User(
            id="wb-connector-user",
            username="wb-connector-user",
            password_hash="unused",
            user_type="human",
            display_name="WorkBuddy Connector User",
            is_active=True,
        ))
        db.add(Group(
            id="wb-connector-admin-group",
            group_name=MANAGEMENT_GROUP_NAME,
            description="test management access",
        ))
        db.add(UserGroup(
            user_id="wb-connector-user",
            group_id="wb-connector-admin-group",
            group_role="admin",
        ))
        db.commit()

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    from app.api import workbuddy_customer_service as connector_api

    monkeypatch.setattr(connector_api, "enforce_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(connector_api.operation_log_service, "log_operation", lambda *args, **kwargs: None)
    app_client = TestClient(app)
    jwt = create_access_token({"sub": "wb-connector-user"})
    try:
        yield app_client, Session, {"Authorization": f"Bearer {jwt}"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_workbuddy_token_is_one_time_user_scoped_and_revocable(connector_client):
    client, Session, user_headers = connector_client
    created = client.post(
        "/api/workbuddy/customer-service/tokens",
        headers=user_headers,
        json={"name": "WorkBuddy 客服", "expires_in_days": 30},
    )
    assert created.status_code == 200
    payload = created.json()
    token = payload["token"]
    assert token.startswith("cscwb_")

    listed = client.get("/api/workbuddy/customer-service/tokens", headers=user_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert "token" not in listed.json()["items"][0]

    with Session() as db:
        stored = db.query(WorkBuddyCustomerServiceToken).one()
        assert stored.token_hash != token
        assert stored.token_hash

    revoked = client.delete(
        f"/api/workbuddy/customer-service/tokens/{payload['id']}",
        headers=user_headers,
    )
    assert revoked.status_code == 200
    rejected = client.post(
        "/api/workbuddy/customer-service/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "测试"},
    )
    assert rejected.status_code == 401


def test_workbuddy_ask_runs_rag_pipeline_and_returns_sanitized_sources(connector_client, monkeypatch):
    client, sessions, user_headers = connector_client
    from app.api import workbuddy_customer_service as connector_api
    with sessions() as db:
        db.add(Product(id="product-cs", sku="CS-G25-A", product_name_cn="小青炉升级版", barcode="3", brand="测试"))
        db.commit()

    created = client.post(
        "/api/workbuddy/customer-service/tokens",
        headers=user_headers,
        json={},
    )
    token = created.json()["token"]
    calls = []

    async def fake_ask_customer_service(db, **kwargs):
        calls.append(kwargs)
        return {
            "answer": "小青炉的燃料请按说明书要求使用。",
            "conversation_id": "conversation-1",
            "message_id": "message-1",
            "answer_type": "faq",
            "intent": "customer_faq",
            "confidence": "high",
            "uncertainty": "confirmed",
            "needs_clarification": False,
            "suggested_followups": ["还想了解点火步骤吗？"],
            "sku": "CS-G25-A",
            "result_skus": ["CS-G25-A"],
            "sources": [
                {
                    "type": "rag_evidence",
                    "source_type": "knowledge_chunk",
                    "source_id": "doc-1",
                    "source_title": "小青炉升级版 FAQ",
                    "source_section": "使用与燃料",
                    "evidence_id": "evidence-1",
                    "content": "private source content is not exposed by this connector",
                },
                {"type": "agent_meta", "source_type": "internal", "answer_metadata": {"secret": "omit"}},
            ],
            "debug": {"internal": "omit"},
            "answer_metadata": {"internal": "omit"},
        }

    monkeypatch.setattr(connector_api.customer_service_service, "ask_customer_service", fake_ask_customer_service)
    monkeypatch.setattr(connector_api.customer_llm_service, "set_governed_customer_user", lambda user: object())
    monkeypatch.setattr(connector_api.customer_llm_service, "reset_governed_customer_user", lambda token: None)

    response = client.post(
        "/api/workbuddy/customer-service/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "客户问燃料", "sku": "CS-G25-A", "conversation_id": "conversation-0"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("小青炉")
    assert payload["conversation_id"] == "conversation-1"
    assert payload["message_id"] == "message-1"
    assert payload["sources"] == [{
        "source_type": "knowledge_chunk",
        "sku": None,
        "source_id": "doc-1",
        "evidence_id": "evidence-1",
        "title": "小青炉升级版 FAQ",
        "section": "使用与燃料",
    }]
    assert "debug" not in payload
    assert "content" not in payload["sources"][0]
    assert calls[0]["user_id"] == "wb-connector-user"
    assert calls[0]["question"] == "客户问燃料"
    assert calls[0]["conversation_id"] == "conversation-0"
    assert calls[0]["pipeline"] == connector_api.customer_pipeline_service.WORKBUDDY_RAG_PIPELINE
    assert calls[0]["server_selected_pipeline"] is True


def test_product_link_uses_existing_skus_and_preserves_variants(connector_client):
    client, _, user_headers = connector_client
    reader = _connector_headers(client, user_headers)
    url = "https://detail.tmall.com/item.htm?id=123456&spm=share"
    search = CONNECTOR_PATH + "/products/search"
    mapping = CONNECTOR_PATH + "/product-links"
    assert client.post(search, headers=reader, json={"query": url}).json()["status"] == "link_mapping_missing"
    assert client.put(mapping, headers=reader, json={"url": url, "sku": "TEST-SKU-A"}).status_code == 401
    assert client.put(mapping, headers=user_headers, json={"url": url, "sku": "NOT-IN-CATALOG"}).status_code == 404
    for sku in ("TEST-SKU-A", "TEST-SKU-B"):
        saved = client.put(mapping, headers=user_headers, json={"url": url, "sku": sku})
        assert saved.status_code == 200
        assert saved.json()["changed"]
    mobile = "https://h5.m.taobao.com/awp/core/detail.htm?id=123456&track=other"
    result = client.post(search, headers=reader, json={"query": mobile}).json()
    assert result["status"] == "choose_variant"
    assert {item["sku"] for item in result["items"]} == {"TEST-SKU-A", "TEST-SKU-B"}
    listing = CONNECTOR_PATH + "/listings/search"
    lookup = {"sku": "TEST-SKU-A", "query": "收纳配置"}
    assert client.post(listing, headers=reader, json=lookup).json()["status"] == "no_snapshot"
    saved = client.put(mapping, headers=user_headers, json={
        "url": url, "sku": "TEST-SKU-A", "snapshot_text": "配置：附收纳袋",
    })
    assert saved.json()["changed"]
    evidence = client.post(listing, headers=reader, json=lookup).json()["items"]
    assert evidence[0]["excerpt"] == "配置：附收纳袋"
    assert evidence[0]["url"] == "https://item.taobao.com/item.htm?id=123456"
    assert client.post(listing, headers=reader, json={**lookup, "sku": "TEST-SKU-B"}).json()["items"] == []
    assert client.put(mapping, headers=user_headers, json={
        "url": url, "sku": "TEST-SKU-B", "enabled": False,
    }).status_code == 200
    assert client.post(search, headers=reader, json={"query": mobile}).json()["status"] == "mapped_link"


def test_exact_sku_search_returns_only_the_selected_variant(connector_client):
    client, sessions, user_headers = connector_client
    with sessions() as db:
        db.add(Product(id="product-a-pro", sku="TEST-SKU-A-PRO", product_name_cn="测试炉专业版", barcode="3", brand="测试"))
        db.commit()
    reader = _connector_headers(client, user_headers)
    payload = client.post(CONNECTOR_PATH + "/products/search", headers=reader, json={"query": "test-sku-a"}).json()
    assert payload == {"status": "exact_sku", "items": [{"sku": "TEST-SKU-A", "name": "测试炉"}]}


def test_product_search_ignores_spacing_in_product_names(connector_client):
    client, sessions, user_headers = connector_client
    reader = _connector_headers(client, user_headers)
    with sessions() as db:
        db.add(Product(id="product-plus", sku="TEST-PLUS", product_name_cn="享膳Plus水壶", barcode="3", brand="测试"))
        db.add(Product(id="product-time", sku="TEST-TIME", product_name_cn="时光煮水户外水壶套装", barcode="4", brand="测试"))
        db.commit()
    result = client.post(CONNECTOR_PATH + "/products/search", headers=reader, json={"query": "享膳 Plus"}).json()
    assert [item["sku"] for item in result["items"]] == ["TEST-PLUS"]
    result = client.post(CONNECTOR_PATH + "/products/search", headers=reader, json={"query": "时光煮水套装"}).json()
    assert [item["sku"] for item in result["items"]] == ["TEST-TIME"]


def test_ask_rejects_unknown_explicit_sku(connector_client):
    client, _, user_headers = connector_client
    reader = _connector_headers(client, user_headers)
    response = client.post(CONNECTOR_PATH + "/ask", headers=reader, json={"question": "带锅盖吗？", "sku": "MISSING-SKU"})
    assert response.status_code == 404


def test_product_profile_and_export_show_only_selected_product(connector_client, monkeypatch):
    client, _, user_headers = connector_client
    from app.services import workbuddy_customer_knowledge_service as service

    monkeypatch.setattr(service.product_service, "get_product_detail", lambda db, sku: {
        "specs": {"capacity": [{"value": "2.3", "unit": "L"}], "body_material": "铝合金"},
        "content": {"long_description_cn": "商品描述"},
        "business": {"price_positioning": "内部信息"},
    })
    headers = _connector_headers(client, user_headers)
    prefix = CONNECTOR_PATH + "/products/"
    profile = client.post(prefix + "profile", headers=headers, json={"sku": "test-sku-a"})
    assert profile.status_code == 200
    assert profile.json()["sku"] == "TEST-SKU-A"
    assert profile.json()["specs"]["body_material"] == "铝合金"
    assert "business" not in profile.json()
    response = client.post(prefix + "export", headers=headers, json={"sku": "TEST-SKU-A"})
    assert response.status_code == 200
    paragraphs = [p.text for p in Document(BytesIO(response.content)).paragraphs]
    assert any("2.3 L" in p for p in paragraphs)
    assert any("铝合金" in p for p in paragraphs)
    assert any("商品描述" in p for p in paragraphs)
    assert all("内部信息" not in p for p in paragraphs)
    assert client.post(prefix + "profile", headers=headers, json={"sku": "missing"}).status_code == 404


def test_stdio_retries_reads_but_not_stateful_calls(monkeypatch):
    from urllib.error import URLError
    from scripts.customer_service_mcp_server import CustomerServiceMcp

    mcp = CustomerServiceMcp("http://127.0.0.1:18101", "", anonymous=True)
    attempts = []

    def send(name, arguments, request, *, timeout):
        attempts.append((name, timeout))
        if len(attempts) == 1 or name == "revise_customer_qa":
            raise URLError("temporary connection error")
        return {"isError": False}

    monkeypatch.setattr(mcp, "_send", send)
    assert not mcp._call("export_customer_qa", {"sku": "TEST-SKU-A"})["isError"]
    assert mcp._call("revise_customer_qa", {"sku": "TEST-SKU-A"})["isError"]
    assert attempts == [
        ("export_customer_qa", 15), ("export_customer_qa", 15), ("revise_customer_qa", 120),
    ]


def test_workbuddy_clarification_keeps_explicitly_selected_product(connector_client):
    _, sessions, _ = connector_client
    from app.services import customer_service_workbuddy_rag_service as rag

    meta = {
        "type": "agent_meta", "result_skus": [], "candidate_skus": ["TEST-SKU-B"],
        "answer_metadata": {"confirmed_request_sku": "TEST-SKU-A", "purchase_identity_reset": True},
    }
    with sessions() as db:
        db.add(CustomerServiceConversation(id="clarify-connector", user_id="wb-connector-user",
                                           pipeline=rag.PIPELINE_VERSION))
        db.add(CustomerServiceMessage(id="clarify-answer", conversation_id="clarify-connector",
                                      role="assistant", content="请确认炉具类型。", sources_json=json.dumps([meta])))
        db.commit()
        memory = rag._load_previous_turn_memory(db, user_id="wb-connector-user", conversation_id="clarify-connector")
    assert memory["active_product_skus"] == ["TEST-SKU-A"]
    assert memory["candidate_product_skus"] == ["TEST-SKU-B"]


def test_named_product_qa_recall_matches_hose_question(connector_client):
    _, sessions, _ = connector_client
    from app.services import customer_service_workbuddy_rag_service as rag

    with sessions() as db:
        db.add_all([
            ProductQa(product_id="product-a", question="测试炉的气管有多长？",
                      answer="原配气管约 37 厘米。", integrity_status="approved"),
            ProductQa(product_id="product-a", question="测试炉支持什么气罐？",
                      answer="使用适配气罐。", integrity_status="approved"),
            ProductQa(product_id="product-a", question="测试炉的气管有多长？",
                      answer="错误的待审记录。", integrity_status="review"),
        ])
        db.commit()
        rows = rag._lexical_candidate_qa(db, "TEST-SKU-A", "测试炉连接气罐的那根软管大概有多长？")
    assert len(rows) == 1
    assert "37 厘米" in rows[0]["content"]
    assert "待审" not in rows[0]["content"]


def test_connector_sources_exclude_other_products():
    from app.api.workbuddy_customer_service import _connector_answer

    sources = [
        {"sku": "TEST-SKU-B", "source_id": "other", "source_type": "product_record"},
        {"sku": "TEST-SKU-A", "source_id": "selected", "source_type": "product_record"},
    ]
    result = _connector_answer({"answer": "答复", "result_skus": ["TEST-SKU-A"], "sources": sources})
    assert [source["source_id"] for source in result["sources"]] == ["selected"]
    ambiguous = _connector_answer({"answer": "请确认型号", "result_skus": [], "sources": sources})
    assert ambiguous["sources"] == []


def test_qa_revision_preserves_original_until_review_and_rejects_stale_proposals(connector_client, monkeypatch):
    client, sessions, user_headers = connector_client
    from app.services import workbuddy_customer_knowledge_service as service

    original_id = "52bbc483-f44d-41dc-8e3a-8c404a5573cb"
    with sessions() as db:
        db.add(ProductQa(id=original_id, product_id="product-a", question="有没有收纳袋？",
                         answer="原答案", integrity_status="approved"))
        db.commit()
    read_headers = _connector_headers(client, user_headers)
    qa_headers = _connector_headers(client, user_headers, write=True)
    path = CONNECTOR_PATH + "/qa-revisions"
    revision = {"sku": "TEST-SKU-A", "qa_id": original_id, "answer": "新答案", "confirmed": True}
    assert client.post(path, headers=read_headers, json=revision).status_code == 403
    assert client.post(path, headers=qa_headers, json={**revision, "confirmed": False}).status_code == 422
    assert client.post(path, headers=qa_headers, json={**revision, "sku": "TEST-SKU-B"}).status_code == 404
    first = client.post(path, headers=qa_headers, json=revision).json()
    assert first["status"] == "saved" and first["target_qa_id"] == original_id
    repeated = client.post(path, headers=qa_headers, json=revision).json()
    assert repeated["status"] == "existing" and repeated["qa_id"] == first["qa_id"]
    second = client.post(path, headers=qa_headers, json={**revision, "answer": "其他建议"}).json()
    approved_before = client.post(CONNECTOR_PATH + "/knowledge/search", headers=read_headers, json={
        "sku": "TEST-SKU-A", "query": "有没有收纳袋？", "limit": 1,
    }).json()
    assert approved_before["items"][0]["answer"] == "原答案"

    status = "rejected"
    async def audit(db, product, qa, **kwargs):
        qa.integrity_status = status
        qa.integrity_reason = "测试审核"
        db.flush([qa])
        return {"status": status, "reason": "测试审核"}

    monkeypatch.setattr(service.product_qa_integrity_service, "audit_product_qa_item", audit)
    monkeypatch.setattr(service.product_service, "sync_product_to_vector_db", lambda *a: {"ready_for_rag": True})
    review_path = "/api/products/TEST-SKU-A/qa/" + first["qa_id"]
    rejected = client.put(review_path, headers=user_headers, json={"answer": "新答案"}).json()
    assert rejected["integrity_status"] == "rejected"
    with sessions() as db:
        assert db.get(ProductQa, original_id).answer == "原答案"

    status = "approved"
    accepted = client.put(review_path, headers=user_headers, json={"answer": "新答案"}).json()
    assert accepted["id"] == original_id and accepted["ready_for_rag"] is True
    with sessions() as db:
        assert db.get(ProductQa, original_id).answer == "新答案"
        assert db.get(ProductQa, first["qa_id"]) is None
    stale = client.put("/api/products/TEST-SKU-A/qa/" + second["qa_id"], headers=user_headers, json={})
    assert stale.status_code == 409


def test_qa_export_contains_all_matching_rows_and_protects_unapproved(connector_client):
    client, sessions, user_headers = connector_client
    read_headers = _connector_headers(client, user_headers)
    qa_headers = _connector_headers(client, user_headers, write=True)
    path = CONNECTOR_PATH + "/knowledge/export"
    with sessions() as db:
        db.add_all([
            ProductQa(product_id="product-a", question=f"问题 {i}", answer=f"答案 {i}\n补充说明",
                      integrity_status="approved")
            for i in range(12)
        ])
        db.add_all([
            ProductQa(product_id="product-a", question="未审问题", answer="未审答案", integrity_status="review"),
            ProductQa(product_id="product-a", question="拒绝问题", answer="拒绝答案", integrity_status="rejected"),
            ProductQa(product_id="product-b", question="另一规格问题", answer="另一规格答案", integrity_status="approved"),
        ])
        db.commit()

    response = client.post(path, headers=read_headers, json={"sku": " test-sku-a "})
    assert response.status_code == 200
    assert response.headers["X-CaiYan-SKU"] == "TEST-SKU-A"
    assert response.headers["X-CaiYan-QA-Count"] == "12"
    assert response.headers["Cache-Control"] == "no-store"
    paragraphs = {p.text for p in Document(BytesIO(response.content)).paragraphs}
    assert {f"问  问题 {i}" for i in range(12)} <= paragraphs
    assert {f"答  答案 {i}\n补充说明" for i in range(12)} <= paragraphs
    assert {"问  未审问题", "问  拒绝问题", "问  另一规格问题"}.isdisjoint(paragraphs)

    all_states = {"sku": "TEST-SKU-A", "include_unapproved": True}
    assert client.post(path, json=all_states).status_code == 401
    assert client.post(path, headers=read_headers, json=all_states).status_code == 403
    all_response = client.post(path, headers=qa_headers, json=all_states)
    assert all_response.status_code == 200
    assert all_response.headers["X-CaiYan-QA-Count"] == "14"
    paragraphs = [p.text for p in Document(BytesIO(all_response.content)).paragraphs]
    assert {"问  未审问题", "问  拒绝问题"} <= set(paragraphs)
    assert "问  另一规格问题" not in paragraphs
    assert any(text.endswith("  待审核") for text in paragraphs)
    assert any(text.endswith("  未通过") for text in paragraphs)
    assert client.post(path, headers=read_headers, json={"sku": "TEST-NOT-FOUND"}).status_code == 404


def test_qa_semantic_search_accepts_postgresql_uuid_ids(connector_client, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.services import workbuddy_customer_knowledge_service as service

    client, _, user_headers = connector_client
    reader = _connector_headers(client, user_headers)
    qa = SimpleNamespace(id=uuid4(), question="原配软管多长？", answer="37 cm")
    monkeypatch.setattr(service.product_service, "customer_visible_product_qas", lambda *args: [qa])

    async def semantic_hits(db, query, **kwargs):
        assert query == "炉子连罐子的那根气管大概多少厘米"
        return [{"metadata": {"source_id": f"product:TEST-SKU-A:qa:{qa.id}"}}]

    monkeypatch.setattr(service.knowledge_service, "semantic_retrieve", semantic_hits)
    result = client.post(CONNECTOR_PATH + "/knowledge/search", headers=reader, json={
        "sku": "TEST-SKU-A", "query": "炉子连罐子的那根软管大概多少厘米", "limit": 1,
    })
    assert result.status_code == 200
    assert result.json()["items"] == [{"qa_id": str(qa.id), "question": qa.question, "answer": qa.answer, "match": "candidate"}]


def test_confirmed_qa_capture_is_deduplicated_and_hidden_until_approved(connector_client):
    client, sessions, user_headers = connector_client
    reader = _connector_headers(client, user_headers)
    writer = _connector_headers(client, user_headers, write=True)
    draft_path = CONNECTOR_PATH + "/qa-drafts"
    body = {"sku": "TEST-SKU-A", "question": "锅盖可以单独买？", "answer": "可单独购买。", "confirmed": True}
    assert client.post(draft_path, headers=reader, json=body).status_code == 403
    assert client.post(draft_path, headers=writer, json={**body, "confirmed": False}).status_code == 422
    assert client.post(draft_path, headers=writer, json={**body, "answer": "联系 test@example.com"}).status_code == 422
    assert client.post(draft_path, headers=writer, json={**body, "message_id": "unknown"}).status_code == 404
    result = client.post(draft_path, headers=writer, json=body)
    assert result.status_code == 200, result.text
    draft = result.json()
    assert draft["integrity_status"] == "review"
    assert draft["qa_id"] in draft["review_path"]
    repeat = client.post(draft_path, headers=writer, json=body).json()
    assert repeat["status"] == "existing"
    assert repeat["qa_id"] == draft["qa_id"]
    assert client.post(draft_path, headers=writer, json={**body, "answer": "无法单独购买"}).status_code == 409
    search = CONNECTOR_PATH + "/knowledge/search"
    lookup = {"sku": "TEST-SKU-A", "query": "锅盖可以单独买", "limit": 1}
    assert client.post(search, headers=reader, json=lookup).json()["items"] == []
    with sessions() as db:
        qa = db.get(ProductQa, draft["qa_id"])
        qa.integrity_status = "approved"
        db.commit()
    assert client.post(search, headers=reader, json=lookup).json()["items"][0]["qa_id"] == draft["qa_id"]


def test_qa_draft_can_reference_an_answer_owned_by_a_postgresql_uuid_user(connector_client):
    from uuid import uuid4

    from app.services import workbuddy_customer_knowledge_service as service

    _, sessions, _ = connector_client
    user_id = uuid4()
    with sessions() as db:
        db.add(CustomerServiceConversation(id="qa-source-conversation", user_id=str(user_id), sku="TEST-SKU-A"))
        db.add(CustomerServiceMessage(id="qa-source-answer", conversation_id="qa-source-conversation", role="assistant",
                                      sku="TEST-SKU-A", content="原装软管长37厘米。"))
        db.commit()
        receipt = service.save_qa_draft(db, user_id=user_id, sku="TEST-SKU-A", question="软管长度？", answer="37 cm",
                                        message_id="qa-source-answer", request=None)
        assert receipt["status"] == "saved"
        assert receipt["integrity_status"] == "review"


def test_workbuddy_token_cannot_be_used_as_a_normal_user_access_token(connector_client):
    client, _, user_headers = connector_client
    created = client.post(
        "/api/workbuddy/customer-service/tokens",
        headers=user_headers,
        json={},
    )
    token = created.json()["token"]

    response = client.post(
        "/api/workbuddy/customer-service/tokens",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 401
