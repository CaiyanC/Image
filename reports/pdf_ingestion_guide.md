# PDF 知识库入库操作手册

## 目标

把一个 PDF 从上传文件变成可被 `semantic_search_knowledge` / `semantic_retrieve` 命中的语义知识。

当前流程分两段：

1. 文件上传和解析：自动触发 Celery `parse_document`，写入 `knowledge_documents` / `knowledge_chunks`。
2. embedding 生成：需要手动触发补跑任务，把 `knowledge_chunks.embedding_status` 从 `pending` 更新为 `synced`。

## 前置条件

1. Redis 已启动。
2. FastAPI backend 已启动。
3. Celery worker 已启动。
4. 当前数据库已迁移到最新版。
5. embedding 所需的模型/API 配置可用。

本地常用启动命令：

```powershell
docker exec caiyan-redis redis-cli ping

cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload

cd backend
.\venv\Scripts\activate
celery -A app.core.celery_app.celery_app worker --loglevel=info --pool=solo
```

## 步骤 1：上传 PDF

Endpoint:

```text
POST /api/knowledge-base/files/upload
```

请求类型：`multipart/form-data`

常用字段：

- `files`: PDF 文件
- `related_skus`: 可选，关联 SKU 列表

成功后返回里应包含：

- `document_id`
- `task_id`
- `task_status`
- `parse_status`

预期状态：

- `task_status = pending`
- `parse_status = processing`

## 步骤 2：等待解析完成

Endpoint:

```text
GET /api/knowledge-base/tasks/{task_id}
```

轮询直到：

- `status = done`：解析成功
- `status = error`：解析失败，查看 `error_message`

解析成功后，PDF 内容会写入：

- `knowledge_documents`
- `knowledge_chunks`

注意：这一步完成后，chunk 通常仍是：

```text
embedding_status = pending
```

此时还不能保证被语义向量检索命中。

## 步骤 3：触发 embedding 补跑

Endpoint:

```text
POST /api/knowledge-base/jobs/retry-embeddings
```

用途：把未完成 embedding 的 chunks 补跑为向量。

常用参数：

```json
{
  "limit": 20
}
```

该接口需要管理员权限。

返回中会有 job id。可用下面接口查看任务：

```text
GET /api/knowledge-base/jobs/{job_id}
```

## 步骤 4：确认 embedding 已 synced

可以从数据库确认：

```sql
SELECT
  d.id AS document_id,
  d.file_name,
  d.file_type,
  d.parse_status,
  c.embedding_status,
  COUNT(*) AS chunk_count
FROM knowledge_documents d
JOIN knowledge_chunks c ON c.document_id = d.id
WHERE d.file_type = 'pdf'
GROUP BY d.id, d.file_name, d.file_type, d.parse_status, c.embedding_status
ORDER BY d.file_name, c.embedding_status;
```

可语义检索的预期状态：

```text
parse_status = done
embedding_status = synced
```

如果仍是 `pending`，说明 embedding 补跑任务还没执行或没有覆盖到该 chunk。

如果是 `failed`，查看：

```sql
SELECT
  d.file_name,
  c.id AS chunk_id,
  c.embedding_status,
  c.embedding_error
FROM knowledge_documents d
JOIN knowledge_chunks c ON c.document_id = d.id
WHERE d.file_type = 'pdf'
  AND c.embedding_status = 'failed';
```

## 步骤 5：验证 PDF 内容可以被语义检索命中

推荐用知识库搜索预览接口：

```text
POST /api/knowledge-base/search-preview
```

请求示例：

```json
{
  "query": "输入 PDF 中真实存在的一句话或关键词",
  "limit": 5
}
```

验证点：

- 返回结果中能看到 PDF 相关内容片段。
- 返回的 `source_type` 应为 `file`。
- metadata 中应能看到 `file_type = pdf` 或 PDF 页码信息。

如果要从智能客服链路验证，可在前端用 PDF 中真实内容提问，观察工具调用是否命中：

```text
semantic_search_knowledge
```

## 常见问题

### 上传后只有 task_id，没有内容

这是正常的。P1.5 后解析由 Celery worker 异步执行，需要轮询 task 状态。

### task 已 done，但语义检索不到

通常是 embedding 还没补跑。检查该 PDF chunks 是否仍为 `pending`。

### keyword 能搜到，semantic 搜不到

说明 chunk 已入库，但 embedding 可能还不是 `synced`。

### retry-embeddings 后仍 failed

检查 `embedding_error`，通常与 embedding API 配置、网络或模型返回有关。
