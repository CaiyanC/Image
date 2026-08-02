# Asset Tag Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled visual-expression tags and authenticated cross-SKU asset search for the 20-SKU pilot.

**Architecture:** Preserve the existing `product_assets.tags` JSON structure. Add validation in `asset_service`, a separate `/api/assets/search` router, and an `/assets/search` React page that links back to SKU management.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, React, TypeScript, Tailwind, pytest, Vite.

## Global Constraints

- Work only in `codex/asset-tag-search`; do not edit `master`.
- Smoke ports are `8002` and `5277`, using `product_knowledge_dev` read-only for manual checks.
- Preserve all SKU-scoped asset APIs and existing tag keys.
- Global search requires `product.read`; updates retain current `product.update`, `tag.edit`, and risk review restrictions.

---

### Task 1: Controlled tag validation

**Files:**
- Modify: `backend/app/schemas/asset.py`
- Modify: `backend/app/services/asset_service.py`
- Test: `backend/tests/test_asset_service.py`, `backend/tests/test_asset_api.py`

**Interfaces:** Create `validate_asset_tags(tags: dict[str, list[str]]) -> dict[str, list[str]]`. New keys are `expression_tags`, `selling_point_tags`, `scene_tags`, `mood_tags`.

- [ ] Write a failing test that `{"expression_tags": ["卖点图"]}` returns HTTP 422, and that `{"expression_tags": ["场景图"], "scene_tags": ["家庭露营"]}` succeeds.
- [ ] Run `backend\venv\Scripts\python.exe -m pytest backend/tests/test_asset_service.py -q`; verify the failure is the missing validator.
- [ ] Add the new optional arrays to `AssetTagsUpdate`; make the validator require `selling_point_tags` for 卖点图, `scene_tags` for 场景图, and `mood_tags` for 氛围图. Call it from create, tag-patch, and tag update paths.
- [ ] Run `backend\venv\Scripts\python.exe -m pytest backend/tests/test_asset_service.py backend/tests/test_asset_api.py -q`; verify pass.
- [ ] Commit: `git add backend/app/schemas/asset.py backend/app/services/asset_service.py backend/tests/test_asset_service.py backend/tests/test_asset_api.py; git commit -m "feat: validate visual asset expression tags"`.

### Task 2: Cross-SKU search API

**Files:**
- Create: `backend/app/api/asset_search.py`
- Modify: `backend/app/services/asset_service.py`, `backend/app/main.py`
- Test: `backend/tests/test_asset_api.py`

**Interfaces:** `GET /api/assets/search` accepts SKU, category, channel, review status, authorization status, and repeated `expression_tags`, `selling_point_tags`, `scene_tags`, `mood_tags`, plus `limit` 1-100. `search_assets` ANDs distinct filters and ORs values within one tag dimension.

- [ ] Write a failing API test with assets under two SKUs: searching `scene_tags=家庭露营&channel=Amazon` returns only the matching SKU; `limit=101` returns 422.
- [ ] Run `backend\venv\Scripts\python.exe -m pytest backend/tests/test_asset_api.py -q`; verify the new path is 404.
- [ ] Implement the service with scalar SQL filtering, tag matching through `parse_tags`, stable SKU/category/sequence ordering, max 100 records, and `product.read` authentication.
- [ ] Run `backend\venv\Scripts\python.exe -m pytest backend/tests/test_asset_api.py backend/tests/test_l6_smoke.py -q`; verify pass.
- [ ] Commit: `git add backend/app/api/asset_search.py backend/app/services/asset_service.py backend/app/main.py backend/tests/test_asset_api.py; git commit -m "feat: add cross sku asset search"`.

### Task 3: Tag UI and search page

**Files:**
- Modify: `frontend/src/types/index.ts`, `frontend/src/pages/assetLibraryConfig.ts`, `frontend/src/services/api.ts`, `frontend/src/pages/AssetLibrary.tsx`, `frontend/src/App.tsx`, `frontend/src/components/layout/Header.tsx`
- Create: `frontend/src/pages/AssetSearch.tsx`

**Interfaces:** Add four optional arrays to `AssetTags`; add `api.assets.search(filters)`. Route `/assets/search` remains behind `product.read`.

- [ ] Write a failing frontend test or existing-compatible helper assertion that the expression preset equals `['卖点图', '场景图', '氛围图']` and repeated tag values serialize as repeated query keys.
- [ ] Run the established frontend test command and verify failure before code exists.
- [ ] Add presets for expression, selling point, scene, and mood. Extend existing tag panels. Build the search page with multi-select chips, scalar filters, result cards showing SKU/tags, and a link to `/assets?sku=<sku>`; make the library read that parameter.
- [ ] Run `pnpm --dir frontend run build`; verify TypeScript build succeeds.
- [ ] Commit: `git add frontend/src; git commit -m "feat: add visual asset search page"`.

### Task 4: Isolated verification and branch handoff

**Files:** local-only environment overrides only; no secrets committed.

- [ ] Configure port overrides for backend `8002` and frontend `5277` while preserving `APP_ENV=dev` and the existing development database.
- [ ] Run `backend\venv\Scripts\python.exe -m pytest backend/tests/test_asset_service.py backend/tests/test_asset_api.py backend/tests/test_l6_smoke.py -q` and `pnpm --dir frontend run build`; verify both pass.
- [ ] Start the isolated services; verify `/health` on 8002 and `/assets/search` on 5277. Use API-test-created records for tag mutation; manual checks against `product_knowledge_dev` must be read-only.
- [ ] From `D:\CaiYan\Image-Generation-feature-v5-graphify`, run `graphify update . --no-cluster` and `graphify cluster-only . --no-label`; inspect the asset-library community and do not commit graph output.
- [ ] Push `codex/asset-tag-search`; integrate into `dev` only after deliberately reconciling the other developers’ work. Never merge to `master`.

## Plan self-review

The plan covers tag rules, search, permissions, automated tests, requested ports, development database safeguards, and graph updates. It explicitly excludes real 20-SKU data entry, vector search, OCR, and production release.
