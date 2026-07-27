# 统一工具平台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有系统升级为按部门权限展示的统一工具平台，并接入 v1.0.35 电商数据自动填表工具的三个流程。

**Architecture:** 后端以 `Tool` 目录和 `ToolRun` 运行记录为核心，现有 RBAC 权限决定工具可见性和 API 访问；工具执行通过 Celery 和受限文件目录完成。前端以 `/tools` 工具中心作为默认入口，管理组维护已编写内部工具的展示注册；首个财务工具以独立 Python 内部包复用同版本 Excel 业务逻辑，不运行桌面 EXE/Tkinter。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、Celery、PostgreSQL/SQLite 测试、React 18、TypeScript、Vite、Tailwind CSS、openpyxl、pytest。

## Global Constraints

- 所有实现仅在 `codex/unified-tool-platform` 隔离 worktree 中进行，最终通过 `dev` 发布；不得修改 `master`。
- 未经用户明确要求，绝不将本功能合并到 `master` 或重启生产服务。
- 工具目录仅登记代码内允许的内部路由和权限；不执行 EXE、脚本、命令行或外部 URL。
- `C:\Users\wnt\Desktop\测试7_23\EcommerceDataFillTool_v1.0.35` 仅作行为对照；使用 `C:\Users\wnt\Desktop\电商数据分析表自动填写工具` 的 v1.0.35 Python 源码。
- 仅接受 `.xlsx` 输入文件；输入/输出路径必须位于当前环境 `UPLOAD_DIR/tool-runs/<run-id>/` 内。
- 所有工具运行创建、完成、失败和下载写入操作日志；下载只允许所有者或总经办/IT 部。
- 后端完整 `pytest tests -q` 当前被缺失的 `tmp_supplemental_rerun.py` 阻塞；本期执行相关测试和 `pytest tests -q --ignore=tests/test_full_regression_runner.py`。
- 现有前端 lint 有 `AssetLibrary.tsx` 的无关错误；本期必须运行 `npm run build`，不混入该无关修复。

---

## File Structure

### Backend

- Create `backend/app/models/tool.py` — `Tool` SQLAlchemy 实体。
- Create `backend/app/models/tool_run.py` — `ToolRun` SQLAlchemy 实体及受限状态枚举。
- Modify `backend/app/models/__init__.py` — 导入新实体，保证 `init_db()` 和 Alembic 可发现模型。
- Modify `backend/app/core/permission_constants.py` — 工具管理、财务填表权限、路由和默认部门权限。
- Create `backend/app/schemas/tool.py` — 工具目录、运行、文件及管理请求/响应 Pydantic 模型。
- Create `backend/app/services/tool_registry_service.py` — 受控工具白名单、目录 CRUD、用户可见性和默认工具种子。
- Create `backend/app/services/tool_run_service.py` — 运行状态转换、路径验证、可见性和文件清单。
- Create `backend/app/api/tools.py` — 用户工具目录、运行创建/查询/下载 API。
- Create `backend/app/api/admin_tools.py` — 管理端工具目录 API。
- Create `backend/app/tasks/tool_runs.py` — Celery 填表任务。
- Create `backend/app/tool_runtimes/ecommerce_data_fill/` — 从 v1.0.35 源码移植的无 GUI Excel 运行包。
- Create `backend/alembic/versions/20260727_add_tools_and_tool_runs.py` — 创建两张表和索引。
- Modify `backend/app/main.py` — 注册新 routers 与任务模块。
- Modify `backend/app/core/database.py` — 启动时幂等种子默认工具。

### Frontend

- Modify `frontend/src/types/index.ts` — 工具目录、运行和文件 API 类型。
- Modify `frontend/src/services/api.ts` — tools/admin-tools/run 的请求方法和受鉴权文件下载方法。
- Create `frontend/src/pages/ToolCenter.tsx` — 按权限展示工具卡片。
- Create `frontend/src/pages/AdminTools.tsx` — 管理端工具目录维护页。
- Create `frontend/src/pages/EcommerceDataFill.tsx` — 三种 Excel 流程的上传、提交、状态和下载页。
- Modify `frontend/src/App.tsx` — `/tools`、`/tools/ecommerce-data-fill`、`/admin/tools` 受保护路由与首页重定向。
- Modify `frontend/src/pages/Login.tsx` — 登录优先跳转工具中心。
- Modify `frontend/src/components/layout/Header.tsx` — 工具中心入口与“工具管理”管理菜单。

### Tests

- Create `backend/tests/test_tool_registry.py` — 目录可见性、CRUD、白名单和默认种子。
- Create `backend/tests/test_tool_runs.py` — 运行权限、任务归属、文件路径、安全下载和状态迁移。
- Create `backend/tests/test_ecommerce_data_fill_runtime.py` — 三种模式对固定测试工作簿的运行契约。
- Create `frontend/src/pages/ToolCenter.test.tsx`、`AdminTools.test.tsx`、`EcommerceDataFill.test.tsx`（若项目未配置 React 测试运行器，则在 Task 9 中先最小化配置 Vitest；否则只增加现有模式要求的测试）。

## Task 1: 数据模型、迁移和权限种子

**Files:**
- Create: `backend/app/models/tool.py`
- Create: `backend/app/models/tool_run.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/permission_constants.py`
- Modify: `backend/app/core/database.py`
- Create: `backend/alembic/versions/20260727_add_tools_and_tool_runs.py`
- Test: `backend/tests/test_tool_registry.py`

**Interfaces:**
- Produces: `Tool`, `ToolRun`, `TOOL_MANAGE_PERMISSION = "tool.manage"`, `ECOMMERCE_DATA_FILL_PERMISSION = "finance.ecommerce_data_fill"`.
- Consumes: existing `Permission`, `GroupPermission`, `User`, `get_user_permissions()` and `_seed_default_permissions()`.

- [ ] **Step 1: Write failing seed and model tests**

```python
def test_default_seed_creates_finance_tool_permissions_and_tool():
    db = make_session()
    _seed_default_groups(db)
    _seed_default_permissions(db)
    seed_default_tools(db)
    assert db.query(Permission).filter_by(permission_key="tool.manage").one()
    assert db.query(Permission).filter_by(permission_key="finance.ecommerce_data_fill").one()
    tool = db.query(Tool).filter_by(tool_key="ecommerce_data_fill").one()
    assert tool.route_path == "/tools/ecommerce-data-fill"
    assert tool.permission_key == "finance.ecommerce_data_fill"
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `py -m pytest tests/test_tool_registry.py::test_default_seed_creates_finance_tool_permissions_and_tool -v`

Expected: FAIL because `Tool`, `seed_default_tools`, and permission definitions do not exist.

- [ ] **Step 3: Create `Tool` and `ToolRun` models**

```python
class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="通用工具")
    icon_key: Mapped[str] = mapped_column(String(64), nullable=False, default="tool")
    route_path: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    permission_key: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

`ToolRun` stores `tool_key`, `created_by`, `status`, `parameters`, `input_files`, `output_files`, `error_message`, `started_at`, `completed_at`, `created_at`, and `updated_at`. Use SQLAlchemy `JSON` for the three JSON fields and `ForeignKey("users.id")` for `created_by`.

- [ ] **Step 4: Add migration and idempotent defaults**

Add the two permission definitions and `GROUP_PERMISSION_KEYS` assignments: `tool.manage` only for total office/IT; `finance.ecommerce_data_fill` for finance/total office/IT. Add `/tools`, `/tools/ecommerce-data-fill`, `/admin/tools` to route definitions. In `seed_default_tools(db)`, seed existing built-in tool cards and `ecommerce_data_fill` using upsert-by-`tool_key`; do not delete administrator-created rows.

- [ ] **Step 5: Run model/seed tests**

Run: `py -m pytest tests/test_tool_registry.py -v`

Expected: PASS, including rerunning seeds without duplicate rows.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models backend/app/core/permission_constants.py backend/app/core/database.py backend/alembic/versions backend/tests/test_tool_registry.py
git commit -m "feat: add tool registry data model"
```

## Task 2: 受控工具目录服务和管理 API

**Files:**
- Create: `backend/app/schemas/tool.py`
- Create: `backend/app/services/tool_registry_service.py`
- Create: `backend/app/api/admin_tools.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_tool_registry.py`

**Interfaces:**
- Consumes: `Tool`, `ToolCreateRequest`, `ToolUpdateRequest`, `get_current_super_admin()`.
- Produces: `list_visible_tools(db, user_id)`, `create_tool(db, payload)`, `update_tool(db, tool_key, payload)`, `/api/tools`, `/api/admin/tools` APIs.

- [ ] **Step 1: Add failing authorization and allowlist tests**

```python
def test_non_manager_cannot_create_tool(client, finance_headers):
    response = client.post("/api/admin/tools", headers=finance_headers, json=valid_tool_payload())
    assert response.status_code == 403

def test_admin_cannot_register_external_or_unknown_route(client, management_headers):
    payload = valid_tool_payload(route_path="https://example.com")
    assert client.post("/api/admin/tools", headers=management_headers, json=payload).status_code == 422
```

- [ ] **Step 2: Verify the tests fail**

Run: `py -m pytest tests/test_tool_registry.py::test_non_manager_cannot_create_tool tests/test_tool_registry.py::test_admin_cannot_register_external_or_unknown_route -v`

Expected: FAIL because the admin tools API does not exist.

- [ ] **Step 3: Implement registry contracts and service**

Use these fixed registrations inside `tool_registry_service.py`:

```python
ALLOWED_TOOL_ENTRIES = {
    "ai_create": {"route_path": "/", "permission_key": "ai.generate"},
    "customer_service": {"route_path": "/customer-service", "permission_key": "ai.customer_service"},
    "product_management": {"route_path": "/products", "permission_key": "product.read"},
    "asset_library": {"route_path": "/assets", "permission_key": "product.read"},
    "ecommerce_data_fill": {
        "route_path": "/tools/ecommerce-data-fill",
        "permission_key": "finance.ecommerce_data_fill",
    },
}
```

`ToolCreateRequest` accepts only `tool_key`, display fields, `is_enabled`, and `sort_order`; it does not accept free-form route, permission, URL, executable or command fields. The service derives route and permission from `ALLOWED_TOOL_ENTRIES`, rejects unknown keys, and preserves immutable execution fields during update.

- [ ] **Step 4: Implement endpoints and logging**

Implement `GET /api/tools` for the current user's enabled, permitted cards. Implement `GET/POST/PUT /api/admin/tools` with `get_current_super_admin`. Call `operation_log_service.log_operation` for create/update/enable/disable events using the same request metadata conventions as existing admin APIs.

- [ ] **Step 5: Run focused tests**

Run: `py -m pytest tests/test_tool_registry.py -v`

Expected: PASS for manager-only mutation, immutable route/permission, enabled filtering and per-user visibility.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/tool.py backend/app/services/tool_registry_service.py backend/app/api/admin_tools.py backend/app/main.py backend/tests/test_tool_registry.py
git commit -m "feat: add managed tool directory API"
```

## Task 3: 工具运行、隔离存储和受鉴权下载

**Files:**
- Create: `backend/app/schemas/tool.py` additions
- Create: `backend/app/services/tool_run_service.py`
- Create: `backend/app/api/tools.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_tool_runs.py`

**Interfaces:**
- Consumes: `Tool`, `ToolRun`, `require_permission("finance.ecommerce_data_fill")`, `settings.UPLOAD_DIR`.
- Produces: `create_run`, `get_run_for_user`, `transition_run`, `save_run_upload`, `resolve_run_file`, `GET/POST /api/tools/ecommerce-data-fill/runs`.

- [ ] **Step 1: Write failing run ownership and path safety tests**

```python
def test_other_finance_user_cannot_read_or_download_run(client, owner_headers, other_finance_headers):
    run = create_run_as_owner(client, owner_headers)
    assert client.get(f"/api/tools/ecommerce-data-fill/runs/{run['id']}", headers=other_finance_headers).status_code == 403

def test_run_file_resolution_rejects_path_escape(tmp_path):
    with pytest.raises(HTTPException, match="Invalid run file"):
        resolve_run_file(tmp_path, "../../.env")
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `py -m pytest tests/test_tool_runs.py -v`

Expected: FAIL because run APIs and storage service are absent.

- [ ] **Step 3: Implement run service**

Use one run root per UUID:

```python
run_root = Path(settings.UPLOAD_DIR).resolve() / "tool-runs" / run_id
input_dir = run_root / "input"
output_dir = run_root / "output"
```

Ensure every resolved input/output file remains a descendant of `run_root`; save upload bytes using generated UUID names, retain the original display name in `input_files`, allow only lower-case `.xlsx`, and reject zero-byte or over-limit uploads before database commit. Keep `ToolRun.status` transitions constrained to `queued -> running -> succeeded|failed`.

- [ ] **Step 4: Implement user APIs**

`POST /runs` accepts `mode`, parameters and `files[]`, creates a queued run, saves input files and dispatches a Celery task after commit. `GET /runs` returns the current user's runs unless management filters by `user_id`. Detail and download endpoints require both tool permission and run ownership/management membership. Downloads use `FileResponse` with the stored display name and log the event.

- [ ] **Step 5: Run security and lifecycle tests**

Run: `py -m pytest tests/test_tool_runs.py -v`

Expected: PASS for permission denial, owner isolation, management audit, path escape rejection, file extension rejection, status transitions and logged download.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/tool.py backend/app/services/tool_run_service.py backend/app/api/tools.py backend/app/main.py backend/tests/test_tool_runs.py
git commit -m "feat: add secure tool run workflow"
```

## Task 4: 移植 v1.0.35 Excel 核心并建立运行适配器

**Files:**
- Create: `backend/app/tool_runtimes/ecommerce_data_fill/__init__.py`
- Create: `backend/app/tool_runtimes/ecommerce_data_fill/runner.py`
- Create: `backend/app/tool_runtimes/ecommerce_data_fill/core/` from `C:\Users\wnt\Desktop\电商数据分析表自动填写工具` non-GUI source modules
- Create: `backend/tests/test_ecommerce_data_fill_runtime.py`
- Modify: `backend/requirements.txt` only if the source import requires a dependency not already present

**Interfaces:**
- Produces: `run_ecommerce_data_fill(mode: Literal["ecommerce", "kepule", "amazon"], input_dir: Path, output_dir: Path, parameters: dict[str, str]) -> list[RunOutput]`.
- Consumes: source `run_ecommerce_fill`, `run_kepule_fill`, `run_amazon_inventory_fill`; no `tkinter`, `windnd`, `gui_*`, `app_paths.app_base_dir()` desktop side effects.

- [ ] **Step 1: Write failing mode dispatch tests**

```python
@pytest.mark.parametrize("mode", ["ecommerce", "kepule", "amazon"])
def test_runner_returns_only_files_under_output_dir(mode, fixture_input_dir, tmp_path):
    outputs = run_ecommerce_data_fill(mode, fixture_input_dir(mode), tmp_path, fixture_parameters(mode))
    assert outputs
    assert all(item.path.is_file() and tmp_path.resolve() in item.path.resolve().parents for item in outputs)
```

- [ ] **Step 2: Run runtime tests and verify failure**

Run: `py -m pytest tests/test_ecommerce_data_fill_runtime.py -v`

Expected: FAIL because the runtime package is absent.

- [ ] **Step 3: Copy only reusable source modules and normalize imports**

Copy `amazon_inventory.py`, `date_rules.py`, `excel_utils.py`, `file_scanner.py`, `models.py`, `reports.py`, `role_detector.py`, `runtime.py`, `shop_mapping.py`, `source_builders.py`, `validators.py`, `workbook_copier.py`, `fillers/`, configuration YAML files, and the non-GUI orchestration functions. Exclude `gui_window.py`, `gui_*`, `windnd`, PyInstaller spec files, `dist/`, `build/`, input/output/log folders, and desktop EXE.

Place source package imports under `app.tool_runtimes.ecommerce_data_fill.core`. Replace desktop base/config path discovery with explicit `input_dir`, `output_dir`, and a packaged `config_dir`. Ensure the runner closes every workbook on exception and converts business exceptions to a structured `ToolRuntimeError` containing a safe user-facing message.

- [ ] **Step 4: Implement the mode dispatcher**

```python
RUNNERS = {
    "ecommerce": run_ecommerce_fill,
    "kepule": run_kepule_fill,
    "amazon": run_amazon_inventory_fill,
}

def run_ecommerce_data_fill(mode, input_dir, output_dir, parameters):
    if mode not in RUNNERS:
        raise ToolRuntimeError("不支持的填表模式")
    RUNNERS[mode](str(input_dir), str(output_dir), **parameters)
    return collect_output_files(output_dir)
```

Only return expected `.xlsx` and `.txt` artifacts from the generated output directory; never expose logs outside the run directory.

- [ ] **Step 5: Run fixture-based runtime tests**

Run: `py -m pytest tests/test_ecommerce_data_fill_runtime.py -v`

Expected: PASS for the three modes, output containment and invalid-mode rejection. Manually compare one representative output from each mode against v1.0.35 desktop output using the existing source project's audit scripts.

- [ ] **Step 6: Commit**

```bash
git add backend/app/tool_runtimes backend/tests/test_ecommerce_data_fill_runtime.py backend/requirements.txt
git commit -m "feat: add ecommerce data fill runtime"
```

## Task 5: Celery execution and operation logging

**Files:**
- Create: `backend/app/tasks/tool_runs.py`
- Modify: `backend/app/tasks/__init__.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/tool_run_service.py`
- Test: `backend/tests/test_tool_runs.py`

**Interfaces:**
- Consumes: `ToolRun`, `run_ecommerce_data_fill`, `SessionLocal`, `operation_log_service`.
- Produces: Celery task `run_ecommerce_data_fill_tool_run(run_id: str)`.

- [ ] **Step 1: Add a failing success/failure task test**

```python
def test_celery_task_marks_run_succeeded_and_records_outputs(db, queued_run, monkeypatch):
    monkeypatch.setattr(tool_runs, "run_ecommerce_data_fill", fake_successful_runner)
    tool_runs.run_ecommerce_data_fill_tool_run.run(queued_run.id)
    refreshed = db.get(ToolRun, queued_run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.output_files[0]["display_name"] == "结果.xlsx"
```

- [ ] **Step 2: Verify task tests fail**

Run: `py -m pytest tests/test_tool_runs.py -k "celery or task" -v`

Expected: FAIL because the task does not exist.

- [ ] **Step 3: Implement the task with explicit status handling**

The task loads the run in a fresh DB session, atomically moves `queued` to `running`, invokes the runner using the persisted parameters, persists sanitized output metadata, then marks `succeeded`. Catch `ToolRuntimeError` and unexpected exceptions separately; record a safe error summary, mark `failed`, and write `tool_run_failed` operation log events. Do not retain raw tracebacks in API responses.

- [ ] **Step 4: Run task tests**

Run: `py -m pytest tests/test_tool_runs.py -v`

Expected: PASS for queued/success/failure transitions and operation logs.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks backend/app/services/tool_run_service.py backend/app/main.py backend/tests/test_tool_runs.py
git commit -m "feat: run spreadsheet tools in celery"
```

## Task 6: 前端 API 类型、工具中心和登录入口

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Create: `frontend/src/pages/ToolCenter.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Test: `frontend/src/pages/ToolCenter.test.tsx` or build-only verification if Task 9 determines test runner is absent

**Interfaces:**
- Consumes: `api.tools.list() -> Promise<ToolCard[]>`, `useAuthStore`, route `/tools`.
- Produces: `ToolCard`, `ToolRun`, user default route `/tools`.

- [ ] **Step 1: Add a failing ToolCenter rendering test (or configure Vitest first if absent)**

```tsx
it('renders only tools returned for the signed-in user', async () => {
  mockToolsList.mockResolvedValue([{ tool_key: 'ecommerce_data_fill', name: '电商数据自动填表', route_path: '/tools/ecommerce-data-fill' }])
  render(<ToolCenter />)
  expect(await screen.findByText('电商数据自动填表')).toBeInTheDocument()
  expect(screen.queryByText('未授权工具')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test and verify failure**

Run: `npm run test -- ToolCenter.test.tsx`

Expected: FAIL because the page/API type does not exist, or because a test runner has not been configured.

- [ ] **Step 3: Implement typed API and ToolCenter**

Add `ToolCard`, `ToolRunStatus`, `ToolRunFile`, and `ToolRun` types. Add `api.tools.list`, `api.tools.listRuns`, `api.tools.getRun`, `api.tools.createEcommerceDataFillRun`, and `api.tools.downloadRunFile`; multipart requests must preserve the authorization header from the shared request helper. `ToolCenter` groups cards by category, shows an empty-state message when no tools are returned, and navigates only to `route_path` from the API.

- [ ] **Step 4: Move default navigation to the platform**

Add a permission-protected `/tools` route that requires only authentication because the API itself filters cards. Add lazy-loaded `ToolCenter` and make login navigate to `/tools` for every signed-in user. Keep existing direct routes. Update header navigation with a “工具中心” item and make the brand/home route `/tools`; preserve existing individual business entries for backward compatibility.

- [ ] **Step 5: Run focused frontend verification**

Run: `npm run test -- ToolCenter.test.tsx` and `npm run build`

Expected: ToolCenter test PASS (if configured) and production build PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/services/api.ts frontend/src/pages/ToolCenter.tsx frontend/src/App.tsx frontend/src/pages/Login.tsx frontend/src/components/layout/Header.tsx frontend/src/pages/ToolCenter.test.tsx frontend/package.json
git commit -m "feat: add unified tool center"
```

## Task 7: 管理端工具目录页面

**Files:**
- Create: `frontend/src/pages/AdminTools.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/services/api.ts`
- Test: `frontend/src/pages/AdminTools.test.tsx` or configured equivalent

**Interfaces:**
- Consumes: `api.adminTools.list/create/update`, `isManagement`.
- Produces: `/admin/tools` page and management menu entry.

- [ ] **Step 1: Write failing manager UI test**

```tsx
it('does not offer arbitrary route or command fields', async () => {
  render(<AdminTools />)
  await screen.findByText('工具管理')
  expect(screen.getByLabelText('工具编码')).toBeInTheDocument()
  expect(screen.queryByLabelText(/命令|脚本|外部地址/)).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run test and verify failure**

Run: `npm run test -- AdminTools.test.tsx`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement management page**

Build a table/card list with create and edit dialogs. The form allows only allowlisted `tool_key` selection plus name, description, category, icon, enabled flag and sort order. Show server-derived route and permission read-only after selecting a tool key. Include enable/disable control, save feedback and API error text. Route guard requires `isManagement`; backend remains authoritative.

- [ ] **Step 4: Run page test and build**

Run: `npm run test -- AdminTools.test.tsx` and `npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminTools.tsx frontend/src/App.tsx frontend/src/components/layout/Header.tsx frontend/src/services/api.ts frontend/src/pages/AdminTools.test.tsx
git commit -m "feat: add tool management page"
```

## Task 8: 电商自动填表页面与任务体验

**Files:**
- Create: `frontend/src/pages/EcommerceDataFill.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/services/api.ts`
- Test: `frontend/src/pages/EcommerceDataFill.test.tsx` or configured equivalent

**Interfaces:**
- Consumes: `api.tools.createEcommerceDataFillRun`, `api.tools.getRun`, `api.tools.downloadRunFile`.
- Produces: `/tools/ecommerce-data-fill` UI supporting `ecommerce`, `kepule`, `amazon` modes.

- [ ] **Step 1: Write failing three-mode submission test**

```tsx
it.each(['ecommerce', 'kepule', 'amazon'] as const)('submits %s mode with selected files', async (mode) => {
  render(<EcommerceDataFill />)
  await userEvent.click(screen.getByRole('button', { name: MODE_LABELS[mode] }))
  await userEvent.upload(screen.getByLabelText('上传 Excel 文件'), new File(['xlsx'], 'source.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
  await userEvent.click(screen.getByRole('button', { name: '开始处理' }))
  expect(mockCreateRun).toHaveBeenCalledWith(expect.objectContaining({ mode }))
})
```

- [ ] **Step 2: Run test and verify failure**

Run: `npm run test -- EcommerceDataFill.test.tsx`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement mode-specific form and polling**

Use explicit mode definitions with title, explanation and only fields required by the v1.0.35 function signatures. Validate at least one `.xlsx` before submit; backend performs authoritative validation. Submit `FormData`, show queued/running/succeeded/failed state, poll only while queued/running, cancel polling on unmount, and show files from `output_files` as download buttons. Do not render raw exception text.

- [ ] **Step 4: Run page test and production build**

Run: `npm run test -- EcommerceDataFill.test.tsx` and `npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/EcommerceDataFill.tsx frontend/src/App.tsx frontend/src/services/api.ts frontend/src/pages/EcommerceDataFill.test.tsx
git commit -m "feat: add ecommerce data fill tool page"
```

## Task 9: 前端测试运行器（条件任务）

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Test: the three page test files from Tasks 6–8

**Interfaces:**
- Produces: `npm run test` command using Vitest, jsdom and Testing Library.

- [ ] **Step 1: Confirm whether a test runner already exists**

Run: `npm run`

Expected: If `test` is absent, proceed with this task; if present, do not add duplicate configuration and adapt Tasks 6–8 to it.

- [ ] **Step 2: Add failing smoke test configuration**

Create `frontend/src/test/setup.ts` importing `@testing-library/jest-dom`; add a one-line page render test. Add `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, and `@testing-library/jest-dom` as development dependencies.

- [ ] **Step 3: Run smoke test to verify red state**

Run: `npm run test -- ToolCenter.test.tsx`

Expected: FAIL until test environment/globals are fully configured.

- [ ] **Step 4: Configure and verify tests**

Configure `environment: 'jsdom'`, `setupFiles: ['./src/test/setup.ts']`, and React plugin in `vitest.config.ts`; add `"test": "vitest run"` to scripts. Ensure the page tests mock API calls and router context rather than making network requests.

- [ ] **Step 5: Run all frontend feature tests and build**

Run: `npm run test` and `npm run build`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test frontend/src/pages/*.test.tsx
git commit -m "test: add frontend tool platform coverage"
```

## Task 10: 端到端验证、Graphify 更新和文档

**Files:**
- Modify: `README.md` or `README-start.md` only if startup/API documentation needs a new tools section.
- Modify: `docs/permissions.md` with new tool permissions and access behavior.
- Update (untracked external graph workspace): `D:\CaiYan\Image-Generation-feature-v5-graphify\graphify-out/`.

**Interfaces:**
- Consumes: complete backend/frontend implementation.
- Produces: documented department-to-tool mapping and verified developer handoff.

- [ ] **Step 1: Run focused backend suite**

Run: `py -m pytest tests/test_tool_registry.py tests/test_tool_runs.py tests/test_ecommerce_data_fill_runtime.py -v`

Expected: PASS.

- [ ] **Step 2: Run broader backend regression excluding known external fixture blocker**

Run: `py -m pytest tests -q --ignore=tests/test_full_regression_runner.py`

Expected: PASS, or record each failure with proof that it predates this branch before deciding whether it is in scope.

- [ ] **Step 3: Run frontend verification**

Run: `npm run test` and `npm run build`

Expected: PASS. Run `npm run lint` as an informational check and distinguish the pre-existing `AssetLibrary.tsx` error from any new lint failures.

- [ ] **Step 4: Manual authorization smoke test in development environment**

Start only development services (`start-dev.bat` or equivalent dev commands). Verify with a finance user that `/tools` shows the spreadsheet card and can create/download its own run; verify a non-finance user cannot see or call it; verify IT/total office can manage tools and inspect runs. Do not start production services.

- [ ] **Step 5: Update Graphify after code changes**

Run from `D:\CaiYan\Image-Generation-feature-v5-graphify`:

```powershell
graphify update . --no-cluster
graphify cluster-only . --no-label
```

Inspect the affected permissions, tools, task and file-access communities. Do not commit `graphify-out/` or `.graphifyignore` to the application repository.

- [ ] **Step 6: Update permissions documentation and commit**

Document `tool.manage`, `finance.ecommerce_data_fill`, tool-center visibility and owner/management download rules. Then commit only product code/tests/docs:

```bash
git add backend frontend docs README.md README-start.md
git commit -m "docs: document unified tool platform access"
```

## Plan Self-Review

- Spec coverage: Tasks 1–2 implement the controlled directory and RBAC; Tasks 3 and 5 provide isolated upload/background/download lifecycle; Task 4 preserves all three v1.0.35 flows; Tasks 6–8 implement user and management UI; Task 10 verifies, documents and updates Graphify.
- Placeholder scan: no unfinished markers or deferred implementation steps; the only conditional branch is Task 9, which explicitly checks whether a frontend test runner already exists before adding one.
- Type consistency: tool keys use `ecommerce_data_fill`; its permission is always `finance.ecommerce_data_fill`; run states are always `queued`, `running`, `succeeded`, `failed`; route is always `/tools/ecommerce-data-fill`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-27-unified-tool-platform.md`.

Two execution options:

1. Subagent-Driven (recommended) — dispatch a fresh implementer per task and review between tasks.
2. Inline Execution — execute the tasks in this session using the execution-plan workflow, with checkpoints.

Choose one option before implementation starts.
