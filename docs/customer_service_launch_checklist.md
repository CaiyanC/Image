# 智能客服正式上线检查清单

## 目标

正式上线前，每次修改智能客服、产品导入、QA 导入、向量同步、确认修改/删除流程后，都要跑一遍回归测试集。

## 自动测试

### 1. 基础单元测试

```powershell
$env:PYTHONPATH='backend'; python -m unittest backend.tests.test_customer_agent_service backend.tests.test_agent_action_service backend.tests.test_product_service backend.tests.test_product_vector_index_service backend.tests.test_agent_trace_service backend.tests.test_customer_service_regression_cases
```

### 2. 前端构建

```powershell
cd frontend
npm run build
```

### 3. 智能客服真实接口回归

先启动后端，然后准备登录 token：

```powershell
$env:CUSTOMER_SERVICE_TOKEN="你的登录 token"
python scripts/customer_service_regression_runner.py --base-url http://127.0.0.1:8001
```

只检查测试集格式：

```powershell
python scripts/customer_service_regression_runner.py --dry-run
```

只跑前 5 条快速冒烟：

```powershell
python scripts/customer_service_regression_runner.py --limit 5
```

## 通过标准

- 单元测试全部通过。
- 前端构建通过。
- 回归测试平均分 `>= 0.90`。
- 写库类问题只生成待确认动作，不直接承诺已修改。
- 修改/删除确认后，知识库/向量同步结果要进入动作结果；失败不能阻断主写库，但必须记录 error。
- 推荐类问题必须有依据和查询结果，不能复读上一轮无关场景。

## 当前测试集覆盖

测试集位置：`docs/customer_service_regression_cases.json`

覆盖范围：

- 模糊推荐：露营、泡咖啡、四人做饭、送礼、单人徒步。
- 多轮上下文：这些、他的、切换场景、不锁旧 SKU。
- 产品详情：按名称、SKU、缺失 SKU 查询。
- 产品对比：显式 SKU 对比、上一轮候选继续对比。
- 写库动作：修改、批量修改、删除产品、清空字段。
- 数据质量：尺寸 unit、缺失资料不编造。
- 安全风控：不能绕过确认、不能编造库存价格。
- 前端体验：回答后必须有来源和查询结果。
