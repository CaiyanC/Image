# 产品页面 Bug 修复计划

> 创建时间：2026-05-09\
> 涉及文件：backend/app/schemas/product.py、backend/app/services/product\_service.py、backend/app/api/products.py、frontend/src/pages/ProductManagement.tsx、frontend/src/services/api.ts

***

## Bug 1：保存后的产品无法修改 SKU

### 根因

* **前端**：编辑模式下没有可编辑 SKU 的输入框，`saveEditing()` 发送 `PUT /api/products/{sku}` 时 `sku` 取自 `selected.sku`（原始值），无法覆盖

* **后端**：`ProductUpdate` schema 不包含 `sku` 字段，路由路径 `/{sku}` 只用于定位产品

### 修复方案

**后端 — \[schemas/product.py]**

1. `ProductUpdate` 新增 `new_sku: Optional[str] = None` 字段

**后端 — \[services/product\_service.py]**
2\. `update_product()` 中，若 `new_sku` 存在且与当前 sku 不同，先检查新 sku 是否已存在，再 `setattr(product, 'sku', ...)` 更新

**后端 — \[api/products.py]**
3\. 无需改动（路由于 `/{sku}` 不变，`new_sku` 在 body 中传递）

**前端 — \[ProductManagement.tsx]**
4\. 编辑模式 L1 基本信息区新增 `EditableKV label="SKU"`，绑定到 `editData.sku`（初始值取 `selected.sku`）
5\. `startEditing()` 中添加 `sku: selected.sku`
6\. `saveEditing()` 中 l1 对象新增 `new_sku: editData.sku !== sku ? editData.sku : undefined`

***

## Bug 2：L5 媒体资产 — 按渠道（淘宝/京东/亚马逊）组织主图/详情页/场景图

### 根因

* 当前 L5 媒体资产是**扁平维度**（主图/详情图/场景图/视频/3D），无法按渠道区分

* 编辑模式下只有主图有上传按钮，详情图和场景图仅有 textarea

* 用户需要的是**渠道维度**的组织方式，如淘宝、京东、亚马逊各有一套独立的主图+详情页+场景图

### 目标结构

```
渠道：淘宝
  ├── 主图（可多张上传，带缩略图预览）
  ├── 详情页图（可多张上传，带缩略图预览）
  └── 场景图（可多张上传，带缩略图预览）

渠道：京东（同上）
渠道：亚马逊（同上）
```

### 修复方案

**后端 — \[models/product\_media.py]**

1. `ProductMedia` 新增字段：`channel_media: Mapped[str] = mapped_column(Text, nullable=True)`

   * JSON 结构：

   ```json
   {
     "taobao": { "main_images": [...], "detail_images": [...], "scene_images": [...] },
     "jd": { "main_images": [...], "detail_images": [...], "scene_images": [...] },
     "amazon": { "main_images": [...], "detail_images": [...], "scene_images": [...] }
   }
   ```

**后端 — \[schemas/product.py]**
2\. `ProductMediaUpdate` 新增 `channel_media: Optional[Dict[str, ChannelMediaData]] = None`
3\. 新增 `ChannelMediaData` schema：

```python
class ChannelMediaData(BaseModel):
    main_images: Optional[List[str]] = None
    detail_images: Optional[List[str]] = None
    scene_images: Optional[List[str]] = None
```

**后端 — \[services/product\_service.py]**
4\. `update_product_media()` 中支持 `channel_media` 的序列化/反序列化

**前端 — \[ProductManagement.tsx]**
5\. **L5 查看模式**：渠道 Tab 切换（淘宝/京东/亚马逊），每个 Tab 下分组展示主图/详情页/场景图的缩略图网格
6\. **L5 编辑模式**：同上渠道 Tab 切换，每个 Tab 内分为三个区：

* 主图区：textarea + 上传按钮 + 缩略图预览网格

* 详情页图区：textarea + 上传按钮 + 缩略图预览网格

* 场景图区：textarea + 上传按钮 + 缩略图预览网格

1. 新增 `editData.channel_media_json` 字段（JSON 序列化整个渠道媒体数据）
2. `startEditing()` 中初始化 `channel_media_json: JSON.stringify(selected.media?.channel_media || defaultChannels)`

   * `defaultChannels = { taobao: {main_images:[], detail_images:[], scene_images:[]}, jd: {...}, amazon: {...} }`
3. `saveEditing()` 中解析并发送 `channel_media` 到 `PUT /products/{sku}/media`

**前端 — \[ProductManagement.tsx]**
10\. 新增 9 个上传处理函数（3 渠道 × 3 类型）或用一个通用函数参数化渠道+类型：
`ts
    async function handleChannelImageUpload(channel: string, type: 'main'|'detail'|'scene', e: ChangeEvent) { ... }
    `
&#x20;  &#x20;
上传后解析 `editData.channel_media_json` → 修改对应渠道的图片列表 → 序列化回 `editData`

***

## Bug 3：L6 内容生成模板保存后不可修改

### 根因

* `saveEditing()` 仅更新 L1\~L5，**完全没有发送任何 prompts 相关请求**

* L6 区域在编辑模式下**空白**，只渲染了 L1\~L5 的编辑 UI

### 修复方案

**前端 — \[ProductManagement.tsx]**

1. **编辑模式 L6 UI**：在 `{editingMode ? (<> ... </>` 的 L6 区域（当前为空）新增：

   * 每个 prompt 模板的可编辑卡片：模板名称输入框 + Prompt 文本 textarea + 删除按钮

   * 底部 "+ 添加模板" 按钮

   * `editData` 中新增 `prompts_json` 字段（JSON 序列化存储）

2. **`startEditing()`** 中新增：

   ```
   prompts_json: JSON.stringify(selected.prompts || [])
   ```

3. **`saveEditing()`** 末尾新增 prompts 更新逻辑：

   * 解析 `editData.prompts_json`

   * 调 `api.products.deleteAllPrompts(sku)` 清空旧模板（或逐个对比增量更新）

   * 逐个调 `api.products.addPrompt(sku, {...})` 添加新模板

**前端 — \[services/api.ts]**
14\. 新增 `products.deletePrompt(sku, promptId)` 方法（`DELETE /products/{sku}/prompts/{prompt_id}`）

**后端 — \[api/products.py] + \[services/product\_service.py]**
15\. 新增 `DELETE /products/{sku}/prompts/{prompt_id}` 端点
16\. 新增 `delete_product_prompt(db, prompt_id)` 服务函数

***

## Bug 4：上市时间可忽略月份和日期

### 根因

* 创建和编辑模式均使用 `type="date"`，HTML 强制要求完整 YYYY-MM-DD 格式

### 修复方案

**前端 — \[ProductManagement.tsx]**

1. **创建模式**：`<Field label="上市时间" type="date" />` 改为 `type="text"`，placeholder 改为 `"2025 或 2025-01 或 2025-01-15"`
2. **编辑模式**：`<input type="date" />` 改为 `type="text"`，同样支持三种格式

**后端 — \[schemas/product.py]**
19\. `launch_date` 字段类型从 `Optional[date]` 改为 `Optional[str]`，前端传什么后端存什么（保持 PostgreSQL/SQLite 的 `Date` 列仍可存字符串）

> **更优方案**：后端 `launch_date` 保持 `Optional[str]`，不做 date 类型转换，前端自由输入。Product model 中 `launch_date = Column(String, nullable=True)` 无需改动。

***

## 实施顺序

| 步骤 | Bug | 涉及文件                                  | 说明                                                                     |
| -- | --- | ------------------------------------- | ---------------------------------------------------------------------- |
| 1  | #4  | ProductManagement.tsx（2处）             | 上市时间 type="date" → type="text"                                         |
| 2  | #4  | schemas/product.py                    | launch\_date: Optional\[date] → Optional\[str]                         |
| 3  | #1  | schemas/product.py                    | ProductUpdate 新增 new\_sku                                              |
| 4  | #1  | product\_service.py                   | update\_product 支持 new\_sku 更新                                         |
| 5  | #1  | ProductManagement.tsx                 | L1 新增 SKU 编辑框，startEditing/saveEditing 适配                              |
| 6  | #2  | product\_media.py                     | 新增 channel\_media Text 字段                                              |
| 7  | #2  | schemas/product.py                    | 新增 ChannelMediaData + ProductMediaUpdate.channel\_media                |
| 8  | #2  | product\_service.py                   | \_make\_product\_detail / update\_product\_media 适配 channel\_media 序列化 |
| 9  | #2  | ProductManagement.tsx                 | L5 查看模式：渠道 Tab + 分组缩略图预览                                               |
| 10 | #2  | ProductManagement.tsx                 | L5 编辑模式：渠道 Tab + 3区上传控件                                                |
| 11 | #3  | api/products.py + product\_service.py | 新增 DELETE /products/{sku}/prompts/{prompt\_id}                         |
| 12 | #3  | api.ts                                | 新增 products.deletePrompt()                                             |
| 13 | #3  | ProductManagement.tsx                 | L6 编辑模式：可编辑卡片 + 添加/删除模板                                                |
| 14 | —   | 全量 TypeScript + Python 语法检查           | 编译验证                                                                   |

