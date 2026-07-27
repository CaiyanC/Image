# Mature Customer Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mature, evidence-grounded customer service flow that answers from unified same-SKU data, tolerates valid DeepSeek plan variation, performs useful comparisons and open-product dialogue, and produces one consistent customer-friendly final answer.

**Architecture:** Preserve DeepSeek semantic ownership and the existing FieldContract/EntityResolutionContract boundaries. Add focused evidence aggregation, answer-coverage and final-arbitration components, then migrate comparison and product-QA/RAG paths incrementally while deleting superseded shortcuts.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy, PostgreSQL, Redis DB1, DeepSeek-compatible chat API, pytest, UTF-8 HTTP audit scripts.

## Global Constraints

- Work only in `D:\CaiYan\Image-n065-audit` on branch `dev`.
- Use API 8001, database `product_knowledge_dev`, and Redis DB1 until every release gate passes.
- DeepSeek owns full-sentence semantics; deterministic code owns contracts, evidence and safety only.
- Never add SKU, product-name, fixed-question, keyword-route or regex special cases.
- Preserve the dirty worktree and precisely stage only approved source, tests and delivery documents.
- Do not operate production 8000, production DB or Redis DB0 before the release gate.

---

### Task 1: Stabilize sealed product comparisons

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Modify: `backend/tests/test_customer_contracts.py`
- Modify: `backend/tests/test_customer_service_route_level_supplemental_regression.py`

**Interfaces:**
- Consumes: validated comparison intent and sealed `EntityResolutionContract` objects.
- Produces: `semantic_pairwise_structured_overview_contract` for fieldless comparisons and field contracts for explicit dimensions.

- [ ] Add a failing contract test where two sealed products and comparison intent survive a semantic `fallback_reason` or missing subtype.
- [ ] Add a failing route test proving “A 和 B 有什么不同” returns a grounded overview rather than clarification.
- [ ] Replace invalid-preplan clarification with a recovery adapter that preserves sealed identities and selects the existing structured-overview executor.
- [ ] Keep true unsealed or ambiguous comparison inputs on clarification.
- [ ] Run focused comparison contract and route tests.
- [ ] Run repeated UTF-8 HTTP comparison probes across different product pairs and explicit/implicit criteria.
- [ ] Commit the independently passing comparison recovery.

### Task 2: Introduce answer coverage contracts and remove contradictory tails

**Files:**
- Create: `backend/app/services/customer_answer_coverage_contract.py`
- Modify: `backend/app/services/customer_service_service.py`
- Create: `backend/tests/test_customer_answer_coverage_contract.py`
- Modify: `backend/tests/test_customer_field_evidence_policy.py`

**Interfaces:**
- Produces: `AnswerRequestUnit`, `AnswerCoverageContract`, and `reconcile_answer_coverage(...)`.
- Consumes: semantic child requests, selected evidence IDs and grounded generated clauses.

- [ ] Write tests for fully answered, partially answered, unsupported and contradictory compound answers.
- [ ] Implement immutable request-unit and coverage result dataclasses.
- [ ] Replace normalized-substring coverage checks with evidence-backed request-unit coverage.
- [ ] Ensure a verified temperature limit supporting “不能灌沸水” marks that request answered.
- [ ] Preserve safe missing text only for independently unsupported requests.
- [ ] Run focused tests and varied compound QA HTTP probes.
- [ ] Commit the independently passing coverage contract.

### Task 3: Build unified same-SKU customer evidence bundles

**Files:**
- Create: `backend/app/services/customer_evidence_bundle.py`
- Modify: `backend/app/services/customer_service_service.py`
- Create: `backend/tests/test_customer_evidence_bundle.py`

**Interfaces:**
- Produces: `CustomerEvidenceBundle` and typed `CustomerEvidenceItem` values.
- Consumes: a resolved canonical SKU plus existing structured-field, QA and knowledge retrieval providers.

- [ ] Write tests proving one bundle contains only customer-visible evidence for one SKU.
- [ ] Write tests for invalid placeholders, internal fields and conflicting values.
- [ ] Implement structured, QA, product-content and file-knowledge adapters.
- [ ] Attach stable evidence IDs and source metadata.
- [ ] Route open product dialogue and comparison overview through bundle selection.
- [ ] Verify no cross-SKU evidence and no internal-field exposure.
- [ ] Commit the independently passing evidence bundle.

### Task 4: Implement progressive best-effort answering

**Files:**
- Create: `backend/app/services/customer_progressive_answer_service.py`
- Modify: `backend/app/services/customer_service_service.py`
- Create: `backend/tests/test_customer_progressive_answer_service.py`

**Interfaces:**
- Consumes: semantic contract, entity contracts, evidence bundles and answer coverage.
- Produces: one of `complete`, `partial`, `overview`, `clarification`, or `unsupported`.

- [ ] Write failing tests for partial evidence, open overview, fieldless comparison, real ambiguity and total absence.
- [ ] Implement the five-state decision without lexical intent inference.
- [ ] Make fieldless comparisons answer first and optionally ask a follow-up preference.
- [ ] Make open product questions use available evidence rather than require a canonical field.
- [ ] Preserve realtime and sensitive-data boundaries.
- [ ] Run focused tests and UTF-8 HTTP holdouts across different categories.
- [ ] Commit the independently passing progressive answer service.

### Task 5: Centralize final answer arbitration and customer-friendly polish

**Files:**
- Create: `backend/app/services/customer_final_answer_arbiter.py`
- Modify: `backend/app/services/customer_service_service.py`
- Create: `backend/tests/test_customer_final_answer_arbiter.py`

**Interfaces:**
- Consumes: grounded draft, coverage contract, evidence bundle IDs and answer metadata.
- Produces: one internally consistent final answer plus audit findings.

- [ ] Write tests for contradiction, duplicated missing text, uncovered requests, empty answers and unsupported factual additions.
- [ ] Implement deterministic structural checks without rewriting semantic meaning.
- [ ] Run DeepSeek polish only after grounding and revalidate facts afterward.
- [ ] Remove internal labels and redundant templates while preserving every verified fact.
- [ ] Attach final coverage and evidence audit metadata for HTTP review.
- [ ] Run focused tests and manually read diverse answers.
- [ ] Commit the independently passing final arbiter.

### Task 6: Multi-turn, QA/RAG, recommendation and comparison integration

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Modify: `backend/app/services/customer_dialogue_state.py`
- Modify: relevant focused tests under `backend/tests/`

**Interfaces:**
- Consumes: the central evidence, coverage, progressive-answer and final-arbiter services.
- Produces: consistent behavior across field, QA, RAG, recommendation, comparison and multi-turn routes.

- [ ] Migrate same-SKU QA/RAG to the shared evidence bundle.
- [ ] Migrate comparison to shared coverage and final arbitration.
- [ ] Ensure current question owns intent and context only fills product identity.
- [ ] Verify recommendation candidate identity and hard constraints from same-SKU evidence.
- [ ] Remove only shortcuts whose behavior is now covered by central services.
- [ ] Run focused adjacency tests and new multi-session UTF-8 HTTP holdouts.
- [ ] Commit the integrated customer-service flow.

### Task 7: Business review and release

**Files:**
- Create or update: `reports/final_delivery/`
- Use: UTF-8 HTTP audit scripts under `backend/`

**Interfaces:**
- Consumes: frozen source snapshot.
- Produces: reviewed release evidence and a production-ready commit.

- [ ] Generate independent holdout questions covering fields, QA rewrites, file RAG, open dialogue, comparisons, recommendations, ambiguity, missing data and multi-turn.
- [ ] Save actual question, answer, semantic plan, contracts, SKU and evidence metadata.
- [ ] Manually classify every FAIL, WARNING and changed answer.
- [ ] Fix any P0/P1 issue by central root cause and rerun only affected plus independent holdout cases.
- [ ] Run focused pytest, `py_compile`, `git diff --check` and fresh dev 8001.
- [ ] Precisely stage source, tests and required delivery evidence; verify no environment files or audit junk are staged.
- [ ] Commit and push `origin/dev`.
- [ ] When every release gate passes, fast-forward `master`, push, restart production and immediately return to `dev`.
- [ ] Run production UTF-8 HTTP smoke and manually review complete answers.
- [ ] Mark DELIVERY READY only when production evidence proves all mandatory invariants.
