# Graphify Development Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Install Graphify as an isolated, local-first Codex development assistant and build a verified knowledge graph for the committed \`dev\` snapshot without affecting application runtimes or production.

**Architecture:** Graphify is a user-level \`uv\` tool, not an application dependency. A detached worktree based on \`dev\` holds the generated graph and a local ignore file; the actual \`dev\` worktree receives only a Codex workflow rule pointing to the dedicated graph.

**Tech Stack:** Windows PowerShell, Git worktrees, Python 3.10, uv, Graphify 0.9.20, Codex \`AGENTS.md\`.

## Global Constraints

- Perform repository writes only in \`D:\\CaiYan\\Image-n065-audit\` on \`dev\`; never modify \`D:\\CaiYan\\Image-Generation-feature-v5\` on \`master\`.
- Do not modify application dependencies, Docker files, service scripts, ports, databases, Redis, Celery, or production configuration.
- Install exactly \`graphifyy==0.9.20\`; do not install Git hooks, a file watcher, an LLM extraction backend, or an API key.
- Create the detached analysis worktree at \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\` from committed \`dev\`.
- Exclude environment files, uploads, logs, reports, product QA documents, dependency directories, and generated artifacts.
- The graph aids navigation and impact review; source files and tests remain authoritative.

---

### Task 1: Install and validate Graphify

**Files:**
- Create: user-level uv tool environment for \`graphifyy==0.9.20\`
- Test: \`graphify\` command-line checks

**Interfaces:**
- Consumes: installed \`uv\` and Python 3.10.
- Produces: a \`graphify\` command reporting version 0.9.20 and a user-level Codex skill.

- [ ] **Step 1: Install the pinned CLI**

Run:

\`\`\`powershell
uv tool install graphifyy==0.9.20
\`\`\`

Expected: uv reports that it installed the \`graphify\` executable.

- [ ] **Step 2: Verify CLI and install the Codex skill**

Run:

\`\`\`powershell
graphify --version
graphify install --platform codex
\`\`\`

Expected: version is \`graphify 0.9.20\`; installation reports a user-level Codex skill and does not modify project files.

- [ ] **Step 3: Confirm application runtime files are unchanged**

Run:

\`\`\`powershell
git -C 'D:\\CaiYan\\Image-n065-audit' status --short -- backend/requirements.txt frontend/package.json docker-compose.yml start-dev.bat start-prod.bat
\`\`\`

Expected: no output.

### Task 2: Create an isolated, excluded analysis snapshot

**Files:**
- Create: \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\.graphifyignore\`
- Create: \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\\graph.json\`
- Create: \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\\GRAPH_REPORT.md\`
- Create: \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\\graph.html\`
- Test: Git worktree status, source exclusions, Graphify lookups

**Interfaces:**
- Consumes: committed \`dev\` at \`D:\\CaiYan\\Image-n065-audit\`.
- Produces: a detached source snapshot and a local AST graph not mixed with active changes.

- [ ] **Step 1: Assert the target is absent and create detached snapshot**

Run:

\`\`\`powershell
git -C 'D:\\CaiYan\\Image-n065-audit' worktree list --porcelain
git -C 'D:\\CaiYan\\Image-n065-audit' worktree add --detach 'D:\\CaiYan\\Image-Generation-feature-v5-graphify' dev
git -C 'D:\\CaiYan\\Image-Generation-feature-v5-graphify' status --short --branch
\`\`\`

Expected: the target path did not exist before; afterwards the new worktree is detached and clean.

- [ ] **Step 2: Create local-only exclusions**

Create \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\.graphifyignore\` with exactly:

\`\`\`gitignore
.env
.env.*
backend/.env
backend/.env.*
uploads/
uploads_dev/
backend/uploads/
backend/uploads_dev/
logs/
backend/logs/
reports/
产品QA库/
产品库元数据.xlsx
**/node_modules/
**/__pycache__/
dist/
build/
graphify-out/
*.log
*.out
*.err
*.pid
*.tmp
*.xlsx
*.docx
\`\`\`

Expected: the file remains untracked and is never added to Git.

- [ ] **Step 3: Build the local-first graph**

Run:

\`\`\`powershell
Set-Location 'D:\\CaiYan\\Image-Generation-feature-v5-graphify'
graphify extract . --no-gitignore --no-cluster
Get-Item '.\\graphify-out\\graph.json', '.\\graphify-out\\GRAPH_REPORT.md', '.\\graphify-out\\graph.html' | Select-Object Name,Length
\`\`\`

Expected: all three files exist with a non-zero length; Graphify does not request an API key.

- [ ] **Step 4: Validate exclusions and query availability**

Run:

\`\`\`powershell
$graph = Get-Content -Raw '.\\graphify-out\\graph.json'
@('backend/.env', 'uploads_dev/', '产品QA库/', 'node_modules/', '.xlsx', '.docx') | ForEach-Object {
  if ($graph.Contains($_)) { throw "Excluded path found in graph: $_" }
}
graphify explain 'FastAPI'
graphify explain 'CustomerService'
\`\`\`

Expected: no excluded path is found and both explain commands return a node or nearest-match result.

### Task 3: Persist the default Codex graph-review workflow

**Files:**
- Modify: \`D:\\CaiYan\\Image-n065-audit\\AGENTS.md\`
- Test: targeted Git diff and Graphify-update command

**Interfaces:**
- Consumes: verified graph at \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\`.
- Produces: default graph navigation before changes and graph refresh/impact checking after changes.

- [ ] **Step 1: Append this section after the existing environment table**

\`\`\`markdown
## Graphify 开发辅助（默认）

- 代码改动前，先读取 \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\\GRAPH_REPORT.md\` 或使用 \`graphify\` 查询图谱，确认受影响模块与调用关系。
- 代码改动后，在 \`D:\\CaiYan\\Image-Generation-feature-v5-graphify\` 执行 \`graphify update . --no-cluster\`，再检查受影响社区和关键路径。
- 图谱用于减少重复检索并辅助影响分析；涉及安全、数据库迁移、发布或测试失败时，仍必须核对源代码、迁移脚本和测试结果。
- 用户明确要求“跳过图谱”或“快速修改”时，可跳过本节流程。
- 不运行 \`graphify hook install\`、\`graphify watch\`、\`graphify codex install\`，且不将 \`graphify-out/\` 或 \`.graphifyignore\` 提交到本项目。
\`\`\`

- [ ] **Step 2: Verify and commit only the workflow rule**

Run:

\`\`\`powershell
git -C 'D:\\CaiYan\\Image-n065-audit' diff --check -- AGENTS.md
git -C 'D:\\CaiYan\\Image-n065-audit' add AGENTS.md
git -C 'D:\\CaiYan\\Image-n065-audit' commit --only -m 'docs: add Graphify development review workflow' -- AGENTS.md
\`\`\`

Expected: no whitespace errors; the commit contains only \`AGENTS.md\`.

### Task 4: Verify operational isolation

**Files:**
- Test: graph report, persistent rule, dev status, and update command

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: evidence that Graphify is ready for default development use with no production impact.

- [ ] **Step 1: Confirm the graph and workflow are readable**

Run:

\`\`\`powershell
graphify --version
Get-Content 'D:\\CaiYan\\Image-Generation-feature-v5-graphify\\graphify-out\\GRAPH_REPORT.md' -TotalCount 40
Get-Content 'D:\\CaiYan\\Image-n065-audit\\AGENTS.md' | Select-String -Pattern 'Graphify 开发辅助' -Context 0,6
\`\`\`

Expected: version 0.9.20, a readable graph report, and the five workflow rules.

- [ ] **Step 2: Refresh once without a watcher and check runtime isolation**

Run:

\`\`\`powershell
Set-Location 'D:\\CaiYan\\Image-Generation-feature-v5-graphify'
graphify update . --no-cluster
git -C 'D:\\CaiYan\\Image-n065-audit' status --short -- backend/requirements.txt frontend/package.json docker-compose.yml start-dev.bat start-prod.bat
\`\`\`

Expected: the graph refreshes without an API key, hook, watcher, or app restart; the final Git status command has no output.

- [ ] **Step 3: Record regular maintenance command**

Run:

\`\`\`powershell
Set-Location 'D:\\CaiYan\\Image-Generation-feature-v5-graphify'
graphify update . --no-cluster
\`\`\`

Expected: after stable dev changes are committed, this updates only the detached analysis graph.

