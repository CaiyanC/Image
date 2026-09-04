import asyncio
import json
import uuid
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument
from ..models.product import Product
from . import dmxapi_service, product_service


PRODUCT_SOURCE_TYPE = "product"
RECOMMENDATION_SECTION = "recommendation"


def customer_visible_usage_instruction(
    *,
    product_name_cn: Any,
    product_name_en: Any,
    category: Any,
    sub_category: Any,
    value: Any,
) -> str:
    """Exclude an instruction cell that clearly belongs to another product domain."""
    instruction = str(value or "").strip()
    identity = " ".join(
        str(part or "")
        for part in (product_name_cn, product_name_en, category, sub_category)
    )
    domain_rules = (
        (("研磨粗细", "研磨器", "刀盘", "grind size", "grinder burr"), ("磨豆", "研磨机", "研磨器", "grinder")),
        (("气罐对准炉头", "火力调节阀", "按下点火装置"), ("炉", "灶", "烤炉")),
    )
    for evidence_terms, identity_terms in domain_rules:
        if any(term in instruction for term in evidence_terms) and not any(term in identity for term in identity_terms):
            return ""
    cup_only = "杯" in identity and not any(term in identity for term in ("壶", "锅", "炉", "灶"))
    cookware_markers = ("锅身", "水壶置于灶具", "壶身", "壶底", "烹饪前", "小火预热", "严禁干烧")
    if cup_only and sum(marker in instruction for marker in cookware_markers) >= 2:
        return ""
    return instruction


def build_product_documents(detail: dict[str, Any]) -> list[dict[str, Any]]:
    sku = str(detail.get("sku") or "").strip()
    if not sku:
        return []

    docs: list[dict[str, Any]] = []

    recommendation_doc = build_product_recommendation_document(detail)
    if recommendation_doc:
        docs.append(recommendation_doc)

    profile_lines = _compact_lines([
        ("SKU", sku),
        ("中文名", detail.get("product_name_cn")),
        ("英文名", detail.get("product_name_en")),
        ("品牌", detail.get("brand")),
        ("系列", detail.get("series")),
        ("类目", _join_nonempty([detail.get("category"), detail.get("sub_category")], " / ")),
        ("等级", detail.get("product_level")),
        ("生命周期", detail.get("lifecycle_status")),
        ("负责人", detail.get("person_in_charge")),
        ("品质情况", detail.get("quality_note")),
        ("备注", detail.get("status_note")),
    ])

    specs = dict(detail.get("specs") or {})
    specs["usage_instruction"] = customer_visible_usage_instruction(
        product_name_cn=detail.get("product_name_cn"),
        product_name_en=detail.get("product_name_en"),
        category=detail.get("category"),
        sub_category=detail.get("sub_category"),
        value=specs.get("usage_instruction"),
    )
    profile_lines.extend(_section_lines("规格信息", specs, [
        ("size_info", "尺寸"),
        ("capacity", "容量"),
        ("gross_weight_g", "毛重g"),
        ("body_material", "材质"),
        ("color", "颜色"),
        ("surface_finish", "表面工艺"),
        ("heat_source", "适用热源"),
        ("power", "功率"),
        ("technical_advantages", "技术优势"),
        ("usage_instruction", "使用说明"),
    ]))

    business = detail.get("business") or {}
    profile_lines.extend(_section_lines("业务信息", business, [
        ("top_selling_points", "核心卖点"),
        ("target_audience", "目标人群"),
        ("positioning", "定位"),
        ("price_positioning", "价格定位"),
        ("emotional_value", "情绪价值"),
        ("usage_scenarios", "使用场景"),
        ("competitor_benchmark", "竞品信息"),
    ]))

    association_lines = _compact_lines([
        ("关键词", [item.get("keyword") for item in detail.get("keywords") or []]),
        ("渠道", [item.get("channel_name") for item in detail.get("channels") or []]),
        ("地区", [item.get("region_name") for item in detail.get("regions") or []]),
        ("认证", [item.get("certification_name") for item in detail.get("certifications") or []]),
    ])
    if association_lines:
        profile_lines.append("关联信息:")
        profile_lines.extend(f"- {line}" for line in association_lines)

    docs.append(_doc(sku, "profile", f"{sku} 产品基础与规格", profile_lines))

    content = detail.get("content") or {}
    content_lines = _section_lines("内容信息", content, [
        ("title_cn", "中文标题"),
        ("title_en", "英文标题"),
        ("long_description_cn", "中文描述"),
        ("long_description_en", "英文描述"),
        ("long_description_ja", "日文描述"),
        ("search_keywords", "搜索关键词"),
        ("amazon_title", "Amazon 标题"),
        ("website_title", "官网标题"),
        ("bullet_points", "五点描述"),
        ("a_plus_content", "A+ 内容"),
        ("listing_cn", "中文 Listing"),
        ("listing_en", "英文 Listing"),
        ("listing_ja", "日文 Listing"),
    ])
    if content_lines:
        docs.append(_doc(sku, "content", f"{sku} Listing 与内容", content_lines))

    for index, item in enumerate(detail.get("qa_items") or [], start=1):
        if str(item.get("integrity_status") or "").strip().lower() != "approved":
            continue
        question = _stringify(item.get("question"))
        answer = _stringify(item.get("answer"))
        if not question and not answer:
            continue
        item_id = item.get("id") or str(index)
        lines = [f"Q: {question}", f"A: {answer}"]
        tags = _stringify(item.get("tags"))
        if tags:
            lines.append(f"标签: {tags}")
        docs.append(_doc(sku, f"qa:{item_id}", f"{sku} QA {index}", lines))

    qa_negative = detail.get("qa_negative")
    if qa_negative:
        negative_lines = _compact_lines([
            ("高频负面词", qa_negative.get("high_freq_negative_words")),
            ("应答口径", qa_negative.get("response_tone")),
        ])
        if negative_lines:
            item_id = qa_negative.get("id") or "default"
            docs.append(_doc(sku, f"qa_negative:{item_id}", f"{sku} 差评应答", negative_lines))

    return [item for item in docs if item["content"].strip()]


def build_product_recommendation_document(
    detail: dict[str, Any],
) -> dict[str, Any] | None:
    """Build one compact retrieval-only document for a catalogue SKU.

    The document makes product identity, form, use, audience and maintained
    specifications available to semantic recall. It is not an answer evidence
    source; customer-service verification still binds claims to the product row.
    """
    sku = str(detail.get("sku") or "").strip()
    if not sku:
        return None

    specs = dict(detail.get("specs") or {})
    business = dict(detail.get("business") or {})
    content = dict(detail.get("content") or {})
    lines = _compact_lines([
        ("SKU", sku),
        ("商品名称", detail.get("product_name_cn")),
        ("英文名称", detail.get("product_name_en")),
        ("商品类目", detail.get("category")),
        ("商品子类", detail.get("sub_category")),
        ("系列", detail.get("series")),
        ("中文标题", content.get("title_cn")),
        ("官网标题", content.get("website_title")),
        ("Amazon 标题", content.get("amazon_title")),
        ("检索关键词", content.get("search_keywords")),
        # Content is included here as semantic recall context.  The document
        # remains retrieval-only (fact_authority=False); final answers still
        # bind claims to the live same-SKU evidence packet.
        ("中文描述", content.get("long_description_cn")),
        ("英文描述", content.get("long_description_en")),
        ("中文 Listing", content.get("listing_cn")),
        ("英文 Listing", content.get("listing_en")),
        ("五点描述", content.get("bullet_points")),
        ("核心卖点", business.get("top_selling_points")),
        ("商品定位", business.get("positioning")),
        ("使用场景", business.get("usage_scenarios")),
        ("目标人群", business.get("target_audience")),
        ("容量", specs.get("capacity")),
        ("尺寸", specs.get("size_info")),
        ("重量", specs.get("gross_weight_g")),
        ("材质", specs.get("body_material")),
        ("表面工艺", specs.get("surface_finish")),
        ("适用热源", specs.get("heat_source")),
    ])
    if not lines:
        return None
    return _doc(
        sku,
        RECOMMENDATION_SECTION,
        f"{sku} 推荐召回画像",
        lines,
        metadata={
            "retrieval_role": "recommendation_candidate_recall",
            "fact_authority": False,
        },
    )


def index_all_products(db: Session) -> dict[str, int]:
    products = db.query(Product).order_by(Product.sku.asc()).all()
    indexed = 0
    documents = 0
    chunks = 0
    for product in products:
        result = index_product(db, product.sku)
        indexed += 1
        documents += result["documents"]
        chunks += result["chunks"]
    return {"products": indexed, "documents": documents, "chunks": chunks}


def index_all_product_recommendations(db: Session) -> dict[str, int]:
    products = db.query(Product).order_by(Product.sku.asc()).all()
    indexed = 0
    for product in products:
        result = index_product_recommendation(db, product.sku)
        indexed += result["documents"]
    return {"products": len(products), "documents": indexed, "chunks": indexed}


def index_product_recommendation(db: Session, sku: str) -> dict[str, int]:
    detail = product_service.get_product_detail(db, sku)
    item = build_product_recommendation_document(detail)
    if not item:
        return {"documents": 0, "chunks": 0}

    doc = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == PRODUCT_SOURCE_TYPE,
        KnowledgeDocument.sku == sku,
        KnowledgeDocument.source_id == item["source_id"],
    ).first()
    if not doc:
        doc = KnowledgeDocument(
            source_type=PRODUCT_SOURCE_TYPE,
            source_id=item["source_id"],
            sku=sku,
            title=item["title"],
            content=item["content"],
            parse_status="done",
            parse_error=None,
            metadata_json=json.dumps(item["metadata"], ensure_ascii=False),
        )
        db.add(doc)
        db.flush()
    else:
        doc.title = item["title"]
        doc.content = item["content"]
        doc.parse_status = "done"
        doc.parse_error = None
        doc.metadata_json = json.dumps(item["metadata"], ensure_ascii=False)
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc.id
        ).delete()

    db.add(KnowledgeChunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        sku=sku,
        source_type=PRODUCT_SOURCE_TYPE,
        chunk_index=0,
        content=item["content"],
        metadata_json=json.dumps(item["metadata"], ensure_ascii=False),
        embedding_status="pending",
    ))
    db.commit()
    return {"documents": 1, "chunks": 1}


def index_product(db: Session, sku: str) -> dict[str, int]:
    detail = product_service.get_product_detail(db, sku)
    docs = build_product_documents(detail)
    wanted_source_ids = {item["source_id"] for item in docs}
    prefix = f"product:{sku}:"

    existing_docs = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.source_type == PRODUCT_SOURCE_TYPE,
        KnowledgeDocument.sku == sku,
        KnowledgeDocument.source_id.like(f"{prefix}%"),
    ).all()
    for existing in existing_docs:
        if existing.source_id not in wanted_source_ids:
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == existing.id).delete()
            db.delete(existing)

    existing_by_source_id = {
        item.source_id: item
        for item in db.query(KnowledgeDocument).filter(
            KnowledgeDocument.source_type == PRODUCT_SOURCE_TYPE,
            KnowledgeDocument.sku == sku,
            KnowledgeDocument.source_id.in_(wanted_source_ids) if wanted_source_ids else text("false"),
        ).all()
    }

    for item in docs:
        doc = existing_by_source_id.get(item["source_id"])
        if not doc:
            doc = KnowledgeDocument(
                source_type=PRODUCT_SOURCE_TYPE,
                source_id=item["source_id"],
                sku=sku,
                title=item["title"],
                content=item["content"],
                parse_status="done",
                parse_error=None,
                metadata_json=json.dumps(item["metadata"], ensure_ascii=False),
            )
            db.add(doc)
            db.flush()
        else:
            doc.title = item["title"]
            doc.content = item["content"]
            doc.parse_status = "done"
            doc.parse_error = None
            doc.metadata_json = json.dumps(item["metadata"], ensure_ascii=False)
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete()

        db.add(KnowledgeChunk(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            sku=sku,
            source_type=PRODUCT_SOURCE_TYPE,
            chunk_index=0,
            content=item["content"],
            metadata_json=json.dumps(item["metadata"], ensure_ascii=False),
            embedding_status="pending",
        ))

    product = db.query(Product).filter(Product.sku == sku).first()
    if product:
        product.sync_flag = True

    db.commit()
    return {"documents": len(docs), "chunks": len(docs)}


async def embed_pending_chunks(
    db: Session,
    *,
    limit: int | None = None,
    model: str | None = None,
    document_id: str | None = None,
    sku: str | None = None,
    sections: list[str] | None = None,
) -> dict[str, int]:
    query = db.query(KnowledgeChunk).filter(KnowledgeChunk.embedding_status != "synced")
    if document_id:
        query = query.filter(KnowledgeChunk.document_id == document_id)
    normalized_sku = str(sku or "").strip().upper()
    if normalized_sku:
        # Product updates replace only this SKU's product documents.  Keep the
        # embedding worker scoped to the same identity so one QA edit cannot
        # consume every pending chunk in the knowledge base.
        query = query.filter(KnowledgeChunk.sku == normalized_sku)
    normalized_sections = [
        str(section or "").strip()
        for section in (sections or [])
        if str(section or "").strip()
    ]
    if normalized_sections:
        query = query.join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        ).filter(
            or_(*[
                KnowledgeDocument.source_id.like(f"%:{section}")
                for section in normalized_sections
            ])
        )
    chunks = query.order_by(KnowledgeChunk.updated_at.asc()).limit(limit).all() if limit else query.all()
    embedded = 0
    failed = 0
    vector_ready = False

    for chunk in chunks:
        try:
            embedding, model_id = await dmxapi_service.create_embedding(db, chunk.content, model=model)
            if not vector_ready:
                ensure_pgvector_storage(db, len(embedding))
                vector_ready = True
            db.execute(
                text(
                    "UPDATE knowledge_chunks "
                    "SET embedding = CAST(:embedding AS vector), embedding_model = :model, "
                    "embedding_status = 'synced', embedding_error = NULL "
                    "WHERE id = :id"
                ),
                {"embedding": _vector_literal(embedding), "model": model_id, "id": chunk.id},
            )
            db.commit()
            embedded += 1
        except Exception as exc:
            db.rollback()
            chunk.embedding_status = "failed"
            chunk.embedding_error = str(exc)[:2000]
            db.commit()
            failed += 1
    return {"total": len(chunks), "embedded": embedded, "failed": failed}


def ensure_pgvector_storage(db: Session, dimensions: int | None = None) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("当前数据库不是 PostgreSQL，无法写入 pgvector")

    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    column = db.execute(text(
        "SELECT data_type, udt_name "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = 'knowledge_chunks' AND column_name = 'embedding'"
    )).first()
    vector_type = f"vector({dimensions})" if dimensions else "vector"
    if not column:
        db.execute(text(f"ALTER TABLE knowledge_chunks ADD COLUMN embedding {vector_type}"))
    elif dimensions:
        db.execute(text(f"ALTER TABLE knowledge_chunks ALTER COLUMN embedding TYPE vector({dimensions}) USING embedding::vector({dimensions})"))
    db.commit()


def create_embedding_index(db: Session) -> bool:
    dimensions = db.execute(text(
        "SELECT vector_dims(embedding) "
        "FROM knowledge_chunks "
        "WHERE embedding IS NOT NULL "
        "LIMIT 1"
    )).scalar()
    if not should_create_ivfflat_index(dimensions):
        db.rollback()
        return False

    db.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding "
        "ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    ))
    db.commit()
    return True


def should_create_ivfflat_index(dimensions: int | None) -> bool:
    return bool(dimensions and dimensions <= 2000)


def run_embed_pending_chunks(
    db: Session,
    *,
    limit: int | None = None,
    model: str | None = None,
    document_id: str | None = None,
    sku: str | None = None,
    sections: list[str] | None = None,
) -> dict[str, int]:
    return asyncio.run(embed_pending_chunks(
        db,
        limit=limit,
        model=model,
        document_id=document_id,
        sku=sku,
        sections=sections,
    ))


def _doc(
    sku: str,
    section: str,
    title: str,
    lines: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_id = f"product:{sku}:{section}"
    return {
        "source_id": source_id,
        "sku": sku,
        "title": title,
        "content": "\n".join(line for line in lines if line).strip(),
        "metadata": {
            "sku": sku,
            "section": section,
            "title": title,
            "source_id": source_id,
            **(metadata or {}),
        },
    }


def _section_lines(title: str, values: dict[str, Any], fields: list[tuple[str, str]]) -> list[str]:
    lines = _compact_lines([(label, values.get(key)) for key, label in fields])
    if not lines:
        return []
    return [f"{title}:"] + [f"- {line}" for line in lines]


def _compact_lines(items: list[tuple[str, Any]]) -> list[str]:
    lines = []
    for label, value in items:
        text_value = _stringify(value)
        if text_value:
            lines.append(f"{label}: {text_value}")
    return lines


def _stringify(value: Any) -> str:
    if value in (None, "", []):
        return ""
    if isinstance(value, list):
        return ", ".join(_stringify(item) for item in value if _stringify(item))
    if isinstance(value, dict):
        visible = []
        for key, item in value.items():
            text_value = _stringify(item)
            if text_value:
                visible.append(f"{key}: {text_value}")
        return ", ".join(visible)
    return str(value).strip()


def _join_nonempty(values: list[Any], separator: str) -> str:
    return separator.join(_stringify(value) for value in values if _stringify(value))


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"
