# Experience Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an internal experience layer for clarify soft replies, query rewrite, and implicit intent hints without changing routing, intent, final layer, or API schema.

**Architecture:** Introduce a small internal helper package under `backend/app/internal/experience_layer/` that owns three pure functions: implicit intent tagging, retrieval query rewriting, and tone shaping. Wire it into the existing service pipeline only at safe seams: intent parsing / retrieval preparation for rewrite and the final clarify output path for soft replies. Keep recommendation and product_detail deterministic and untouched except for optional internal query rewrite inputs that do not change their answer format.

**Tech Stack:** Python, existing FastAPI service layer, existing customer service services, pytest / HTTP regression scripts.

---

### Task 1: Add internal experience helpers

**Files:**
- Create: `backend/app/internal/experience_layer/__init__.py`
- Create: `backend/app/internal/experience_layer/implicit_intent.py`
- Create: `backend/app/internal/experience_layer/query_rewrite.py`
- Create: `backend/app/internal/experience_layer/tone_shaping.py`
- Test: `tests/test_experience_layer.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.app.internal.experience_layer.implicit_intent import infer_secondary_intents
from backend.app.internal.experience_layer.query_rewrite import rewrite_query_for_retrieval
from backend.app.internal.experience_layer.tone_shaping import soften_clarify_answer


def test_infer_secondary_intents_preserves_primary():
    result = infer_secondary_intents("适合当礼物吗", primary_intent="recommendation")
    assert result["primary_intent"] == "recommendation"
    assert "gift_scenario" in result["secondary_intents"]


def test_rewrite_query_for_retrieval_keeps_meaning():
    assert rewrite_query_for_retrieval("简单说下") == "产品核心信息总结"
    assert rewrite_query_for_retrieval("适合吗") == "使用场景推荐"


def test_soften_clarify_answer_keeps_clarify_style():
    text = soften_clarify_answer("我还需要一个更明确的产品范围。")
    assert "更明确" in text or "补充" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: FAIL because the module/files do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/internal/experience_layer/implicit_intent.py
def infer_secondary_intents(text: str, primary_intent: str | None = None) -> dict:
    ...

# backend/app/internal/experience_layer/query_rewrite.py
def rewrite_query_for_retrieval(text: str) -> str:
    ...

# backend/app/internal/experience_layer/tone_shaping.py
def soften_clarify_answer(answer: str) -> str:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/internal/experience_layer tests/test_experience_layer.py
git commit -m "feat: add internal experience layer helpers"
```

### Task 2: Wire rewrite and implicit intent into retrieval prep

**Files:**
- Modify: `backend/app/services/customer_agent_intent_service.py`
- Modify: `backend/app/services/customer_agent_runtime_service.py`
- Test: `tests/test_experience_layer.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.app.internal.experience_layer.query_rewrite import rewrite_query_for_retrieval


def test_query_rewrite_is_internal_only():
    assert rewrite_query_for_retrieval("能买吗") == "购买建议"
    assert rewrite_query_for_retrieval("怎么样") == "评价与使用体验"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: FAIL until wiring is in place.

- [ ] **Step 3: Write minimal implementation**

```python
# in customer_agent_intent_service.py, before QA/KB retrieval:
from ..internal.experience_layer.query_rewrite import rewrite_query_for_retrieval
from ..internal.experience_layer.implicit_intent import infer_secondary_intents

rewrite = rewrite_query_for_retrieval(question)
hint = infer_secondary_intents(question, primary_intent=intent.intent)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/customer_agent_intent_service.py backend/app/services/customer_agent_runtime_service.py backend/app/internal/experience_layer tests/test_experience_layer.py
git commit -m "feat: wire internal query rewrite and intent hints"
```

### Task 3: Add clarify soft reply shaping only

**Files:**
- Modify: `backend/app/services/customer_service_service.py`
- Modify: `backend/app/services/customer_agent_runtime_service.py`
- Test: `tests/test_experience_layer.py`

- [ ] **Step 1: Write the failing test**

```python
from backend.app.internal.experience_layer.tone_shaping import soften_clarify_answer


def test_soften_clarify_answer_adds_soft_bridge():
    text = soften_clarify_answer("请先告诉我要查询哪款产品。")
    assert "如果你愿意" in text or "我可以先帮你" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: FAIL until clarify output shaping is implemented.

- [ ] **Step 3: Write minimal implementation**

```python
# in customer_service_service.py clarify branch only:
from ..internal.experience_layer.tone_shaping import soften_clarify_answer
faq_result["answer"] = soften_clarify_answer(faq_result["answer"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `backend\\venv\\Scripts\\python.exe -m pytest tests/test_experience_layer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/customer_service_service.py backend/app/services/customer_agent_runtime_service.py backend/app/internal/experience_layer tests/test_experience_layer.py
git commit -m "feat: soften clarify replies in experience layer"
```

### Task 4: Regression verification

**Files:**
- Test: existing HTTP regression scripts under `tmp/`

- [ ] **Step 1: Run knowledge + business + perf regression**

Run:
`backend\\venv\\Scripts\\python.exe tmp\\dev8001_knowledge_usability_verify_query_expansion.py`
`backend\\venv\\Scripts\\python.exe tmp\\dev8001_full_regression_200_recommendation_perf.py`
`backend\\venv\\Scripts\\python.exe tmp\\dev8001_customer_service_perf_analysis.py`

- [ ] **Step 2: Verify no schema changes**

Check the response JSON keys against the previous reports. Expected: identical top-level schema.

- [ ] **Step 3: Verify experience-only behavior**

Confirm:
- `clarify` answers are softer and include an explanatory bridge.
- `product_detail` answers remain factual and short.
- `recommendation` answers remain SKU-first and reason-first.
- `business_pass` remains `200/200`.
- `llm_call_count_nonzero` remains `0`.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-06-24-experience-layer.md
git commit -m "docs: add experience layer implementation plan"
```
