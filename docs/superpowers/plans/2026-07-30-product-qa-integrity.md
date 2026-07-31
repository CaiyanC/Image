# Product QA Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement task-by-task with tests first.

**Goal:** Ensure intelligent customer service and the product vector index consume only same-SKU Product QA explicitly approved by a semantic integrity audit; preserve rejected and reviewable QA unchanged for operations.

**Architecture:** Add auditable integrity fields to `ProductQa`. A dedicated service supplies only sealed same-SKU evidence to DeepSeek and persists one of `approved`, `rejected`, or `review`; malformed or unavailable results fail closed to `review`. All customer retrieval and QA vector documents call one approved-only product-service helper, while management CRUD remains unfiltered. A development-only audit command may apply verdicts and reindex changed SKUs.

**Tech Stack:** Python, SQLAlchemy, Alembic, FastAPI services, customer LLM service, pytest, PostgreSQL.

## Global Constraints

- Work only on `dev`; do not alter production, `master`, port 8000, or production data.
- DeepSeek performs semantic judgement. Deterministic code only seals SKU, validates model JSON, records a verdict, and filters evidence.
- Never rewrite a QA answer during audit; rejected and review records remain available to management.
- No SKU-, category-, or keyword-specific allow/deny rules.
- Run Graphify update and clustering after code changes; do not commit temp outputs or the user's existing untracked files.

---

### Task 1: Establish persistent audit state and the approved-only retrieval contract

**Files:** `backend/alembic/versions/20260730_add_product_qa_integrity.py`; `backend/app/models/product_qa.py`; `backend/app/services/product_service.py`; `backend/tests/test_product_qa_integrity_service.py`.

- [ ] Write a failing test that creates rejected QA and asserts its original answer is retained but `customer_visible_product_qas(db, product_id)` returns no record.
- [ ] Add `integrity_status`, `integrity_reason`, `integrity_model`, and `integrity_audited_at`, with an indexed migration defaulting legacy rows to `review`.
- [ ] Implement `customer_visible_product_qas(db, product_id)` to return only `approved` records in priority/update order.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Audit a single QA item from sealed same-SKU evidence

**Files:** `backend/app/services/product_qa_integrity_service.py`; `backend/tests/test_product_qa_integrity_service.py`.

- [ ] Write a failing async-service test in which the LLM rejects inapplicable water-kettle QA and assert only audit fields change.
- [ ] Build a bounded evidence bundle from the same product's specs, business and content; request JSON `{status, reason}` from the customer LLM.
- [ ] Validate only `approved`, `rejected`, or `review`; malformed output and provider errors persist `review`.
- [ ] Re-run all integrity-service tests.

### Task 3: Apply the boundary to every customer-facing QA reader and index builder

**Files:** `backend/app/services/customer_service_service.py`; `backend/app/services/customer_agent_intent_service.py`; `backend/app/services/product_vector_index_service.py`; affected customer-service tests.

- [ ] Write failing regressions for rejected QA being unavailable through exact/same-SKU customer matching and absent from generated `qa:*` vector documents.
- [ ] Replace direct customer-facing `ProductQa` reads with the approved-only helper; retain direct reads only in administration and integrity auditing.
- [ ] Make vector document construction receive approved QA rather than serialised management detail QA; stale rejected-QA index documents must be deleted on reindex.
- [ ] Run focused customer and vector regression tests.

### Task 4: Audit development history and reindex safely

**Files:** `backend/scripts/audit_product_qa_integrity.py`; integrity-service tests.

- [ ] Write a failing test proving dry-run performs no persistence and `--apply` changes audit fields only.
- [ ] Add a development-environment guard, per-item result ledger, `--apply`, and resync only SKUs whose QA verdict changed.
- [ ] Run a dry audit of `product_knowledge_dev`, inspect every rejected/review result, then apply only after the dry ledger is accepted.

### Task 5: Verification and handoff

- [ ] Run `py_compile`, `git diff --check`, focused integrity/customer/vector tests, and relevant wider regressions.
- [ ] Refresh `D:\CaiYan\Image-Generation-feature-v5-graphify` with `graphify update . --no-cluster` then `graphify cluster-only . --no-label` and inspect the affected customer/index communities.
- [ ] Run fresh UTF-8 HTTP checks against development port 8001 for both normal and rejected-QA cases; verify evidence SKU and persisted conversation integrity.
- [ ] Commit only the intended source, tests, migration and documentation to `dev`, then push `origin/dev`. Do not merge or restart production.
