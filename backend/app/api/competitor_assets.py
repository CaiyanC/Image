"""Independent internal references, without product SKUs or publication grants."""
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.security import require_any_permission, require_permission
from ..models.user import User
from ..models.competitor_asset import CompetitorAsset
from ..schemas.competitor_asset import CompetitorAssetUpdate
from ..services import competitor_asset_service as service, operation_log_service
from .assets import (_cleanup_saved_paths, _prevalidate_asset_upload, _save_upload_file,
                     MAX_ASSET_IMAGES_PER_REQUEST, MAX_ASSET_VIDEOS_PER_REQUEST)

router = APIRouter(prefix="/api/competitor-assets", tags=["competitor-assets"])

def _serialize(asset) -> dict:
    return {column.name: getattr(asset, column.name) for column in asset.__table__.columns}

@router.get("/brands")
def brands(user: User = Depends(require_any_permission("competitor.view", "media.upload")), db: Session = Depends(get_db)):
    return {"items": service.list_brand_counts(db)}

@router.get("")
def list_assets(brand: str = Query(..., min_length=1, max_length=64), asset_type: str | None = None,
                limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                user: User = Depends(require_any_permission("competitor.view", "media.upload")), db: Session = Depends(get_db)):
    return {"items": [_serialize(item) for item in service.list_assets(db, brand=brand, asset_type=asset_type, limit=limit, offset=offset)]}

@router.patch("/{asset_id}")
def update_metadata(request: Request, asset_id: str, body: CompetitorAssetUpdate,
                    user: User = Depends(require_permission("media.upload")), db: Session = Depends(get_db)):
    current = db.get(CompetitorAsset, asset_id)
    if current is None:
        raise HTTPException(status_code=404, detail="竞品素材不存在")
    fields = ("brand", "maintainer", "source_note", "notes")
    before = {key: getattr(current, key) for key in fields}
    try:
        updated = service.update_metadata(db, asset_id, body.model_dump(exclude_unset=True))
        after = {key: getattr(updated, key) for key in fields}
        if before != after:
            operation_log_service.log_operation(db, operator_id=user.id, action_type="competitor_asset_update",
                action_name="更新竞品参考字段", target_type="competitor_asset", target_id=asset_id, target_name=updated.brand,
                request_data={"before": before}, response_data={"after": after}, request=request)
        else:
            db.commit()
        db.refresh(updated)
    except Exception:
        db.rollback()
        raise
    return _serialize(updated)

@router.post("/upload")
def upload(request: Request, brand: str = Form(..., max_length=64), asset_type: str = Form("image"),
           maintainer: str | None = Form(None, max_length=100), source_note: str | None = Form(None, max_length=2000),
           files: list[UploadFile] = File(...), user: User = Depends(require_permission("media.upload")), db: Session = Depends(get_db)):
    brand = service.normalize_brand(brand)
    if asset_type not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="竞品素材仅支持图片和视频")
    max_files = MAX_ASSET_VIDEOS_PER_REQUEST if asset_type == "video" else MAX_ASSET_IMAGES_PER_REQUEST
    if not 1 <= len(files) <= max_files:
        raise HTTPException(status_code=400, detail=f"每批最多上传 {max_files} 个文件")
    for file in files:
        _prevalidate_asset_upload(file, is_video=asset_type == "video")
    saved_paths, created = [], []
    storage_id = uuid.uuid4().hex
    try:
        for file in files:
            metadata = _save_upload_file(sku=storage_id, upload=file, category_code="06" if asset_type == "video" else "01",
                                         sub_category=None, material_type=None, storage_scope="competitors")
            saved_paths.extend(metadata.pop("_local_paths"))
            created.append(service.create_uploaded_asset(db, brand=brand, uploaded_by=user.id, metadata=metadata,
                                                          maintainer=maintainer, source_note=source_note))
        operation_log_service.log_operation(db, operator_id=user.id, action_type="competitor_asset_upload",
            action_name="上传竞品参考素材", target_type="competitor_brand", target_id=brand, target_name=brand,
            request_data={"brand": brand, "asset_type": asset_type},
            response_data={"count": len(created), "asset_ids": [item.id for item in created]}, request=request, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        _cleanup_saved_paths(saved_paths)
        raise
    for item in created:
        db.refresh(item)
    return {"count": len(created), "items": [_serialize(item) for item in created]}
