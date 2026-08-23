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
    source_key: Optional[str] = None
    angle_scene: Optional[str] = None
    channel: Optional[str] = None
    language_tag: Optional[str] = None
    version_tag: Optional[str] = None
    product_version: Optional[str] = None
    market_version: Optional[str] = None
    date_tag: Optional[str] = None
    status_tag: Optional[str] = None
    file_name: Optional[str] = None
    original_file_name: Optional[str] = None
    file_format: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None
    asset_level: str = "C"
    is_real_product: bool = True
    is_ai_generated: bool = False
    is_competitor: bool = False
    is_latest_version: bool = True
    is_public: bool = False
    ai_customer_usable: bool = False
    ai_marketing_usable: bool = False
    ai_reference_usable: bool = False
    editable_flag: bool = False
    review_status: str = "pending"
    authorization_status: str = "unknown"
    forbidden_usage: Optional[str] = None
    maintainer: Optional[str] = None
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
    source_key: Optional[str] = None
    angle_scene: Optional[str] = None
    channel: Optional[str] = None
    language_tag: Optional[str] = None
    version_tag: Optional[str] = None
    product_version: Optional[str] = None
    market_version: Optional[str] = None
    date_tag: Optional[str] = None
    status_tag: Optional[str] = None
    file_name: Optional[str] = None
    original_file_name: Optional[str] = None
    file_format: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    resolution: Optional[str] = None
    aspect_ratio: Optional[str] = None
    asset_level: Optional[str] = None
    is_real_product: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    is_competitor: Optional[bool] = None
    is_latest_version: Optional[bool] = None
    is_public: Optional[bool] = None
    ai_customer_usable: Optional[bool] = None
    ai_marketing_usable: Optional[bool] = None
    ai_reference_usable: Optional[bool] = None
    editable_flag: Optional[bool] = None
    review_status: Optional[str] = None
    authorization_status: Optional[str] = None
    forbidden_usage: Optional[str] = None
    maintainer: Optional[str] = None
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
    expression_tags: Optional[list[str]] = None
    selling_point_tags: Optional[list[str]] = None
    scene_tags: Optional[list[str]] = None
    mood_tags: Optional[list[str]] = None
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
