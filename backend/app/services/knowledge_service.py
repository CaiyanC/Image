import json
import re
from typing import Any

from sqlalchemy import distinct, func, or_, text
from sqlalchemy.orm import Session

from ..models.knowledge_base import KnowledgeChunk, KnowledgeDocument
from ..models.product import Product
from . import dmxapi_service
from . import customer_cache_service


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


def health_report(db: Session) -> dict:
    status = vector_status(db)
    total_documents = db.query(KnowledgeDocument).count()
    total_chunks = db.query(KnowledgeChunk).count()
    total_products = db.query(Product).count()
    status_counts = {
        str(row[0] or "unknown"): int(row[1] or 0)
        for row in db.query(KnowledgeChunk.embedding_status, func.count(KnowledgeChunk.id))
        .group_by(KnowledgeChunk.embedding_status)
        .all()
    }
    source_type_counts = {
        str(row[0] or "unknown"): int(row[1] or 0)
        for row in db.query(KnowledgeChunk.source_type, func.count(KnowledgeChunk.id))
        .group_by(KnowledgeChunk.source_type)
        .all()
    }
    indexed_product_skus = {
        row[0]
        for row in db.query(distinct(KnowledgeChunk.sku))
        .filter(KnowledgeChunk.source_type == "product", KnowledgeChunk.sku.isnot(None))
        .all()
        if row[0]
    }
    embedded_product_skus = {
        row[0]
        for row in db.query(distinct(KnowledgeChunk.sku))
        .filter(
            KnowledgeChunk.source_type == "product",
            KnowledgeChunk.sku.isnot(None),
            KnowledgeChunk.embedding_status == "synced",
        )
        .all()
        if row[0]
    }
    pending_products = db.query(Product).filter(Product.sync_flag.is_(False)).count()
    failed_chunks = status_counts.get("failed", 0)
    pending_chunks = status_counts.get("pending", 0)
    embedded_chunks = status_counts.get("synced", 0)
    coverage = (len(indexed_product_skus) / total_products) if total_products else 1.0
    embedding_coverage = (embedded_chunks / total_chunks) if total_chunks else 0.0

    recommendations: list[str] = []
    if not status.get("available"):
        recommendations.append("Enable PostgreSQL pgvector and embedding storage for semantic retrieval.")
    if total_products and coverage < 1:
        recommendations.append("Run product knowledge reindex so every product has searchable chunks.")
    if total_chunks and embedding_coverage < 1:
        recommendations.append("Run embedding sync for pending or failed chunks.")
    if failed_chunks:
        recommendations.append("Review failed chunks and retry embedding after fixing provider/config errors.")
    if pending_products:
        recommendations.append("Sync products marked as pending to keep answers fresh.")
    if not total_chunks:
        recommendations.append("Create or import product knowledge before enabling customer-service answers.")

    grade = "healthy"
    if not total_chunks or (total_products and coverage < 0.8):
        grade = "critical"
    elif recommendations:
        grade = "warning"

    return {
        "grade": grade,
        "vector": status,
        "totals": {
            "products": total_products,
            "documents": total_documents,
            "chunks": total_chunks,
            "indexed_product_skus": len(indexed_product_skus),
            "embedded_product_skus": len(embedded_product_skus),
            "pending_products": pending_products,
        },
        "coverage": {
            "product_index_coverage": round(coverage, 4),
            "embedding_coverage": round(embedding_coverage, 4),
        },
        "embedding_status_counts": status_counts,
        "source_type_counts": source_type_counts,
        "samples": {
            "failed_chunks": _sample_chunks(db, "failed"),
            "pending_chunks": _sample_chunks(db, "pending"),
        },
        "recommendations": recommendations,
    }


async def search_preview(db: Session, query: str, sku: str | None = None, limit: int = 8) -> dict:
    query_text = query.strip()
    rows = await semantic_retrieve(db, query_text, sku=sku, limit=limit)
    status = vector_status(db)
    mode = "semantic" if status.get("available") and status.get("embedded_chunks", 0) > 0 else "keyword"
    return {
        "query": query_text,
        "sku": sku,
        "mode": mode,
        "vector": status,
        "count": len(rows),
        "results": rows,
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


def keyword_retrieve(
    db: Session,
    query: str,
    sku: str | None = None,
    limit: int = 5,
    *,
    skus: list[str] | None = None,
    sections: list[str] | None = None,
) -> list[dict]:
    query_text = query.strip()
    if not query_text:
        return []
    tokens = _query_tokens(query_text)
    db_query = db.query(KnowledgeChunk)
    normalized_sections = tuple(dict.fromkeys(
        str(section or "").strip()
        for section in (sections or [])
        if str(section or "").strip()
    ))
    if normalized_sections:
        db_query = db_query.join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeChunk.document_id,
        ).filter(or_(*[
            KnowledgeDocument.source_id.like(f"%:{section}")
            for section in normalized_sections
        ]))
    if sku:
        db_query = db_query.filter(_chunk_matches_sku_sql(sku))
    elif skus:
        normalized_skus = list(dict.fromkeys(
            str(item or "").strip().upper()
            for item in skus
            if str(item or "").strip()
        ))
        if not normalized_skus:
            return []
        db_query = db_query.filter(KnowledgeChunk.sku.in_(normalized_skus))
    if tokens:
        # Natural Chinese questions are tokenless from SQL's point of view. The
        # tokenizer below emits bounded character n-grams, so keep a wider
        # lexical window than the old eight-token slice; otherwise the first
        # few generic fragments can hide the product term that appears later
        # in the question. This is still only a lexical recall signal: the
        # semantic layer and same-SKU binding remain the answer authority.
        conditions = [KnowledgeChunk.content.ilike(f"%{token}%") for token in tokens[:32]]
        db_query = db_query.filter(or_(*conditions))
    else:
        db_query = db_query.filter(KnowledgeChunk.content.ilike(f"%{query_text}%"))
    chunks = db_query.order_by(KnowledgeChunk.updated_at.desc()).limit(max(limit * 8, limit)).all()
    ranked = sorted(
        chunks,
        key=lambda item: (_keyword_score(query_text, tokens, item.content), item.updated_at),
        reverse=True,
    )[:limit]
    document_source_ids = {
        str(document_id): str(source_id or "")
        for document_id, source_id in db.query(
            KnowledgeDocument.id,
            KnowledgeDocument.source_id,
        ).filter(
            KnowledgeDocument.id.in_([item.document_id for item in ranked])
        ).all()
    } if ranked else {}
    return [
        {
            "source_type": item.source_type,
            "sku": item.sku,
            "content": item.content,
            "metadata": _metadata_with_source_id(
                item.metadata_json,
                document_source_ids.get(str(item.document_id)),
            ),
            "score": _keyword_score(query_text, tokens, item.content),
        }
        for item in ranked
    ]


def merge_retrieval_rows(
    primary_rows: list[dict] | None,
    supplemental_rows: list[dict] | None,
    *,
    limit: int,
    prefer_product_sources: bool = False,
) -> list[dict]:
    """Merge semantic and lexical evidence without dropping product chunks.

    A vector index can be only partially populated while product chunks are
    still searchable by keyword.  The old implementation returned the vector
    page as soon as it had any rows, so an unrelated file chunk could hide the
    exact product evidence that was already available.  This helper keeps the
    two retrieval signals separate and only promotes SKU-bound product rows
    when the caller is doing product retrieval; generic knowledge search keeps
    the vector order and receives lexical rows as additional evidence.
    """
    if limit <= 0:
        return []
    combined: list[tuple[int, int, dict]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for origin, rows in enumerate((primary_rows or [], supplemental_rows or [])):
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            source_id = str(metadata.get("source_id") or metadata.get("source_id_hash") or "").strip()
            identity = (
                str(row.get("source_type") or "").strip(),
                str(row.get("sku") or "").strip().upper(),
                source_id,
                str(row.get("content") or "").strip(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            combined.append((origin, index, row))

    if prefer_product_sources:
        # Vector similarity and lexical match scores have different scales;
        # comparing their raw numbers made a keyword score such as 4.0 always
        # outrank a cosine score in [0, 1].  Fuse source ranks instead.  This
        # keeps semantic and lexical retrieval as independent signals and does
        # not encode any product phrase or category preference.
        rank_score_by_sku: dict[str, float] = {}
        for origin, rows in enumerate((primary_rows or [], supplemental_rows or [])):
            best_rank_in_source: dict[str, int] = {}
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                sku = str(row.get("sku") or "").strip().upper()
                if sku and sku not in best_rank_in_source:
                    best_rank_in_source[sku] = index
            for sku, rank in best_rank_in_source.items():
                rank_score_by_sku[sku] = rank_score_by_sku.get(sku, 0.0) + 1.0 / (20.0 + rank)
        combined.sort(
            key=lambda item: (
                0 if str(item[2].get("sku") or "").strip() else 1,
                -rank_score_by_sku.get(str(item[2].get("sku") or "").strip().upper(), 0.0),
                item[0],
                item[1],
            )
        )
    return [row for _origin, _index, row in combined[:limit]]


async def semantic_retrieve(
    db: Session,
    query: str,
    sku: str | None = None,
    limit: int = 5,
    *,
    prefer_product_sources: bool = False,
    skus: list[str] | None = None,
    sections: list[str] | None = None,
) -> list[dict]:
    if not query.strip():
        return []
    query_key = customer_cache_service.normalize_text(query)
    normalized_skus = tuple(dict.fromkeys(
        str(item or "").strip().upper()
        for item in (skus or [])
        if str(item or "").strip()
    ))
    normalized_sections = tuple(dict.fromkeys(
        str(section or "").strip()
        for section in (sections or [])
        if str(section or "").strip()
    ))
    cache_key = customer_cache_service.make_key(
        "semantic_retrieve",
        id(db),
        query_key,
        sku,
        limit,
        prefer_product_sources,
        normalized_skus,
        normalized_sections,
    )
    cached = customer_cache_service.recommendation_candidate_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        status = vector_status(db)
        if not status.get("available"):
            rows = keyword_retrieve(
                db,
                query,
                sku=sku,
                limit=limit,
                skus=list(normalized_skus),
                sections=list(normalized_sections),
            )
            customer_cache_service.recommendation_candidate_cache.set(cache_key, rows)
            return rows
        embedding_key = customer_cache_service.make_key("embedding", id(db), query_key)
        embedding = customer_cache_service.embedding_cache.get(embedding_key)
        if embedding is None:
            embedding, _model_id = await dmxapi_service.create_embedding(db, query)
            customer_cache_service.embedding_cache.set(embedding_key, embedding)
        where = "c.embedding_status = 'synced' AND c.embedding IS NOT NULL"
        params = {"embedding": _vector_literal(embedding), "limit": limit}
        if sku:
            where += (
                " AND (c.sku = :sku "
                "OR c.metadata_json LIKE :sku_json_quoted)"
            )
            params["sku"] = sku
            params["sku_json_quoted"] = f'%"{sku}"%'
        elif normalized_skus:
            placeholders = []
            for index, allowed_sku in enumerate(normalized_skus):
                key = f"allowed_sku_{index}"
                placeholders.append(f":{key}")
                params[key] = allowed_sku
            where += f" AND c.sku IN ({', '.join(placeholders)})"
        if normalized_sections:
            section_placeholders = []
            for index, section in enumerate(normalized_sections):
                key = f"source_id_section_{index}"
                section_placeholders.append(f"d.source_id LIKE :{key}")
                params[key] = f"%:{section}"
            where += f" AND ({' OR '.join(section_placeholders)})"
        rows = db.execute(text(
            "SELECT c.source_type, c.sku, c.content, c.metadata_json, d.source_id AS document_source_id, "
            "c.embedding <=> CAST(:embedding AS vector) AS distance "
            "FROM knowledge_chunks c "
            "JOIN knowledge_documents d ON d.id = c.document_id "
            f"WHERE {where} "
            "ORDER BY c.embedding <=> CAST(:embedding AS vector) "
            "LIMIT :limit"
        ), params).mappings().all()
        if not rows:
            rows = keyword_retrieve(
                db,
                query,
                sku=sku,
                limit=limit,
                skus=list(normalized_skus),
                sections=list(normalized_sections),
            )
            customer_cache_service.recommendation_candidate_cache.set(cache_key, rows)
            return rows
        vector_result = [
            {
                "source_type": row["source_type"],
                "sku": row["sku"],
                "content": row["content"],
                "metadata": _metadata_with_source_id(
                    row["metadata_json"],
                    row["document_source_id"],
                ),
                "score": 1 - float(row["distance"] or 0),
            }
            for row in rows
        ]
        # Keep lexical product chunks in the same retrieval pass.  This is
        # essential during an incremental embedding sync: vector retrieval can
        # be healthy while the newest product records are still pending.
        keyword_rows = keyword_retrieve(
            db,
            query,
            sku=sku,
            limit=max(limit * 3, limit),
            skus=list(normalized_skus),
            sections=list(normalized_sections),
        )
        result = merge_retrieval_rows(
            vector_result,
            keyword_rows,
            limit=limit,
            prefer_product_sources=prefer_product_sources,
        )
        customer_cache_service.recommendation_candidate_cache.set(cache_key, result)
        return result
    except Exception:
        # Knowledge retrieval is an optional evidence layer.  When its
        # underlying table or vector capability is unavailable, the keyword
        # fallback may fail for the same reason; structured product retrieval
        # must still be able to finish safely without knowledge rows.
        try:
            rows = keyword_retrieve(
                db,
                query,
                sku=sku,
                limit=limit,
                skus=list(normalized_skus),
                sections=list(normalized_sections),
            )
        except Exception:
            rows = []
        customer_cache_service.recommendation_candidate_cache.set(cache_key, rows)
        return rows


def _safe_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _metadata_with_source_id(value: str | None, source_id: str | None) -> dict:
    """Preserve document provenance on every retrieved knowledge chunk."""
    metadata = _safe_json(value)
    if source_id and not metadata.get("source_id"):
        metadata["source_id"] = str(source_id)
    return metadata


def same_sku_customer_context(db: Session, sku: str, limit: int = 1) -> list[dict]:
    """Return a small authoritative same-SKU product context for semantic RAG.

    Vector similarity is useful for narrow QA, but broad product questions can
    rank several related QA rows above the product's own Listing or profile.
    This function does not choose an answer: it merely makes one customer-
    facing, same-SKU source available to the semantic evidence selector.
    """
    normalized_sku = str(sku or "").strip().upper()
    if not normalized_sku or limit <= 0:
        return []
    rows = (
        db.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.sku == normalized_sku,
            KnowledgeChunk.source_type == "product",
        )
        .all()
    )
    ranked: list[tuple[int, KnowledgeChunk]] = []
    for row in rows:
        section = str((_safe_json(row.metadata_json).get("section") or "")).strip().lower()
        priority = {"content": 0, "profile": 1}.get(section)
        if priority is not None and str(row.content or "").strip():
            ranked.append((priority, row))
    ranked.sort(key=lambda item: (item[0], str(item[1].id or "")))
    selected_rows = [row for _, row in ranked[:limit]]
    document_source_ids = {
        str(document_id): str(source_id or "")
        for document_id, source_id in db.query(
            KnowledgeDocument.id,
            KnowledgeDocument.source_id,
        ).filter(
            KnowledgeDocument.id.in_([row.document_id for row in selected_rows])
        ).all()
    } if selected_rows else {}
    return [
        {
            "source_type": row.source_type,
            "sku": normalized_sku,
            "content": str(row.content or ""),
            "metadata": _metadata_with_source_id(
                row.metadata_json,
                document_source_ids.get(str(row.document_id)),
            ),
            "score": None,
        }
        for row in selected_rows
    ]


def _chunk_matches_sku_sql(sku: str):
    like_quoted = f'%"{sku}"%'
    return or_(
        KnowledgeChunk.sku == sku,
        KnowledgeChunk.metadata_json.ilike(like_quoted),
    )


def _query_tokens(query: str) -> list[str]:
    raw = [item.strip() for item in re.split(r"[\s,，。！？?、/；;：:（）()]+", query) if item.strip()]
    tokens = []
    stopwords = {"哪些", "哪个", "哪种", "适合", "推荐", "产品", "商品", "这个", "这些", "一下", "给我", "比较"}
    domain_words = (
        "年轻人", "送礼", "露营", "泡咖啡", "咖啡", "便携", "轻量", "轻便", "多人", "三人",
        "一个人", "情侣", "家庭", "锅具", "炉具", "容量", "材质", "颜值", "场景",
    )
    def add_token(value: str) -> None:
        token = str(value or "").strip()
        if not token or token in stopwords or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", token):
            return
        if token not in tokens:
            tokens.append(token)

    for word in domain_words:
        if word in query:
            add_token(word)
    for item in raw:
        if item in stopwords:
            continue
        if len(item) >= 2:
            # Keep short Chinese terms and explicit non-Chinese terms intact.
            # A long Chinese item is usually an entire natural-language clause;
            # its character n-grams below are much more useful for recall.
            if not re.fullmatch(r"[\u4e00-\u9fff]+", item) or len(item) <= 6:
                add_token(item)

    # Do not require the whole query to collapse to one token before falling
    # back to n-grams. Chinese has no whitespace boundary, so a multi-clause
    # question such as “想找能把一套餐具收在一起的收纳包” must expose generic
    # terms like “餐具” and “收纳包” even when other clauses are present.
    # Generate per contiguous Han run so punctuation/Latin SKU boundaries do
    # not create artificial tokens. Three-character grams carry most meaning;
    # two-character grams cover compact catalogue terms such as 水杯/收纳.
    han_runs = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", query)
    for size in (3, 2):
        for run in han_runs:
            for index in range(0, max(len(run) - size + 1, 0)):
                add_token(run[index:index + size])

    # Bound SQL predicate growth while retaining all short terms and a useful
    # spread of n-grams from natural questions. This is language-agnostic
    # tokenization, not a product/category vocabulary or a routing rule.
    return tokens[:32]


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


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _sample_chunks(db: Session, status: str, limit: int = 5) -> list[dict]:
    rows = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.embedding_status == status)
        .order_by(KnowledgeChunk.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "sku": row.sku,
            "source_type": row.source_type,
            "chunk_index": row.chunk_index,
            "error": row.embedding_error,
            "updated_at": str(row.updated_at) if row.updated_at else None,
            "preview": (row.content or "")[:180],
        }
        for row in rows
    ]
