# 语义 RAG 智能客服正式上线检查清单

## 目标

正式上线前，以 Flash 语义理解、RAG 召回/重排和同 SKU 事实绑定为主链完成开发环境验收。旧版固定词、答案字数、平均分和规则路由测试不再作为发布依据。

## 自动测试

### 1. 当前语义 RAG 单元测试

```powershell
cd backend
$env:PYTHONPATH='.'
python -m pytest tests/test_customer_semantic_rag_recall.py tests/test_semantic_rag_deep_audit.py tests/test_semantic_rag_release_gate.py -q
```

### 2. 前端构建

```powershell
cd frontend
npm run build
```

### 3. 开发环境真实 HTTP 深度抽检

只允许对开发后端 `8001` 执行。脚本会覆盖自然问法、推荐、对比、上下文、知识库、安全和普通/SSE 一致性，并保存完整答案与 trace：

```powershell
cd backend
python scripts/semantic_rag_deep_audit.py http://127.0.0.1:8001
```

逐条人工检查报告中的答案可用性与事实一致性后，再执行当前 RAG 离线发布门槛：

```powershell
python scripts/semantic_rag_release_gate.py reports/semantic_rag_deep_audit_YYYYMMDD_HHMMSS.json
```

## 通过标准

- Flash 完成语义计划，不能以旧关键词路由替代正常自然问法理解。
- 商品结果、公开证据、最终答案审计必须保持同 SKU 绑定。
- 容量、重量、功率、热源等硬事实与开发库及 RAG evidence 一致，不能在润色时升级成无依据结论。
- 推荐、对比和多轮追问中的商品身份连续且可解释；无匹配时不得发布候选 SKU。
- 安全问题不采纳提示注入或危险指令，知识缺口要明确说明。
- 普通接口与 SSE 的答案和 `result_skus` 一致。
- 深度抽检报告逐条人工复核可用，且 `semantic_rag_release_gate.py` 通过。
- 前端构建通过。

## 发布边界

未经明确“发布”或“更新生产”，不得合并 `master`、重启生产服务或访问生产后端 `8000` 做写操作。开发验收通过也不自动授权发布。
