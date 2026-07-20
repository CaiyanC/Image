# Model and Knowledge Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model configuration safe and deterministic, and execute knowledge maintenance jobs through Celery.

**Architecture:** Database-backed model and job records remain the source of truth. API routes validate and enqueue; Celery performs knowledge work; frontend receives masked model secrets and immutable embedding metadata.

**Tech Stack:** FastAPI, SQLAlchemy, Celery, Redis, cryptography/Fernet, React, pytest.

## Global Constraints

- Work only in the isolated feature worktree until the user provides a dev restart window.
- Do not expose API keys in GET responses or operation logs.
- Do not publish production without explicit release approval.

---

### Task 1: Model configuration safety

- [ ] Add failing tests for masked key responses, preserved blank keys, deterministic defaults, and environment fallback.
- [ ] Implement encrypted persistence and default selection.
- [ ] Update the admin UI for default selection and read-only embedding state.

### Task 2: Celery knowledge jobs

- [ ] Add failing tests that enqueue work instead of using the in-process executor.
- [ ] Add persistent `KnowledgeJob`, a Celery task, and database-backed job service.
- [ ] Include the task module in the worker configuration.

### Task 3: Unsupported video surface

- [ ] Add a failing route test for a 501 response.
- [ ] Hide the video mode and return a clear 501 from the backend.

### Task 4: Verification and release handoff

- [ ] Run focused backend tests and the frontend production build.
- [ ] Commit only feature files and wait for the dev restart window before merging or restarting services.
