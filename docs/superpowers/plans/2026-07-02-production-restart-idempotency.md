# Production Restart Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production backend restart idempotent and make the production frontend reliably start from the existing build with persistent logs.

**Architecture:** Keep the existing Windows service-control entry point. Treat listener disappearance as the stop success criterion, suppress expected process-race errors, and launch the production frontend directly from `frontend/dist` through `npm run serve:prod` with redirected logs.

**Tech Stack:** PowerShell 5.1, pytest static contract tests, FastAPI health-version test.

---

### Task 1: Add deployment-script regression tests

**Files:**
- Create: `backend/tests/test_service_control_windows.py`
- Test: `deploy/scripts/service_control_windows.ps1`

- [x] Write tests asserting that process-not-found is non-fatal, port release is the final stop condition, version verification remains mandatory, and frontend startup uses `serve:prod` with production paths and logs.
- [x] Run `pytest backend/tests/test_service_control_windows.py -v` and confirm the current script fails the new contracts.

### Task 2: Make backend stop idempotent

**Files:**
- Modify: `deploy/scripts/service_control_windows.ps1`
- Test: `backend/tests/test_service_control_windows.py`

- [x] Replace fatal native `taskkill` handling with best-effort process-tree cleanup.
- [x] Re-query port 8000 until it is clear; fail only when a remaining listener is unresolved or is not the production backend.
- [x] Preserve listener, health/live/ready, PID, commit, `code_root`, and `cwd` gates after startup.
- [x] Run the focused tests and confirm they pass.

### Task 3: Stabilize production frontend startup

**Files:**
- Modify: `deploy/scripts/service_control_windows.ps1`
- Test: `backend/tests/test_service_control_windows.py`

- [x] Start only `frontend` production assets through `npm run serve:prod` on 5275.
- [x] Set the frontend working directory explicitly and redirect stdout/stderr into `logs/prod`.
- [x] Keep the healthy-frontend skip behavior and require HTTP success after startup.
- [x] Run focused tests and confirm they pass.

### Task 4: Verify and publish dev

**Files:**
- Verify: `deploy/scripts/service_control_windows.ps1`
- Verify: `backend/tests/test_health_version.py`
- Verify: `backend/tests/test_service_control_windows.py`

- [x] Run PowerShell parser validation.
- [x] Run focused pytest and `py_compile`.
- [x] Run `git diff --check` and inspect the diff.
- [ ] Commit with `chore(deploy): make production restart idempotent and verify frontend startup`.
- [ ] Push `HEAD:dev` without touching master or production services.
