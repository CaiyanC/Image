# 多张生成 — 结果展示 + 灯箱画廊升级计划

## 问题诊断

当前 `n > 1` 时，API 确实返回多张图片（`data[]` 数组中多个 `b64_json`），但存在两个瓶颈导致只展示一张：

| 瓶颈 | 位置 | 原因 |
|---|---|---|
| `_extract_and_save_b64()` | [generation_service.py:L43-L55](file:///e:/trea/AItool/backend/app/services/generation_service.py#L43-L55) | 遍历 `data[]` 时命中第一张就 `return`，其余丢弃 |
| `Generation.result_image_path` | [models/generation.py:L19](file:///e:/trea/AItool/backend/app/models/generation.py#L19) | ORM 模型只有单字段，只能存一张图路径 |
| 前端 `resultUrl: string\|null` | [Workspace.tsx:L21](file:///e:/trea/AItool/frontend/src/pages/Workspace.tsx#L21) | 只能存一个 URL |
| History 详情 | [History.tsx:L230-L240](file:///e:/trea/AItool/frontend/src/pages/History.tsx#L230-L240) | `<img>` 单图展示 |
| History 列表加载 | [History.tsx](file:///e:/trea/AItool/frontend/src/pages/History.tsx) | 左侧列表初始加载不完整，需要搜索才能看到更早记录 |

---

## Step 0: 生成张数上限调整

### 0.1 后端

**文件**: `backend/app/services/generation_service.py`

`create_txt2img()` 和 `create_img2img()` 中的 `n` 上限：

```diff
- n = max(1, min(10, params.get("n", 1)))
+ n = max(1, min(4, params.get("n", 1)))
```

### 0.2 前端 Workspace

**文件**: `frontend/src/pages/Workspace.tsx`

生成张数下拉选项：

```diff
- {[1,2,3,4,5,6,7,8,9,10].map(v => ...)}
+ {[1,2,3,4].map(v => ...)}
```

### 0.3 前端 params 默认值不变

默认 `n: 1` 保持不变。

---

## Step 1: 后端 — 支持多图存储（最小侵入方案）

### 1.1 Generation 模型新增字段

**文件**: `backend/app/models/generation.py`

在 `result_image_path` 字段后新增：

```python
result_images: Mapped[list] = mapped_column(JSON, nullable=True)
```

- JSON 类型存储 `["/uploads/generated/xxx.png", ...]` 字符串数组
- 保留现有 `result_image_path` 字段不变（向后兼容），但新生成记录时不写入它，改用 `result_images`

### 1.2 `_extract_and_save_b64()` 改为返回列表

**文件**: `backend/app/services/generation_service.py`

```python
async def _extract_and_save_b64(data: dict) -> list[str]:
    """返回所有图片的保存路径列表 (可能为空)"""
    paths = []
    if data.get("data"):
        for item in data["data"]:
            if item.get("b64_json"):
                import base64
                image_data = base64.b64decode(item["b64_json"])
                path = await save_generated_image(image_data)
                paths.append(path)
            elif item.get("url"):
                async with httpx.AsyncClient() as client:
                    img_response = await client.get(item["url"])
                    img_response.raise_for_status()
                    path = await save_generated_image(img_response.content)
                    paths.append(path)
    return paths
```

### 1.3 `create_txt2img()` / `create_img2img()` 适配

**文件**: `backend/app/services/generation_service.py`

两处逻辑改为：

```python
image_paths = await _extract_and_save_b64(result)
if image_paths:
    generation.result_images = image_paths
    generation.result_image_path = image_paths[0]  # 保留兼容单图展示
    generation.status = "completed"
else:
    generation.status = "failed"
    generation.error_message = "No image data in response"
```

GPT 和 Gemini 分支均适配。

### 1.4 GenerationResponse schema 新增字段

**文件**: `backend/app/schemas/generation.py`

```python
class GenerationResponse(BaseModel):
    # ... 现有字段 ...
    result_images: Optional[list] = None  # 新增
```

---

## Step 2: 前端 Workspace — 多图展示 + 灯箱

### 2.1 状态改为字符串数组

**文件**: `frontend/src/pages/Workspace.tsx`

```typescript
const [resultUrls, setResultUrls] = useState<string[]>([])
```

`handleGenerate` 中：

```typescript
if (result.result_images && result.result_images.length > 0) {
  setResultUrls(result.result_images)
} else if (result.result_image_path) {
  setResultUrls([result.result_image_path])
}
```

### 2.2 新建 Lightbox 组件

**文件**: `frontend/src/components/Lightbox.tsx`（新建）

```tsx
interface LightboxProps {
  images: string[]
  initialIndex: number
  onClose: () => void
}
```

功能：
- 全屏遮罩 + 大图居中
- **左右箭头**：`<` 上一张 / `>` 下一张（首尾循环）
- **键盘支持**：`←` `→` 切换，`Escape` 关闭
- **底部缩略图指示器**：圆点 `● ○ ○` 显示当前位置
- **关闭按钮**：右上角 ×
- **下载按钮**：每张图可下载

### 2.3 升级右侧结果区域

**文件**: `frontend/src/pages/Workspace.tsx`

当 `resultUrls.length > 0` 时：

| 条件 | 展示 |
|---|---|
| `resultUrls.length === 1` | 单张大图（现有 behavior）+ 悬浮下载/清除按钮 |
| `resultUrls.length > 1` | **缩略图网格** + 点击打开 Lightbox |

缩略图网格布局：
```
┌────────────┬────────────┐
│  图1       │  图2       │
│  悬浮:编号  │  悬浮:编号  │
├────────────┼────────────┤
│  图3       │  图4       │
│  ...       │  ...       │
└────────────┴────────────┘
```
- 最多 2 列，自适应
- 每张缩略图带编号标签 (#1, #2, ...)
- 点击任意一张 → 打开 Lightbox 定位到该 index

顶部工具栏：
```
[清除全部] [下载全部]  共 N 张
```

### 2.4 清除逻辑更新

```typescript
function handleClearResult() {
  setResultUrls([])
}
```

---

## Step 3: 前端 History — 多图预览

### 3.1 列表页：显示 "N 张图" 标签

**文件**: `frontend/src/pages/History.tsx`

在生成记录卡片行中，当 `record.result_images` 存在时，显示 `"3 张图"` 标签（带图标），替代或补充现有的单张缩略图预览。

### 3.2 详情面板：缩略图网格 + Lightbox

**文件**: `frontend/src/pages/History.tsx`

在历史详情右侧"生成结果"区域：

| 条件 | 展示 |
|---|---|
| `result_images.length === 1` | 单张大图（现有） |
| `result_images.length > 1` | 缩略图网格 + 点击打开 Lightbox（复用同一组件） |

---

## Step 4: 类型定义更新

### 4.1 前端类型

**文件**: `frontend/src/types/index.ts`

```typescript
export interface GenerationRecord {
  // ... 现有字段 ...
  result_images?: string[]  // 新增
}
```

---
## Step 5: History 列表初始加载修复

### 5.1 问题诊断

**文件**: `frontend/src/pages/History.tsx`

当前右侧详情面板通过点击左侧列表项打开。左侧列表依赖搜索触发加载，初次进入页面时可能因默认查询参数不完整导致部分历史记录未展示。需要检查 `loadGenerations` 的默认分页/搜索参数，确保首次加载 `page_size` 足够大且无多余过滤条件。

### 5.2 修复方向

在 `useEffect` 首次调用 `loadGenerations` 时：
- `page_size` 从默认值改为一个合理的较大值（如 50）
- 确保 `keyword` 为空时不添加额外的过滤条件

---

## 影响范围汇总

| 文件 | 操作 | 行数估计 |
|---|---|---|
| `backend/app/services/generation_service.py` | n 上限 4 + `_extract_and_save_b64` 改返回列表 + 两处适配 | ±25 |
| `backend/app/models/generation.py` | 新增 `result_images` JSON 字段 | +3 |
| `backend/app/schemas/generation.py` | `GenerationResponse` 新增 `result_images` | +1 |
| `frontend/src/pages/Workspace.tsx` | n 上限 4 + 状态改数组 + 多图网格 + Lightbox 集成 | +50 |
| `frontend/src/types/index.ts` | `GenerationRecord` 新增 `result_images` | +1 |
| `frontend/src/components/Lightbox.tsx` | **新建** — 全屏灯箱画廊组件 | +80 |
| `frontend/src/pages/History.tsx` | 列表加载修复 + 列表标签 + 详情多图 | +35 |

**总计**: ~195 行

---

## 验证步骤

1. 文生图 n=4 → 右侧显示 4 张缩略图 → 点击打开 Lightbox → 左右切换正常
2. 图生图 n=2 → 同上
3. 生成张数下拉仅 1-4 可选，默认 1
4. 历史记录页 → 首次进入列表加载完整（无需搜索补全）→ 列表显示 "N 张图" → 详情面板展示多图 → Lightbox 正常
5. n=1 时 → 单图展示不变（向下兼容）
6. Lightbox → 键盘 ← → 切换、Esc 关闭
