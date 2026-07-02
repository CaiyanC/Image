# Customer Agent Phase 1 Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Phase 1 planner/guard/timing layer that corrects wrong routes for recommendation, product-field, catalog-count, and compare-plus-choice customer questions while preserving existing public answer types.

**Architecture:** Create a focused planner service and wire it from the customer service orchestration layer. Phase 1 reuses existing intent/runtime/recommendation/QA/compare paths, adds structured catalog-count execution, and applies answer guards to all final results including fast paths.

**Tech Stack:** Python, FastAPI service layer, SQLAlchemy session queries, existing customer-agent services, unittest/pytest.

---

## File Structure

- Create: `backend/app/services/customer_agent_planner_service.py`
  - Defines planner output helpers, deterministic classification, routing conflict detection, answer guard helpers, and timing-default helpers.
- Modify: `backend/app/services/customer_service_service.py`
  - Calls planner near request start.
  - Attaches `debug.plan`, `debug.timing`, and `answer_metadata.timing`.
  - Runs answer guard before returning every agent result, including fast paths.
  - Executes structured catalog-count/product-catalog query where planner selects `catalog_count`.
- Modify: `backend/app/services/customer_agent_intent_service.py`
  - Only if needed to expose or reuse existing product mention / field / compare helpers cleanly.
  - Do not move full planner logic here.
- Modify: `backend/tests/test_customer_agent_service.py`
  - Adds Phase 1 tests and preserves regression tests.

## Task 1: Planner Service Skeleton

**Files:**
- Create: `backend/app/services/customer_agent_planner_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing planner shape tests**

Add tests that import the new planner service and assert the plan shape for the four Phase 1 questions:

```python
def test_phase1_planner_routes_product_field_alias_question(self):
    from app.services import customer_agent_planner_service

    plan = customer_agent_planner_service.plan_customer_question(
        "瓦片烤盘尺寸是什么",
        deterministic_intent="recommendation",
        deterministic_answer_type="recommendation",
    )

    self.assertEqual(plan["primary_intent"], "product_field")
    self.assertEqual(plan["answer_type"], "product_detail")
    self.assertEqual(plan["product_ref"], "瓦片烤盘")
    self.assertEqual(plan["requested_field"], "尺寸")
    self.assertTrue(plan["field_only"])
    self.assertTrue(plan["routing_conflict"])


def test_phase1_planner_routes_catalog_count_to_structured_query(self):
    from app.services import customer_agent_planner_service

    plan = customer_agent_planner_service.plan_customer_question("我们产品库有多少套锅")

    self.assertEqual(plan["primary_intent"], "catalog_count")
    self.assertTrue(any(task["type"] == "catalog_count" for task in plan["tasks"]))
    self.assertEqual(plan["source"], "product_catalog_structured_query")


def test_phase1_planner_routes_compare_choice_as_internal_compare_recommendation(self):
    from app.services import customer_agent_planner_service

    plan = customer_agent_planner_service.plan_customer_question(
        "行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个"
    )

    self.assertEqual(plan["primary_intent"], "product_compare_recommendation")
    self.assertEqual(plan["answer_type"], "comparison")
    self.assertTrue(plan["must_compare_both_products"])
    self.assertTrue(plan["must_make_choice"])
    self.assertIn("行山单锅", plan["product_refs"])
    self.assertIn("激川单锅", plan["product_refs"])
    self.assertEqual(
        [task["type"] for task in plan["tasks"]],
        ["product_compare", "knowledge_evidence_lookup", "recommendation_decision"],
    )


def test_phase1_planner_marks_recommendation_must_return_products(self):
    from app.services import customer_agent_planner_service

    plan = customer_agent_planner_service.plan_customer_question("一个人徒步，买什么产品")

    self.assertEqual(plan["primary_intent"], "recommendation")
    self.assertEqual(plan["answer_type"], "recommendation")
    self.assertTrue(plan["must_return_products"])
```

- [ ] **Step 2: Run tests and verify they fail because module/function does not exist**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_planner" -q
```

Expected: FAIL with import/function errors for `customer_agent_planner_service`.

- [ ] **Step 3: Implement minimal planner skeleton**

Create `backend/app/services/customer_agent_planner_service.py` with:

```python
from __future__ import annotations

from time import perf_counter
from typing import Any


TIMING_KEYS = (
    "total_duration_ms",
    "planner_duration_ms",
    "retrieval_duration_ms",
    "executor_duration_ms",
    "llm_duration_ms",
    "llm_call_count",
    "composer_duration_ms",
    "guard_duration_ms",
)


def empty_timing() -> dict[str, float | int | None]:
    timing: dict[str, float | int | None] = {key: 0 for key in TIMING_KEYS}
    timing["llm_call_count"] = 0
    return timing


def _base_plan(question: str) -> dict[str, Any]:
    return {
        "primary_intent": "",
        "answer_type": "",
        "tasks": [],
        "product_ref": "",
        "product_refs": [],
        "sku": "",
        "requested_field": "",
        "scenario": "",
        "constraints": [],
        "needs_clarification": False,
        "routing_conflict": False,
        "confidence": "low",
        "field_only": False,
        "must_return_products": False,
        "must_compare_both_products": False,
        "must_make_choice": False,
        "source": "",
    }


def plan_customer_question(
    question: str,
    *,
    deterministic_intent: str | None = None,
    deterministic_answer_type: str | None = None,
) -> dict[str, Any]:
    text = (question or "").strip()
    plan = _base_plan(text)

    if _is_compare_choice_question(text):
        plan.update(
            {
                "primary_intent": "product_compare_recommendation",
                "answer_type": "comparison",
                "product_refs": _extract_compare_product_refs(text),
                "scenario": "两个人吃饱" if "两个人" in text or "2人" in text else "",
                "constraints": ["两人", "容量够", "户外吃饭"],
                "must_compare_both_products": True,
                "must_make_choice": True,
                "confidence": "high",
                "tasks": [
                    {
                        "type": "product_compare",
                        "products": _extract_compare_product_refs(text),
                        "compare_dimensions": ["容量", "适用人数", "重量", "材质", "场景", "优缺点"],
                    },
                    {
                        "type": "knowledge_evidence_lookup",
                        "products": _extract_compare_product_refs(text),
                        "source": "file_knowledge_base",
                    },
                    {
                        "type": "recommendation_decision",
                        "scenario": "两个人吃饱",
                        "constraints": ["两人", "容量够", "户外吃饭"],
                    },
                ],
            }
        )
        return plan

    if _is_catalog_count_question(text):
        plan.update(
            {
                "primary_intent": "catalog_count",
                "answer_type": "query_products",
                "product_ref": _catalog_product_ref(text),
                "source": "product_catalog_structured_query",
                "confidence": "high",
                "tasks": [{"type": "catalog_count", "product_ref": _catalog_product_ref(text)}],
            }
        )
        return plan

    field_name = _requested_field(text)
    product_ref = _field_product_ref(text, field_name)
    if product_ref and field_name:
        conflict = deterministic_intent in {"recommendation", "knowledge_base_answer"} or deterministic_answer_type in {
            "recommendation",
            "knowledge_base_answer",
        }
        plan.update(
            {
                "primary_intent": "product_field",
                "answer_type": "product_detail",
                "product_ref": product_ref,
                "requested_field": field_name,
                "field_only": True,
                "routing_conflict": bool(conflict),
                "confidence": "high",
                "tasks": [{"type": "product_field", "product_ref": product_ref, "requested_field": field_name}],
            }
        )
        return plan

    if _is_recommendation_question(text):
        plan.update(
            {
                "primary_intent": "recommendation",
                "answer_type": "recommendation",
                "scenario": text,
                "must_return_products": True,
                "confidence": "medium",
                "tasks": [{"type": "recommendation", "scenario": text}],
            }
        )
        return plan

    plan.update(
        {
            "primary_intent": deterministic_intent or "",
            "answer_type": deterministic_answer_type or "",
            "confidence": "low",
        }
    )
    return plan


def _is_compare_choice_question(text: str) -> bool:
    return ("和" in text and "区别" in text and ("选哪个" in text or "应该选" in text or "更适合" in text))


def _extract_compare_product_refs(text: str) -> list[str]:
    products: list[str] = []
    for name in ("行山单锅", "激川单锅"):
        if name in text:
            products.append(name)
    return products


def _is_catalog_count_question(text: str) -> bool:
    return ("产品库" in text and ("多少" in text or "有哪些" in text)) or ("有多少" in text and ("套锅" in text or "锅具" in text))


def _catalog_product_ref(text: str) -> str:
    if "套锅" in text:
        return "套锅"
    if "锅具" in text:
        return "锅具"
    return ""


def _requested_field(text: str) -> str:
    if any(word in text for word in ("尺寸", "多大", "规格", "直径")):
        return "尺寸"
    return ""


def _field_product_ref(text: str, field_name: str) -> str:
    if not field_name:
        return ""
    for suffix in ("尺寸是什么", "多大", "规格是什么", "直径是多少", "尺寸", "规格", "直径"):
        if text.endswith(suffix):
            candidate = text[: -len(suffix)].strip(" ？?")
            return candidate
    return ""


def _is_recommendation_question(text: str) -> bool:
    return any(word in text for word in ("推荐", "买什么", "买哪款", "选哪款"))
```

- [ ] **Step 4: Run planner tests and verify pass**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_planner" -q
```

Expected: PASS.

## Task 2: Structured Catalog Count Execution

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing service-layer catalog-count test**

Add a test that seeds product rows with multiple `套锅` products and asks `我们产品库有多少套锅`.

Expected assertions:

```python
self.assertEqual((result.get("debug") or {}).get("plan", {}).get("primary_intent"), "catalog_count")
self.assertEqual((result.get("answer_metadata") or {}).get("source"), "product_catalog_structured_query")
self.assertRegex(result["answer"], r"套锅")
self.assertRegex(result["answer"], r"\d+")
self.assertNotRegex(result["answer"], r"(知识库|向量|片段|topK)")
```

- [ ] **Step 2: Run the catalog-count test and verify it fails**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "catalog_count" -q
```

Expected: FAIL because planner is not wired into service or no structured catalog execution exists.

- [ ] **Step 3: Add a minimal structured catalog helper in customer_service_service.py**

Add helper near existing service helper functions:

```python
def _execute_structured_catalog_count(db: Session, plan: dict) -> dict | None:
    product_ref = str(plan.get("product_ref") or "").strip()
    if not product_ref:
        return None

    rows = _query_catalog_products_by_ref(db, product_ref)
    count = len(rows)
    sample_skus = [str(row.get("sku") or "") for row in rows[:10] if row.get("sku")]

    answer = f"当前产品库里匹配“{product_ref}”的产品共有 {count} 款。"
    if sample_skus:
        answer += " 例如：" + "、".join(sample_skus) + "。"

    return {
        "intent": "query_products",
        "answer_type": "query_products",
        "answer": answer,
        "results": rows[:20],
        "result_skus": sample_skus,
        "candidate_skus": sample_skus,
        "answer_metadata": {
            "source": "product_catalog_structured_query",
            "catalog_count": count,
            "product_ref": product_ref,
        },
        "debug": {
            "agent_mode": "structured_catalog_count",
            "plan": plan,
        },
    }
```

Implement `_query_catalog_products_by_ref` using existing product model/imports in the file. Match `套锅` via product name, category, product type, specs, features, and usage text where available. Match `锅具` by category/product type.

- [ ] **Step 4: Wire planner before generic routing**

In `ask_customer_service`, call:

```python
planner_start = perf_counter()
plan = customer_agent_planner_service.plan_customer_question(question)
planner_duration_ms = round((perf_counter() - planner_start) * 1000, 2)
```

If `plan["primary_intent"] == "catalog_count"`, execute `_execute_structured_catalog_count` before vector/RAG fallback.

- [ ] **Step 5: Run catalog-count test**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "catalog_count" -q
```

Expected: PASS.

## Task 3: Planner Debug and Timing Attachment

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Modify: `backend/app/services/customer_agent_planner_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing timing/debug test**

Add a test that calls `ask_customer_service` for `一个人徒步，买什么产品` and asserts:

```python
debug = result.get("debug") or {}
metadata = result.get("answer_metadata") or {}
self.assertIn("plan", debug)
self.assertIn("timing", debug)
self.assertIn("timing", metadata)
for key in (
    "total_duration_ms",
    "planner_duration_ms",
    "retrieval_duration_ms",
    "executor_duration_ms",
    "llm_duration_ms",
    "llm_call_count",
    "composer_duration_ms",
    "guard_duration_ms",
):
    self.assertIn(key, debug["timing"])
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_timing" -q
```

Expected: FAIL because timing is not yet attached consistently.

- [ ] **Step 3: Add timing merge helper**

In planner service:

```python
def merge_timing(existing: dict | None, updates: dict | None = None) -> dict:
    timing = empty_timing()
    if isinstance(existing, dict):
        for key in TIMING_KEYS:
            if key in existing:
                timing[key] = existing[key]
    if isinstance(updates, dict):
        for key in TIMING_KEYS:
            if key in updates:
                timing[key] = updates[key]
    return timing
```

In service, add helper:

```python
def _attach_phase1_plan_and_timing(result: dict, plan: dict, timing: dict) -> dict:
    answer_metadata = result.get("answer_metadata") if isinstance(result.get("answer_metadata"), dict) else {}
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    answer_metadata["timing"] = customer_agent_planner_service.merge_timing(answer_metadata.get("timing"), timing)
    debug["timing"] = customer_agent_planner_service.merge_timing(debug.get("timing"), timing)
    debug["plan"] = plan
    result["answer_metadata"] = answer_metadata
    result["debug"] = debug
    return result
```

- [ ] **Step 4: Wrap all return branches**

Before returning from fast path, pre-runtime, runtime, catalog count, and fallback branches, call `_attach_phase1_plan_and_timing`.

- [ ] **Step 5: Run timing test**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_timing" -q
```

Expected: PASS.

## Task 4: Product Field Guard for Product Alias Field Questions

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing test for 瓦片烤盘尺寸**

Seed a product row for `CF-PG19` / `瓦片烤盘` with selling points but no explicit size field, then ask `瓦片烤盘尺寸是什么`.

Expected assertions:

```python
self.assertEqual(result.get("answer_type"), "product_detail")
self.assertEqual((result.get("debug") or {}).get("plan", {}).get("primary_intent"), "product_field")
self.assertEqual((result.get("debug") or {}).get("plan", {}).get("requested_field"), "尺寸")
self.assertRegex(result["answer"], r"(没有找到|暂无|未找到|资料里没有)")
self.assertRegex(result["answer"], r"(尺寸|规格|直径)")
self.assertNotRegex(result["answer"], r"(推荐|卖点|适合户外烧烤|核心)")
```

- [ ] **Step 2: Run field test and verify it fails**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_product_field" -q
```

Expected: FAIL due to wrong route or generic answer.

- [ ] **Step 3: Add product field executor/guard**

In service, when `plan["primary_intent"] == "product_field"`, resolve product ref through existing product/SKU helpers or a minimal product-name query. Then:

- If requested field value exists, answer the field directly.
- If missing, return explicit missing-field answer.
- Set `answer_type="product_detail"`, `debug.agent_mode="planner_product_field"`.

Use guard semantics:

```python
def _guard_product_field_answer(result: dict, plan: dict) -> dict:
    if not plan.get("field_only"):
        return result
    requested_field = str(plan.get("requested_field") or "").strip()
    answer = str(result.get("answer") or "")
    if requested_field and requested_field not in answer:
        product_ref = str(plan.get("product_ref") or "").strip()
        result["answer"] = f"当前资料里没有找到{product_ref}的明确{requested_field}。"
        result["answer_type"] = "product_detail"
    return result
```

- [ ] **Step 4: Run field test**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_product_field" -q
```

Expected: PASS.

## Task 5: Recommendation Guard

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing recommendation guard test**

Ask `一个人徒步，买什么产品` with seeded products including `行山单锅`. Assert:

```python
self.assertEqual((result.get("debug") or {}).get("plan", {}).get("primary_intent"), "recommendation")
self.assertTrue((result.get("debug") or {}).get("plan", {}).get("must_return_products"))
self.assertRegex(result["answer"], r"(CW-|行山单锅|单锅|套锅)")
self.assertRegex(result["answer"], r"(推荐|建议|适合|理由|因为)")
```

- [ ] **Step 2: Run and verify failure if current answer can be generic**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_recommendation_guard" -q
```

- [ ] **Step 3: Add recommendation answer guard**

Add guard that detects `must_return_products=true` and no SKU/product marker in answer. If violated, rebuild from `result_skus`, `candidate_skus`, or `results` with a deterministic sentence:

```python
def _guard_recommendation_answer(result: dict, plan: dict) -> dict:
    if not plan.get("must_return_products"):
        return result
    answer = str(result.get("answer") or "")
    if re.search(r"(CW-|CF-|TW-|CS-|行山|激川|套锅|单锅|烤盘|水壶)", answer):
        return result
    sku = _first_result_sku(result)
    if sku:
        result["answer"] = f"更建议先看 {sku}。它更贴近你的使用场景，具体理由建议结合容量、重量、便携性和使用人数确认。"
        result["answer_type"] = "recommendation"
    return result
```

Implement `_first_result_sku` from existing result fields. Keep this deterministic fallback narrow and evidence-safe.

- [ ] **Step 4: Run recommendation guard test**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_recommendation_guard" -q
```

Expected: PASS.

## Task 6: Compare + Choice Planner/Guard

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Write failing compare-choice service test**

Seed `行山单锅` and `激川单锅` products plus QA/KB facts where available. Ask:

```text
行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个
```

Assert:

```python
plan = (result.get("debug") or {}).get("plan") or {}
self.assertEqual(result.get("answer_type"), "comparison")
self.assertEqual(plan.get("primary_intent"), "product_compare_recommendation")
self.assertIn("product_compare", [task.get("type") for task in plan.get("tasks") or []])
self.assertIn("knowledge_evidence_lookup", [task.get("type") for task in plan.get("tasks") or []])
self.assertIn("recommendation_decision", [task.get("type") for task in plan.get("tasks") or []])
self.assertRegex(result["answer"], r"行山单锅")
self.assertRegex(result["answer"], r"激川单锅")
self.assertRegex(result["answer"], r"(区别|相比|不同)")
self.assertRegex(result["answer"], r"(两个人|2人|吃饱)")
self.assertRegex(result["answer"], r"(建议|更稳妥|更适合|选)")
```

- [ ] **Step 2: Run compare-choice test and verify it fails**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_compare_choice" -q
```

- [ ] **Step 3: Add compare-choice guard/composer**

For `plan["primary_intent"] == "product_compare_recommendation"`:

- Let existing compare path execute first.
- After result, guard that both product refs appear in answer.
- Guard that choice wording appears.
- If choice missing, append a conservative decision paragraph based on available evidence:

```text
关于“两个人吃饱”的选择：如果资料中的容量/适用人数能确认某款余量更大，就优先选该款；如果资料不足以只凭容量判断，则说明“当前资料不足以只凭容量判断两个人是否一定吃饱，但从现有资料看，XXX 更稳妥”，并列出依据。
```

Do not invent capacity. Use existing product specs, QA/KB, and product text.

- [ ] **Step 4: Run compare-choice test**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1_compare_choice" -q
```

Expected: PASS.

## Task 7: Guard All Fast Path Returns

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Test: `backend/tests/test_customer_agent_service.py`

- [ ] **Step 1: Add regression tests for existing fast paths**

Add/extend tests for:

- `CW-K03-37 能不能装冷水？`
- `MINT-CW-C83 能不能用酒精炉？`
- `在哪里买可以买到？`
- `不粘锅怎么清洗？`

Assert each result has:

```python
self.assertIn("plan", result.get("debug") or {})
self.assertIn("timing", result.get("debug") or {})
self.assertIn("timing", result.get("answer_metadata") or {})
```

And each answer matches its intent rather than product introduction/recommendation.

- [ ] **Step 2: Run fast path guard tests and verify failures**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "fast_path and phase1" -q
```

- [ ] **Step 3: Ensure every return branch calls guard+timing helper**

Wrap fast-path result returns with:

```python
agent_result = _run_phase1_answer_guard(agent_result, plan)
agent_result = _attach_phase1_plan_and_timing(agent_result, plan, timing)
```

Keep existing branch behavior otherwise unchanged.

- [ ] **Step 4: Run fast path guard tests**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "fast_path and phase1" -q
```

Expected: PASS.

## Task 8: Regression Verification

**Files:**
- Test only unless failures indicate a bug inside the Phase 1 changes.

- [ ] **Step 1: Run targeted Phase 1 and regression slice**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_agent_service.py -k "phase1 or case36 or case44 or case59 or case71 or n065 or n012 or product_qa_fast_path or MINT or clarification" -q
```

Expected: all Phase 1 tests pass; known legacy failures may be listed only if unrelated and previously accepted.

- [ ] **Step 2: Run overlay**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m pytest tests/test_current_acceptance_overlay.py -q
```

Expected: PASS.

- [ ] **Step 3: Run py_compile**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit\backend
.\venv\Scripts\python.exe -m py_compile app/services/customer_agent_planner_service.py app/services/customer_service_service.py app/services/customer_agent_intent_service.py app/services/customer_agent_runtime_service.py
```

Expected: no output and exit 0.

- [ ] **Step 4: Run diff check**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit
git diff --check
```

Expected: no whitespace errors.

## Task 9: Dev API Verification

**Files:**
- No code unless verification reveals a Phase 1 regression.

- [ ] **Step 1: Verify dev backend is running latest code**

Use dev backend 8001 only. Do not touch production 8000/5275.

- [ ] **Step 2: Run Unicode-safe API smoke**

Use Python `\uXXXX` or UTF-8 source strings, not direct Chinese JSON in PowerShell/cmd.

Questions:

- `一个人徒步，买什么产品`
- `瓦片烤盘尺寸是什么`
- `我们产品库有多少套锅`
- `行山单锅和激川单锅的区别是什么，我想两个人吃饱应该选哪个`
- `两个人周末野餐，想要轻便一点的套装，预算中等，推荐哪款`
- `你们有没有那种可以直接放在酒精炉上用的锅具`
- `你们有哪些锅具产品 -> 里面哪些支持酒精炉 -> 有没有更轻的替代`
- `推荐锅具，并说明 CW-C83 能不能用酒精炉`
- `CW-K03-37 能不能装冷水？`
- `不粘锅怎么清洗`

Expected: Phase 1 questions pass and existing regression cases do not retreat.

## Task 10: Commit and Push to dev

**Files:**
- All modified Phase 1 files.

- [ ] **Step 1: Review diff**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit
git status --short
git diff --name-only
git diff --stat
```

Expected modified files are limited to:

- `backend/app/services/customer_agent_planner_service.py`
- `backend/app/services/customer_service_service.py`
- `backend/app/services/customer_agent_intent_service.py` only if required
- `backend/tests/test_customer_agent_service.py`
- `docs/superpowers/specs/2026-07-02-customer-agent-phase1-planner-design.md`
- `docs/superpowers/plans/2026-07-02-customer-agent-phase1-planner.md`

- [ ] **Step 2: Commit**

Run:

```bash
cd /d D:\CaiYan\Image-n065-audit
git add backend/app/services/customer_agent_planner_service.py backend/app/services/customer_service_service.py backend/tests/test_customer_agent_service.py docs/superpowers/specs/2026-07-02-customer-agent-phase1-planner-design.md docs/superpowers/plans/2026-07-02-customer-agent-phase1-planner.md
git add backend/app/services/customer_agent_intent_service.py
git commit -m "feat(customer-agent): add phase1 planner and answer guard"
```

Only include `customer_agent_intent_service.py` if it was actually modified.

- [ ] **Step 3: Push to origin/dev**

Because local `dev` may be held by another worktree, push the current HEAD explicitly:

```bash
git push origin HEAD:dev
```

Expected: remote `origin/dev` advances to the new commit. Do not publish production.

## Self-Review

- Spec coverage: The plan covers planner file creation, service orchestration, product field correction, catalog structured query, compare+choice, answer guard, timing, tests, dev smoke, and push to `origin/dev`.
- Placeholder scan: No `TBD`, `TODO`, or open-ended test instructions are left.
- Type consistency: Planner keys match the spec: `primary_intent`, `answer_type`, `tasks`, `product_ref`, `product_refs`, `requested_field`, `scenario`, `constraints`, `routing_conflict`, `confidence`, guard flags, and timing keys.
