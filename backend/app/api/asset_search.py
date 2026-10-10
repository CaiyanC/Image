from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import require_any_permission, require_permission
from ..models.user import User
from ..services import asset_service, asset_taxonomy

router = APIRouter(prefix="/api/assets", tags=["asset-search"])


@router.get("/taxonomy")
def get_asset_taxonomy(
    current_user: User = Depends(require_any_permission("media.read", "media.search", "media.upload", "product.full.view")),
):
    del current_user
    return asset_taxonomy.dictionary_payload()


@router.get("/overview")
def get_asset_overview(
    q: str = Query("", max_length=200),
    limit: int = Query(default=500, ge=1, le=500),
    current_user: User = Depends(require_permission("media.read")),
    db: Session = Depends(get_db),
):
    """Return product cards with the first image and asset counts."""
    del current_user
    return asset_service.list_product_asset_overview(db, q=q, limit=limit)


@router.get("/search")
def search_assets(
    sku: str | None = None,
    category: str | None = None,
    channel: str | None = None,
    maintainer: str | None = Query(default=None, max_length=100),
    review_status: str | None = None,
    authorization_status: str | None = None,
    is_public: bool | None = None,
    ai_customer_usable: bool | None = None,
    ai_marketing_usable: bool | None = None,
    ai_reference_usable: bool | None = None,
    quality_status: str | None = None,
    duplicate_status: str | None = None,
    category_tags: list[str] = Query(default=[]),
    quality_check_tags: list[str] = Query(default=[]),
    expression_tags: list[str] = Query(default=[]),
    selling_point_tags: list[str] = Query(default=[]),
    scene_tags: list[str] = Query(default=[]),
    mood_tags: list[str] = Query(default=[]),
    product_tags: list[str] = Query(default=[]),
    material_type_tags: list[str] = Query(default=[]),
    usage_tags: list[str] = Query(default=[]),
    version_tags: list[str] = Query(default=[]),
    risk_tags: list[str] = Query(default=[]),
    channel_tags: list[str] = Query(default=[]),
    language_tags: list[str] = Query(default=[]),
    subject_tags: list[str] = Query(default=[]),
    composition_tags: list[str] = Query(default=[]),
    view_tags: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: User = Depends(require_permission("media.search")),
    db: Session = Depends(get_db),
):
    del current_user
    items = asset_service.search_assets(
        db,
        sku=sku,
        category=category,
        channel=channel,
        maintainer=maintainer,
        review_status=review_status,
        authorization_status=authorization_status,
        is_public=is_public,
        ai_customer_usable=ai_customer_usable,
        ai_marketing_usable=ai_marketing_usable,
        ai_reference_usable=ai_reference_usable,
        quality_status=quality_status,
        duplicate_status=duplicate_status,
        category_tags=category_tags,
        quality_check_tags=quality_check_tags,
        expression_tags=expression_tags,
        selling_point_tags=selling_point_tags,
        scene_tags=scene_tags,
        mood_tags=mood_tags,
        product_tags=product_tags,
        material_type_tags=material_type_tags,
        usage_tags=usage_tags,
        version_tags=version_tags,
        risk_tags=risk_tags,
        channel_tags=channel_tags,
        language_tags=language_tags,
        subject_tags=subject_tags,
        composition_tags=composition_tags,
        view_tags=view_tags,
        limit=limit,
    )
    return {"items": [asset_service.model_to_dict(item) for item in items]}
