# Customer Service Boundary And Timeout Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unsupported gifting/quality marketing claims and keep deterministic multi-turn product context usable when semantic planning times out.

**Architecture:** Keep the existing same-SKU evidence contracts as the authority. Extend the existing gifting boundary into the sealed same-SKU RAG renderer, and convert a bounded marketing answer to the existing safe-missing product-QA shape. Before semantic preplanning, detect only context-bound follow-up questions with an existing recommendation/candidate context and let the existing deterministic follow-up handlers resolve them.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, real HTTP at `127.0.0.1:8001`, Graphify.

---

### Task 1: Add Failing Regression Tests

**Files:**
- Modify: `backend/tests/test_customer_service_batch_regressions.py`
- Modify: `backend/tests/test_customer_service_route_level_supplemental_regression.py`

- [x] **Step 1: Add the quality/gifting boundary test**

Call `service._bound_gifting_qa_answer_to_evidence` with question `饭盒（黑色盖子+硬质氧化铝身）品质出众吗？` and the answer containing `品质出众、包装精美、适合作为礼物`. Assert the result removes all three marketing claims and contains `未直接标注` or `无法确认`.

- [x] **Step 2: Run the boundary test red**

Run:

```powershell
backend\venv\Scripts\python.exe -m pytest -q backend/tests/test_customer_service_batch_regressions.py -k "gifting or marketing"
```

Expected: the new assertion fails because the current helper only activates when the question contains `送人`, `送礼`, `礼物`, or `赠送`.

- [x] **Step 3: Add a timeout-safe comparison follow-up route test**

Create a comparison first turn with `route_client_and_db`, then monkeypatch `customer_service_service._maybe_run_semantic_preplan` to raise `AssertionError` for the second turn `你更建议哪一个？请说明理由。`. Assert the second request is HTTP 200, has `answer_type != chat`, returns only the first turn's `final_choice_sku`, and names that SKU.

- [x] **Step 4: Add a timeout-safe recommendation follow-up route test**

Create a recommendation first turn, then monkeypatch `_maybe_run_semantic_preplan` to raise for `你刚才推荐的第一款，重量和容量分别是多少？`. Assert HTTP 200, one result SKU equal to the first turn's result SKU, and both `重量` and `容量` in the answer.

- [x] **Step 5: Run the new route tests red**

Run:

```powershell
backend\venv\Scripts\python.exe -m pytest -q backend/tests/test_customer_service_route_level_supplemental_regression.py -k "timeout_safe or semantic_preplan_context"
```

Expected: the monkeypatched second turns fail because the service currently invokes semantic preplanning before deterministic context follow-up resolution.

### Task 2: Bound Marketing Claims In Both QA Paths

**Files:**
- Modify: `backend/app/services/customer_service_service.py:28500-28515, 28745-28825, 29231-29610`

- [x] **Step 1: Expand the marker predicate**

Keep one ordered marker tuple containing `包装精美`, `品质出众`, `绝佳礼物`, `非常适合`, and `送给户外露营爱好者`. Trigger the helper when the answer contains one of those markers and either the question asks about `送人|送礼|礼物|赠送|品质|包装`, or the answer itself contains `礼物|送给`.

- [x] **Step 2: Reuse a safe-missing result builder**

Extract the existing safe-missing product-QA result shape into a small local helper that receives the resolved product and conservative answer. It must return `evidence_status=missing`, `field_evidence_missing=true`, empty `evidence` and `sources`, `debug.agent_mode=sealed_product_qa_safe_missing`, and `skip_polish=true`.

- [x] **Step 3: Apply the builder to deterministic QA**

Replace the duplicated inline return in `_try_product_qa_shortcut` with the helper, preserving the resolved SKU and product display fields.

- [x] **Step 4: Apply the same boundary after sealed RAG drafting**

Immediately after the RAG answer is drafted/repaired and before `safe_missing["answer"] = answer`, pass it through `_bound_gifting_qa_answer_to_evidence`. If it changes, return the safe-missing shape instead of publishing the selected knowledge evidence as a positive answer.

- [x] **Step 5: Run the boundary tests green**

Run:

```powershell
backend\venv\Scripts\python.exe -m pytest -q backend/tests/test_customer_service_batch_regressions.py backend/tests/test_customer_service_route_level_supplemental_regression.py -k "gifting or marketing"
```

Expected: all selected tests pass and no unsupported marketing marker remains in the answer.

### Task 3: Bypass Semantic Planning For Bound Context Follow-Ups

**Files:**
- Modify: `backend/app/services/customer_service_service.py` immediately before the `_maybe_run_semantic_preplan` call around line 23400.

- [x] **Step 1: Add the context predicate**

Add a helper that returns true only when `conversation_id` is present, at least one of `_latest_recommendation_context_for_sources` or `_latest_candidate_context_for_sources` has follow-up result context, and the question matches `_is_comparison_choice_followup_question`, `_is_recommendation_followup_question`, `_is_ordinal_compare_followup_question`, or a named candidate field follow-up.

- [x] **Step 2: Bypass only the semantic call**

Set `semantic_preplan = None` for that predicate; otherwise call `_maybe_run_semantic_preplan` unchanged. Do not synthesize a route, SKU, or answer in the bypass. Existing deterministic context handlers later in `ask_customer_service` remain authoritative.

- [x] **Step 3: Run the route tests green**

Run:

```powershell
backend\venv\Scripts\python.exe -m pytest -q backend/tests/test_customer_service_route_level_supplemental_regression.py -k "timeout_safe or semantic_preplan_context"
```

Expected: both context tests pass without invoking the monkeypatched semantic planner.

- [x] **Step 4: Cover a selected-choice third-turn field follow-up**

After a comparison and explicit choice, verify `你刚才选的那款，材质、容量、重量一次说清楚。` retains the selected SKU, returns all three formal fields, and does not invoke semantic preplanning.

### Task 4: Verify And Publish

- [x] **Step 1: Run changed-area tests**

```powershell
backend\venv\Scripts\python.exe -m pytest -q backend/tests/test_customer_service_batch_regressions.py backend/tests/test_customer_service_route_level_regression.py backend/tests/test_customer_service_route_level_supplemental_regression.py backend/tests/test_customer_agent_service.py backend/tests/test_customer_recommendation_verification_contract.py
```

- [x] **Step 2: Run the full test suite**

```powershell
backend\venv\Scripts\python.exe -m pytest -q
```

Require zero customer-service failures and errors. Report concurrent unrelated
work separately and exclude it from this release scope.

- [x] **Step 3: Run real development acceptance**

Run `backend\venv\Scripts\python.exe backend\tmp_enterprise_customer_acceptance_20260809.py`, the 60-question audit runner, and a focused repeated comparison/recommendation context audit. Require HTTP 200, non-empty answers, no unsupported markers, and preserved SKUs.

- [x] **Step 4: Refresh Graphify**

From `D:\CaiYan\Image-Generation-feature-v5-graphify`, run `graphify update . --no-cluster` and `graphify cluster-only . --no-label`. Confirm the customer-service communities remain present.

- [x] **Step 5: Review and commit dev**

Run `git diff --check`, stage only the production files, tests, and this plan, then commit on `dev` with `fix: seal customer QA and context followups`.

- [ ] **Step 6: Publish only after all gates pass**

On `dev`, push and commit any remaining changes. Checkout `master`, merge `dev`, push `master`, run `stop-prod.bat` and `start-prod.bat`, then immediately checkout `dev`. Verify production health before reporting completion.
