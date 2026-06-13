from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import require_any_permission, require_permission
from ..models.user import User
from ..services import knowledge_job_service, knowledge_service, product_service, product_vector_index_service

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])


class KnowledgeDocumentCreate(BaseModel):
    source_type: str = "manual"
    title: str
    content: str
    sku: str | None = None
    source_id: str | None = None
    metadata: dict | None = None


class KnowledgeSearchPreviewRequest(BaseModel):
    query: str
    sku: str | None = None
    limit: int = 8


class ProductReindexRequest(BaseModel):
    mode: str = "pending"
    limit: int | None = None
    embed: bool = True


class EmbeddingRetryRequest(BaseModel):
    limit: int | None = 20


@router.get("/status")
def status(
    current_user: User = Depends(require_any_permission("ai.customer_service", "ai.call")),
    db: Session = Depends(get_db),
):
    return knowledge_service.vector_status(db)


@router.get("/health")
def health(
    current_user: User = Depends(require_any_permission("ai.customer_service", "ai.call")),
    db: Session = Depends(get_db),
):
    return knowledge_service.health_report(db)


@router.post("/search-preview")
async def search_preview(
    body: KnowledgeSearchPreviewRequest,
    current_user: User = Depends(require_any_permission("ai.customer_service", "ai.call")),
    db: Session = Depends(get_db),
):
    limit = min(max(body.limit, 1), 20)
    return await knowledge_service.search_preview(db, body.query, sku=body.sku, limit=limit)


@router.post("/reindex-products")
async def reindex_products(
    body: ProductReindexRequest,
    current_user: User = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    mode = (body.mode or "pending").strip().lower()
    if mode == "full":
        indexed = product_vector_index_service.index_all_products(db)
        embed_limit = body.limit
    else:
        limit = min(max(body.limit or 100, 1), 1000)
        indexed = product_service.sync_pending_products_to_vector_db(db, limit=limit)
        embed_limit = limit
    embedded = None
    if body.embed:
        embedded = await product_vector_index_service.embed_pending_chunks(db, limit=embed_limit)
    return {
        "mode": mode,
        "indexed": indexed,
        "embedding": embedded,
        "health": knowledge_service.health_report(db),
    }


@router.post("/jobs/reindex-products")
def create_reindex_job(
    body: ProductReindexRequest,
    current_user: User = Depends(require_permission("ai.call")),
):
    return knowledge_job_service.create_reindex_job(
        created_by=current_user.id,
        mode=body.mode,
        limit=body.limit,
        embed=body.embed,
    )


@router.post("/jobs/retry-embeddings")
def create_embedding_retry_job(
    body: EmbeddingRetryRequest,
    current_user: User = Depends(require_permission("ai.call")),
):
    limit = min(max(body.limit or 20, 1), 500)
    return knowledge_job_service.create_embedding_retry_job(created_by=current_user.id, limit=limit)


@router.get("/jobs")
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission("ai.call")),
):
    return knowledge_job_service.list_jobs(limit=limit)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    current_user: User = Depends(require_permission("ai.call")),
):
    job = knowledge_job_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/documents")
def create_document(
    body: KnowledgeDocumentCreate,
    current_user: User = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    doc = knowledge_service.create_document(
        db,
        source_type=body.source_type,
        title=body.title,
        content=body.content,
        sku=body.sku,
        source_id=body.source_id,
        metadata=body.metadata,
        created_by=current_user.id,
    )
    return {
        "id": doc.id,
        "source_type": doc.source_type,
        "sku": doc.sku,
        "title": doc.title,
        "created_at": str(doc.created_at),
    }
