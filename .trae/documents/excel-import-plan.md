# Excel 表格导入产品数据 — 技术方案

## 一、需求总结

| #  | 决策项          | 结论                                                       |
| -- | ------------ | -------------------------------------------------------- |
| 1  | 文件格式         | **Excel (.xlsx)**                                        |
| 2  | 数据量          | 批量导入为主（支持单产品）                                            |
| 3  | 表格1（L1-L4）结构 | **单 Sheet 分区**，包含 L1-L4 全部列                              |
| 4  | 表格2（L5）结构    | **单文件双 Sheet**（Sheet1=Q\&A库、Sheet2=差评应对），支持多文件上传         |
| 5  | 模板来源         | 公司已有在线文档模板，团队共填后下载上传                                     |
| 6  | 模板行结构        | 第1行=部门 / 第2行=说明 / 第3行=层级 / 第4行=列名 / 第5行=示例 / **第6行起=数据** |
| 7  | L5/L6/L7列    | 模板中包含 L5-L7 列，但**全部跳过**不解析（L5 列为链接，实际数据通过独立模板上传）         |
| 8  | L5产品关联       | 文件名前缀提取 SKU（如 `CW-C01-37_产品名.xlsx` → `CW-C01-37`）        |
| 9  | L5文件名解析失败    | **报错拒收**，提示"文件名格式不正确"                                    |
| 10 | SKU关联        | 按 SKU 列判断：新建或更新                                          |
| 11 | 上传入口         | **ProductManagement 产品管理列表页**，两个独立模块                     |
| 12 | 确认机制         | 导入 → **草稿箱** → 人工检查 → 发布                                 |
| 13 | 解析位置         | **前端**（SheetJS / xlsx 库）                                 |
| 14 | 已有SKU-数据一致   | **跳过**不处理                                                |
| 15 | 已有SKU-数据不一致  | **左右对比面板**（左=旧数据、右=新数据），差异字段**红色高亮**，逐条「确认」或「保留原数据」      |
| 16 | 新SKU         | **直接创建草稿**                                               |
| 17 | 数据结束判断       | **SKU 列为空即停止**                                           |
| 18 | 对比粒度         | **逐字段精确对比**                                              |
| 19 | 确认后目标        | 写入**草稿箱**，后续人工检查发布                                       |

***

## 二、列映射规则（Excel → 系统字段）

### 2.1 L1 产品身份

| Excel 列名 | 系统字段               | 解析规则                                        |
| -------- | ------------------ | ------------------------------------------- |
| SKU      | `sku`              | 直接取值，trim                                   |
| 条形码      | `barcode`          | 直接取值，trim                                   |
| 商品中文名称   | `name_zh`          | 直接取值                                        |
| 商品英文名称   | `name_en`          | 直接取值                                        |
| 上架渠道     | `listing_channel`  | 逗号分隔 → 数组 → `business_data.listing_channel` |
| 售卖地区     | `sales_region`     | 逗号分隔 → 数组 → `specs_data.sales_region`       |
| 品牌       | `brand`            | 直接取值                                        |
| 系列       | `series`           | 直接取值                                        |
| 系统分类     | `category`         | 直接取值                                        |
| 商品分级     | `grade`            | 直接取值                                        |
| 上市时间     | `launch_date`      | 日期转换（如 `2026/5/19` → `2026-05-19`）          |
| 生命周期     | `lifecycle`        | 直接取值                                        |
| 负责人      | `person_in_charge` | 直接取值                                        |

### 2.2 L2 物理规格

| Excel 列名 | 系统字段路径                     | 解析规则                                                   |
| -------- | -------------------------- | ------------------------------------------------------ |
| 尺寸信息     | `specs.dimension_lines`    | 按换行拆分，格式 `label:value unit` → `[{label, value, unit}]` |
| 容量信息     | `specs.capacity_lines`     | 按换行拆分，格式 `label + value` → `[{label, value}]`          |
| 毛重(g)    | `specs.gross_weight`       | 数字提取                                                   |
| 主体材质     | `specs.material`           | 直接取值                                                   |
| 主色系      | `specs.main_color`         | 直接取值                                                   |
| 表面处理     | `specs.surface_finish`     | 直接取值                                                   |
| 适用热源     | `specs.heat_source`        | 按换行拆分 → 逗号连接字符串                                        |
| 功率（炉具类）  | `specs.power_wattage`      | 直接取值                                                   |
| 技术优势     | `specs.tech_advantages`    | 按换行拆分，去序号 → 数组                                         |
| 认证信息     | `specs.certifications`     | 按换行拆分 → 数组                                             |
| 使用说明     | `specs.usage_instructions` | 直接取值（支持多行文本）                                           |

### 2.3 L3 商业价值

| Excel 列名  | 系统字段路径                         | 解析规则                  |
| --------- | ------------------------------ | --------------------- |
| 核心卖点 TOP5 | `business.core_selling_points` | 按换行拆分，去序号 → 数组        |
| 目标人群      | `business.target_audience`     | 直接取值（逗号分隔字符串）         |
| 差异化定位     | `business.differentiation`     | 直接取值                  |
| 价格定位带     | `business.price_positioning`   | 直接取值                  |
| 情感价值      | `business.emotional_value`     | 直接取值                  |
| 使用场景      | `business.use_scenarios`       | 按换行拆分 → 数组            |
| 竞品对标      | `business.competitors`         | 按换行拆分 → `[{name}]` 数组 |

### 2.4 L4 内容素材

| Excel 列名  | 系统字段路径                    | 解析规则                                    |
| --------- | ------------------------- | --------------------------------------- |
| 标题（英文）    | `content.amazon_title`    | 直接取值                                    |
| 标题（中文）    | `content.website_title`   | 直接取值                                    |
| 产品长描述（英文） | `content.listing_en`      | 直接取值                                    |
| 产品长描述（中文） | `content.listing_zh`      | 直接取值                                    |
| 搜索关键词库    | `content.search_keywords` | 按换行拆分 → `[{keyword, priority: 'B'}]` 数组 |

> ⚠️ **L5/L6/L7 列**（常见问题Q\&A库、差评高频词及应对话术、原始素材层及之后所有列）在 L1-L4 表格解析中**全部跳过**。L5 列为在线文档链接非实际数据，L5 知识库通过独立模板上传。

***

## 三、L5 独立模板结构

**Sheet1: Q\&A库**

| 列/位置                 | 系统字段路径                 | 解析规则                |
| -------------------- | ---------------------- | ------------------- |
| B列 Q内容               | `content.qa_items[].q` | 格式 `Q：问题文本`，提取冒号后内容 |
| C列 A内容               | `content.qa_items[].a` | 格式 `A：答案文本`，提取冒号后内容 |
| 每2行为一组（序号行+内容行），空行跳过 | —                      | —                   |

**Sheet2: 差评高频词及应对话术**

| 列/位置                 | 系统字段路径                                      | 解析规则                  |
| -------------------- | ------------------------------------------- | --------------------- |
| B列 差评词               | `content.negative_review_coping[].keyword`  | 格式 `差评词: xxx`，提取冒号后内容 |
| C列 话术                | `content.negative_review_coping[].response` | 格式 `话术：xxx`，提取冒号后内容   |
| 每2行为一组（序号行+内容行），空行跳过 | —                                           | —                     |

***

## 四、技术架构

```
┌──────────────────────────────────────────────────────────┐
│  ProductManagement.tsx                                    │
│  ┌────────────────────┐  ┌─────────────────────────────┐ │
│  │ 模块A: L1-L4 导入   │  │ 模块B: L5 知识库导入         │ │
│  │ [选择文件] [上传]   │  │ [选择文件(可多选)] [上传]    │ │
│  └────────┬───────────┘  └──────────────┬──────────────┘ │
│           │                             │                 │
│           ▼                             ▼                 │
│  ┌────────────────┐          ┌──────────────────┐        │
│  │ ExcelParser     │          │ L5ExcelParser     │        │
│  │ (xlsx 库解析)   │          │ (xlsx 库解析)     │        │
│  └────────┬───────┘          └────────┬─────────┘        │
│           │                           │                   │
│           ▼                           ▼                   │
│  ┌────────────────────────────────────────────┐          │
│  │  PreviewModal (预览确认弹窗)                 │          │
│  │  ┌──────────────────────────────────────┐  │          │
│  │  │ 解析结果表格（SKU/名称/操作类型/状态）  │  │          │
│  │  │ 对不一致SKU → 打开 ComparisonPanel     │  │          │
│  │  └──────────────────────────────────────┘  │          │
│  │  [全选] [确认导入草稿箱]                     │          │
│  └──────────────────┬─────────────────────────┘          │
│                     │                                     │
│                     ▼                                     │
│  ┌──────────────────────────────────────────┐            │
│  │ API: checkSkus() → 返回已有数据用于对比    │            │
│  │ API: drafts.createBatch() → 批量写入草稿   │            │
│  └──────────────────────────────────────────┘            │
└──────────────────────────────────────────────────────────┘
```

***

## 五、实施步骤

### Step 1: 安装前端依赖

```bash
cd frontend && npm install xlsx
```

### Step 2: 创建 Excel 解析器工具模块

**新文件**: `frontend/src/utils/excelParser.ts`

* `parseL1L4Excel(file: File): Promise<ImportRow[]>` — 解析 L1-L4 表格

  * 用 `xlsx` 库读取 Sheet1

  * 跳过前 5 行（部门/说明/层级/列名/示例）

  * 第 6 行起逐行解析，SKU 为空即停止

  * 跳过 L6/L7 列（原始素材层及之后）

  * 应用列映射规则（见第二章）

  * 返回 `ImportRow[]`

* `parseL5Excel(file: File): Promise<{sku: string, qaItems: QAItem[], reviewItems: ReviewItem[]}>`

  * 从文件名提取 SKU（正则：`/^([A-Z]+-\d+-\d+)/`）

  * 解析失败 → throw Error("文件名格式不正确，无法提取SKU")

  * 读取 Sheet1 → 解析 Q\&A 库

  * 读取 Sheet2 → 解析差评应对

  * 返回结构化数据

**解析辅助函数**:

* `parseMultilineToArray(cell: string): string[]` — 换行拆分 + 去序号 + trim

* `parseCommaSeparated(cell: string): string[]` — 逗号/顿号拆分

* `parseDimensionLines(cell: string): DimensionLine[]` — 解析尺寸如 `展开:φ14*28.5 cm`

* `parseCapacityLines(cell: string): CapacityLine[]` — 解析容量如 `锅900ml`

* `parseCompetitors(cell: string): {name: string}[]` — 竞品名列表

* `parseSearchKeywords(cell: string): {keyword: string, priority: string}[]` — 关键词库

* `parseDate(cell: string): string` — 日期格式统一转 `YYYY-MM-DD`

**类型定义**:

```typescript
interface ImportRow {
  sku: string
  name_zh: string
  action: 'create' | 'update_consistent' | 'update_conflict'
  existingData?: ProductDraft  // 已存在的数据（用于对比）
  newData: ImportProductData   // 从 Excel 解析的新数据
  diffFields?: string[]        // 差异字段列表
  selected: boolean            // 用户是否勾选导入
}

interface ImportProductData {
  sku: string; barcode?: string; name_zh?: string; name_en?: string;
  brand?: string; series?: string; category?: string;
  grade?: string; launch_date?: string; lifecycle?: string;
  person_in_charge?: string;
  specs_data: Record<string, any>;
  business_data: Record<string, any>;
  content_data: Record<string, any>;
}
```

### Step 3: 创建后端 API

**新文件/修改**: `backend/app/api/drafts.py`

新增端点：

```python
# POST /api/products/drafts/check-skus
# 入参: { "skus": ["CW-C01-37", "CW-C02-01"] }
# 返回: { "existing": { "CW-C01-37": {...完整draft或product数据...} }, "missing": ["CW-C02-01"] }
# 逻辑:
#   1. 先在 product_drafts 表中查（按 user_id + sku）
#   2. 再在 products 表中查（全局）
#   3. 已有数据返回完整的 ProductResponse 结构
#   4. 不存在的SKU放入 missing 列表
```

```python
# POST /api/products/drafts/batch
# 入参: { "items": [{...ProductDraftCreate...}, ...] }
# 返回: { "created": 3, "updated": 2, "skipped": 1 }
# 逻辑:
#   1. 逐条处理
#   2. SKU已存在草稿 → 更新该草稿
#   3. SKU不存在 → 创建新草稿
#   4. 返回计数统计
```

```python
# PUT /api/products/drafts/{draft_id}/content
# 入参: { "qa_items": [...], "review_tags": [...] }
# 逻辑: 更新指定草稿的 content_data 中 qa_items 和 negative_review_coping 字段
```

**修改**: `frontend/src/services/api.ts`

新增前端 API 方法：

```typescript
products: {
  checkSkus: (skus: string[]) => request<CheckSkusResponse>('/products/drafts/check-skus', { method: 'POST', body: JSON.stringify({ skus }) }),
}
drafts: {
  createBatch: (items: ProductDraftCreate[]) => request<BatchResult>('/products/drafts/batch', { method: 'POST', body: JSON.stringify({ items }) }),
  updateContent: (draftId: string, data: { qa_items: any[], review_tags: any[] }) => request(`/products/drafts/${draftId}/content`, { method: 'PUT', body: JSON.stringify(data) }),
}
```

### Step 4: 创建前端导入组件

**新文件**: `frontend/src/components/ProductImport/L1L4Importer.tsx`

L1-L4 导入模块：

* 文件选择 input（accept=".xlsx"）

* 点击「上传解析」→ 调 `parseL1L4Excel()` → 调 `api.products.checkSkus()` → 对比数据

* 展示预览结果表格

**新文件**: `frontend/src/components/ProductImport/L5Importer.tsx`

L5 知识库导入模块：

* 文件选择 input（accept=".xlsx", multiple）

* 支持多文件选择

* 每个文件解析后预览 SKU + Q\&A数量 + 差评条目数

**新文件**: `frontend/src/components/ProductImport/ImportPreviewTable.tsx`

预览表格组件：

* 列：复选框 | SKU | 产品名称 | 操作类型(新建/更新/跳过) | 状态(一致/有N个差异) | 操作按钮

* 不一致行：可点击「查看对比」展开 ComparisonPanel

* 底部：\[全选] \[反选] \[确认导入草稿箱] 按钮

* 导入完成后显示结果统计

**新文件**: `frontend/src/components/ProductImport/ComparisonPanel.tsx`

左右对比面板：

* 左侧：已有产品/草稿数据预览（L1-L5 分组展示）

* 右侧：Excel 新数据预览（L1-L5 分组展示）

* 差异字段：红色背景高亮

* 底部：\[确认采用新数据] \[保留原数据不更新]

### Step 5: 修改 ProductManagement 页面

**修改**: `frontend/src/pages/ProductManagement.tsx`

在页面顶部区域（搜索栏上方或右侧）添加两个导入模块入口：

```tsx
{/* 导入区域 */}
<div className="flex gap-4 mb-4">
  <L1L4Importer onImportComplete={handleL1L4ImportComplete} />
  <L5Importer onImportComplete={handleL5ImportComplete} />
</div>
```

状态管理：

```typescript
const [showImportPreview, setShowImportPreview] = useState(false)
const [importRows, setImportRows] = useState<ImportRow[]>([])
```

### Step 6: L5 后处理

L5 确认导入后：

1. 前端遍历确认的 L5 数据项
2. 根据 SKU 查找对应草稿（已有草稿 → 更新 content；无草稿 → 创建仅含 L5 数据的草稿）
3. 调用 `api.drafts.updateContent(draftId, { qa_items, review_tags })`

***

## 六、数据流完整时序

```
用户操作                       前端                          后端
───────────                  ──────                        ──────
1. 选择L1-L4文件 ──→ parseL1L4Excel()
                    返回 ImportProductData[]
                          │
2. 自动调用 ─────────→ POST /products/drafts/check-skus
                      ← { existing: {...}, missing: [...] }
                          │
3. 生成 ImportRow[]
   - missing SKU         → action='create'
   - existing + 全部一致  → action='update_consistent' (跳过)
   - existing + 有差异    → action='update_conflict'
                          │
4. 展示预览表格
   用户勾选/查看对比/逐条确认
                          │
5. 用户点击确认 ─────→ POST /products/drafts/batch
                     ← { created: N, updated: M, skipped: K }
                          │
6. 显示结果统计
   提示前往草稿箱检查
```

***

## 七、文件清单

| 操作     | 文件                                                             | 说明                                        |
| ------ | -------------------------------------------------------------- | ----------------------------------------- |
| **新增** | `frontend/src/utils/excelParser.ts`                            | Excel 解析核心工具                              |
| **新增** | `frontend/src/components/ProductImport/L1L4Importer.tsx`       | L1-L4 导入组件                                |
| **新增** | `frontend/src/components/ProductImport/L5Importer.tsx`         | L5 导入组件                                   |
| **新增** | `frontend/src/components/ProductImport/ImportPreviewTable.tsx` | 预览表格                                      |
| **新增** | `frontend/src/components/ProductImport/ComparisonPanel.tsx`    | 左右对比面板                                    |
| **修改** | `frontend/src/pages/ProductManagement.tsx`                     | 集成导入入口                                    |
| **修改** | `frontend/src/services/api.ts`                                 | 新增 API 方法                                 |
| **修改** | `backend/app/api/drafts.py`                                    | 新增 check-skus / batch / update-content 端点 |
| **修改** | `backend/app/services/draft_service.py`                        | 新增批量创建/查询服务逻辑                             |
| **安装** | `frontend/package.json`                                        | 添加 `xlsx` 依赖                              |

***

## 八、解析规则补充说明

### 尺寸信息解析示例

```
输入: "展开:φ14*28.5 cm\n\n收纳:φ14*16.5 cm\n锅:φ12.5*10 cm\n\n\n碗:φ12*5 cm"
输出: [
  { label: "展开", value: "φ14*28.5", unit: "cm" },
  { label: "收纳", value: "φ14*16.5", unit: "cm" },
  { label: "锅", value: "φ12.5*10", unit: "cm" },
  { label: "碗", value: "φ12*5", unit: "cm" }
]
```

### 技术优势/核心卖点解析

```
输入: "1.无涂层更安全 \n2.越用越好用 \n3.导热均匀"
输出: ["无涂层更安全", "越用越好用", "导热均匀"]
```

规则：按换行拆分 → 去除行首序号（`^\d+\.\s*`）→ trim → 过滤空行

### 竞品对标解析

```
输入: "火枫 寻味\n凯斯 露营锅"
输出: [{ name: "火枫 寻味" }, { name: "凯斯 露营锅" }]
```

### 日期解析

```
输入: "2026/5/19" 或 "2026-05-19" 或 "2026.5.19"
输出: "2026-05-19"
```

---

## 九、具体任务清单（共 13 步）


### Phase 1：基础设施搭建（可并行）

---

#### 任务 1.1：安装前端依赖

**操作**：在 `frontend/` 目录安装 `xlsx`（SheetJS）

```bash
cd frontend && npm install xlsx
```

**验证**：
```bash
cd frontend && node -e "const XLSX = require('xlsx'); console.log('xlsx version:', XLSX.version);"
```

---

#### 任务 1.2：创建类型定义

**文件**：`frontend/src/utils/excelParser.ts`（先只写类型）

```typescript
export interface ImportProductData {
  sku: string
  name_zh: string
  name_en: string
  barcode: string
  brand: string
  series: string
  category: string
  grade: string
  launch_date: string
  lifecycle: string
  person_in_charge: string
  specs_data: Record<string, any>
  business_data: Record<string, any>
  content_data: Record<string, any>
}

export interface ImportRow {
  index: number
  sku: string
  name_zh: string
  action: 'create' | 'update_consistent' | 'update_conflict'
  existingData?: ImportProductData
  newData: ImportProductData
  diffFields: string[]
  selected: boolean
  confirmed: boolean  // 用户在对比面板中是否已确认
}

export interface L5ImportData {
  sku: string
  qaItems: { q: string; a: string }[]
  reviewItems: { keyword: string; response: string }[]
}
```

**验证**：文件语法无误，TypeScript 编译通过。

---

### Phase 2：核心解析引擎

---

#### 任务 2.1：编写底层解析辅助函数

**文件**：`frontend/src/utils/excelParser.ts`（追加）

需要实现的纯函数（无副作用，方便单测）：

| 函数 | 输入 → 输出 |
|------|------------|
| `parseDate(raw)` | `"2026/5/19"` → `"2026-05-19"` |
| `parseMultilineToArray(raw)` | `"1.aaa\n2.bbb"` → `["aaa", "bbb"]` |
| `parseCommaSeparated(raw)` | `"淘宝,京东,Amazon"` → `["淘宝", "京东", "Amazon"]` |
| `parseDimensionLines(raw)` | `"展开:φ14*28.5 cm\n收纳:φ14*16.5 cm"` → `[{label, value, unit}]` |
| `parseCapacityLines(raw)` | `"锅900ml\n碗450ml"` → `[{label, value}]` |
| `parseCompetitors(raw)` | `"火枫 寻味\n凯斯 露营锅"` → `[{name}]` |
| `parseSearchKeywords(raw)` | `"cast iron\nnon-stick"` → `[{keyword, priority:"B"}]` |
| `extractSkuFromFilename(name)` | `"CW-C01-37_xxx.xlsx"` → `"CW-C01-37"` |

**验证 🧪**：编写一个临时测试脚本或直接在浏览器 console 中手动调函数验证。

---

#### 任务 2.2：编写 parseL1L4Excel 主函数

**文件**：`frontend/src/utils/excelParser.ts`（追加）

**核心逻辑**：
1. 用 `XLSX.read()` 读取 workbook，取 Sheet1
2. 转成二维数组 `XLSX.utils.sheet_to_json({ header: 1 })`
3. 取第 4 行作为列名映射表（`headerRow`），建立 `列名 → 列索引` 映射
4. 从第 6 行（`startRow = 5`，0-based）开始遍历
5. 每行：取 SKU → 空则 `break`
6. 根据列名映射提取 L1-L4 字段（找到"搜索关键词库"列后停止，后续 L5/L6/L7 跳过）
7. 应用解析辅助函数转换类型
8. 返回 `ImportProductData[]`

**验证 🧪**：
- 准备一个小的测试 `.xlsx` 文件（2-3 条数据）
- 写临时测试代码加载文件验证解析结果

---

#### 任务 2.3：编写 parseL5Excel 主函数

**文件**：`frontend/src/utils/excelParser.ts`（追加）

**核心逻辑**：
1. 从 `file.name` 提取 SKU → 正则 `/^([A-Z]+-\d+-\d+)/`
2. 失败则 `throw new Error("文件名格式不正确，无法提取SKU，请按 CW-C01-37_产品名.xlsx 格式命名")`
3. 读取 Sheet1（Q&A库）→ 按行扫描，跳过空行和间隔行，匹配 `Q：...` / `A：...` 模式
4. 读取 Sheet2（差评应对）→ 按行扫描，匹配 `差评词:...` / `话术：...` 模式
5. 返回 `L5ImportData`

**验证 🧪**：
- 准备一个测试 L5 `.xlsx` 文件
- 验证 SKU 提取正确、Q&A 和差评数据解析正确
- 验证不规范文件名抛出错误

---

### Phase 3：后端 API

---

#### 任务 3.1：后端 check-skus 接口

**文件 3.1a**：`backend/app/services/draft_service.py` — 追加函数

```python
async def check_skus(db: AsyncSession, skus: list[str], user_id: str) -> dict:
    """
    返回 { "existing": { sku: ProductResponse }, "missing": [sku] }
    """
    # 1. 查 product_drafts（当前用户的草稿，按 sku 去重取最新）
    # 2. 查 products（正式产品）
    # 3. 优先返回草稿数据，其次正式产品数据
    # 4. 不在以上两者的 SKU 放入 missing
```

**文件 3.1b**：`backend/app/api/drafts.py` — 追加路由

```python
@router.post("/check-skus")
async def check_skus(body: CheckSkusRequest, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await draft_service.check_skus(db, body.skus, current_user.id)
    return result
```

**验证 🧪**：
```bash
# 用 curl 测试
curl -X POST http://localhost:8000/api/products/drafts/check-skus \
  -H "Authorization: Bearer <token>" \
  -d '{"skus": ["CW-C01-37", "NOT-EXIST"]}'
```

---

#### 任务 3.2：后端 batch 批量创建/更新接口

**文件 3.2a**：`backend/app/services/draft_service.py` — 追加函数

```python
async def batch_create_or_update(db: AsyncSession, items: list[dict], user_id: str) -> dict:
    """
    返回 { "created": int, "updated": int, "skipped": int, "ids": [draft_id] }
    - 已存在同 SKU 的草稿（同一用户）→ 更新
    - 不存在 → 创建新草稿
    """
```

**文件 3.2b**：`backend/app/api/drafts.py` — 追加路由

```python
@router.post("/batch")
async def batch_import(body: BatchCreateRequest, db=Depends(get_db), current_user=Depends(get_current_user)):
    result = await draft_service.batch_create_or_update(db, body.items, current_user.id)
    return result
```

**验证 🧪**：
```bash
curl -X POST http://localhost:8000/api/products/drafts/batch \
  -H "Authorization: Bearer <token>" \
  -d '{"items": [{"sku":"TEST-01","name_zh":"测试产品","specs_data":{},"business_data":{},"content_data":{}}]}'
```

---

#### 任务 3.3：后端 update-content 接口

**文件 3.3a**：`backend/app/services/draft_service.py` — 追加函数

```python
async def update_draft_content(db: AsyncSession, draft_id: str, qa_items: list, review_tags: list, user_id: str) -> ProductDraft:
    # 获取草稿 → 权限校验 → 更新 content_data 中的 qa_items 和 negative_review_coping
```

**文件 3.3b**：`backend/app/api/drafts.py` — 追加路由

```python
@router.put("/{draft_id}/content")
async def update_content(draft_id: str, body: UpdateContentRequest, ...):
    ...
```

**验证 🧪**：
```bash
curl -X PUT http://localhost:8000/api/products/drafts/{draft_id}/content \
  -H "Authorization: Bearer <token>" \
  -d '{"qa_items":[{"q":"Q1","a":"A1"}],"review_tags":[{"keyword":"生锈","response":"养护方法..."}]}'
```

---

#### 任务 3.4：前端 API 方法对接

**文件**：`frontend/src/services/api.ts` — 追加

```typescript
products: {
  checkSkus: (skus: string[]) =>
    request<{ existing: Record<string, any>; missing: string[] }>(
      '/products/drafts/check-skus',
      { method: 'POST', body: JSON.stringify({ skus }) }
    ),
},

drafts: {
  // 已有方法...
  
  createBatch: (items: any[]) =>
    request<{ created: number; updated: number; skipped: number }>(
      '/products/drafts/batch',
      { method: 'POST', body: JSON.stringify({ items }) }
    ),
    
  updateContent: (draftId: string, data: { qa_items: any[]; review_tags: any[] }) =>
    request(`/products/drafts/${draftId}/content`, { method: 'PUT', body: JSON.stringify(data) }),
},
```

**验证 🧪**：
- 前端启动后，在浏览器 console 中调 `api.products.checkSkus(['CW-C01-37'])` 验证返回正常
- 验证后端三个接口在 Swagger docs 中可见

---

### Phase 4：UI 组件

---

#### 任务 4.1：创建文件上传基础组件

**文件**：`frontend/src/components/ProductImport/FileDropZone.tsx`

一个可复用的拖拽上传区域组件：

- 虚线边框区域 + 上传图标
- 支持点击选择文件和拖拽文件
- `accept` 属性控制文件类型
- `multiple` 属性控制是否多选
- 选择后回调 `onFiles(files: File[])`
- 显示文件名和大小

**Props**：`{ accept: string, multiple: boolean, onFiles: (files: File[]) => void, label: string }`

**验证 🧪**：
- 在浏览器中测试：点击选择文件 / 拖拽文件 / 多选
- 确认文件名字和大小显示正确

---

#### 任务 4.2：创建对比面板组件

**文件**：`frontend/src/components/ProductImport/ComparisonPanel.tsx`

左右双栏布局，差异字段红色高亮：

- **左侧**：已有产品/草稿数据，按 L1→L2→L3→L4 分组展示
- **右侧**：Excel 新数据，同样分组
- **差异高亮**：字段值不同时，新值侧 `bg-red-100 border-red-300`
- **底部按钮**：`[确认采用新数据]` / `[保留原数据不更新]`
- **Props**：`{ existing: ImportProductData, newData: ImportProductData, onConfirm: () => void, onSkip: () => void, onClose: () => void }`

**验证 🧪**：
- 构造两组不同的产品数据传入组件，确认差异字段正确高亮
- 点击确认/保留按钮后回调正确触发

---

#### 任务 4.3：创建预览表格组件

**文件**：`frontend/src/components/ProductImport/ImportPreviewTable.tsx`

**表格结构**：
```
| ☑ | SKU       | 产品名称        | 操作   | 状态              | 操作     |
|───|───────────|────────────────|────────|──────────────────|──────────|
| ☑ | CW-C01-37 | 野营锅7件套      | 更新   | ⚠ 有3个字段差异   | 查看对比  |
| ☑ | CW-C02-01 | 煎锅            | 新建   | 🆕 将创建草稿     | —        |
| — | CW-C01-01 | 炒锅            | 跳过   | ✅ 数据一致       | —        |
────────────────────────────────────────────────────────────────────────
[全选] [反选] 已选 2/3                     [确认导入草稿箱] [取消]
```

**功能**：
- 全选/反选/单行勾选
- 不一致行显示「查看对比」→ 打开 `ComparisonPanel`
- 确认后批量调 `api.drafts.createBatch()`
- 完成后弹 Toast 结果统计

**Props**：`{ rows: ImportRow[], onConfirm: (selectedRows) => Promise<void>, onClose: () => void }`

**验证 🧪**：
- 传入混合数据（新建、更新、跳过），确认表格渲染正确
- 勾选/全选/反选正确
- 打开对比面板正常

---

#### 任务 4.4：创建 L1-L4 导入组件

**文件**：`frontend/src/components/ProductImport/L1L4Importer.tsx`

**完整交互流程**：
1. 初始态：显示 `FileDropZone`（accept=".xlsx"，label="点击或拖拽上传 L1-L4 产品表格"）
2. 选择文件后：显示 loading → 调 `parseL1L4Excel(file)` 解析
3. 解析完成 → 提取全部 SKU → 调 `api.products.checkSkus(skus)`
4. 对比存量数据：
   - 不存在 SKU → `action='create'`
   - 存在 + 全部字段一致 → `action='update_consistent'`（默认不勾选）
   - 存在 + 有差异 → `action='update_conflict'`
5. 生成 `ImportRow[]` → 打开 `ImportPreviewTable`
6. 用户确认 → 调 `api.drafts.createBatch()` → 显示结果
7. 提供「前往草稿箱」链接

**状态机**：
```
IDLE → PARSING → COMPARING → PREVIEW → IMPORTING → DONE
  │        │          │          │          │
  └── 选文件  └── 解析Excel └── 查后端 └── 用户确认 └── 写入草稿
```

**Props**：`{ onImportComplete: () => void }`

**验证 🧪**：
- 准备一个真实的 Excel 文件上传
- 追踪完整流程：选择 → 解析 → 对比 → 预览 → 确认 → 导入
- 检查草稿箱中有新数据

---

#### 任务 4.5：创建 L5 导入组件

**文件**：`frontend/src/components/ProductImport/L5Importer.tsx`

**完整交互流程**：
1. 初始态：`FileDropZone`（accept=".xlsx", multiple, label="上传 L5 知识库表格（支持多文件）"）
2. 逐个文件：
   - 调 `parseL5Excel(file)` 解析
   - 成功 → 加入列表（文件名 / SKU / Q&A条数 / 差评条数）
   - 失败（SKU提取失败等）→ 跳过并显示错误提示
3. 全部解析完 → 展示文件预览列表
4. 用户确认 → 对每个已解析的文件：
   - 先查找 SKU 对应的草稿（调 check-skus 或 drafts.list）
   - 有草稿 → `api.drafts.updateContent(draftId, { qa_items, review_tags })`
   - 无草稿 → 创建仅含 SKU+content 的最小草稿
5. 显示导入完成结果

**Props**：`{ onImportComplete: () => void }`

**验证 🧪**：
- 上传 2-3 个 L5 文件（包含正确和错误文件名的）
- 验证 SKU 提取失败的文件被正确跳过
- 验证成功导入的数据在草稿箱中出现

---

### Phase 5：页面集成

---

#### 任务 5.1：集成到 ProductManagement 页面

**文件**：`frontend/src/pages/ProductManagement.tsx`

**变更**：
1. 导入两个组件：`L1L4Importer`、`L5Importer`
2. 在现有搜索栏下方新增一行「导入工具栏」：

```tsx
{/* 搜索栏 */}
<div className="flex items-center gap-3 mb-3">
  <input search... />
  <select category... />
</div>

{/* 导入工具栏 — 新增 */}
<div className="flex items-center gap-3 mb-4">
  <L1L4Importer onImportComplete={loadProducts} />
  <L5Importer onImportComplete={loadProducts} />
</div>

{/* 现有左右双栏布局 */}
<div className="flex ...">
  {/* 左侧列表 + 右侧详情 */}
</div>
```

**验证 🧪**：
- 页面加载后看到两个导入按钮/区域
- 执行一次完整导入流程（上传 Excel → 预览 → 确认 → 导入草稿箱）
- 导入后产品列表自动刷新
- 打开草稿箱确认数据存在
- 检查无 console 报错

---

### Phase 6：端到端集成测试

---

#### 任务 6.1：全流程集成测试（手动）

**准备**：
- 一个真实的 L1-L4 产品表格（至少包含 3 条数据：1 个新 SKU、1 个已存在且一致的 SKU、1 个已存在但部分字段不一致的 SKU）
- 一个 L5 知识库表格文件

**测试清单**：

| # | 测试场景 | 预期结果 |
|---|---------|---------|
| 1 | 上传 L1-L4 表格 | 解析成功，预览表格展示 3 行 |
| 2 | 新 SKU → 检查操作类型 | 显示「新建」绿色标签 |
| 3 | 一致 SKU → 检查状态 | 显示「数据一致，将跳过」灰色标签，默认不勾选 |
| 4 | 不一致 SKU → 查看对比 | 点击「查看对比」→ 左右面板显示，差异字段红色高亮 |
| 5 | 对比面板 → 点击确认 | 回到预览表格，该行勾选状态正确 |
| 6 | 对比面板 → 点击保留 | 该行取消勾选 |
| 7 | 点击「确认导入草稿箱」 | API 调用成功，显示结果统计 |
| 8 | 前往草稿箱 | 新 SKU 草稿已创建，更新 SKU 草稿已更新 |
| 9 | 上传 L5 表格 | 文件解析成功，显示 SKU + Q&A 数量 |
| 10 | 确认导入 L5 | 对应草稿的 content_data.qa_items 已写入 |
| 11 | 上传不规范文件名的 L5 | 错误提示，不进行解析 |
| 12 | 空 SKU 行停止解析 | Excel 中空 SKU 后的行不出现 |

---

#### 任务 6.2：异常场景测试

| # | 测试场景 | 预期结果 |
|---|---------|---------|
| 1 | 上传非 .xlsx 文件（如 .csv） | 无法选择或被拒绝 |
| 2 | 上传空的 Excel（无数据行） | 提示"未找到有效数据行" |
| 3 | 上传只有元数据行（无第6行） | 提示"未找到有效数据行" |
| 4 | 网络断开时上传 | 后续 API 调用失败，提示"网络错误" |
| 5 | 后端 check-skus 返回 500 | 前端显示错误提示，不崩溃 |

---

### Phase 7：后端验证

---

#### 任务 7.1：后端接口验证

在 Swagger docs（`/docs`）中或 curl 逐一验证：

| # | 接口 | 验证项 |
|---|------|-------|
| 1 | `POST /check-skus` | 传入已知 SKU → 返回 existing 含完整数据；传入未知 SKU → 在 missing 中 |
| 2 | `POST /batch` | 传入 3 条数据 → 返回 created/updated 计数正确 |
| 3 | `PUT /{id}/content` | 传入 QA 和差评数据 → 数据库中 content_data 字段正确更新 |
| 4 | 权限 | 非登录用户调接口 → 返回 401；非 owner 调 update-content → 返回 404 |

---

## 十、执行顺序（细化版）

| 顺序 | 任务 | 依赖 | 预计产出 |
|------|------|------|---------|
| 1.1 | 安装 xlsx 依赖 | 无 | package.json 更新 |
| 1.2 | 类型定义 | 1.1 | excelParser.ts（类型部分） |
| 2.1 | 解析辅助函数 | 1.2 | 8 个纯工具函数 |
| 2.2 | parseL1L4Excel | 2.1 | L1-L4 解析函数 |
| 2.3 | parseL5Excel | 2.1 | L5 解析函数 |
| 3.1 | 后端 check-skus | 无 | 新增 API 端点 |
| 3.2 | 后端 batch | 3.1 | 批量导入端点 |
| 3.3 | 后端 update-content | 3.1 | L5 更新端点 |
| 3.4 | 前端 api.ts | 无 | 3 个新 API 方法 |
| 4.1 | FileDropZone | 无 | 可复用上传组件 |
| 4.2 | ComparisonPanel | 无 | 对比面板 |
| 4.3 | ImportPreviewTable | 4.2 | 预览表格 |
| 4.4 | L1L4Importer | 2.2, 3.4, 4.1, 4.3 | L1-L4 导入流 |
| 4.5 | L5Importer | 2.3, 3.4, 4.1 | L5 导入流 |
| 5.1 | ProductManagement 集成 | 4.4, 4.5 | 页面功能完整 |
| 6.1 | 全流程集成测试 | 5.1 | 测试通过 |
| 6.2 | 异常场景测试 | 5.1 | 异常处理正确 |
| 7.1 | 后端接口验证 | 3.x | 所有端点正常 |

> **推荐执行顺序**：先并行做 1.1+1.2 → 接着 2.1→2.2→2.3（解析器） 和 3.1→3.2→3.3（后端API）→3.4 两路并行 → 然后 4.1→4.2→4.3→4.4→4.5（前端组件链） → 5.1 集成 → 6.1+6.2 测试

***

## 十一、L5 知识库共享功能

### 11.1 需求背景

同产品组的变体 SKU（如 `CW-C83`、`CW-C83-1`、`CW-C83-2`）需要共享同一份 L5 知识库（Q\&A + 差评话术）。变体通过引用主 SKU 自动同步内容，无需重复维护。

### 11.2 架构决策

| 决策项 | 结论 |
|--------|------|
| 共享粒度 | L5 整包（`qa_items` + `negative_review_coping`） |
| 存储模型 | 引用链接：变体 `ProductContent.shared_content_sku` → 主 SKU |
| 关联方向 | 变体视角：CW-C83-1 指向 CW-C83 |
| 存储位置 | `product_content` 表新增 `shared_content_sku` 列 |
| 关联时已有内容 | 丢弃（生产环境中变体不会单独填写 L5） |
| 解除关联 | 恢复空内容，不保留历史 |
| 链式共享 | 禁止：只能指向有真实内容的 SKU，不能指向已共享的变体 |
| 自我引用 | 禁止：不能关联自身 |
| 写入保护 | 已共享的变体禁止通过「导入L5」直接导入，需先取消关联 |

### 11.3 数据模型

**ProductContent 表新增列**：

```python
shared_content_sku: Mapped[str] = mapped_column(String(64), nullable=True)
```

**读取时自动解析**（`get_product_with_details`）：

```
查询 product_content
├── shared_content_sku 为空 → 正常返回自身 content
└── shared_content_sku 非空 → 查源 SKU 的 ProductContent
    ├── 原 qa_items → 替换为源 qa_items
    └── 原 negative_review_coping → 替换为源 negative_review_coping
    同时返回 shared_content_sku 字段供前端展示
```

### 11.4 后端 API

**Schema 新增**：

```python
class ShareContentRequest(BaseModel):
    source_sku: str
```

**端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `PUT` | `/products/{sku}/content/share` | `body: { source_sku }` → 关联共享 |
| `PUT` | `/products/{sku}/content/unshare` | 解除关联 |

**校验逻辑**：

- 变体 SKU 的 ProductContent 必须存在
- 不允许 `sku == source_sku`（自我引用）
- 源 SKU 的 ProductContent 必须存在
- 源 SKU 的 `shared_content_sku` 必须为空（不可链式）

### 11.5 前端 UI

**ProductManagement 预览面板 → L5 区域**：

```
📚 L5 - 知识库层

┌─ 知识库来源 ─────────────────────────┐
│ 未关联时：
│ [输入主 SKU...___________] [关联]    │
│                                       │
│ 已关联时：
│ 📎 共享自 CW-C83         [解除关联]  │
└───────────────────────────────────────┘

Q&A 库（8条）
差评话术（5条）
[导入L5] [编辑] [删除]
```

**L5 导入拦截**：已关联共享的 SKU 点击「导入L5」→ 提示"当前知识库共享自 XXX，请先取消关联后再导入"

### 11.6 修改文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **修改** | `backend/app/models/product_content.py` | 新增 `shared_content_sku` 列 |
| **修改** | `backend/app/schemas/product.py` | 新增 `ShareContentRequest` |
| **修改** | `backend/app/api/products.py` | 新增 `/share`、`/unshare` 端点 |
| **修改** | `backend/app/services/product_service.py` | 新增 `share_content`、`unshare_content`；`get_product_with_details` 增加共享解析 |
| **修改** | `backend/app/services/draft_service.py` | `publish_draft` 已有产品分支增加共享内容合并逻辑 |
| **修改** | `frontend/src/types/index.ts` | `ProductContent` 新增 `shared_content_sku` |
| **修改** | `frontend/src/services/api.ts` | 新增 `shareContent`、`unshareContent` |
| **修改** | `frontend/src/pages/ProductManagement.tsx` | 新增「知识库来源」UI 区域 + 共享处理器 |

### 11.7 数据流

```
CW-C83-1 关联 CW-C83：

1. 前端：ProductManagement 预览面板 → 输入"CW-C83" → 点击 [关联]
2. PUT /products/CW-C83-1/content/share { source_sku: "CW-C83" }
3. 后端：CW-C83-1.product_content.shared_content_sku = "CW-C83"
         CW-C83-1.product_content.qa_items = null
         CW-C83-1.product_content.negative_review_coping = null
4. 后续读取 CW-C83-1 时：
   → get_product_with_details → 检测 shared_content_sku="CW-C83"
   → 查 CW-C83 的 ProductContent → 返回其 qa_items + negative_review_coping
   → 响应中 content.shared_content_sku = "CW-C83"
5. 前端预览面板显示「📎 共享自 CW-C83」+ [解除关联]

CW-C83-1 解除关联：

1. PUT /products/CW-C83-1/content/unshare
2. 后端：CW-C83-1.product_content.shared_content_sku = null
3. 读取时恢复自身 content（此时为空）
```

