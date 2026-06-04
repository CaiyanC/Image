# AI Tool Docker 部署方案

## 决策汇总

| # | 问题 | 决策 |
|---|------|------|
| 1 | 部署路径 | 开发阶段 → 本地 Docker 测试 → 内网服务器部署 |
| 2 | 容器拆分 | **A. 双容器**：后端 FastAPI + 前端 Nginx |
| 3 | 数据持久化 | **A. Docker Volume**：`ai_tool_db` + `ai_tool_uploads` |
| 4 | 前端 API 地址 | 改为 `VITE_API_BASE` 环境变量，Docker 内用相对路径 `/api` |
| 5 | 端口映射 | 后端 8000:8000，前端 80:80 |
| 6 | 双模式 | `docker-compose.yml`（生产）+ `docker-compose.dev.yml`（开发热重载） |
| 7 | 前端构建 | **多阶段构建**：Node 构建 → Nginx 托管静态文件 |
| 8 | Python 镜像 | `python:3.12-slim` |

---

## 需要创建/修改的文件

### 新建文件

| 文件 | 说明 |
|------|------|
| `Dockerfile.backend` | 后端 FastAPI 镜像 |
| `Dockerfile.frontend` | 前端多阶段构建镜像 |
| `nginx.conf` | Nginx 配置（反向代理 /api、/uploads） |
| `docker-compose.yml` | 生产模式编排 |
| `docker-compose.dev.yml` | 开发模式编排（热重载） |
| `.dockerignore` | 排除不需要打入镜像的文件 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `frontend/src/services/api.ts` | `BASE_URL` 改为 `import.meta.env.VITE_API_BASE || ''` |
| `backend/app/core/config.py` | `UPLOAD_DIR` 改为从环境变量读取，默认相对路径 `./uploads` |
| `backend/app/core/config.py` | `CORS_ORIGINS` 支持环境变量扩展 |

---

## 架构图

```
┌──────────────────────────────────────────────┐
│                  宿主机 :80                    │
│                      │                        │
│  ┌───────────────────▼────────────────────┐  │
│  │         frontend (nginx:alpine)        │  │
│  │  - 静态文件 /                           │  │
│  │  - /api → proxy_pass backend:8000/api  │  │
│  │  - /uploads → proxy_pass backend:8000  │  │
│  └───────────────────┬────────────────────┘  │
│                      │                        │
│  ┌───────────────────▼────────────────────┐  │
│  │       backend (python:3.12-slim)       │  │
│  │  - uvicorn app.main:app :8000          │  │
│  │  - SQLite /app/data/app.db             │  │
│  │  - 文件存储 /app/data/uploads/          │  │
│  └───────────────────┬────────────────────┘  │
│                      │                        │
│  ┌───────────────────▼────────────────────┐  │
│  │       Docker Volumes (持久化)           │  │
│  │  - 数据卷: /app/data                   │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

---

## 实施步骤

### 步骤 1：修改现有代码适配 Docker 环境
- [ ] `frontend/src/services/api.ts` — BASE_URL 改用 `VITE_API_BASE` 环境变量
- [ ] `backend/app/core/config.py` — UPLOAD_DIR 可配置，CORS_ORIGINS 支持环境变量

### 步骤 2：创建 .dockerignore
- 排除 `node_modules/`, `.git/`, `__pycache__/`, `*.db`, `.env` 等

### 步骤 3：创建 Dockerfile.backend
- 基于 `python:3.12-slim`
- 安装 `requirements.txt` 依赖
- 复制 `backend/` 代码
- 暴露 8000 端口
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

### 步骤 4：创建 Dockerfile.frontend
- 第一阶段：`node:20-alpine` 安装依赖 + `vite build`
- 第二阶段：`nginx:alpine` 复制 dist + nginx.conf

### 步骤 5：创建 nginx.conf
- `/` → 前端静态文件
- `/api/` → 反向代理到 backend:8000/api/
- `/uploads/` → 反向代理到 backend:8000/uploads/

### 步骤 6：创建 docker-compose.yml（生产模式）
- 定义 `backend` + `frontend` 两个 service
- Volume 持久化数据
- 自定义内部网络

### 步骤 7：创建 docker-compose.dev.yml（开发模式）
- 后端挂载源码目录 + `--reload` 热重载
- 前端直接用 Node 镜像跑 `vite dev --host` + HMR
- 端口映射到宿主机方便调试

### 步骤 8：本地验证
- `docker compose build` 构建镜像
- `docker compose up -d` 启动生产模式
- 访问 `http://localhost` 验证功能
- `docker compose -f docker-compose.dev.yml up` 验证开发模式

---

## 项目文件结构（新增文件）

```
e:\trea\AItool\
├── Dockerfile.backend          # 后端镜像
├── Dockerfile.frontend         # 前端多阶段构建
├── nginx.conf                  # Nginx 反向代理配置
├── docker-compose.yml          # 生产模式
├── docker-compose.dev.yml      # 开发模式
├── .dockerignore               # 构建排除规则
├── backend/
├── frontend/
└── ...
```

## 目录规划

```
e:\trea\AItool\
├── backend/          ← 源码目录（挂载到容器 /app）
├── frontend/         ← 源码目录（开发模式挂载）
├── data/             ← Volume 映射目标（可选，Volume 自动管理）
│   ├── app.db
│   └── uploads/
│       ├── images/
│       ├── videos/
│       └── generated/
```
