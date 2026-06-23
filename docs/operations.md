# Operations Guide

本文档记录当前 Windows 内网部署的日常运维流程。不要在本文档中写入真实密码、Token 或 API Key。

## 1. 启停流程

### 当前唯一标准

| 环境 | 启动 | 停止 | 后端 | 前端 | 数据库 |
| --- | --- | --- | --- | --- | --- |
| 生产 | `start-prod.bat` | `stop-prod.bat` | `8000` | `5275` | `product_knowledge` |
| 开发 | `start-dev.bat` | `stop-dev.bat` | `8001` | `5276` | `product_knowledge_dev` |

不再使用后端 `8002`，不使用 Vite 默认 `5173` 作为本项目服务端口。不要手动直接运行无 env 的 `uvicorn app.main:app`，除非已经确认当前 shell 指向开发库。

### 启动顺序

生产入口是仓库根目录的 `start-prod.bat`，开发入口是 `start-dev.bat`。`start-all.bat` 仅作为 `start-prod.bat` 的内部兼容脚本保留，日常不要直接使用。

1. 启动 Docker Desktop。
2. 生产双击或执行：

```bat
start-prod.bat
```

开发双击或执行：

```bat
start-dev.bat
```

脚本会按顺序处理：

1. 检查 Docker 是否可用。
2. 检查 Redis 容器 `caiyan-redis`。
   - 不存在则执行 `docker run --name caiyan-redis -p 6379:6379 -d redis:7`。
   - 已存在但停止则执行 `docker start caiyan-redis`。
3. 启动后端。生产固定 `8000`，开发固定 `8001`，由脚本加载对应 env 后执行：

```bat
cd backend
venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT% --timeout-keep-alive 120
```

4. 启动 Celery worker。必须带环境对应的 queue、worker name、pidfile、logfile：

```bat
cd backend
venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo -Q %CELERY_QUEUE% -n %CELERY_WORKER_NAME%@%COMPUTERNAME% --pidfile=..\%LOG_DIR_WIN%\celery.pid --logfile=..\%LOG_DIR_WIN%\celery.log
```

5. 启动前端：

```bat
cd frontend
npm install
npm run dev:prod
```

开发前端使用：

```bat
npm run dev:dev
```

生产前端固定端口是 `5275`，生产后端固定端口是 `8000`。同事访问地址通常是：

```text
http://<内网IP>:5275
```

### 单独启动

不推荐单独手动启动后端或前端。需要只启动某个子进程时，使用当前环境脚本的子命令，例如 `start-prod.bat` 内部调用的 `start-all.bat backend/frontend/worker`，或 `start-dev.bat backend/frontend/worker`。手动启动前必须确认 env、端口和数据库。

### 停止顺序

优先使用：

```bat
stop-prod.bat
stop-dev.bat
```

脚本会停止：

- 生产脚本只处理 `8000`、`5275`、`celery_prod`、`worker_prod`。
- 开发脚本只处理 `8001`、`5276`、`celery_dev`、`worker_dev`。
- 不要泛杀所有 `python`、`node` 或 `celery` 进程。

脚本会询问是否停止 Redis。默认不停止 Redis，避免下次启动变慢；如需停止，回答 `y`。

PostgreSQL 当前是 Windows 服务 `postgresql-x64-18`，通常不随应用启停。需要手动启停时：

```powershell
Get-Service postgresql-x64-18
Start-Service postgresql-x64-18
Stop-Service postgresql-x64-18
```

### 开机/登录自启动

当前通过 Windows 任务计划程序配置登录后自启动任务。自启动只管理生产环境，不自动启动开发环境。

- `CaiYanStartupRedis`：登录后启动 Docker Desktop，并确保 `caiyan-redis` 容器运行。
- `CaiYanStartupBackend`：登录后延迟 1 分钟启动生产后端 `8000`。
- `CaiYanStartupWorker`：登录后延迟 90 秒启动生产 Celery worker，使用 `celery_prod` / `worker_prod`。
- `CaiYanStartupFrontend`：登录后延迟 2 分钟启动生产前端 `5275`。
- `CaiYanHealthCheck`：定时检查生产 Redis、后端、前端和 worker；只重启生产组件。

说明：

- Docker Desktop 是用户会话程序，不是普通 Windows 服务；当前方案是在当前 Windows 用户登录后自动启动 Docker/Redis。
- Redis 任务会先检查 `docker info`。如果 Docker 未就绪，会尝试启动 `Docker Desktop.exe` 并等待 Docker 可用。
- 后端启动前会确认 Redis、PostgreSQL 可用。
- 前端延迟启动，避免后端还未就绪时访问失败。
- 开发环境不设置开机自启。需要开发时手动运行 `start-dev.bat`，停止时运行 `stop-dev.bat`。
- PM2 的 `cc-connect` 和 Docker 的 `new-api` / `LibreChat` 相关容器属于其他项目，本项目运维脚本不管理它们。
- 端口 `8000` orphan 是单独遗留项，需要管理员 PowerShell 专项排查，不由日常自启动任务处理。

生产自启动固定规范：

| 组件 | 端口/队列 | 启动任务 |
| --- | --- | --- |
| Redis | `caiyan-redis` / `6379` | `CaiYanStartupRedis` |
| 后端 | `8000` | `CaiYanStartupBackend` |
| 前端 | `5275` | `CaiYanStartupFrontend` |
| Worker | `celery_prod` / `worker_prod` | `CaiYanStartupWorker` |

查看任务：

```powershell
Get-ScheduledTask -TaskName CaiYanStartupRedis,CaiYanStartupBackend,CaiYanStartupWorker,CaiYanStartupFrontend,CaiYanHealthCheck
```

手动模拟开机启动：

```powershell
Start-ScheduledTask -TaskName CaiYanStartupRedis
Start-ScheduledTask -TaskName CaiYanStartupBackend
Start-ScheduledTask -TaskName CaiYanStartupWorker
Start-ScheduledTask -TaskName CaiYanStartupFrontend
```

自启动和看门狗共用脚本：

```text
deploy\scripts\service_control_windows.ps1
```

该脚本在重新拉起服务前会先检查端口。如果端口被旧进程占用但服务不健康，会清理监听进程及其子进程，等待端口释放后再启动，避免 orphan worker 造成端口冲突。

## 2. 备份/恢复流程

详细流程见 [backup-windows.md](./backup-windows.md)。

当前已配置 Windows 定时任务：

- 任务名：`CaiYanPostgresBackup`
- 账号：`SYSTEM`
- 时间：每天 `03:00`
- 脚本：`deploy\scripts\backup_postgres.ps1`
- 备份目录：`backups\postgres`
- 保留时间：14 天

查看任务：

```powershell
Get-ScheduledTask -TaskName CaiYanPostgresBackup
Get-ScheduledTaskInfo -TaskName CaiYanPostgresBackup
```

手动触发一次：

```powershell
Start-ScheduledTask -TaskName CaiYanPostgresBackup
```

修改备份时间，例如改为每天 02:30：

```powershell
$task = Get-ScheduledTask -TaskName CaiYanPostgresBackup
$trigger = New-ScheduledTaskTrigger -Daily -At 2:30am
Set-ScheduledTask -TaskName CaiYanPostgresBackup -Trigger $trigger
```

修改保留天数，例如改为 30 天，需要修改任务 Action 的参数，给脚本追加 `-RetentionDays 30`。建议先导出现有动作确认：

```powershell
(Get-ScheduledTask -TaskName CaiYanPostgresBackup).Actions
```

然后重新注册或在任务计划程序 GUI 中编辑 Action：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\CaiYan\Image-Generation-feature-v5\deploy\scripts\backup_postgres.ps1 -RetentionDays 30
```

恢复演练必须恢复到测试库先校验，不能直接覆盖生产库。示例：

```powershell
createdb --host localhost --port 5432 --username postgres product_knowledge_restore_check
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\scripts\restore_postgres.ps1 -BackupFile .\backups\postgres\product_knowledge_YYYYMMDD_HHMMSS.dump -TargetDatabase product_knowledge_restore_check
```

## 3. 限流策略

当前后端标准启动脚本使用 4 worker：

```bat
start-prod.bat
```

限流不是进程内计数，而是 Redis 分布式共享计数。所有 worker 使用同一组 Redis key，因此登录、AI 生成、文件签名/上传等限流不会因为 `--workers 4` 被放大。

当前 Redis key 格式：

```text
rate_limit:<scope>:<user_or_ip_key>
```

当前已接入的主要限流：

- 登录/注册：按 `IP + username`，8 次/分钟。
- AI 生成：按用户，15 次/分钟。
- 文件签名：按用户，45 次/分钟。
- 文件上传：按用户，45 次/分钟。

Redis 限流采用 fail-open 策略：

- 如果 Redis 正常，所有 worker 共享限流计数。
- 如果 Redis 不可用，请求不会因为限流组件故障而返回 500。
- Redis 不可用期间，限流会短暂失效，但登录、产品、客服、AI 等核心接口继续可用。
- Redis 恢复后，限流自动恢复。
- Redis 不可用会记录 warning 到 `logs\rate_limit.log`，日志内容包含 `fail open and allow request`。

维护 Redis 时需要注意：

1. 维护窗口内限流会短暂失效。
2. 核心业务请求应继续可用。
3. 维护完成后执行：

```powershell
docker exec caiyan-redis redis-cli ping
```

正常应返回：

```text
PONG
```

4. 可用一次错误密码登录快速验证限流恢复：同一用户名第 9 次应返回 `429`。

## 4. `.env` 密钥和环境变量清单

权限模型和账号分配建议见 [permissions.md](./permissions.md)。

### 后端

- `SECRET_KEY`：JWT 和签名文件 URL 的签名密钥。必须是高强度随机值。
- `DATABASE_URL`：后端连接 PostgreSQL 的 SQLAlchemy 连接串。
- `REDIS_URL`：Celery broker/result backend，当前本地默认 `redis://localhost:6379/0`。
- `DEBUG`：是否启用调试模式。
- `ENABLE_PUBLIC_REGISTRATION`：是否允许公开注册。当前应保持 `false`。
- `ACCESS_TOKEN_EXPIRE_MINUTES`：登录 JWT 有效期。
- `SIGNED_FILE_EXPIRE_SECONDS`：签名文件 URL 有效期，当前默认 600 秒。
- `AI_REQUEST_TIMEOUT_SECONDS`：通用 AI 请求超时。
- `EMBEDDING_REQUEST_TIMEOUT_SECONDS`：embedding 请求超时。
- `AI_MAX_CONCURRENT_REQUESTS`：AI 请求并发上限。
- `DMXAPI_BASE_URL`：DMXAPI 服务地址。
- `DMXAPI_API_KEY`：DMXAPI 图像/视频生成服务密钥。
- `DMXAPI_TXT2IMG_TIMEOUT`：文生图读超时。
- `DMXAPI_IMG2IMG_READ_TIMEOUT`：图生图读超时。
- `DMXAPI_IMG2IMG_CONNECT_TIMEOUT`：图生图连接超时。
- `DASHSCOPE_API_KEY`：阿里云百炼 embedding 服务密钥。
- `DEFAULT_ADMIN_USERNAME`：首次启动自动创建的管理员用户名。
- `DEFAULT_ADMIN_EMAIL`：首次启动自动创建的管理员邮箱。
- `DEFAULT_ADMIN_PASSWORD`：首次启动自动创建的管理员密码。生产环境必须修改。

### Docker/生产示例

- `POSTGRES_USER`：PostgreSQL 用户名。
- `POSTGRES_PASSWORD`：PostgreSQL 密码。
- `POSTGRES_DB`：PostgreSQL 数据库名。
- `WORKERS`：后端 Gunicorn/Uvicorn worker 数。
- `CELERY_CONCURRENCY`：Celery worker 并发数。

### 前端

- `VITE_API_BASE_URL`：前端直接访问后端 API 的基础路径。不设置时默认使用 `/api`。
- `VITE_API_PROXY_TARGET`：Vite dev server `/api` 代理目标，默认 `http://localhost:8000`。
- `VITE_TRACE_CUSTOMER_AGENT`：是否打开客服 agent 前端调试输出。
- `VITE_ENABLE_PUBLIC_REGISTRATION`：是否在登录页展示注册链接。必须和后端 `ENABLE_PUBLIC_REGISTRATION` 保持一致。

### 辅助脚本

- `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`：PostgreSQL 命令行工具使用的连接参数。
- `FRONTEND_BASE_URL`、`CAIYAN_USERNAME`、`CAIYAN_PASSWORD`：前端验证脚本使用的测试地址和账号。
- `CUSTOMER_SERVICE_API_URL`、`CUSTOMER_SERVICE_TOKEN`：客服回归脚本使用的 API 地址和 Token。

## 5. `SECRET_KEY` 轮换说明

`SECRET_KEY` 用于：

- 登录 JWT 签名和验签。
- 文件签名 URL 的 token 签名和验签。

更换影响：

- 所有已登录用户的 JWT 立即失效，需要重新登录。
- 尚未过期的签名文件 URL 立即失效，需要前端重新请求签名 URL。
- 不影响数据库中的用户、产品、历史记录、知识库文件。

轮换步骤：

1. 通知用户会话将失效，选择低峰期。
2. 先确认数据库备份任务最近一次成功。
3. 生成新的高强度随机值，不复用旧值。
4. 修改 `backend\.env` 中的 `SECRET_KEY`。
5. 重启后端服务。当前本地可执行：

```bat
stop-all.bat
start-all.bat
```

6. 验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

7. 让用户重新登录。

## 6. 健康检查方式

### 本地监控告警

Windows 定时任务 `CaiYanHealthCheck` 每 5 分钟执行一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\CaiYan\Image-Generation-feature-v5\deploy\scripts\health_check_windows.ps1
```

脚本检查：

- `GET http://127.0.0.1:8000/api/health/live`
- `GET http://127.0.0.1:8000/api/health/ready`

告警策略：

- 首次发现故障时，通过 `msg.exe` 弹出 Windows 桌面消息。
- 故障期间继续写 `logs\health_check.log`。
- 为避免重复骚扰，同一故障持续期间最多每 30 分钟弹一次提醒。
- 服务恢复后弹一次恢复通知，并把状态改回 healthy。

看门狗策略：

- `CaiYanHealthCheck` 同时承担轻量看门狗职责，不再额外创建一个重复定时任务。
- 如果健康检查发现后端不可用，会调用 `deploy\scripts\service_control_windows.ps1 -Action Watchdog`。
- 看门狗会确认 Redis、PostgreSQL、后端、前端状态。
- 如果后端或前端进程不存在，或端口残留但服务不可用，会先清理旧监听进程和子进程，再重新拉起。
- 看门狗日志写入 `logs\watchdog.log`。

状态文件：

```text
backend\runtime\health_check_state.json
```

查看任务：

```powershell
Get-ScheduledTask -TaskName CaiYanHealthCheck
Get-ScheduledTaskInfo -TaskName CaiYanHealthCheck
```

手动执行一次：

```powershell
Start-ScheduledTask -TaskName CaiYanHealthCheck
```

### 前端

本机：

```powershell
Invoke-WebRequest http://127.0.0.1:5275 -UseBasicParsing
```

内网同事访问：

```text
http://<内网IP>:5275
```

### 后端

进程存活：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
```

就绪检查，包含数据库和向量能力：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

`ready.status=ok` 表示后端和数据库正常，向量能力可用。`ready.status=degraded` 表示数据库可用但向量能力不可用，需要检查 pgvector/知识库向量配置。

### PostgreSQL

服务状态：

```powershell
Get-Service postgresql-x64-18
```

连接检查：

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --host localhost --port 5432 --username postgres --dbname product_knowledge --command "SELECT 1;"
```

### Redis

容器状态：

```powershell
docker ps --filter "name=^/caiyan-redis$"
```

连接检查：

```powershell
docker exec caiyan-redis redis-cli ping
```

正常返回：

```text
PONG
```

限流日志检查：

```powershell
Get-Content .\logs\rate_limit.log -Tail 20
```

### Celery worker

查看进程：

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like '*worker_prod@*' -or
  $_.CommandLine -like '*worker_dev@*' -or
  $_.CommandLine -like '*-Q celery_prod*' -or
  $_.CommandLine -like '*-Q celery_dev*'
} | Select-Object ProcessId, CommandLine
```

知识库文件上传后，worker 日志中应出现 `parse_document` 任务执行记录。

## 7. 日志位置

### 后端

- 运行窗口：`start-all.bat` 打开的 `CaiYan Backend - 8000` 控制台。
- 错误日志：`logs\error.log`，按天轮转，保留 30 天。
- 限流降级日志：`logs\rate_limit.log`，记录 Redis 限流不可用时的 fail-open warning。
- 开发/验证期间可能存在临时日志：`backend\*.out.log`、`backend\*.err.log`。这些是手动验证或临时启动产生的，不是生产依赖。

优先排查顺序：

1. 后端控制台是否有启动失败、数据库连接失败、权限错误。
2. `logs\error.log` 是否有 500 异常栈。
3. 数据库连接和 Redis 连接是否正常。

### Celery worker

- 生产运行窗口：`start-prod.bat` 打开的 `CaiYan Celery Worker` 控制台，日志在 `logs\prod\celery.log`。
- 开发运行窗口：`start-dev.bat` 打开的 `CaiYan Dev Celery Worker` 控制台，日志在 `logs\dev\celery.log`。
- 知识库文件解析失败时优先看 worker 控制台和 `knowledge_parse_tasks` 状态。

### 前端

- 生产运行窗口：`CaiYan Frontend - 5275` 控制台。
- 开发运行窗口：`CaiYan Dev Frontend - 5276` 控制台。
- 浏览器 DevTools Console 和 Network。
- 临时验证日志可能在 `frontend\*.log`。

### Redis

```powershell
docker logs --tail=100 caiyan-redis
```

### PostgreSQL

当前是 Windows PostgreSQL 服务。优先看：

- Windows 服务状态：`Get-Service postgresql-x64-18`
- Windows 事件查看器中的 PostgreSQL 相关事件。
- PostgreSQL 数据目录下的日志目录，具体位置以本机 PostgreSQL 配置为准。

可用 SQL 辅助排查：

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --host localhost --port 5432 --username postgres --dbname product_knowledge --command "SELECT now();"
```

## 8. 已知问题记录

### Windows uvicorn 多进程 orphan worker

现象：

- 生产后端使用 `uvicorn --workers 4`。
- Windows 上关闭父窗口或异常中断后，可能留下 orphan worker。
- 表现为端口 `8000` 仍被占用、旧代码仍在响应、重启后改动不生效，或出现多个 Python 进程。

检测：

```powershell
netstat -ano | findstr ":8000"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn app.main:app*' } | Select-Object ProcessId, ParentProcessId, CommandLine
```

清理：

```powershell
stop-prod.bat
```

如果仍有残留，不要泛杀所有 uvicorn、python、node 或 celery。先记录 PID 和命令行，再按明确 PID 清理：

```powershell
netstat -ano | findstr ":8000"
Get-Process -Id <PID>
wmic process where processid=<PID> get ProcessId,ParentProcessId,Name,CommandLine
taskkill /F /PID <PID>
```

8000 orphan 的处理应作为专项清理执行，避免误伤开发环境或其他项目。

### 文件编码污染：UTF-16LE 被误存为 UTF-8

现象：

- `npm run build` 在 `History.tsx`、`Workspace.tsx` 等文件报大量 `Invalid character`、`Unexpected keyword or identifier`。
- 文件内容显示为类似 `浩潰瑲...` 的乱码。
- `git diff --stat` 可能显示原本几百行的 TSX 文件变成一行大改动。

根因：

- 原始 UTF-8/TSX 内容被错误按 UTF-16LE 解码，再保存为 UTF-8，导致源码字符级污染。

检测方法：

```powershell
npm run build
git diff -- frontend/src/pages/History.tsx frontend/src/pages/Workspace.tsx
git diff --stat -- frontend/src/pages/History.tsx frontend/src/pages/Workspace.tsx
Format-Hex frontend\src\pages\History.tsx -Count 64
```

判断要点：

- 如果大量源码变成不可读 CJK 字符，优先怀疑编码污染。
- 如果 diff 显示整个文件被替换成一行，不能手工局部修几个字符，应从 Git 中恢复干净版本再重放真实业务改动。

修复流程：

1. 确认污染只在工作区，Git 历史中的版本正常。
2. 记录污染前后真实业务改动。
3. 从 HEAD 恢复文件。
4. 重新应用真实业务改动。
5. 运行 `npm run build` 验证生产构建。

注意：不要用“另存为”或编辑器自动猜编码强行覆盖源码；先确认编码和 diff。

## 9. 生产/开发双环境

当前这台机器保留两套独立应用入口：

- 生产环境：后端 `8000`，前端 `5275`，数据库 `product_knowledge`，同事日常使用。
- 开发环境：后端 `8001`，前端 `5276`，数据库 `product_knowledge_dev`，只用于开发调试。

配置文件分开：

- 生产后端：`backend\.env`
- 开发后端：`backend\.env.dev`
- 生产前端：`frontend\.env`
- 开发前端：`frontend\.env.dev`

启动/停止：

```bat
start-prod.bat
stop-prod.bat
start-dev.bat
stop-dev.bat
```

开发环境脚本会显式加载 `backend\.env.dev`，并让前端代理到 `http://localhost:8001`。开发环境 Redis 使用 `redis://localhost:6379/1`，避免和生产 Redis DB0 混用。

首次或需要刷新开发库时，从生产库复制：

```powershell
$env:PGPASSWORD = "<postgres password>"
& "C:\Program Files\PostgreSQL\18\bin\dropdb.exe" --host localhost --port 5432 --username postgres --if-exists product_knowledge_dev
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" --host localhost --port 5432 --username postgres product_knowledge_dev
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" --host localhost --port 5432 --username postgres --format custom --file tmp\product_knowledge_dev_seed.dump product_knowledge
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --host localhost --port 5432 --username postgres --dbname product_knowledge_dev --no-owner tmp\product_knowledge_dev_seed.dump
```

发布注意事项：

1. 先在开发环境 `http://127.0.0.1:5276` 验证功能。
2. 确认改动不依赖开发库里的临时数据。
3. 代码发布到生产前，先备份 `product_knowledge`。
4. 生产发布只更新代码和生产配置，不把 `product_knowledge_dev` 数据覆盖到 `product_knowledge`。
5. 如涉及数据库结构变更，先在开发库验证迁移，再安排低峰期对生产执行。

## 10. 生产/开发环境安全准则

当前方案是“同代码目录、不同配置”的小强隔离：生产和开发共用这一份代码目录，但通过不同 env、端口、数据库、Redis DB、Celery queue、worker name、pidfile、logfile、上传目录和启动脚本隔离。它不是两个物理目录、两套依赖、两套操作系统用户的完全强隔离。

### 固定入口

- 生产启动：`start-prod.bat`
- 生产停止：`stop-prod.bat`
- 开发启动：`start-dev.bat`
- 开发停止：`stop-dev.bat`

`start-prod.bat` / `stop-prod.bat` 是生产环境的明确入口，内部复用现有 `start-all.bat` / `stop-all.bat` 逻辑。日常操作时优先使用带 `prod` 或 `dev` 的脚本名，避免误操作。

### 端口和数据库

| 环境 | 后端 | 前端 | 数据库 | 后端 env | 前端 env | 上传目录 |
| --- | --- | --- | --- | --- | --- | --- |
| 生产 | `8000` | `5275` | `product_knowledge` | `backend\.env` | `frontend\.env` | `backend\uploads` |
| 开发 | `8001` | `5276` | `product_knowledge_dev` | `backend\.env.dev` | `frontend\.env.dev` | `backend\uploads_dev` |

### 运行隔离参数

| 环境 | Redis | Celery queue | Worker name | Worker pidfile | Worker logfile | 后端日志 |
| --- | --- | --- | --- | --- | --- | --- |
| 生产 | `redis://localhost:6379/0` | `celery_prod` | `worker_prod@<COMPUTERNAME>` | `logs\prod\celery.pid` | `logs\prod\celery.log` | `logs\prod\error.log` |
| 开发 | `redis://localhost:6379/1` | `celery_dev` | `worker_dev@<COMPUTERNAME>` | `logs\dev\celery.pid` | `logs\dev\celery.log` | `logs\dev\error.log` |

后端启动时会校验 `APP_ENV`、数据库名和上传目录组合：

- `APP_ENV=prod` 只能连接 `product_knowledge`，不能连接 `product_knowledge_dev`。
- `APP_ENV=dev` 只能连接 `product_knowledge_dev`，不能连接 `product_knowledge`。
- 生产不能使用 `uploads_dev`。
- 开发不能使用 `uploads`。
- Celery queue 和 worker name 必须显式配置；生产只能使用 `celery_prod` / `worker_prod`，开发只能使用 `celery_dev` / `worker_dev`，不允许使用默认 `celery` 队列。
- `APP_ENV` 只能是 `prod` 或 `dev`。

启动日志会打印当前环境、数据库名、上传目录、后端端口、Redis URL、Celery queue、worker name 和日志目录。日志不会打印数据库密码、密钥或 token。

开发环境严禁连接生产库。开发后端必须通过 `start-dev.bat` 启动，或在手动启动前明确确认当前环境变量 `DATABASE_URL` 指向 `product_knowledge_dev`。

不要手动直接运行：

```bat
uvicorn app.main:app
```

除非已经确认当前 shell 的 env 指向开发库。直接在 `backend` 目录启动时，默认会加载 `backend\.env`，存在写入生产库风险。

### 发布到生产

1. 在开发环境 `http://127.0.0.1:5276` 完成功能验证。
2. 确认改动不依赖 `product_knowledge_dev` 中的临时数据。
3. 确认生产配置仍指向 `product_knowledge`，开发配置仍指向 `product_knowledge_dev`。
4. 生产发布使用同一套代码和生产 env，不复制开发库数据到生产库。
5. 发布前运行前端构建和后端相关测试。
6. 低峰期执行 `stop-prod.bat`，更新代码后执行 `start-prod.bat`。
7. 验证 `http://127.0.0.1:8000/api/health/live` 和 `http://127.0.0.1:8000/api/health/ready`。

### 数据库迁移和回滚

数据库结构变更必须先在开发库执行并验证：

1. 备份或刷新 `product_knowledge_dev`。
2. 在 `product_knowledge_dev` 执行迁移。
3. 启动开发环境并完成核心流程验证。
4. 记录迁移命令、影响表、验证结果和回滚方式。

生产迁移必须先备份：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\scripts\backup_postgres.ps1
```

确认备份文件存在后，低峰期执行生产迁移。迁移后立即验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

如果迁移失败且无法通过向前修复解决，按备份恢复流程恢复到新库或原生产库。恢复前先停止生产服务，避免应用继续写入：

```bat
stop-prod.bat
```

恢复备份示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\scripts\restore_postgres.ps1 -BackupFile .\backups\postgres\product_knowledge_YYYYMMDD_HHMMSS.dump -TargetDatabase product_knowledge
```

恢复后执行：

```bat
start-prod.bat
```

并重新验证生产健康检查和核心业务流程。
