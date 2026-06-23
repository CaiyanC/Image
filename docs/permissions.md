# Permissions Guide

本文档记录当前权限模型和已知边界，用于排查“为什么某个用户看不到/操作不了某个功能”。

## 1. 当前权限模型

系统当前使用 RBAC：

1. 用户属于一个或多个组。
2. 组绑定权限点。
3. 接口通过 `require_permission(...)`、`require_product_permission(...)`、`get_current_super_admin` 做鉴权。
4. `管理层` 组拥有全部权限点，并且可以通过管理组专属接口做系统级配置和人员管理。

当前预置组：

- `管理层`
- `产品团队`
- `设计团队`
- `电商运营`
- `海外营销`
- `AI内容岗`
- `客服团队`
- `AI工程师`
- `经销商`
- `外部达人`
- `广告代理商`

## 2. 当前完整权限点

权限点来自 `backend/app/core/permission_constants.py` 的 `PERMISSION_DEFS`。

| 权限点 | 名称 | 类型 | 主要用途 |
| --- | --- | --- | --- |
| `history.view` | 查看历史记录 | page | 查看自己的 AI 生成历史；管理组可看全量历史统计和详情 |
| `profile.view` | 查看个人资料 | page | 查看/修改个人资料 |
| `category.read` | 查看产品品类 | api | 读取产品分类 |
| `product.read` | 查看产品 | page | 查看产品列表、搜索、详情、草稿列表入口 |
| `product.create` | 创建产品 | button | 创建产品、创建草稿、批量导入草稿、发布草稿 |
| `product.edit` | 编辑产品 | button | 编辑产品、更新草稿、删除草稿 |
| `product.delete` | 删除产品 | button | 删除产品；没有该权限时仅产品团队 admin 有删除兜底权限 |
| `product.review` | 审核产品 | button | 产品审核类操作预留/授权 |
| `media.upload` | 上传素材 | button | 上传产品图片/视频 |
| `media.review` | 审核素材 | button | 素材审核类操作预留/授权 |
| `media.download` | 下载素材 | button | 素材下载类操作授权 |
| `tag.edit` | 编辑标签 | button | 创建/删除产品品类 |
| `ai.call` | AI 调用 | api | 产品向量同步、向量状态查看等 AI/知识库调用类入口 |
| `ai.generate` | AI 生图 | api | 模型列表、文生图、图生图、文生视频、参考图上传 |
| `ai.customer_service` | 智能客服 | api | 客服会话、提问、流式提问、反馈、动作确认/取消 |
| `ai.authorize` | AI 调用授权 | button | AI 授权类操作预留/授权 |
| `competitor.view` | 查看竞品 | page | 竞品查看类入口预留/授权 |
| `new_product.view` | 查看新品 | page | 新品查看类入口预留/授权 |
| `export.approved` | 导出审批 | button | 导出审批类操作预留/授权 |

## 3. 产品数据可见范围限制

当前拥有 `product.read` 权限的用户可以查看全部产品数据，没有按部门/SKU/产品线做行级隔离。这是当前已知且接受的限制，不是遗漏。

如果未来业务需要部门级数据隔离，需要重新评估并设计行级权限方案。可能需要补充的数据模型包括：产品所属部门、SKU 范围规则、产品线归属、用户部门归属、跨部门共享规则、管理员例外规则、历史数据迁移方案。

当前相关行为：

- 产品列表、搜索、详情：`product.read` 可访问全部产品。
- 产品图片/视频签名展示：拥有 `product.read` 即可签名查看产品图片/视频。
- 产品草稿：普通用户只能看自己的草稿；`管理层` 可看全部草稿。
- AI 生成历史：普通用户只能看自己的历史；`管理层` 可看全量历史和统计。
- AI 生成文件：生成结果按所有者校验；`管理层` 可查看全部生成文件。

## 4. 主要接口权限映射

### 产品与分类

- 产品读取：`product.read`
- 产品创建：`product.create`
- 产品编辑：`product.edit`
- 产品删除：`product.delete`；产品团队 admin 有删除兜底权限
- 产品向量同步和向量状态：`ai.call`
- 产品图片/视频上传：`media.upload`
- 分类读取：`category.read` 或 `product.read` 或 `product.create` 或 `product.edit`
- 分类创建/删除：`tag.edit`

### AI 生成

- 模型列表：`ai.generate`
- 文生图：`ai.generate`
- 图生图：`ai.generate`
- Gemini 图生图：`ai.generate`
- 文生视频：`ai.generate`
- 参考图上传：`ai.generate`

### 智能客服

以下客服接口均需要 `ai.customer_service`：

- 会话列表、会话详情、删除会话
- 消息反馈
- review samples
- 动作确认/取消
- 普通提问 `/api/customer-service/ask`
- 流式提问 `/api/customer-service/ask-stream`

### 个人与历史

- 个人资料查看/修改：`profile.view`
- 个人密码修改：登录用户即可，不依赖权限点
- 个人 AI 历史列表/详情/统计/删除：`history.view`
- 全量 AI 历史 `/api/history/admin`：`管理层`

### 文件访问

- 产品图片/视频签名：需要 `product.read`
- AI 生成文件签名：需要文件所有者本人，或属于 `管理层`
- 知识库文件：不能走公开签名路径，只能走知识库管理下载接口，且仅限 `管理层`

## 5. 仅限管理组的操作

以下接口使用 `get_current_super_admin`，只有 `管理层` 用户可以访问。

### 用户管理

- `GET /api/users`
- `GET /api/users/{user_id}`
- `POST /api/users`
- `PUT /api/users/{user_id}`
- `PUT /api/users/{user_id}/password/reset`
- `DELETE /api/users/{user_id}`

### 组和权限管理

- `GET /api/admin/groups`
- `GET /api/admin/groups/permissions`
- `POST /api/admin/groups`
- `PUT /api/admin/groups/{group_id}`
- `DELETE /api/admin/groups/{group_id}`
- `GET /api/admin/groups/{group_id}/users`
- `GET /api/admin/groups/{group_id}/permissions`
- `PUT /api/admin/groups/{group_id}/permissions`
- `POST /api/admin/groups/{group_id}/users`
- `DELETE /api/admin/groups/{group_id}/users/{user_id}`
- `PUT /api/admin/groups/{group_id}/users/{user_id}`

### 系统管理

- `GET /api/admin/models-config`
- `PUT /api/admin/models-config`
- `GET /api/admin/operation-logs`

### 知识库管理

- `GET /api/knowledge-base/status`
- `GET /api/knowledge-base/health`
- `POST /api/knowledge-base/search-preview`
- `POST /api/knowledge-base/reindex-products`
- `POST /api/knowledge-base/jobs/reindex-products`
- `POST /api/knowledge-base/jobs/retry-embeddings`
- `GET /api/knowledge-base/jobs`
- `GET /api/knowledge-base/jobs/{job_id}`
- `POST /api/knowledge-base/documents`
- `GET /api/knowledge-base/tasks/{task_id}`
- `GET /api/knowledge-base/files/{document_id}/download`
- `POST /api/knowledge-base/files/upload`
- `POST /api/knowledge-base/files/recover-stuck`

### 全量历史

- `GET /api/history/admin`
- 管理组查看单条生成记录时可跨用户查看。
- 管理组查看统计时是全量统计。

## 6. 20 人使用场景的账号分配建议

建议每个人使用独立账号，不要共用 `admin` 账号。

原因：

- 操作日志按 `user_id`、用户名、IP、User-Agent 记录。
- 共用账号会导致操作责任无法追溯。
- 禁用离职人员、重置密码、调整权限时，共用账号会影响所有人。
- 限流按用户或 IP+用户名生效，共用账号会互相影响。

建议分配方式：

- 日常系统管理员：少数人加入 `管理层`，用于用户、组、模型配置、知识库文件、审计日志。
- 产品录入/维护人员：加入 `产品团队`，按需授予 `product.create`、`product.edit`、`product.review`、`tag.edit`。
- 设计/内容人员：加入 `设计团队` 或 `AI内容岗`，重点授予 `ai.generate`、`media.upload`、`media.download`。
- 客服人员：加入 `客服团队`，授予 `ai.customer_service` 和 `product.read`。
- 外部经销商/达人/代理商：只授予必要的 `product.read`、`media.download`，不要加入 `管理层`。

排查访问失败时，先确认：

1. 用户是否登录的是自己的账号。
2. 用户是否属于正确的组。
3. 组是否绑定了对应权限点。
4. 目标接口是否是 `管理层` 专属。
5. 该功能是否受当前已知限制影响，例如 `product.read` 是全量产品可见，不是部门隔离。
