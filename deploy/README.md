# Production Deployment Notes

本目录用于把当前系统迁移到单台 Linux 服务器或小规模企业内网环境。

## 推荐结构

- PostgreSQL：独立服务，启用 `pgvector` 扩展。
- Backend：`uvicorn app.main:app`，建议由 systemd 管理。
- Frontend：执行 `npm run build` 后，用 Nginx 静态托管 `dist`。
- Uploads：保留 `backend/uploads`，迁移服务器时必须同步。
- Backup：每日备份 PostgreSQL，至少保留 7 到 30 天。

## 上线前检查

1. 复制 `backend/.env.example` 为 `backend/.env`，设置真实 `SECRET_KEY`、`DATABASE_URL`、`DMXAPI_API_KEY`。
2. 后端执行 `pip install -r requirements.txt`。
3. 前端执行 `npm install && npm run build`。
4. PostgreSQL 执行 `CREATE EXTENSION IF NOT EXISTS vector;`。
5. 启动后访问 `/api/health/live` 和 `/api/health/ready`。

## 健康检查语义

- `/api/health/live`：只证明后端进程可响应，适合进程存活探针。
- `/api/health/ready`：检查数据库连接和知识库向量能力，适合负载均衡 readiness。
- `ready.status=degraded`：数据库可用，但向量能力不可用，系统可运行但 RAG 质量会下降。
- HTTP 503：数据库不可用，不应继续接入流量。

## 迁移清单

1. 停止旧服务。
2. 备份 PostgreSQL。
3. 复制代码、`.env`、`backend/uploads`。
4. 新服务器恢复数据库。
5. 安装依赖并构建前端。
6. 启动 backend 和 nginx。
7. 跑健康检查和登录/产品库/客服问答冒烟测试。
