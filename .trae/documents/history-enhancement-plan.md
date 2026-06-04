# 历史记录功能完善实施计划

## 一、需求分析

| 需求点 | 描述 | 当前状态 |
|--------|------|----------|
| 1. 管理员查看全部记录 | admin 用户可以查看所有用户的生成记录 | ❌ 未实现 |
| 2. 普通用户查看自己记录 | 普通用户只能查看自己的生成记录 | ✅ 已实现 |
| 3. 顶部看板统计 | 显示使用次数、各类型统计等 | ❌ 未实现 |
| 4. 搜索功能 | 按提示词关键词、日期搜索 | ❌ 未实现 |
| 5. 参数脱敏 | 不直接暴露原始请求参数 | ❌ 未实现 |

## 二、实施步骤

### 步骤 1：后端 API 增强

**修改文件**: `backend/app/api/history.py`

新增接口：
- `GET /api/history/admin` - 管理员查看所有用户记录（支持搜索）
- `GET /api/history/stats` - 获取统计数据

**修改文件**: `backend/app/services/generation_service.py`

新增方法：
- `get_all_generations(db, skip, limit, search_query, date_from, date_to)` - 管理员查询所有记录
- `get_generation_stats(db, user_id=None)` - 获取统计数据

### 步骤 2：前端历史记录页面增强

**修改文件**: `frontend/src/pages/History.tsx`

新增功能：
- 顶部看板区域（统计卡片）
- 搜索栏（关键词 + 日期选择）
- 隐藏 parameters 的 JSON 展示，改为友好的参数摘要

### 步骤 3：API 服务层更新

**修改文件**: `frontend/src/services/api.ts`

新增方法：
- `history.adminList()` - 管理员查询
- `history.stats()` - 获取统计

### 步骤 4：类型定义更新

**修改文件**: `frontend/src/types/index.ts`

新增类型：
- `GenerationStats` - 统计数据类型
- `SearchFilters` - 搜索过滤条件

## 三、数据库查询设计

### 搜索查询逻辑

```sql
-- 按提示词搜索 + 日期范围
SELECT * FROM generations
WHERE (user_id = ? OR admin_flag = true)
  AND (prompt LIKE ? OR negative_prompt LIKE ?)
  AND created_at >= ?
  AND created_at <= ?
ORDER BY created_at DESC
```

### 统计查询逻辑

```sql
-- 按类型统计
SELECT type, COUNT(*) as count 
FROM generations 
WHERE user_id = ? 
GROUP BY type

-- 按日期统计
SELECT DATE(created_at) as date, COUNT(*) as count 
FROM generations 
WHERE user_id = ? 
GROUP BY DATE(created_at)
```

## 四、参数脱敏方案

| 参数 | 处理方式 |
|------|----------|
| `size` | 显示为 "1024x1024" |
| `n` | 显示为 "生成数量: 2" |
| `quality` | 显示为 "质量: high" |
| `output_format` | 显示为 "格式: jpeg" |
| 其他技术参数 | 隐藏不显示 |

## 五、前端页面布局

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ 总数    │ │ 文生图  │ │ 图生图  │ │ 视频    │  看板区域    │
│  │ 128     │ │ 85      │ │ 32      │ │ 11      │              │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
├─────────────────────────────────────────────────────────────────┤
│  [搜索框] [日期选择]                    [筛选类型]             │
├─────────────────────────────────────────────────────────────────┤
│  记录列表区域                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## 六、文件修改清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `backend/app/api/history.py` | 修改 | 新增管理员接口和统计接口 |
| `backend/app/services/generation_service.py` | 修改 | 新增查询和统计方法 |
| `backend/app/schemas/generation.py` | 修改 | 新增统计响应模型 |
| `frontend/src/pages/History.tsx` | 修改 | 新增看板、搜索、参数脱敏 |
| `frontend/src/services/api.ts` | 修改 | 新增 API 调用方法 |
| `frontend/src/types/index.ts` | 修改 | 新增类型定义 |

## 七、风险与注意事项

| 风险 | 说明 | 应对措施 |
|------|------|----------|
| 性能问题 | 大量记录时查询慢 | 添加分页和索引 |
| 权限问题 | 普通用户可能访问管理员接口 | 后端权限校验 |
| 参数展示 | 参数格式不一致 | 统一参数格式化逻辑 |
| 日期时区 | 时间显示不一致 | 使用 UTC 时间存储，前端转换 |