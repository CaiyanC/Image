from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProductAssetBase(BaseModel):
    category_code: str
    category_name: str
    sub_category: Optional[str] = None
    asset_type: str = "image"
    url: str
    thumbnail_url: Optional[str] = None
    brand: Optional[str] = None
    material_type: Optional[str] = None
    angle_scene: Optional[str] = None
    channel: Optional[str] = None
    language_tag: Optional[str] = None
    version_tag: Optional[str] = None
    date_tag: Optional[str] = None
    status_tag: Optional[str] = None
    seq: Optional[int] = None
    sort_order: int = 0
    tags: dict[str, list[str]] = Field(default_factory=dict)
    notes: Optional[str] = None


class ProductAssetCreate(ProductAssetBase):
    pass


class ProductAssetUpdate(BaseModel):
    category_code: Optional[str] = None
    category_name: Optional[str] = None
    sub_category: Optional[str] = None
    asset_type: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    brand: Optional[str] = None
    material_type: Optional[str] = None
    angle_scene: Optional[str] = None
    channel: Optional[str] = None
    language_tag: Optional[str] = None
    version_tag: Optional[str] = None
    date_tag: Optional[str] = None
    status_tag: Optional[str] = None
    seq: Optional[int] = None
    sort_order: Optional[int] = None
    tags: Optional[dict[str, list[str]]] = None
    notes: Optional[str] = None


class ProductAssetResponse(ProductAssetBase):
    id: str
    sku: str
    seq: int
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AssetGrouped(BaseModel):
    category_code: str
    category_name: str
    count: int
    items: list[ProductAssetResponse]


class AssetUploadResponse(BaseModel):
    count: int
    items: list[ProductAssetResponse]


class AssetTagsUpdate(BaseModel):
    product_tags: Optional[list[str]] = None
    material_type_tags: Optional[list[str]] = None
    usage_tags: Optional[list[str]] = None
    version_tags: Optional[list[str]] = None
    risk_tags: Optional[list[str]] = None
    channel_tags: Optional[list[str]] = None
    language_tags: Optional[list[str]] = None

    def normalized(self) -> dict[str, list[str]]:
        data: dict[str, Any] = self.model_dump(exclude_unset=True)
        return {
            key: [str(item).strip() for item in value if str(item).strip()]
            for key, value in data.items()
            if isinstance(value, list)
        }
