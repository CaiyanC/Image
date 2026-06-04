# 产品管理页面重构计划

## 决策总结

| # | 决策点 | 选择 |
|---|--------|------|
| 1 | 左侧列表形式 | 紧凑表格，和当前类似 |
| 2 | 右侧详情展示 | 六层全部展开平铺 |
| 3 | 草稿保存方式 | 按用户保存草稿，新增页面含「保存草稿」+「正式保存」两个按钮 |
| 4 | 草稿箱入口 | 产品管理页面顶部加按钮，草稿箱有独立列表 |
| 5 | 草稿存储 | 独立 `product_drafts` 表，与 `products` 表分离 |

---

## Step 1: 数据库 — 新建草稿表

### 后端 ORM 模型

创建 [product_draft.py](file:///e:/trea/AItool/backend/app/models/product_draft.py)

```python
class ProductDraft(Base):
    __tablename__ = "product_drafts"
    id: UUID (主键)
    user_id: String (创建者，外键 users.id)
    
    # L1 基本信息（同 products 表字段，sku 可为空/nullable）
    sku: String (可为空，正式保存时校验)
    barcode, brand, series, name_zh, name_en, name_ja
    category, sub_category
    retail_price, online_price
    retail_prices: Text(JSON)
    online_prices: Text(JSON)
    grade, is_active, sync_stock, person_in_charge, lifecycle
    launch_date
    
    # L2-L5 子表数据（JSON 列存储完整子对象）
    specs_data: JSON      # ProductSpecsBase 全量
    business_data: JSON   # ProductBusinessBase 全量
    content_data: JSON    # ProductContentBase 全量
    media_data: JSON      # ProductMediaBase 全量
    
    # L6 提示词模板
    prompts_data: JSON    # list of prompts
    
    # 草稿状态
    status: String        # 'draft' / 'ready'（ready=已确认待发布）
    
    created_at, updated_at
```

> **设计理由**：草稿不需要完整的关系型约束（sku 可能未填写），所有子数据用 JSON 列存储避免创建 5 张子草稿表。正式发布时再解包写入 products + 子表。

---

## Step 2: 后端 — Pydantic Schema

### [product.py](file:///e:/trea/AItool/backend/app/schemas/product.py) 扩展

```python
class ProductDraftCreate(BaseModel):
    """创建/保存草稿"""
    sku: Optional[str]
    # ... 所有 L1 字段 Optional
    specs_data: Optional[dict]
    business_data: Optional[dict]
    content_data: Optional[dict]
    media_data: Optional[dict]
    prompts_data: Optional[list]

class ProductDraftUpdate(ProductDraftCreate):
    """更新草稿"""
    pass

class ProductDraftResponse(BaseModel):
    """草稿响应"""
    id: str
    user_id: str
    status: str
    # ... 所有字段
    created_at: datetime
    updated_at: datetime

class ProductDraftListResponse(BaseModel):
    items: list[ProductDraftResponse]
    total: int

class ProductDraftPublish(BaseModel):
    """草稿正式发布请求"""
    draft_id: str
    # 可选覆盖 sku
```

---

## Step 3: 后端 — API 端点

### 草稿 API: [drafts.py](file:///e:/trea/AItool/backend/app/api/drafts.py)（新建）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/products/drafts` | 当前用户草稿列表（分页） |
| POST | `/api/products/drafts` | 创建/保存草稿 |
| GET | `/api/products/drafts/{id}` | 获取单个草稿详情 |
| PUT | `/api/products/drafts/{id}` | 更新草稿 |
| DELETE | `/api/products/drafts/{id}` | 删除草稿 |
| POST | `/api/products/drafts/{id}/publish` | 正式发布草稿（→创建 products 记录） |

### 草稿服务: [draft_service.py](file:///e:/trea/AItool/backend/app/services/draft_service.py)（新建）

核心函数：
- `get_user_drafts(db, user_id, skip, limit)` — 分页查当前用户的草稿
- `get_draft_by_id(db, draft_id)` — 单查草稿
- `create_draft(db, user_id, data)` — 创建草稿
- `update_draft(db, draft_id, data)` — 更新草稿
- `delete_draft(db, draft_id)` — 删除草稿
- `publish_draft(db, draft_id)` — 发布草稿：
  1. 校验必填字段（sku 不能为空）
  2. 检查 sku 是否已存在
  3. 调用 `product_service.create_product()` 写入 products + 子表
  4. 删除草稿或标记为 published

---

## Step 4: 前端 — 产品管理页面重构

### 4.1 ProductManagement.tsx 左右分栏改造

```
┌─────────────────────────────────────────────────────┐
│  产品管理                [新增产品] [草稿箱(3)] [搜索] │  ← 顶部工具栏
├──────────────────┬──────────────────────────────────┤
│  左侧 320px      │  右侧 (剩余空间)                  │
│  ┌──────────────┐│  ┌──────────────────────────────┐│
│  │ 产品列表表格  ││  │ L1 基本信息                    ││
│  │ SKU │ 名称   ││  │ ──────────────────────────── ││
│  │ xxx │ ...   ││  │ SKU: xxx  品牌: xxx          ││
│  │ xxx │ ...   ││  │ ...                           ││
│  │ xxx │ ...   ││  │                               ││
│  │             ││  │ L2 物理规格                    ││
│  │             ││  │ ──────────────────────────── ││
│  │             ││  │ ...                           ││
│  │             ││  │                               ││
│  │             ││  │ L3 商业价值                    ││
│  │ 分页控件    ││  │ ...                           ││
│  └──────────────┘│  │                               ││
│                  │  │ L4-L6 ...                     ││
│                  │  └──────────────────────────────┘│
└──────────────────┴──────────────────────────────────┘
```

**改动要点**：
- 顶部：新增产品按钮、草稿箱按钮(带数量)、搜索框
- 左侧：表格保留 SKU/名称/品牌/分类 列，点击行选中高亮，右侧联动展示
- 右侧：选中产品后展示六层全部展开平铺（只读预览模式），含编辑/删除按钮
- 搜索和分页逻辑不变

### 4.2 抽离组件

从 1743 行的单文件拆分为：
| 组件 | 文件 | 职责 |
|------|------|------|
| `ProductTable` | `components/ProductTable.tsx` | 左侧产品列表表格 + 分页 |
| `ProductDetail` | `components/ProductDetail.tsx` | 右侧六层详情只读展示 |
| `DraftBox` | `components/DraftBox.tsx` | 草稿箱弹窗/侧边栏 |
| `ProductManagement` | `pages/ProductManagement.tsx` | 顶层容器（左右布局 + 状态管理） |

### 4.3 新增产品页面

文件名：[ProductCreate.tsx](file:///e:/trea/AItool/frontend/src/pages/ProductCreate.tsx)（新建）

```
┌─────────────────────────────────────────────────────┐
│  ← 返回产品管理    新增产品    [保存草稿] [正式保存]  │  ← 顶部
├─────────────────────────────────────────────────────┤
│  L1 基本信息 (折叠面板)                              │
│  ┌─────────────────────────────────────────────────┐│
│  │ SKU: [___]  品牌: [___]  名称: [___]            ││
│  │ ...                                             ││
│  └─────────────────────────────────────────────────┘│
│                                                      │
│  L2 物理规格 (折叠面板)                               │
│  ┌─────────────────────────────────────────────────┐│
│  │ ...                                             ││
│  └─────────────────────────────────────────────────┘│
│  L3-L6 ...                                          │
└─────────────────────────────────────────────────────┘
```

**功能**：
- 六层折叠面板（Accordion），方便逐层填写
- 「保存草稿」→ 调用 `POST /api/products/drafts`，成功后提示可返回草稿箱继续编辑
- 「正式保存」→ 先调草稿保存，再调 `POST /api/products/drafts/{id}/publish`
- 如果是草稿箱点击"继续编辑"，则回填已有草稿数据（`GET /api/products/drafts/{id}`）
- 表单字段与现有 ProductCreate schema 一致

### 4.4 草稿箱弹窗

文件名：[DraftBox.tsx](file:///e:/trea/AItool/frontend/src/components/DraftBox.tsx)（新建）

```
┌─────────────────────────────────────┐
│  草稿箱                        [×]  │
├─────────────────────────────────────┤
│  SKU       │ 名称    │ 更新时间     │
│  (空)      │ 登山杖  │ 05-13 14:30 │  [继续编辑] [删除]
│  MM-001    │ 钛锅    │ 05-12 10:00 │  [继续编辑] [删除]
│            │        │             │
│  共 3 条草稿                        │
└─────────────────────────────────────┘
```

**功能**：
- 仅显示当前用户的草稿
- 点击「继续编辑」→ 跳转 `ProductCreate.tsx` 并传入 `draft_id`
- 点击「删除」→ 二次确认后删除草稿
- 弹窗/侧边栏形式（推荐 Modal），不影响主页面

---

## Step 5: 前端 — API & 类型 & 路由

### API 扩展 [api.ts](file:///e:/trea/AItool/frontend/src/services/api.ts)

```typescript
drafts: {
    list: (skip, limit) => request(`/products/drafts?skip=${skip}&limit=${limit}`),
    get: (id: string) => request(`/products/drafts/${id}`),
    create: (data: ProductDraftCreate) => request('/products/drafts', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: string, data: ProductDraftUpdate) => request(`/products/drafts/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: string) => request(`/products/drafts/${id}`, { method: 'DELETE' }),
    publish: (id: string) => request(`/products/drafts/${id}/publish`, { method: 'POST' }),
}
```

### 类型扩展 [types/index.ts](file:///e:/trea/AItool/frontend/src/types/index.ts)

```typescript
export interface ProductDraft {
  id: string
  user_id: string
  sku?: string
  brand?: string
  series?: string
  name_zh?: string
  name_en?: string
  name_ja?: string
  // ... 所有 L1 字段
  specs_data?: Record<string, any>
  business_data?: Record<string, any>
  content_data?: Record<string, any>
  media_data?: Record<string, any>
  prompts_data?: any[]
  status: 'draft' | 'ready'
  created_at: string
  updated_at: string
}

export interface ProductDraftListResponse {
  items: ProductDraft[]
  total: number
}
```

### 路由 [App.tsx]

```tsx
<Route path="/products" element={<ProductManagement />} />
<Route path="/products/create" element={<ProductCreate />} />
<Route path="/products/create/:draftId" element={<ProductCreate />} />
```

---

## Step 6: 验证

- TypeScript 编译 `npx tsc --noEmit` 零错误
- 后端启动无报错
- 新增产品 → 保存草稿 → 草稿箱可见 → 继续编辑 → 正式保存 → 产品列表可见
- 左右分栏：点击左侧产品，右侧联动展示详情

---

## 执行顺序

| 顺序 | 步骤 | 内容 |
|------|------|------|
| 1 | Step 1 | 数据库 ORM 模型 |
| 2 | Step 2 | Pydantic Schema |
| 3 | Step 3 | 后端 API + 服务层 |
| 4 | Step 4.3 | 新增产品页面 ProductCreate.tsx |
| 5 | Step 4.4 | 草稿箱组件 DraftBox.tsx |
| 6 | Step 4.1/4.2 | 产品管理左右分栏 + 组件拆分 |
| 7 | Step 5 | 前端 API + 类型 + 路由 |
| 8 | Step 6 | 编译验证 + 功能验证 |
