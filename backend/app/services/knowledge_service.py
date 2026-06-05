import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument
from . import dmxapi_service


def vector_status(db: Session) -> dict:
    try:
        extension = db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
        column = db.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'"
        )).scalar()
        chunks = db.query(KnowledgeChunk).count()
        embedded = db.query(KnowledgeChunk).filter(KnowledgeChunk.embedding_status == "synced").count()
        return {
            "available": bool(extension and column),
            "extension": bool(extension),
            "embedding_column": bool(column),
            "chunks": chunks,
            "embedded_chunks": embedded,
        }
    except Exception as exc:
        chunks = db.query(KnowledgeChunk).count()
        return {
            "available": False,
            "extension": False,
            "embedding_column": False,
            "chunks": chunks,
            "embedded_chunks": 0,
            "error": str(exc),
        }


def create_document(
    db: Session,
    *,
    source_type: str,
    title: str,
    content: str,
    sku: str | None = None,
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        source_type=source_type,
        source_id=source_id,
        sku=sku,
        title=title,
        content=content,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        created_by=created_by,
    )
    db.add(doc)
    db.flush()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        sku=sku,
        source_type=source_type,
        chunk_index=0,
        content=content,
        metadata_json=json.dumps({"title": title, **(metadata or {})}, ensure_ascii=False),
        embedding_status="pending",
    )
    db.add(chunk)
    db.commit()
    db.refresh(doc)
    return doc


def keyword_retrieve(db: Session, query: str, sku: str | None = None, limit: int = 5) -> list[dict]:
    query_text = query.strip()
    if not query_text:
        return []
    tokens = _query_tokens(query_text)
    db_query = db.query(KnowledgeChunk)
    if sku:
        db_query = db_query.filter((KnowledgeChunk.sku == sku) | (KnowledgeChunk.sku.is_(None)))
    if tokens:
        conditions = [KnowledgeChunk.content.ilike(f"%{token}%") for token in tokens[:8]]
        db_query = db_query.filter(text(" OR ".join([f"content LIKE :token_{index}" for index, _ in enumerate(conditions)]))).params(
            **{f"token_{index}": f"%{token}%" for index, token in enumerate(tokens[:8])}
        )
    else:
        db_query = db_query.filter(KnowledgeChunk.content.ilike(f"%{query_text}%"))
    chunks = db_query.order_by(KnowledgeChunk.updated_at.desc()).limit(max(limit * 4, limit)).all()
    ranked = sorted(
        chunks,
        key=lambda item: (_keyword_score(query_text, tokens, item.content), item.updated_at),
        reverse=True,
    )[:limit]
    return [
        {
            "source_type": item.source_type,
            "sku": item.sku,
            "content": item.content,
            "metadata": _safe_json(item.metadata_json),
            "score": _keyword_score(query_text, tokens, item.content),
        }
        for item in ranked
    ]


async def semantic_retrieve(db: Session, query: str, sku: str | None = None, limit: int = 5) -> list[dict]:
    if not query.strip():
        return []
    try:
        status = vector_status(db)
        if not status.get("available"):
            return keyword_retrieve(db, query, sku=sku, limit=limit)
        embedding, _model_id = await dmxapi_service.create_embedding(db, query)
        where = "embedding_status = 'synced' AND embedding IS NOT NULL"
        params = {"embedding": _vector_literal(embedding), "limit": limit}
        if sku:
            where += " AND (sku = :sku OR sku IS NULL)"
            params["sku"] = sku
        rows = db.execute(text(
            "SELECT source_type, sku, content, metadata_json, "
            "embedding <=> CAST(:embedding AS vector) AS distance "
            "FROM knowledge_chunks "
            f"WHERE {where} "
            "ORDER BY embedding <=> CAST(:embedding AS vector) "
            "LIMIT :limit"
        ), params).mappings().all()
        return [
            {
                "source_type": row["source_type"],
                "sku": row["sku"],
                "content": row["content"],
                "metadata": _safe_json(row["metadata_json"]),
                "score": 1 - float(row["distance"] or 0),
            }
            for row in rows
        ]
    except Exception:
        return keyword_retrieve(db, query, sku=sku, limit=limit)


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}


def _query_tokens(query: str) -> list[str]:
    raw = [item.strip() for item in re.split(r"[\s,，。！？?、/；;：:（）()]+", query) if item.strip()]
    tokens = []
    stopwords = {"哪些", "哪个", "哪种", "适合", "推荐", "产品", "商品", "这个", "这些", "一下", "给我", "比较"}
    domain_words = (
        "年轻人", "送礼", "露营", "泡咖啡", "咖啡", "便携", "轻量", "轻便", "多人", "三人",
        "一个人", "情侣", "家庭", "锅具", "炉具", "容量", "材质", "颜值", "场景",
    )
    for word in domain_words:
        if word in query:
            tokens.append(word)
    for item in raw:
        if item in stopwords:
            continue
        if len(item) >= 2:
            tokens.append(item)
    if len(tokens) <= 1:
        for size in (4, 3, 2):
            for index in range(0, max(len(query) - size + 1, 0)):
                token = query[index:index + size].strip()
                if token and token not in stopwords and re.search(r"[\u4e00-\u9fffA-Za-z0-9]", token):
                    tokens.append(token)
    return list(dict.fromkeys(tokens))[:12]


def _keyword_score(query: str, tokens: list[str], content: str) -> float:
    text = content or ""
    if not text:
        return 0
    score = 0.0
    if query and query in text:
        score += 10
    for token in tokens:
        if token in text:
            score += min(len(token), 6)
    return score
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
