import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.product import Product
from app.models.product_qa import ProductQa
from app.models.product_business import ProductBusiness
from app.models.product_content import ProductContent
from app.models.product_specs import ProductSpecs
from app.services import product_qa_integrity_service
from app.services import product_service
from app.services import customer_agent_intent_service, customer_service_service, product_vector_index_service
from scripts.audit_product_qa_integrity import apply_audit_ledger, ensure_development_target


def test_rejected_qa_keeps_original_text_but_is_not_customer_visible():
    """Quarantined QA stays reviewable but cannot become customer evidence."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-product",
            sku="QA-INTEGRITY-1",
            barcode="000000000001",
            product_name_cn="测试水壶",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-integrity-rejected",
            product_id=product.id,
            question="第一次使用要注意什么？",
            answer="先预热再倒油。",
            integrity_status="rejected",
        )
        db.add_all([product, qa])
        db.commit()

        visible = product_service.customer_visible_product_qas(db, product.id)

        assert qa.answer == "先预热再倒油。"
        assert visible == []
    finally:
        db.close()
        engine.dispose()


def test_stale_vector_qa_requires_live_approved_provenance():
    """An old chunk cannot outlive the ProductQa integrity decision behind it."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-provenance-product",
            sku="QA-PROVENANCE-1",
            barcode="qa-provenance-barcode",
            product_name_cn="测试水壶",
            brand="alocs",
        )
        approved = ProductQa(
            id="qa-approved",
            product_id=product.id,
            question="容量是多少？",
            answer="容量为 1L。",
            integrity_status="approved",
        )
        rejected = ProductQa(
            id="qa-rejected",
            product_id=product.id,
            question="研磨粗细能调吗？",
            answer="可以自由调节。",
            integrity_status="rejected",
        )
        db.add_all([product, approved, rejected])
        db.commit()

        rows = [
            {"content": "profile", "metadata": {"source_id": "product:QA-PROVENANCE-1:profile"}},
            {"content": "approved", "metadata": {"source_id": "product:QA-PROVENANCE-1:qa:qa-approved"}},
            {"content": "stale", "metadata": {"source_id": "product:QA-PROVENANCE-1:qa:qa-rejected"}},
        ]

        visible = customer_service_service._knowledge_rows_with_approved_qa_provenance(
            db,
            rows,
            sku=product.sku,
        )

        assert [item["content"] for item in visible] == ["profile", "approved"]
    finally:
        db.close()
        engine.dispose()




def test_editing_qa_reopens_semantic_integrity_review():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-edit-product",
            sku="QA-EDIT-1",
            barcode="qa-edit-barcode",
            product_name_cn="测试产品",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-edit-item",
            product_id=product.id,
            question="原问题？",
            answer="原答案。",
            integrity_status="approved",
            integrity_reason="previous audit",
            integrity_model="deepseek-v4-flash",
        )
        db.add_all([product, qa])
        db.commit()

        updated = product_service.update_qa_item(db, qa.id, {"answer": "新答案。"})

        assert updated.integrity_status == "review"
        assert updated.integrity_reason is None
        assert updated.integrity_model is None
        assert updated.integrity_audited_at is None
    finally:
        db.close()
        engine.dispose()


def test_semantic_rejection_changes_only_audit_fields(monkeypatch):
    """An inapplicable QA is quarantined without rewriting its product text."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-semantic-product",
            sku="QA-INTEGRITY-2",
            barcode="000000000002",
            product_name_cn="测试水壶",
            brand="alocs",
            category="水壶",
        )
        qa = ProductQa(
            id="qa-integrity-semantic-rejected",
            product_id=product.id,
            question="第一次使用要注意什么？",
            answer="先预热再倒油。",
        )
        db.add_all([product, qa])
        db.commit()

        async def rejected_by_model(*_args, **_kwargs):
            return '{"status":"rejected","conflict_type":"invalid_qa","reason":"倒油指引不适用于水壶。"}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            rejected_by_model,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict == {"status": "rejected", "reason": "倒油指引不适用于水壶。"}
        assert qa.integrity_status == "rejected"
        assert qa.answer == "先预热再倒油。"
    finally:
        db.close()
        engine.dispose()


def test_policy_like_supplemental_fact_is_approved_without_master_evidence(monkeypatch):
    """A valid same-SKU policy QA may supplement otherwise silent master data."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-policy-product",
            sku="QA-INTEGRITY-5",
            barcode="000000000005",
            product_name_cn="test product",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-integrity-policy-qa",
            product_id=product.id,
            question="Does it have a warranty?",
            answer="It has a one-year warranty.",
        )
        db.add_all([product, qa])
        db.commit()

        async def no_conflict(*_args, **_kwargs):
            return '{"status":"review","conflict_type":"none","reason":"Master field is absent, but this is not a conflict."}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            no_conflict,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict == {
            "status": "approved",
            "reason": "Master field is absent, but this is not a conflict.",
        }
        assert qa.integrity_status == "approved"
    finally:
        db.close()
        engine.dispose()


def test_same_sku_supplemental_fact_is_approved_without_master_field(monkeypatch):
    """A same-SKU QA may contribute facts absent from master product fields."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-supplemental-product",
            sku="QA-INTEGRITY-6",
            barcode="000000000007",
            product_name_cn="camp water cup",
            brand="alocs",
            category="water cup",
        )
        qa = ProductQa(
            id="qa-integrity-supplemental-qa",
            product_id=product.id,
            question="有质保吗？",
            answer="提供一年质保。",
        )
        db.add_all([product, qa])
        db.commit()

        async def no_conflict(*_args, **_kwargs):
            return '{"status":"approved","conflict_type":"none","reason":"Supplemental QA fact."}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            no_conflict,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict["status"] == "approved"
        assert qa.integrity_status == "approved"
    finally:
        db.close()
        engine.dispose()


def test_direct_conflict_qa_is_rejected(monkeypatch):
    """Concrete same-SKU evidence rejects incompatible stove-use advice."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-direct-conflict-product",
            sku="QA-INTEGRITY-7",
            barcode="000000000008",
            product_name_cn="water cup",
            brand="alocs",
            category="water cup",
        )
        qa = ProductQa(
            id="qa-integrity-direct-conflict-qa",
            product_id=product.id,
            question="Can I use it on a stove?",
            answer="Yes, it is compatible with an open-flame stove.",
        )
        specs = ProductSpecs(
            product_id=product.id,
            heat_source="Not suitable for open-flame stove use.",
        )
        db.add_all([product, qa, specs])
        db.commit()

        calls = 0

        async def direct_conflict(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return '{"status":"approved","conflict_type":"none","reason":"The QA belongs to the water cup."}'
            return '{"status":"rejected","conflict_type":"direct_conflict","reason":"Evidence says no open flame.","evidence_quote":"Not suitable for open-flame stove use."}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            direct_conflict,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict["status"] == "rejected"
        assert calls == 2
        assert qa.integrity_status == "rejected"
    finally:
        db.close()
        engine.dispose()


def test_cross_category_qa_is_rejected(monkeypatch):
    """QA for another product category is rejected even when it sounds plausible."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-cross-category-product",
            sku="QA-INTEGRITY-8",
            barcode="000000000009",
            product_name_cn="water cup",
            brand="alocs",
            category="water cup",
        )
        qa = ProductQa(
            id="qa-integrity-cross-category-qa",
            product_id=product.id,
            question="What pan coating does it use?",
            answer="Its non-stick pan coating is easy to clean.",
        )
        db.add_all([product, qa])
        db.commit()

        async def cross_category(*_args, **_kwargs):
            return '{"status":"rejected","conflict_type":"cross_category","reason":"QA describes a frying pan, not a water cup."}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            cross_category,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict["status"] == "rejected"
        assert qa.integrity_status == "rejected"
    finally:
        db.close()
        engine.dispose()


def test_cross_category_audit_prioritizes_product_identity_over_contaminated_detail(monkeypatch):
    """A copied appliance instruction cannot override the product's identity evidence."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-identity-priority-product",
            sku="QA-INTEGRITY-IDENTITY-1",
            barcode="000000000019",
            product_name_cn="camping moka pot",
            brand="alocs",
            category="coffee equipment",
        )
        specs = ProductSpecs(
            product_id=product.id,
            usage_instruction="Adjust grind size and clean the grinder burrs after use.",
        )
        content = ProductContent(
            product_id=product.id,
            title_cn="camping moka pot for espresso coffee",
        )
        qa = ProductQa(
            id="qa-integrity-identity-priority-qa",
            product_id=product.id,
            question="Can I adjust the grind size?",
            answer="Yes, freely adjust the grind size for pour-over, French press, and espresso.",
        )
        db.add_all([product, specs, content, qa])
        db.commit()

        calls = []

        async def cross_category(_db, messages, **_kwargs):
            prompt = messages[0]["content"]
            payload = __import__("json").loads(messages[1]["content"])
            calls.append(payload)
            assert "product identity only" in prompt
            assert payload["product_identity"]["category"] == "coffee equipment"
            assert "supplemental_context" not in payload
            return '{"status":"rejected","conflict_type":"cross_category","reason":"A moka pot cannot provide grinder adjustment."}'

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            cross_category,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict["status"] == "rejected"
        assert len(calls) == 1
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("", "A nonempty answer."),
        ("A nonempty question?", "  "),
    ],
)
def test_empty_qa_is_rejected_without_model_call(monkeypatch, question, answer):
    """Empty QA is invalid independent of provider availability."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id=f"qa-integrity-empty-product-{len(question)}",
            sku=f"QA-INTEGRITY-EMPTY-{len(question)}",
            barcode=f"00000000001{len(question)}",
            product_name_cn="water cup",
            brand="alocs",
            category="water cup",
        )
        qa = ProductQa(
            id=f"qa-integrity-empty-qa-{len(question)}",
            product_id=product.id,
            question=question,
            answer=answer,
        )
        db.add_all([product, qa])
        db.commit()

        async def should_not_run(*_args, **_kwargs):
            raise AssertionError("empty QA must be rejected before calling the model")

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            should_not_run,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict == {"status": "rejected", "reason": "Question or answer is empty."}
        assert qa.integrity_status == "rejected"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "raw",
    [
        '{"status":"review","conflict_type":"missing_master_data","reason":"Master field absent."}',
        '{"status":"approved","conflict_type":"none","reason":{"detail":"not a string"}}',
    ],
)
def test_unclassifiable_model_result_remains_review(monkeypatch, raw):
    """A model result outside the exact JSON contract is a technical review."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Product.__table__, ProductQa.__table__, ProductSpecs.__table__,
        ProductBusiness.__table__, ProductContent.__table__,
    ])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-invalid-contract-product",
            sku="QA-INTEGRITY-INVALID-CONTRACT",
            barcode="000000000011",
            product_name_cn="water cup",
            brand="alocs",
            category="water cup",
        )
        qa = ProductQa(
            id="qa-integrity-invalid-contract-qa",
            product_id=product.id,
            question="Does it have a warranty?",
            answer="It has a one-year warranty.",
        )
        db.add_all([product, qa])
        db.commit()

        async def unclassifiable(*_args, **_kwargs):
            return raw

        monkeypatch.setattr(
            product_qa_integrity_service.customer_llm_service,
            "chat_completion",
            unclassifiable,
        )
        verdict = asyncio.run(product_qa_integrity_service.audit_product_qa_item(db, product, qa))

        assert verdict["status"] == "review"
        assert qa.integrity_status == "review"
    finally:
        db.close()
        engine.dispose()


def test_classifier_reason_is_preserved_without_truncation():
    """A valid nonempty classifier reason is retained exactly."""
    reason = "r" * 1001

    verdict = product_qa_integrity_service._parse_verdict(
        f'{{"status":"approved","conflict_type":"none","reason":"{reason}"}}'
    )

    assert verdict["reason"] == reason


def test_unverifiable_direct_conflict_remains_review():
    """A claimed conflict cannot reject supplemental QA without same-SKU evidence."""
    verdict = product_qa_integrity_service._normalize_supplemental_verdict(
        {
            "status": "rejected",
            "conflict_type": "direct_conflict",
            "reason": "Claimed material conflict.",
            "evidence_quote": "PTFE coating",
        },
        question="What is the surface finish?",
        answer="It uses a matte finish.",
        evidence={"specs": {"material": "aluminum"}},
    )

    assert verdict["status"] == "review"


def test_rejected_qa_is_excluded_from_customer_matching_and_vector_documents():
    """Rejected QA cannot re-enter customer evidence through a legacy reader."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-customer-product",
            sku="QA-INTEGRITY-3",
            barcode="000000000003",
            product_name_cn="测试水壶",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-integrity-customer-rejected",
            product_id=product.id,
            question="第一次使用要注意什么？",
            answer="先预热再倒油。",
            integrity_status="rejected",
        )
        db.add_all([product, qa])
        db.commit()

        matched = customer_service_service._best_product_qa_match(db, product, qa.question)
        documents = product_vector_index_service.build_product_documents({
            "sku": product.sku,
            "qa_items": [{
                "id": qa.id,
                "question": qa.question,
                "answer": qa.answer,
                "integrity_status": qa.integrity_status,
            }],
        })

        assert matched is None
        assert not any(doc["metadata"]["section"].startswith("qa:") for doc in documents)
    finally:
        db.close()
        engine.dispose()


def test_rejected_qa_is_excluded_from_keyword_retrieval():
    """The semantic retrieval helper cannot bypass the customer evidence boundary."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-integrity-retrieval-product",
            sku="QA-INTEGRITY-4",
            barcode="000000000004",
            product_name_cn="测试水壶",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-integrity-retrieval-rejected",
            product_id=product.id,
            question="第一次使用要注意什么？",
            answer="先预热再倒油。",
            integrity_status="rejected",
        )
        db.add_all([product, qa])
        db.commit()

        assert customer_agent_intent_service._search_product_qa(db, product.sku, "第一次使用要注意什么") == []
    finally:
        db.close()
        engine.dispose()


def test_history_audit_refuses_non_development_database():
    with __import__("pytest").raises(RuntimeError, match="development"):
        ensure_development_target(SimpleNamespace(APP_ENV="prod", DATABASE_URL="postgresql://localhost/product_knowledge"))


def test_reviewed_ledger_is_applied_without_reauditing(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Product.__table__, ProductQa.__table__])
    db = sessionmaker(bind=engine)()
    try:
        product = Product(
            id="qa-ledger-product",
            sku="QA-LEDGER-1",
            barcode="000000000006",
            product_name_cn="ledger test product",
            brand="alocs",
        )
        qa = ProductQa(
            id="qa-ledger-item",
            product_id=product.id,
            question="Is it valid?",
            answer="No.",
            integrity_status="review",
        )
        db.add_all([product, qa])
        db.commit()
        indexed = []
        monkeypatch.setattr(product_vector_index_service, "index_product", lambda _db, sku: indexed.append(sku))

        apply_audit_ledger(db, [{
            "qa_id": qa.id,
            "sku": product.sku,
            "status": "rejected",
            "reason": "Direct conflict with same-SKU evidence.",
        }])

        assert db.get(ProductQa, qa.id).integrity_status == "rejected"
        assert indexed == [product.sku]
    finally:
        db.close()
        engine.dispose()
