import json
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
    if not query.strip():
        return []
    db_query = db.query(KnowledgeChunk).filter(KnowledgeChunk.content.ilike(f"%{query.strip()}%"))
    if sku:
        db_query = db_query.filter((KnowledgeChunk.sku == sku) | (KnowledgeChunk.sku.is_(None)))
    chunks = db_query.order_by(KnowledgeChunk.updated_at.desc()).limit(limit).all()
    return [
        {
            "source_type": item.source_type,
            "sku": item.sku,
            "content": item.content,
            "metadata": _safe_json(item.metadata_json),
        }
        for item in chunks
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
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
