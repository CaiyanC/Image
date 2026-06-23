# Product Operation Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow admins to restore product-library operations from operation-log snapshots.

**Architecture:** Add a product operation snapshot model/service tied to `operation_logs`, capture before/after product detail JSON around product mutations, expose restore endpoints, and surface restore actions in the operation log UI.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL/SQLite tests, React/TypeScript.

---

### Task 1: Backend snapshot model and service
- [ ] Add `ProductOperationSnapshot` model.
- [ ] Add snapshot create/list/restore service tests first.
- [ ] Implement snapshot creation and restore to before/after state.

### Task 2: Capture snapshots around product operations
- [ ] Capture before/after for product create/update/full/delete and detail sections.
- [ ] Link snapshots to operation log IDs.

### Task 3: Admin API and log query metadata
- [ ] Add restore/list snapshot endpoints.
- [ ] Include `can_restore` and `snapshot_id` in operation log query response.

### Task 4: Frontend restore controls
- [ ] Add restore button in operation detail modal when available.
- [ ] Confirm before restore and refresh logs after restore.

### Task 5: Verification
- [ ] Run backend unit tests.
- [ ] Run frontend build.
- [ ] Smoke-test DB table creation and empty query.
