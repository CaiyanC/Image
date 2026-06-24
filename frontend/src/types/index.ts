export interface UserGroup {
  group_id: string
  group_name: string
  group_role: 'admin' | 'member'
}

export interface User {
  id: string
  username: string
  email: string | null
  user_type: string
  display_name: string | null
  is_active: boolean
  groups: UserGroup[]
  permissions?: string[]
  created_at: string
}

export interface GenerationRecord {
  id: string
  user_id: string
  type: 'txt2img' | 'img2img' | 'txt2vid'
  prompt: string
  negative_prompt?: string
  source_image_path?: string
  result_image_path?: string
  result_images?: string[]
  result_video_path?: string
  model_name: string
  parameters: Record<string, unknown>
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error_message?: string
  created_at: string
}

export interface GenerationStats {
  total: number
  by_type: {
    txt2img: number
    img2img: number
    txt2vid: number
  }
  by_date: Record<string, number>
  success_rate: number
}

export interface GenerationParams {
  width?: number
  height?: number
  steps?: number
  seed?: number
  cfg_scale?: number
  negative_prompt?: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

// ── Product (new field names) ──

export interface Product {
  id: string
  sku: string
  barcode?: string | null
  product_name_cn?: string | null
  product_name_en?: string | null
  brand?: string | null
  series?: string | null
  category?: string | null
  sub_category?: string | null
  product_level?: string | null
  launch_date?: string | null
  lifecycle_status?: string | null
  person_in_charge?: string | null
  quality_note?: string | null
  active_flag?: boolean
  sync_flag?: boolean
  status_note?: string | null
  specs?: ProductSpecs | null
  business?: ProductBusiness | null
  content?: ProductContent | null
  media?: ProductMediaItem[]
  prompts?: ProductPrompts[]
  qa_items?: ProductQa[]
  qa_negative?: ProductQaNegative | null
  channels?: ListingChannel[]
  regions?: SalesRegion[]
  certifications?: Certification[]
  keywords?: ProductKeyword[]
  created_at?: string
  updated_at?: string
}

export interface ProductSpecs {
  id: string
  product_id: string
  size_info?: unknown
  capacity?: unknown
  gross_weight_g?: number | null
  body_material?: string | null
  color?: string | null
  surface_finish?: string | null
  heat_source?: string | null
  power?: string | null
  technical_advantages?: unknown
  usage_instruction?: string | null
  created_at: string
  updated_at: string
}

export interface ProductBusiness {
  id: string
  product_id: string
  top_selling_points?: unknown
  target_audience?: string | null
  positioning?: string | null
  price_positioning?: string | null
  emotional_value?: string | null
  usage_scenarios?: unknown
  competitor_benchmark?: unknown
  created_at: string
  updated_at: string
}

export interface ProductContent {
  id: string
  product_id: string
  title_en?: string | null
  title_cn?: string | null
  long_description_en?: string | null
  long_description_cn?: string | null
  long_description_ja?: string | null
  search_keywords?: unknown
  amazon_title?: string | null
  website_title?: string | null
  bullet_points?: unknown
  a_plus_content?: string | null
  listing_cn?: string | null
  listing_en?: string | null
  listing_ja?: string | null
  created_at: string
  updated_at: string
}

export interface ProductMediaItem {
  id: string
  product_id: string
  sku: string
  media_layer: string
  media_group: string
  media_type?: string | null
  channel_name?: string | null
  page_type?: string | null
  media_version?: string | null
  file_name: string
  file_path: string
  file_url?: string | null
  file_format?: string | null
  media_level: string
  is_real_product: boolean
  is_ai_generated: boolean
  is_competitor: boolean
  is_public: boolean
  ai_customer_usable: boolean
  ai_marketing_usable: boolean
  ai_reference_usable: boolean
  editable_flag: boolean
  review_status: string
  authorization_status: string
  forbidden_usage?: string | null
  language?: string | null
  tag_list?: unknown
  created_at: string
  updated_at: string
}

export interface ProductPrompts {
  id: string
  product_id?: string | null
  sku?: string | null
  prompt_name?: string | null
  prompt_type?: string | null
  prompt_text: string
  version?: string | null
  created_at: string
  updated_at: string
}

export interface ProductQa {
  id: string
  product_id: string
  question: string
  answer: string
  tags?: unknown
  priority?: number | null
  created_at: string
  updated_at: string
}

export interface ProductQaNegative {
  id: string
  product_id: string
  high_freq_negative_words?: string | null
  response_tone?: string | null
  priority?: number | null
  created_at: string
  updated_at: string
}

export interface ListingChannel {
  id: string
  channel_name: string
  channel_code?: string | null
}

export interface SalesRegion {
  id: string
  region_name: string
  region_code?: string | null
}

export interface Certification {
  id: string
  certification_name: string
  certification_code?: string | null
}

export interface ProductKeyword {
  id: string
  keyword: string
  keyword_level?: string | null
}

export interface AssetTags {
  product_tags?: string[]
  material_type_tags?: string[]
  usage_tags?: string[]
  version_tags?: string[]
  risk_tags?: string[]
  channel_tags?: string[]
  language_tags?: string[]
}

export interface ProductAsset {
  id: string
  sku: string
  category_code: string
  category_name: string
  sub_category?: string | null
  asset_type: 'image' | 'video'
  url: string
  thumbnail_url?: string | null
  brand?: string | null
  material_type?: string | null
  angle_scene?: string | null
  channel?: string | null
  language_tag?: string | null
  version_tag?: string | null
  date_tag?: string | null
  status_tag?: string | null
  seq: number
  sort_order: number
  tags?: AssetTags
  notes?: string | null
  created_at: string
  updated_at: string
}

export interface AssetGrouped {
  category_code: string
  category_name: string
  count: number
  items: ProductAsset[]
}

export interface AssetUploadResponse {
  count: number
  items: ProductAsset[]
}

// ── Product list response ──

export interface ProductListItem {
  id: string
  sku: string
  product_name_cn?: string | null
  product_name_en?: string | null
  brand?: string | null
  series?: string | null
  category?: string | null
  product_level?: string | null
  active_flag?: boolean
  created_at?: string
}

export interface ProductListResponse {
  items: ProductListItem[]
  total: number
}

// ── Draft ──

export interface ProductDraft {
  id: string
  product_id?: string | null
  sku?: string | null
  draft_data: Record<string, unknown>
  status: string
  created_by?: string | null
  created_at?: string
  updated_at?: string
  // Flat fields spread from draft_data by backend for convenience
  product_name_cn?: string
  product_name_en?: string
  barcode?: string
  brand?: string
  series?: string
  category?: string
  product_level?: string
  launch_date?: string
  lifecycle_status?: string
  person_in_charge?: string
  specs_data?: Record<string, unknown>
  specs?: Record<string, unknown>
  business_data?: Record<string, unknown>
  business?: Record<string, unknown>
  content_data?: Record<string, unknown>
  content?: Record<string, unknown>
  media_data?: Record<string, unknown>
  media?: Record<string, unknown>
  prompts_data?: Record<string, unknown>
  prompt_data?: Record<string, unknown>
  prompt?: Record<string, unknown>
  qa_items?: ProductQa[]
  qa_negative?: ProductQaNegative | null
}

// ── Deprecated/backward compat type aliases ──

export type Specs = ProductSpecs
export type BusinessInfo = Partial<ProductBusiness>
export type ContentAssets = Partial<ProductContent>
export type MediaAssets = { media?: ProductMediaItem[] }
export type ChannelMedia = Record<string, { main_images?: string[]; detail_images?: string[]; scene_images?: string[] }>
