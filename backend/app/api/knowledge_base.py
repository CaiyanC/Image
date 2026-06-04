from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import require_permission
from ..models.user import User
from ..services import knowledge_service

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])


class KnowledgeDocumentCreate(BaseModel):
    source_type: str = "manual"
    title: str
    content: str
    sku: str | None = None
    source_id: str | None = None
    metadata: dict | None = None


@router.get("/status")
def status(
    current_user: User = Depends(require_permission("ai.call")),
    db: Session = Depends(get_db),
):
    return knowledge_service.vector_status(db)


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
