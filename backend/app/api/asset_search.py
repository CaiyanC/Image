from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import require_product_permission
from ..models.user import User
from ..services import asset_service, asset_taxonomy

router = APIRouter(prefix="/api/assets", tags=["asset-search"])


@router.get("/taxonomy")
def get_asset_taxonomy(
    current_user: User = Depends(require_product_permission("read")),
):
    del current_user
    return asset_taxonomy.dictionary_payload()


@router.get("/search")
def search_assets(
    sku: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    review_status: str | None = None,
    authorization_status: str | None = None,
    quality_status: str | None = None,
    duplicate_status: str | None = None,
    expression_tags: list[str] = Query(default=[]),
    selling_point_tags: list[str] = Query(default=[]),
    scene_tags: list[str] = Query(default=[]),
    mood_tags: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(require_product_permission("read")),
    db: Session = Depends(get_db),
):
    del current_user
    items = asset_service.search_assets(
        db,
        sku=sku,
        category=category,
        channel=channel,
        review_status=review_status,
        authorization_status=authorization_status,
        quality_status=quality_status,
        duplicate_status=duplicate_status,
        expression_tags=expression_tags,
        selling_point_tags=selling_point_tags,
        scene_tags=scene_tags,
        mood_tags=mood_tags,
        limit=limit,
    )
    return {"items": [asset_service.model_to_dict(item) for item in items]}
