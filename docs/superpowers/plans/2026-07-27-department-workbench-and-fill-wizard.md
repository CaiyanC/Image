# 部门工作台与原版填表向导 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the full browser workflow for the ecommerce spreadsheet tool and add a department-oriented IT workbench.

**Architecture:** Add a persisted upload draft and a server-side recognition/precheck service before run creation. The React wizard renders the server precheck result and only submits a confirmed draft. The department workbench reuses group permissions and the controlled tool registry to render a read-only department preview.

**Tech Stack:** FastAPI, SQLAlchemy, Celery, React, TypeScript, Vite, pytest.

## Global Constraints

- Work only on the isolated branch; never modify master or production services.
- Keep tool routes and permission keys server controlled.
- Preserve the copied original spreadsheet runtime as the execution implementation.
- Use a separate preview database, upload directory, ports, and Celery queue for preview.

---

### Task 1: Server-side draft recognition and precheck

**Files:**
- Modify: `backend/app/models/tool_run.py`, `backend/app/services/tool_run_service.py`, `backend/app/api/tools.py`
- Create: `backend/app/services/ecommerce_precheck_service.py`
- Test: `backend/tests/test_ecommerce_precheck.py`

- [ ] Write failing tests for an ecommerce draft that reports its required W27 template missing and for a valid Amazon three-file draft.
- [ ] Run `py -m pytest tests/test_ecommerce_precheck.py -v` and confirm the missing service failure.
- [ ] Implement persisted draft upload, role recognition, and workflow-specific required-role precheck.
- [ ] Run the test again and confirm it passes.
- [ ] Commit the server precheck task.

### Task 2: Confirmed run creation

**Files:**
- Modify: `backend/app/api/tools.py`, `backend/app/schemas/tool.py`
- Test: `backend/tests/test_tool_registry.py`

- [ ] Write failing API tests showing an unconfirmed or failing precheck cannot enqueue a run.
- [ ] Run the focused test and confirm failure.
- [ ] Implement confirmed-draft run creation with cycle/date parameters.
- [ ] Run backend tool tests and commit.

### Task 3: Browser fill wizard

**Files:**
- Modify: `frontend/src/services/api.ts`, `frontend/src/pages/EcommerceDataFill.tsx`
- Test: `frontend/src/pages/EcommerceDataFill.test.tsx`

- [ ] Write a failing UI test for a disabled start action before precheck success.
- [ ] Run the focused frontend test and confirm failure.
- [ ] Implement upload/recognition, parameter confirmation, precheck, explicit execution confirmation, and results steps.
- [ ] Run build and focused test, then commit.

### Task 4: IT department workbench

**Files:**
- Create: `backend/app/api/admin_department_workbench.py`, `frontend/src/pages/AdminDepartmentWorkbench.tsx`
- Modify: `backend/app/main.py`, `frontend/src/services/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/layout/Header.tsx`
- Test: `backend/tests/test_department_workbench.py`

- [ ] Write failing tests for management-only department tool preview.
- [ ] Run the focused test and confirm failure.
- [ ] Implement API and visual department selector/tool grid with links to existing settings.
- [ ] Run backend tests and frontend build, then commit.
