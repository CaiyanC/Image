"""Internal competitor references, grouped by brand and media kind."""
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.competitor_asset import CompetitorAsset


def normalize_brand(value: str) -> str:
    brand = value.strip()
    if not brand or len(brand) > 64:
        raise HTTPException(status_code=422, detail="竞品品牌不能为空，且不能超过 64 个字符")
    return brand


def create_uploaded_asset(db: Session, *, brand: str, uploaded_by: str, metadata: dict,
                          maintainer: str | None = None, source_note: str | None = None) -> CompetitorAsset:
    """Accept only trusted metadata produced by file upload validation."""
    brand = normalize_brand(brand)
    if metadata.get("asset_type") not in {"image", "video"}:
        raise HTTPException(status_code=422, detail="竞品素材仅支持图片和视频")
    if not uploaded_by or len(uploaded_by) > 36:
        raise HTTPException(status_code=422, detail="缺少有效上传操作人")
    maintainer = (maintainer or "").strip() or None
    if maintainer and len(maintainer) > 100:
        raise HTTPException(status_code=422, detail="维护人不能超过 100 个字符")
    allowed = {"asset_type", "url", "thumbnail_url", "original_file_name", "file_size_bytes", "mime_type"}
    asset = CompetitorAsset(id=str(uuid.uuid4()), brand=brand, uploaded_by=uploaded_by,
                            maintainer=maintainer, source_note=source_note,
                            **{key: value for key, value in metadata.items() if key in allowed})
    db.add(asset)
    db.flush()
    return asset


def list_brand_counts(db: Session) -> list[dict]:
    rows = db.query(CompetitorAsset.brand, CompetitorAsset.asset_type, func.count(CompetitorAsset.id)).group_by(
        CompetitorAsset.brand, CompetitorAsset.asset_type,
    ).order_by(CompetitorAsset.brand).all()
    brands = {}
    for brand, kind, count in rows:
        item = brands.setdefault(brand, {"brand": brand, "image_count": 0, "video_count": 0})
        item[f"{kind}_count"] = count
    return list(brands.values())


def list_assets(db: Session, *, brand: str, asset_type: str | None = None,
                limit: int = 100, offset: int = 0) -> list[CompetitorAsset]:
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(status_code=422, detail="分页参数超出范围")
    query = db.query(CompetitorAsset).filter(CompetitorAsset.brand == normalize_brand(brand))
    if asset_type is not None:
        if asset_type not in {"image", "video"}:
            raise HTTPException(status_code=422, detail="未知竞品素材类型")
        query = query.filter(CompetitorAsset.asset_type == asset_type)
    return query.order_by(CompetitorAsset.created_at.desc(), CompetitorAsset.id).offset(offset).limit(limit).all()


def update_metadata(db: Session, asset_id: str, changes: dict) -> CompetitorAsset:
    asset = db.get(CompetitorAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="竞品素材不存在")
    allowed = {"brand", "maintainer", "source_note", "notes"}
    if changes.keys() - allowed:
        raise HTTPException(status_code=422, detail="仅能修改竞品品牌、维护人、来源和备注")
    normalized = dict(changes)
    if "brand" in normalized:
        if not isinstance(normalized["brand"], str):
            raise HTTPException(status_code=422, detail="竞品品牌不能为空")
        normalized["brand"] = normalize_brand(normalized["brand"])
    for key, maximum in (("maintainer", 100), ("source_note", 2000), ("notes", 2000)):
        if key in normalized:
            value = normalized[key]
            if value is not None and (not isinstance(value, str) or len(value) > maximum):
                raise HTTPException(status_code=422, detail="字段内容过长或格式错误")
            normalized[key] = value.strip() or None if value is not None else None
    for key, value in normalized.items():
        setattr(asset, key, value)
    db.flush()
    return asset
