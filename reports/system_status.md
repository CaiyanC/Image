# CaiYan 系统最终状态报告

更新时间：2026-06-21  
代码路径：`D:\CaiYan\Image-Generation-feature-v5`  
当前运行链路：前端 `5275` -> 后端 `8000`，后端 `--workers 4`，Redis 分布式限流，PostgreSQL 数据库 `product_knowledge`

## 1. 测试范围与方法说明

本轮测试覆盖智能客服之外的全部主要模块，并对智能客服相关的性能、并发和上下文链路做了补充回归。

覆盖模块：
- 权限/文件安全
- 产品数据库 PMD
- 知识库 CaiYan
- AI 生成模块
- 后台运维
- 跨模块端到端 E2E
- 智能客服核心链路、性能和并发稳定性

测试方法：
- 使用当前真实运行环境 `5275/8000`，不是 mock。
- 使用真实 PostgreSQL、Redis、Celery worker、DashScope embedding、DeepSeek/DashScope 客服链路。
- 涉及上传、解析、签名 URL、备份恢复、前端路由保护、生产构建、定时任务、看门狗的项目均做真实请求或真实系统命令验证。
- 涉及测试数据的场景使用临时 SKU、临时用户、临时知识文档和临时数据库，测试后清理残留。
- AI 图片生成因为当前没有配置可用图片模型 API Key，未强行接入新服务商；只验证到提交生成请求、失败记录、权限和归属隔离。

## 2. 逐模块测试结果汇总

### 权限/文件安全

结论：通过。

已验证：
- `/uploads` 静态直链不可作为公开访问路径使用，旧直链访问返回 403/404。
- 新增 `/api/files/sign` 和 `/api/files/signed/{token}` 签名访问链路，签名 URL 有效期为 10 分钟。
- 产品图片/视频通过签名 URL 展示。
- 知识库文件不走公开签名展示，必须通过知识库管理下载接口。
- 知识库文件下载仅管理组允许，非管理组拒绝。
- AI 生成文件签名校验按生成记录 owner 或管理组判断。
- 文件签名接口已接入 Redis 分布式限流。
- 全局旧路径扫描确认没有新增未签名直链展示路径。

### 产品数据库 PMD

结论：通过。

已验证：
- 草稿创建、发布、产品详情、搜索、高级搜索。
- 产品规格、业务信息、内容、QA、负面词、提示词、媒体、渠道、地区、认证、关键词维护。
- 图片/视频上传、媒体记录维护、签名 URL 访问。
- QA 批量导入、单品向量同步、待同步接口、删除流程。
- `ProductCreate.tsx` 中 `/uploads` 判断是兼容后端存储路径，不直接绕过签名 URL；真实渲染使用 `SecureImage/SecureFile`。
- 生产构建 `npm run build` 通过，生成 `frontend/dist`。

已修复真实 bug：
- `PUT /api/products/{sku}/specs` 更新 `capacity` 等 JSON/list 字段时返回 500。
- 根因：创建流程会序列化结构化字段，更新流程漏了 `capacity`、`size_info`、`technical_advantages` 的统一序列化，PostgreSQL 报 `can't adapt type 'dict'`。
- 修复：`update_product_specs()` 与创建流程保持一致，对结构化字段统一 `_to_json_str()`。
- 验证：真实前端编辑测试产品规格成功保存；详情再次查询数据结构正确；pytest 通过。

记录的非阻塞问题：
- `POST /api/products` 直接创建接口与实际前端使用的“草稿 -> 发布”路径行为不一致，当前主流程不受影响。
- `ProductMedia.tag_list` 直接媒体接口响应仍可能返回 JSON 字符串，详情聚合中会反序列化为数组。
- 已发布产品编辑页当前不直接回显聚合 `media` 数组，不影响规格编辑主路径。

### 知识库 CaiYan

结论：通过。

已验证：
- TXT/PDF/DOCX/XLSX 文件上传。
- Celery 解析任务创建、消费和状态流转。
- 文本切片、DashScope embedding 向量化。
- `search-preview` 检索命中。
- 重复文件处理。
- 产品 SKU 关联。
- 客服模块可检索关联知识。
- 知识库文件下载权限：管理组可下载，非管理组拒绝。
- 级联清理在数据库 FK 层验证通过。

记录的产品缺口：
- 当前没有完整的知识库文档管理 UI/API，用于列表查看、详情管理、删除文档等后台运维动作。
- 本轮删除级联主要通过数据库层验证，不等价于已有完整文档管理功能。

### AI 生成模块

结论：部分通过，核心图片生成能力因配置缺失不可用。

已验证：
- `ai.generate` 权限校验正常，缺少权限返回 403。
- 生成请求接入限流入口。
- 失败生成记录会写入 `generations.user_id`。
- 普通用户只能查看自己的生成历史，非 owner 查询失败记录返回 404。
- 生成失败时不 500、不卡死，返回业务状态 `failed` 和明确错误信息。

当前阻塞性配置缺失：
- `gpt-image-2-ssvip`、`gpt-image-2`、`gemini-3.1-flash-image-preview` 等 image 模型没有配置可用图片生成 API Key。
- 文生图、图生图真实生成无法完成，因此无法验证“生成成功后的资产归属 + 签名 URL 展示”完整链路。

后续待办：
- 登录百炼控制台确认 `DASHSCOPE_API_KEY` 所属业务空间、模型授权范围和计费开通状态，确认是否能调用 Qwen-Image 等图片模型。
- 如决定使用 DashScope 图片生成，需要新增 `api_format="dashscope_image"` adapter，对接 DashScope 原生图片生成接口。

### 后台运维

结论：通过，存在两个待办。

已验证：
- 后端健康检查：`/api/health/live=ok`，`/api/health/ready=ok`。
- PostgreSQL 服务运行中，数据库连接正常。
- Redis 容器 `caiyan-redis` 返回 `PONG`。
- Celery worker 正常运行并能消费知识库解析任务。
- Admin 模型配置接口、操作日志接口可由管理组访问。
- 操作日志当前可查询，总数正常增长。
- 前端生产构建 `npm run build` 成功。
- `start-all.bat`、`start_backend.bat` 保持 `--workers 4`。
- Redis 分布式限流支持 4 worker，不再被 worker 数放大。
- Windows 定时备份任务 `CaiYanPostgresBackup` 正常运行。
- 最新备份 `product_knowledge_20260621_030002.dump` 可恢复到临时库并查询核心表。
- 健康监控脚本 `health_check_windows.ps1` 返回 `HEALTHY live=ok ready=ok`。
- 存储监控脚本返回 `OK uploads=0GB drive=D: free=157.23GB`。
- 看门狗脚本 `service_control_windows.ps1 -Action Watchdog` 返回 `Watchdog OK`。

待办：
- 当前 `CaiYanStartupRedis`、`CaiYanStartupBackend`、`CaiYanStartupFrontend` 是 `LogonTrigger`，需要用户登录后触发；如果未来要求“无人登录也能自动恢复”，需要改成服务化部署或调整触发方式。
- AI 图片生成 DashScope adapter 另列为独立开发任务。

### 跨模块 E2E

结论：通过。

已验证：
- 新增产品 -> 上传图片 -> 媒体记录 -> 签名 URL -> 向量同步 -> 客服/检索可用。
- 临时产品向量化补测：`documents=3`、`chunks=3`，embedding `embedded=3`，DB 中该 SKU 的 chunk 状态为 `synced=3`。
- 知识文档上传 -> Celery 解析 -> embedding -> `search-preview` 命中。
- 新建普通用户 -> 分配有限权限 -> 登录 -> 后端接口边界验证。
- 前端真实浏览器验证：有限权限用户访问 `/products` 被重定向到 `/no-access`，导航无产品/管理入口；访问 `/history` 正常。
- AI 生成链路按当前配置只验证到提交生成请求并创建失败记录。
- 最新备份恢复到临时库并查询核心表成功，临时库已删除。
- `/uploads`、`file_url`、`getImageUrl` 全局扫描完成，没有新增未签名直链展示风险。

## 3. 今天发现并修复的真实问题清单

### 1. QA 库语义检索和 embedding 服务稳定性

- 问题：客服 QA 补充检索和部分产品详情场景语义命中不稳定。
- 根因：旧 embedding 链路不稳定，且部分 product_detail 场景未稳定补充 QA 检索。
- 修复：迁移到 DashScope `text-embedding-v4`，统一向量维度为 1024，并补齐 product_detail 场景 QA 补充检索。
- 验证：真实客服前端 trace 和知识库检索均命中；QA、材质、容量、安全类问题稳定回答。

### 2. 售后 FAQ 快路径崩溃和意图误判

- 问题：售后电话/售后求助类问题曾出现崩溃或误走产品检索。
- 根因：FAQ 快路径覆盖不足，部分模糊售后求助没有归入 `aftersales`。
- 修复：补充售后意图识别和 FAQ 快路径，避免暴露未配置电话。
- 验证：真实前端 5 条售后变体全部走 FAQ 快路径，`llm_call_count=0`。

### 3. 多轮推荐上下文丢失

- 问题：“换一个推荐，不要刚才那个”可能丢失原始品类约束。
- 根因：推荐上下文没有持久保留 `product_scope` 和历史推荐 SKU。
- 修复：持久化 recommendation_context，换推荐时排除历史 SKU，同时把原始品类需求传给 LLM 判断。
- 验证：真实三轮推荐流程中首轮 5 个 SKU 被排除，换推荐不回推旧 SKU，`llm_call_count=1`。

### 4. 多轮实体指代和产品回溯不稳定

- 问题：“它是什么材质”“前面那款酒精炉”等指代曾可能回错产品。
- 根因：entity_stack 和结构化回指规则不够严格。
- 修复：唯一 SKU 的 product_detail 快路径、实体栈回指和多轮上下文逻辑收敛。
- 验证：`CS-B14` 多轮材质、安全、认证回指稳定命中，`llm_call_count=1`。

### 5. `/uploads` 旧静态路径安全风险

- 问题：文件如果继续通过静态 `/uploads` 暴露，会绕过权限。
- 根因：旧静态挂载不区分产品媒体、知识库文件、AI 生成文件归属。
- 修复：移除静态挂载，新增签名 URL；知识库文件独立走管理下载；AI 生成文件按 owner/管理组校验。
- 验证：旧直链 403/404，签名 URL 可访问，知识库非管理组拒绝。

### 6. 前端生产构建问题

- 问题：`npm run build` 曾因前端文件编码污染失败。
- 根因：文件编码/非法字符导致 TypeScript 构建无法解析。
- 修复：修复污染文件编码，保持 UTF-8。
- 验证：当前 `npm run build` 成功，生成 `frontend/dist` 生产产物。

### 7. PostgreSQL 自动备份脚本不可用

- 问题：原 `backup_postgres.sh` 在当前 Windows 环境不可执行，实际等于没有可用自动备份。
- 根因：Windows 下 bash 指向 WSL，但无可用 bash 环境。
- 修复：新增 Windows 原生 `backup_postgres.ps1`、恢复脚本、定时任务和保留策略。
- 验证：真实生成备份 -> 恢复到测试库 -> 42 张表逐表行数一致；定时任务每天 03:00 执行，保留 14 天。

### 8. 限流在多 worker 下会被放大

- 问题：进程内限流在 `--workers 4` 下每个 worker 单独计数，实际限流约放大 4 倍。
- 根因：旧实现使用进程内 dict/deque。
- 修复：改为 Redis 分布式限流，保留 4 worker；Redis 不可用时 fail-open 并写 warning。
- 验证：4 worker 下登录限流约第 9 次触发 429；Redis 停止时接口不 500，限流临时失效并记录 warning。

### 9. AI 本地并发闸门过紧

- 问题：20 并发压测下 p95/p99 长尾严重，部分请求过早触发 fallback。
- 根因：`AI_MAX_CONCURRENT_REQUESTS=5/worker` 偏紧，且满了立即拒绝。
- 修复：默认提高到 10，并新增 `AI_REQUEST_QUEUE_TIMEOUT_SECONDS=8`，允许短时间排队。
- 验证：小规模并发复测通过，pytest 通过，DB 连接未异常逼近上限。

### 10. compare_products 重复 retry 和多轮工具循环

- 问题：compare 场景出现 5-7 次 LLM 调用，耗时最高约 68.9s。
- 根因：agent 已有结果后仍触发 deterministic retry；compare 路径缺少类似 recommend 的快路径。
- 修复：收窄 retry 条件，保留 `skip_polish`；新增 compare 上下文快路径。
- 验证：无历史 compare 单问从 68.9s 降到约 7.8s；带上下文 compare 从 62.5s/5 次 LLM 降到约 11.1s/1 次 LLM。

### 11. “推荐并说明区别”被误判为 compare

- 问题：“推荐三款适合露营多人做饭的套锅，并说明区别”被误判为 compare，偶发重链路。
- 根因：`_is_compare_like_question()` 只看比较词，没有判断是否存在明确多对象。
- 修复：改为“compare 触发词 + 明确多对象”两段式判断。
- 验证：该句重新走 recommend 快路径；真正 compare 如 `CW-C83 和 CW-C01-37 哪个更轻` 仍走 compare。

### 12. PostgreSQL 连接耗尽风险

- 问题：20 并发下理论连接池上限 4 worker * 30 = 120，超过 PostgreSQL `max_connections=100`，存在 500 风险。
- 根因：每 worker `pool_size=10 + max_overflow=20` 过大，且长请求持有 DB session。
- 修复：连接池收紧为 `pool_size=5 + max_overflow=5`。
- 验证：服务正常启动，后续并发复测无 `too many clients`。

### 13. 客服 SSE 长请求持有数据库连接

- 问题：LLM 等待期间 DB 连接随请求堆叠，导致连接峰值接近危险水位。
- 根因：FastAPI 请求级 DB session 在整个 SSE/LLM 生命周期中被持有。
- 修复：拆分 session 生命周期，读取上下文、工具查库、保存结果均短 session；LLM 等待阶段释放连接；跨阶段传递纯 dict。
- 验证：真实前端回归全部通过；20 并发复测 `713/713` 成功，0 个 4xx/5xx/exception，DB 连接峰值约 21；p95 从 61.4s 降到 16.38s，p99 从 67.4s 降到 23.66s。

### 14. PMD 规格更新 500

- 问题：编辑产品规格 `capacity` 等结构化字段时报 500。
- 根因：更新路径漏序列化 JSON/list 字段。
- 修复：`update_product_specs()` 对 `size_info`、`capacity`、`technical_advantages` 统一 `_to_json_str()`。
- 验证：真实前端编辑保存成功；详情查询正确；pytest 通过。

## 4. 当前已知的未解决事项清单

### 需要你决策

- HTTPS：如果只在公司内网 20 人试用，短期不是最高优先级；如果暴露公网，需要域名、证书和反向代理配置。
- 行级权限隔离：当前 `product.read` 用户可查看全部产品，没有按部门/SKU/产品线隔离。若未来存在“A 部门不能看 B 部门产品”的要求，需要重新设计行级权限。
- 是否换正式服务器：当前本机环境已能支撑内网试用，但如果要求无人值守、高可用、远程访问、统一备份/监控，需要正式服务器或云资源决策。

### 待开发功能

- DashScope 图片生成 adapter：新增 `api_format="dashscope_image"`，对接 DashScope 原生图片生成接口。
- 知识库文档管理 UI/API：文档列表、详情、删除、重新解析、状态管理。
- 开机自启动改造：当前是 LogonTrigger；如需无人登录恢复，需要改为 BootTrigger、Windows 服务化或正式部署方案。

### 已知限制

- 视频/文件容量：按当前磁盘空间和估算上传量，视频容量约 42 天后需要关注；已有存储监控低空间预警。
- `POST /api/products` 直接创建接口与草稿发布路径不一致，当前前端主流程使用草稿发布。
- `tag_list` 在部分直接媒体接口响应中仍是 JSON 字符串，详情聚合中可正常反序列化。
- 已发布产品编辑页不直接回显聚合 `media` 数组，后续 PMD 体验优化处理。
- AI 图片生成核心功能当前不可用，直到配置可用图片模型 API Key 或接入 DashScope adapter。
- 当前自启动依赖用户登录和 Docker Desktop 用户会话，不满足无人值守重启后立即恢复。

## 5. 系统当前整体健康度结论

在“公司内网、约 20 人、接受当前无 HTTPS/无行级隔离/AI 图片生成暂不可用/自启动需用户登录”的前提下，系统已经具备内网试用条件；PMD、知识库、智能客服、权限、文件安全、备份恢复、监控告警和 20 并发稳定性均已通过真实环境验证。
