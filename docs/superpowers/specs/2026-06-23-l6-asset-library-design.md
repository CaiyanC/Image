# L6 Visual Asset Library Design

Date: 2026-06-23

## Goal

Integrate the L6 visual asset library as an independent workspace page in the CaiYan system. The feature manages product visual assets by SKU, using one consistent data contract across database, backend API, and frontend types.

## Entry Point

Add a top-level navigation item named `素材库`.

- Route: `/assets`
- Permission model:
  - View page and list assets: `product.read`
  - Create, update, delete assets and tags: `product.update`
  - Upload files: `media.upload`
- The page starts with SKU search/selection. After a SKU is selected, all asset operations are scoped to that SKU.

## Architecture

The feature is a separate asset domain, not a thin wrapper around existing product media.

- Database: new `product_assets` table.
- Backend: new model, schemas, service, router, and migration.
- Frontend: new `AssetLibrary` page, frontend asset types, API client methods, route, and navigation item.
- Storage: uploaded asset files are stored under the configured development/production `UPLOAD_DIR`, so dev and prod isolation follows the existing environment rules.

## Database Contract

Create `product_assets` with these fields and keep names aligned with backend schemas and frontend types:

- `id`: `String(36)`, primary key UUID.
- `sku`: `String(64)`, required, indexed, references product SKU logically.
- `category_code`: `String(2)`, required.
- `category_name`: `String(64)`, required.
- `sub_category`: `String(64)`, nullable.
- `asset_type`: `String(10)`, required, default `image`; allowed values `image`, `video`.
- `url`: `Text`, required.
- `thumbnail_url`: `Text`, nullable.
- `brand`: `String(64)`, required, default `alocs`.
- `material_type`: `String(64)`, nullable.
- `angle_scene`: `String(128)`, nullable.
- `channel`: `String(64)`, nullable.
- `language_tag`: `String(32)`, nullable.
- `version_tag`: `String(32)`, nullable.
- `date_tag`: `String(16)`, nullable, `YYYYMMDD`.
- `status_tag`: `String(32)`, nullable, Chinese status value.
- `seq`: `Integer`, required, default `0`.
- `sort_order`: `Integer`, required, default `0`.
- `tags`: JSON text, required, default `{}`.
- `notes`: `Text`, nullable.
- `created_at`: `DateTime`.
- `updated_at`: `DateTime`.

Indexes:

- `sku`
- `sku, category_code`
- `sku, category_code, sub_category, material_type`

The third index supports the `seq` grouping rule.

## Categories And Material Types

The frontend owns the display configuration, and the backend validates the values it receives.

Primary categories:

- `01` 产品标准图
- `02` 产品信息图
- `03` 使用说明图
- `04` 场景内容图
- `05` 渠道销售图
- `06` 视频素材
- `07` AI 生成图
- `08` 参考归档禁用图

The frontend exposes the 47 documented subcategories and the documented subcategory-to-`material_type` mapping. Special upload slots override the generic material type:

- 多角度图: `front`, `side`, `back`, `detail`
- Amazon: `mainImage`, `aPlus`
- 天猫 and 京东: `mainImage`, `detailPage`
- AI 提示词模板: `aiPrompt`
- 视频素材: `video`

## Backend API

Add a router under `/api/products/{sku}/assets`.

- `GET /api/products/{sku}/assets`
  - Query params: `category`, `sub_category`, `asset_type`, `grouped`.
  - Returns either a flat list or grouped list.
- `GET /api/products/{sku}/assets/{asset_id}`
- `POST /api/products/{sku}/assets`
  - JSON create for metadata-only records if needed.
- `POST /api/products/{sku}/assets/upload`
  - Multipart params: `files`, `category_code`, `category_name`, `sub_category`, `material_type`, optional metadata fields.
  - Returns `{ count, items }`.
- `POST /api/products/{sku}/assets/batch`
  - JSON batch create.
- `PUT /api/products/{sku}/assets/{asset_id}`
  - Updates editable metadata and applies status movement rules.
- `PATCH /api/products/{sku}/assets/{asset_id}/tags`
  - Replaces only `tags`; does not trigger naming, category, or status movement logic.
- `DELETE /api/products/{sku}/assets/{asset_id}`

All endpoints require an existing product SKU. Read endpoints require `product.read`; mutating endpoints require `product.update`; upload additionally requires `media.upload`.

## Upload Rules

Upload defaults:

- `brand`: `alocs`
- `material_type`: mapped from subcategory or upload slot.
- `channel`: `General`
- `language_tag`: `CN`
- `version_tag`: `V1`
- `date_tag`: current date in `YYYYMMDD`.
- `status_tag`: `待审核`
- `notes`: original filename without extension.

`seq` grouping key:

```text
sku + category_code + sub_category + material_type
```

The next `seq` is the current max for the group plus one. Deleted assets do not recycle numbers.

File validation:

- Categories other than `06` accept images only in normal upload flows.
- Category `06` accepts only MP4, WebM, and MOV.
- Video uploads force `sub_category = 视频`, `material_type = video`, `asset_type = video`.

Thumbnail generation:

- Images get a 400px-wide JPEG thumbnail at upload time.
- The thumbnail path is stored in `thumbnail_url`.
- Videos do not get thumbnails in the first implementation.

## Naming Preview

The frontend displays the documented naming preview:

```text
brand_SKU_materialType[_angleScene]_channel_language_version_date_status_seq.ext
```

The status part uses:

- `待审核` -> `pending`
- `审核中` -> `reviewing`
- `已通过` -> `approved`
- `需修改` -> `needsrevision`
- `禁用` -> `banned`
- `归档历史版本` -> `archived`

The actual stored file path may remain UUID-based for collision safety. The preview is the business naming identity shown to users.

## Status Movement

When updating an asset:

- If `status_tag` becomes `禁用`, set:
  - `category_code = 08`
  - `category_name = 参考归档禁用图`
  - `sub_category = 禁用素材`
  - `material_type = banned`
- If `status_tag` becomes `归档历史版本`, set:
  - `category_code = 08`
  - `category_name = 参考归档禁用图`
  - `sub_category = 历史版本`
  - `material_type = historical`

The dedicated tags endpoint must not apply this movement.

## Frontend Page

The `/assets` page contains:

- Header with SKU search/select.
- Empty state when no SKU is selected.
- Primary category tabs with counts.
- Secondary category filters with `全部`.
- Conditional upload section:
  - Generic dropzone.
  - 多角度图 4-slot upload.
  - Amazon 2-slot upload.
  - 天猫/京东 2-slot upload.
  - AI 提示词模板 image plus prompt text.
  - 视频素材 video-only upload.
- Asset grid:
  - Thumbnail preview with lazy loading.
  - Video card placeholder.
  - Material type color badge.
  - Naming preview.
  - Tags display and per-asset tag panel.
  - Edit and delete controls.
  - Multi-select checkbox.
- Batch toolbar:
  - Select all current filtered assets.
  - Batch tag panel with two-stage save.
  - Batch clear tags with confirmation.
- Lightbox for image/video preview with keyboard navigation.
- Edit modal for metadata and naming preview.

Use existing UI language and layout density, but keep this as a work-focused operational tool.

## Frontend Types

Add frontend types matching the database and API response field names exactly:

- `ProductAsset`
- `AssetTags`
- `AssetGrouped`
- `AssetUploadResponse`

The frontend should not use alternate field names for the same concept. If a field is nullable in the database, the frontend type should allow `null` or absence consistently with API serialization.

## Tests And Verification

Backend tests:

- Create and list assets by SKU.
- Upload applies defaults.
- `seq` increments by `sku + category_code + sub_category + material_type`.
- Video category rejects images and accepts allowed video formats.
- Non-video categories reject videos.
- Tags PATCH only updates tags.
- Status update moves assets to category `08`.

Frontend verification:

- Helper tests for naming preview, category mapping, status mapping, and asset sorting if the current test setup supports it.
- TypeScript build.
- Production build.
- Manual browser smoke on dev frontend/backend:
  - Open `/assets`.
  - Select SKU.
  - Upload image.
  - Edit metadata.
  - Add tag.
  - Open lightbox.

## Rollout Notes

Development must happen on `dev`. Do not merge to `master` or restart production unless the user explicitly asks to publish.

The implementation should include an Alembic migration for `product_assets`; relying only on runtime table creation is not enough for database consistency.
