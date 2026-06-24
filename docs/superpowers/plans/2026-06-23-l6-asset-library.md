# L6 Asset Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `/assets` L6 visual asset library with aligned database, backend API, and frontend types.

**Architecture:** Add a dedicated `product_assets` domain rather than overloading existing `product_media`. Backend rules live in `asset_service`, API endpoints live in `api/assets.py`, and frontend uses a dedicated `AssetLibrary` page with shared field names from `ProductAsset`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic 2, SQLite/PostgreSQL-compatible DDL, React 18, Vite, TypeScript, Tailwind.

---

### Task 1: Backend Asset Domain

**Files:**
- Create: `backend/app/models/product_asset.py`
- Create: `backend/app/schemas/asset.py`
- Create: `backend/app/services/asset_service.py`
- Create: `backend/tests/test_asset_service.py`
- Modify: `backend/app/models/__init__.py`

- [ ] Write failing service tests for `seq`, defaults, tag-only updates, and status movement.
- [ ] Run `python -m pytest backend/tests/test_asset_service.py -q`; expect import or missing-function failures.
- [ ] Add `ProductAsset` model with the exact spec fields.
- [ ] Add Pydantic schemas with the same field names.
- [ ] Implement service helpers: product existence check, `model_to_dict`, create, list, update, delete, patch tags, upload metadata defaults, next `seq`.
- [ ] Run `python -m pytest backend/tests/test_asset_service.py -q`; expect pass.

### Task 2: Backend API, Storage, And Migration Compatibility

**Files:**
- Create: `backend/app/api/assets.py`
- Create: `backend/alembic/versions/20260623_add_product_assets.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/database.py`
- Create: `backend/tests/test_asset_api.py`

- [ ] Write failing API tests for list/create/update/tags and upload file validation.
- [ ] Run `python -m pytest backend/tests/test_asset_api.py -q`; expect missing route failures.
- [ ] Add router `/api/products/{sku}/assets`.
- [ ] Implement multipart upload with image/video validation, configured `UPLOAD_DIR`, UUID filenames, and image thumbnail creation when Pillow is available; gracefully skip thumbnail if unavailable.
- [ ] Register the router in `main.py`.
- [ ] Add migration script for `product_assets`.
- [ ] Add startup compatibility check that creates indexes/columns if the table already exists differently, with existing database as source of truth.
- [ ] Run `python -m pytest backend/tests/test_asset_api.py backend/tests/test_asset_service.py -q`; expect pass.

### Task 3: Frontend Types, API Client, And Helpers

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/src/pages/assetLibraryConfig.ts`
- Create: `frontend/src/pages/assetLibraryHelpers.ts`

- [ ] Add `ProductAsset`, `AssetTags`, `AssetGrouped`, and `AssetUploadResponse` with backend field names.
- [ ] Add `api.assets` methods for list, grouped list, get, create, upload, update, delete, patch tags.
- [ ] Add category/subcategory/material/status config.
- [ ] Add helper functions for naming preview, asset display URL, tag cloning, and sorting.

### Task 4: Frontend Asset Library Page

**Files:**
- Create: `frontend/src/pages/AssetLibrary.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`

- [ ] Implement independent `/assets` page with SKU search/select.
- [ ] Add category tabs, subcategory filters, upload areas, asset grid, edit modal, tags, batch toolbar, and lightbox.
- [ ] Add route protected by `product.read`.
- [ ] Add navigation item `素材库`.

### Task 5: Verification

**Files:**
- No new production files unless fixes are needed.

- [ ] Run backend asset tests.
- [ ] Run a broader focused backend test command including product tests.
- [ ] Run frontend build.
- [ ] Start dev backend/frontend if needed.
- [ ] Run a real API smoke against dev backend using a test product and asset upload.
- [ ] Run a browser smoke against `/assets` and capture any failures.
