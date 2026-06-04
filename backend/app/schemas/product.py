from datetime import datetime, date
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from .common import UuidStr


# ── Product 主表 ──

class ProductBase(BaseModel):
    sku: str
    barcode: Optional[str] = None
    product_name_cn: Optional[str] = None
    product_name_en: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    product_level: Optional[str] = None
    launch_date: Optional[str] = None
    lifecycle_status: Optional[str] = None
    person_in_charge: Optional[str] = None
    active_flag: bool = True
    sync_flag: bool = False
    quality_note: Optional[str] = None
    status_note: Optional[str] = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    barcode: Optional[str] = None
    product_name_cn: Optional[str] = None
    product_name_en: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    product_level: Optional[str] = None
    launch_date: Optional[str] = None
    lifecycle_status: Optional[str] = None
    person_in_charge: Optional[str] = None
    active_flag: Optional[bool] = None
    sync_flag: Optional[bool] = None
    quality_note: Optional[str] = None
    status_note: Optional[str] = None


class ProductResponse(ProductBase):
    id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    id: UuidStr
    sku: str
    product_name_cn: Optional[str] = None
    product_name_en: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    product_level: Optional[str] = None
    active_flag: Optional[bool] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProductAdvancedSearchRequest(BaseModel):
    keyword: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    product_level: Optional[str] = None
    lifecycle_status: Optional[str] = None
    person_in_charge: Optional[str] = None
    quality_note: Optional[str] = None
    active_flag: Optional[bool] = None
    launch_date_from: Optional[str] = None
    launch_date_to: Optional[str] = None
    capacity: Optional[str] = None
    gross_weight_min: Optional[float] = None
    gross_weight_max: Optional[float] = None
    body_material: Optional[str] = None
    color: Optional[str] = None
    surface_finish: Optional[str] = None
    heat_source: Optional[str] = None
    power: Optional[str] = None
    top_selling_points: Optional[str] = None
    target_audience: Optional[str] = None
    positioning: Optional[str] = None
    price_positioning: Optional[str] = None
    usage_scenarios: Optional[str] = None
    channel: Optional[str] = None
    region: Optional[str] = None
    certification: Optional[str] = None
    search_keyword: Optional[str] = None
    sort_by: str = "updated_at"
    sort_order: str = "desc"
    skip: int = 0
    limit: int = 20


# ── ProductSpecs ──

class ProductSpecsBase(BaseModel):
    size_info: Optional[Any] = None
    capacity: Optional[Any] = None
    gross_weight_g: Optional[float] = None
    body_material: Optional[str] = None
    color: Optional[str] = None
    surface_finish: Optional[str] = None
    heat_source: Optional[str] = None
    power: Optional[str] = None
    technical_advantages: Optional[Any] = None
    usage_instruction: Optional[str] = None


class ProductSpecsResponse(ProductSpecsBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductBusiness ──

class ProductBusinessBase(BaseModel):
    top_selling_points: Optional[Any] = None
    target_audience: Optional[str] = None
    positioning: Optional[str] = None
    price_positioning: Optional[str] = None
    emotional_value: Optional[str] = None
    usage_scenarios: Optional[Any] = None
    competitor_benchmark: Optional[Any] = None


class ProductBusinessResponse(ProductBusinessBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductContent ──

class ProductContentBase(BaseModel):
    title_en: Optional[str] = None
    title_cn: Optional[str] = None
    long_description_en: Optional[str] = None
    long_description_cn: Optional[str] = None
    long_description_ja: Optional[str] = None
    search_keywords: Optional[Any] = None
    amazon_title: Optional[str] = None
    website_title: Optional[str] = None
    bullet_points: Optional[Any] = None
    a_plus_content: Optional[str] = None
    listing_cn: Optional[str] = None
    listing_en: Optional[str] = None
    listing_ja: Optional[str] = None


class ProductContentResponse(ProductContentBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductMedia ──

class ProductMediaBase(BaseModel):
    sku: str
    media_layer: str = "raw"
    media_group: str
    media_type: Optional[str] = None
    channel_name: Optional[str] = None
    page_type: Optional[str] = None
    media_version: Optional[str] = None
    file_name: str
    file_path: str
    file_url: Optional[str] = None
    file_format: Optional[str] = None
    media_level: str = "C"
    is_real_product: bool = True
    is_ai_generated: bool = False
    is_competitor: bool = False
    is_public: bool = False
    ai_customer_usable: bool = False
    ai_marketing_usable: bool = False
    ai_reference_usable: bool = False
    editable_flag: bool = False
    review_status: str = "pending"
    authorization_status: str = "unknown"
    forbidden_usage: Optional[str] = None
    language: Optional[str] = None
    tag_list: Optional[Any] = None


class ProductMediaResponse(ProductMediaBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductPrompts ──

class ProductPromptsBase(BaseModel):
    prompt_name: Optional[str] = None
    prompt_type: Optional[str] = None
    prompt_text: str
    version: Optional[str] = None


class ProductPromptsCreate(ProductPromptsBase):
    pass


class ProductPromptsResponse(ProductPromptsBase):
    id: str
    product_id: Optional[str] = None
    sku: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductQa ──

class ProductQaBase(BaseModel):
    question: str
    answer: str
    tags: Optional[Any] = None
    priority: Optional[int] = None


class ProductQaCreate(ProductQaBase):
    pass


class ProductQaResponse(ProductQaBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── ProductQaNegative ──

class ProductQaNegativeBase(BaseModel):
    high_freq_negative_words: Optional[str] = None
    response_tone: Optional[str] = None
    priority: Optional[int] = None


class ProductQaNegativeCreate(ProductQaNegativeBase):
    pass


class ProductQaNegativeResponse(ProductQaNegativeBase):
    id: str
    product_id: UuidStr
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── M2M associations ──

class ListingChannelResponse(BaseModel):
    id: str
    channel_name: str
    channel_code: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class SalesRegionResponse(BaseModel):
    id: str
    region_name: str
    region_code: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class CertificationResponse(BaseModel):
    id: str
    certification_name: str
    certification_code: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class KeywordResponse(BaseModel):
    id: str
    keyword: str
    keyword_level: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Product Detail (aggregated response) ──

class ProductDetailResponse(BaseModel):
    id: str
    sku: str
    barcode: Optional[str] = None
    product_name_cn: Optional[str] = None
    product_name_en: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    product_level: Optional[str] = None
    launch_date: Optional[str] = None
    lifecycle_status: Optional[str] = None
    person_in_charge: Optional[str] = None
    active_flag: bool = True
    sync_flag: bool = False
    quality_note: Optional[str] = None
    status_note: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    specs: Optional[ProductSpecsResponse] = None
    business: Optional[ProductBusinessResponse] = None
    content: Optional[ProductContentResponse] = None
    media: List[ProductMediaResponse] = []
    prompts: List[ProductPromptsResponse] = []
    qa_items: List[ProductQaResponse] = []
    qa_negative: Optional[ProductQaNegativeResponse] = None
    channels: List[ListingChannelResponse] = []
    regions: List[SalesRegionResponse] = []
    certifications: List[CertificationResponse] = []
    keywords: List[KeywordResponse] = []

    model_config = {"from_attributes": True}


# ── Draft schemas ──

class ProductDraftCreate(BaseModel):
    product_id: Optional[str] = None
    sku: Optional[str] = None
    draft_data: dict = {}
    status: str = "draft"


class ProductDraftUpdate(BaseModel):
    product_id: Optional[str] = None
    sku: Optional[str] = None
    draft_data: Optional[dict] = None
    status: Optional[str] = None


class ProductDraftResponse(BaseModel):
    id: str
    product_id: Optional[str] = None
    sku: Optional[str] = None
    draft_data: Any = {}
    status: str = "draft"
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProductDraftListResponse(BaseModel):
    items: List[ProductDraftResponse]
    total: int


class ProductDraftPublish(BaseModel):
    draft_id: str


class CheckSkusRequest(BaseModel):
    skus: list[str]


class BatchCreateItem(BaseModel):
    sku: Optional[str] = None
    product_name_cn: Optional[str] = None
    product_name_en: Optional[str] = None
    barcode: Optional[str] = None
    brand: Optional[str] = None
    series: Optional[str] = None
    category: Optional[str] = None
    product_level: Optional[str] = None
    launch_date: Optional[str] = None
    lifecycle_status: Optional[str] = None
    person_in_charge: Optional[str] = None
    specs_data: Optional[dict] = None
    business_data: Optional[dict] = None
    content_data: Optional[dict] = None


class BatchCreateRequest(BaseModel):
    items: list[BatchCreateItem]


class UpdateContentRequest(BaseModel):
    qa_items: Optional[list[dict]] = None
    review_tags: Optional[list[dict]] = None


class L5MergeRequest(BaseModel):
    qa_items: Optional[list[dict]] = None
    negative_review_coping: Optional[list[dict]] = None


class QaImportItem(BaseModel):
    no: Optional[int] = None
    question: str
    answer: str
    tags: Optional[Any] = None
    priority: Optional[int] = None


class QaReviewImportItem(BaseModel):
    no: Optional[int] = None
    keyword: str
    response: str


class QaBatchImportItem(BaseModel):
    sku: str
    file_name: Optional[str] = None
    qa_items: list[QaImportItem] = Field(default_factory=list)
    review_items: list[QaReviewImportItem] = Field(default_factory=list)
    mode: str = "replace"


class QaBatchImportRequest(BaseModel):
    items: list[QaBatchImportItem] = Field(default_factory=list)
    mode: str = "replace"


class ShareContentRequest(BaseModel):
    source_sku: str
