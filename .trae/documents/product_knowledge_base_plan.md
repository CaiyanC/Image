# 产品知识库重构与 AI Agent 基础实施方案

## 一、项目背景与目标

将当前产品数据存储方式（SQLite + UUID 平铺文件）重构为**以 SKU 为文件夹的知识库结构**，使其成为未来 AI Agent（对话式产品助手）的可读数据基础。

当前系统：Python (FastAPI) 后端 + React (TypeScript + Vite) 前端 + SQLite 数据库。

---

## 二、目标架构

### 2.1 文件夹结构总览

```
{KNOWLEDGE_BASE_DIR}/              # 可配置根目录（Docker 卷挂载点）
├── _index.json                    # 全局索引（所有 SKU 列表 + 元数据摘要）
├── CW001-BK/                      # 产品文件夹（以 SKU 命名）
│   ├── L1_基础信息.md
│   ├── L2_物理规格.md
│   ├── L3_商业信息.md
│   ├── L4_内容素材.md
│   ├── L5_知识库.md
│   ├── L6/
│   │   ├── 原始素材层/
│   │   │   ├── 白底图/
│   │   │   ├── 多角度图/
│   │   │   ├── 结构图/
│   │   │   ├── 爆炸图/
│   │   │   ├── 尺寸图/
│   │   │   ├── 功能示意图/
│   │   │   ├── 使用步骤图/
│   │   │   ├── 收纳图/
│   │   │   ├── 配件图/
│   │   │   ├── 套装图/
│   │   │   ├── 3D渲染图/
│   │   │   └── 户外场景图/
│   │   ├── AI层/
│   │   │   └── AI生成图/
│   │   ├── 渠道层/              # 文件含渠道标签+版本标签
│   │   │   ├── 电商主图/
│   │   │   └── 详情页模块图/
│   │   ├── 社媒层/
│   │   │   ├── 社媒传播图/
│   │   │   ├── 广告投放图/
│   │   │   └── 视频素材/
│   │   └── 参考辅助层/
│   │       ├── 包装图/
│   │       ├── 说明书插图/
│   │       ├── 认证测试图/
│   │       ├── 经销商素材/
│   │       ├── 品牌风格参考图/
│   │       ├── 竞品参考图/
│   │       ├── 历史归档图/
│   │       └── 禁用素材/
│   └── L7_AI提示词/              # 待后续设计
│       └── ...
├── ST001-TI/
│   └── ...
└── ...
```

### 2.2 数据分层定义

| 层级 | 数据来源 | 内容 | 存储格式 |
|------|----------|------|----------|
| **L1** | `products` 主表 | 基础信息：SKU/品名/品牌/分类/价格/渠道/生命周期 | Markdown（混合型） |
| **L2** | `product_specs` 表 | 物理规格：尺寸/重量/材质/表面处理/功率/热源/认证 | Markdown（混合型） |
| **L3** | `product_business` 表 | 商业信息：核心卖点/目标人群/差异化定位/竞品对标/场景 | Markdown（混合型） |
| **L4** | `product_content` 表 | 内容素材：Amazon标题/五点描述/长描述(中英日)/搜索关键词 | Markdown（混合型） |
| **L5** | `product_content` 表 | 知识库：QA对/差评关键词/差评应对话术 | Markdown（混合型） |
| **L6** | `product_media` 表 | 图片+视频（33个字段 → 5层20+子文件夹） | 原始文件（图片/视频/PDF） |
| **L7** | `product_prompts` 表 | AI提示词模板（参数/版本/使用次数） | 待设计 |

### 2.3 文件命名规则

**标准命名公式（9段，下划线分隔）：**

```
品牌_产品ID_SKU_素材类型_角度或场景_渠道_语言_版本_日期_状态.扩展名
```

**段位说明：**

| 段位 | 名称 | 来源 | 示例 |
|------|------|------|------|
| 1 | 品牌 | 表单字段 | ALOCS |
| 2 | 产品ID | 表单字段 | P-CW001 |
| 3 | SKU | 表单字段 | CW001-BK |
| 4 | 素材类型 | 上传格子/插槽自动推断 | White / Size / Scene / Structure / Usage / Detail / Storage / Dealer / AI / Competitor / Reference |
| 5 | 角度或场景 | 上传时用户指定 | Front / Top / FamilyCamping / BurnerHead / FlameControl |
| 6 | 渠道 | 上传时用户指定 | Global / Amazon / Tmall / JD / Instagram / TikTok / Internal |
| 7 | 语言 | 上传时用户指定 | NoText / EN / CN / JA |
| 8 | 版本 | 上传时用户指定（默认V1） | V1 / V2 / V0.8 |
| 9 | 日期 | 自动生成（上传当天） | 20260518 |
| 10 | 状态 | 上传时用户指定 / 审核后更新 | Approved / Internal / AIReview / Archive / Forbidden |

**命名示例：**

```
ALOCS_P-CW001_CW001-BK_White_Front_Global_NoText_V1_20260518_Approved.jpg
ALOCS_P-CW001_CW001-BK_Size_Top_Amazon_EN_V1_20260518_Approved.jpg
ALOCS_P-CW001_CW001-BK_Scene_FamilyCamping_Instagram_EN_V1_20260518_Approved.jpg
ALOCS_P-ST001_ST001-TI_Structure_BurnerHead_Global_NoText_V2_20260518_Internal.png
ALOCS_P-ST001_ST001-TI_Usage_IgnitionGuide_Global_EN_V2_20260518_Approved.jpg
```

---

## 三、数据流与架构关系

### 3.1 Source of Truth 策略

```
Web 表单 (React) ──保存/发布──▶ SQLite 数据库 (Source of Truth)
                                      │
                                      │ 发布产品时自动触发
                                      ▼
                               product_knowledge/{SKU}/
                               ├── L1~L5 Markdown 文件
                               └── L6 媒体文件（写入对应子文件夹）
                                      │
                                      │ AI Agent 只读访问
                                      ▼
                               AI Agent (对话式产品助手)
```

- **数据库** = 主数据源（Source of Truth），Web CRUD 操作写数据库
- **文件系统** = 导出产物，AI Agent 只读
- **同步时机** = 产品发布时自动生成；支持手动"重新导出"按钮

### 3.2 AI Agent 消费路径

| 阶段 | 方式 | 说明 |
|------|------|------|
| **Phase 1** | 直接文件系统访问 | Agent 有 `product_knowledge/` 目录读取权限，通过工具调用读 `.md`、glob 图片路径 |
| **Phase 2** | RAG（向量检索增强生成） | Markdown 内容向量化存入向量库，支持语义搜索；图片路径作为元数据返回 |

### 3.3 AI Agent 服务角色（9 角色）

| 角色 | 典型查询 | 依赖层级 |
|------|----------|----------|
| AI 客服 | 结构、配件、安装、使用、安全问题 | L1, L2, L5, L6(客服用图) |
| 电商运营 | 主图、详情页、卖点图、尺寸图、收纳图、场景图 | L3, L6(原始素材层) |
| 海外营销 | Amazon/独立站/社媒/达人/广告素材 | L4, L6(渠道层+社媒层) |
| 国内营销 | 天猫/京东/拼多多/小红书/抖音素材 | L4, L6(渠道层) |
| 产品经理 | 产品版本、结构变化、卖点、用户反馈 | L1~L5, L6(参考辅助层) |
| 研发人员 | 结构图、爆炸图、配件关系、改版差异 | L2, L6(结构图/爆炸图) |
| 经销商/分销商 | 标准化对外资料包 | L1~L4, L6(经销商素材) |
| AI 视觉生成 | 真实产品图、结构图、风格参考图 | L6(全部层级) |
| 管理层 | 产品线素材完整度、品牌视觉一致性 | L1, L3, L6(全局索引) |

---

## 四、上传流程重构

### 4.1 当前问题

- 文件上传后 UUID 随机命名，与 SKU 无关
- 所有文件平铺在 `uploads/images/` 和 `uploads/videos/`
- 前端按 33 个 media 字段分别存储 URL 的 JSON

### 4.2 新上传流程

```
用户操作流程：
1. 在表单中选择上传区域（格子/插槽），如 "L6 > 原始素材层 > 结构图"
2. 批量选择文件 → 系统自动推断：
     素材类型 = "Structure"（根据所在格子推断）
3. 用户补填角度/场景、渠道、语言、版本、状态（可给默认值）
4. 品牌、产品ID、SKU 从表单当前上下文自动填充
5. 上传 → 后端按命名规则生成文件名 → 写入对应子文件夹
6. 前端 media 状态中存储最终文件路径
```

### 4.3 渠道层特殊处理

渠道层文件需额外携带：
- **渠道标签**：标识渠道唯一性（Amazon / Tmall / JD / 独立站 / 小红书 / 抖音 等）
- **版本标签**：同一渠道同一素材的多版本管理（V1, V2...）

标签体现方式：
- 文件名中的渠道段（第6段）+ 版本段（第8段）
- 各渠道子文件夹（渠道层 > 电商主图/详情页模块图 下按渠道再分子文件夹）

---

## 五、Markdown 模板设计

### 5.1 L1 基础信息.md

```markdown
# L1 基础信息 — {SKU}

## 基本信息

| 属性 | 值 |
|------|-----|
| SKU | {sku} |
| 条形码 | {barcode} |
| 品牌 | {brand} |
| 系列 | {series} |
| 中文名称 | {name_zh} |
| 英文名称 | {name_en} |
| 日文名称 | {name_ja} |
| 系统分类 | {category} |
| 子分类 | {sub_category} |
| 商品分级 | {grade} |
| 负责人 | {person_in_charge} |

## 价格信息

| 币种 | 零售价 | 线上售价 |
|------|--------|----------|
| ... | ... | ... |

## 渠道与区域

上架渠道：{listing_channel}
售卖地区：{sales_region}

## 生命周期

状态：{lifecycle}
上市时间：{launch_date}
库存同步：{sync_stock}
启用状态：{is_active}
```

### 5.2 L2 物理规格.md

```markdown
# L2 物理规格 — {SKU}

## 尺寸与重量

| 名称 | 规格 |
|------|------|
| ... | ... |

毛重：{gross_weight}g

## 材质与工艺

| 属性 | 值 |
|------|-----|
| 主体材质 | {material} |
| 表面处理 | {surface_finish} |
| 主色系 | {main_color} |

## 电气与热源

| 属性 | 值 |
|------|-----|
| 功率 | {power_wattage} |
| 适用热源 | {heat_source} |

## 容量

| 名称 | 容量 |
|------|------|
| ... | ... |

## 认证

{认证列表}

## 技术优势

{技术优势文字描述}

## 使用说明

{使用说明文字描述}
```

### 5.3 L3 商业信息.md

```markdown
# L3 商业信息 — {SKU}

## 核心卖点 TOP5

1. {卖点1}
2. {卖点2}
...

## 目标人群

{目标人群描述}

## 差异化定位

{差异化定位文字}

## 价格定位

{price_positioning}

## 情感价值

{emotional_value}

## 使用场景

- {场景1}
- {场景2}
...

## 竞品对标

| 竞品 | 对比维度 | 优劣势 |
|------|----------|--------|
| ... | ... | ... |
```

### 5.4 L4 内容素材.md

```markdown
# L4 内容素材 — {SKU}

## Amazon 标题

{amazon_title}

## 官网标题

{website_title}

## 五点描述

1. {bullet_1}
2. {bullet_2}
...

## 产品长描述

### 中文
{listing_zh}

### 英文
{listing_en}

### 日文
{listing_ja}

## A+ 内容

{a_plus_content}

## 搜索关键词

{关键词列表}
```

### 5.5 L5 知识库.md

```markdown
# L5 知识库 — {SKU}

## 常见问题 Q&A

### Q: {问题1}
A: {回答1}

### Q: {问题2}
A: {回答2}
...

## 评论标签

{标签列表}

## 差评关键词与应对话术

| 关键词 | 出现频率 | 应对话术 |
|--------|----------|----------|
| ... | ... | ... |
```

---

## 六、数据库分离设计

### 6.1 双库架构

将当前单一 `app.db` 拆分为两个独立的 SQLite 数据库文件：

| 数据库 | 文件位置 | Docker 卷 | 用途 | 包含表 |
|--------|----------|-----------|------|--------|
| **系统运行库** | `data/system.db` | `aitool_system` | Web 应用运行 | `users`, `product_drafts`, 系统配置/日志表 |
| **产品知识库** | `product_knowledge/product_knowledge.db` | `aitool_knowledge` | 产品数据存储 + AI Agent 读取 | `products`, `product_specs`, `product_business`, `product_content`, `product_media`, `product_prompts` |

### 6.2 设计原则

- **系统库** 独立于知识库，Web 应用运行时使用，不与 AI Agent 共享
- **产品知识库** 放在知识库卷 `aitool_knowledge` 内，与 Markdown / 图片 / 视频打包在一起，形成自包含的知识包
- AI Agent 只需挂载 `aitool_knowledge` 一个卷，即可获得全部产品数据（SQLite + Markdown + 媒体文件）
- 知识库卷可独立备份/迁移/挂载到其他服务

### 6.3 知识库卷自包含结构

```
/app/product_knowledge/          # aitool_knowledge 卷
├── _index.json                  # 全局索引
├── product_knowledge.db         # 产品知识库 SQLite（6 张产品表）
├── CW001-BK/                    # 产品文件夹
│   ├── L1_基础信息.md
│   ├── L2_物理规格.md
│   ├── L3_商业信息.md
│   ├── L4_内容素材.md
│   ├── L5_知识库.md
│   ├── L6/
│   │   ├── 原始素材层/
│   │   ├── AI层/
│   │   ├── 渠道层/
│   │   ├── 社媒层/
│   │   └── 参考辅助层/
│   └── L7_AI提示词/
└── ST001-TI/
    └── ...
```

### 6.4 后端数据库连接配置

在 `backend/app/core/config.py` 中新增：

```python
# 系统运行库路径
SYSTEM_DATABASE_URL: str = os.getenv(
    "SYSTEM_DATABASE_URL",
    f"sqlite:///{os.path.join(DATA_DIR, 'system.db')}"
)

# 产品知识库路径（放在知识库卷内）
PRODUCT_DATABASE_URL: str = os.getenv(
    "PRODUCT_DATABASE_URL",
    f"sqlite:///{os.path.join(KNOWLEDGE_BASE_DIR, 'product_knowledge.db')}"
)
```

### 6.5 后端 ORM 改造要点

- `database.py` 需维护两个 SQLAlchemy `engine` + `SessionLocal`：
  - `system_engine` / `SystemSessionLocal` — 连接 `system.db`
  - `product_engine` / `ProductSessionLocal` — 连接 `product_knowledge.db`
- 所有产品相关 CRUD（`product_service.py`、`draft_service.py` 产品部分）使用 `ProductSessionLocal`
- 用户/草稿相关 CRUD 使用 `SystemSessionLocal`
- `product_drafts` 表属于系统库，与其关联的产品数据字段是草稿的临时快照
- 产品发布流程：`SystemSessionLocal` 读草稿 → `ProductSessionLocal` 写入产品表 → 文件系统导出 Markdown/图片

---

## 七、Docker 部署考量

### 7.1 目录挂载

```yaml
# docker-compose.yml 片段
services:
  backend:
    image: aitool-backend:latest
    volumes:
      - aitool_knowledge:/app/product_knowledge   # 知识库卷（含 product_knowledge.db + Markdown + 媒体文件）
      - aitool_uploads:/app/uploads                # 旧上传目录（兼容过渡）
      - aitool_system:/app/data                    # 系统运行库卷（含 system.db）
    environment:
      - KNOWLEDGE_BASE_DIR=/app/product_knowledge

volumes:
  aitool_knowledge:    # 知识库卷：自包含，可独立挂载给 AI Agent
  aitool_uploads:
  aitool_system:       # 系统卷：Web 应用专用
```

### 7.2 可配置路径

在 `backend/app/core/config.py` 中新增：

```python
# 知识库根目录配置
KNOWLEDGE_BASE_DIR: str = os.getenv(
    "KNOWLEDGE_BASE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "product_knowledge")
)

# 系统数据目录
DATA_DIR: str = os.getenv(
    "DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
)
```

---

## 七、实施步骤

### Phase 0：数据库分离与准备工作
- [ ] 确认当前产品数据完整性（有哪些 SKU 已入库）
- [ ] 备份现有数据库和 `uploads/` 目录
- [ ] 在 `config.py` 添加 `KNOWLEDGE_BASE_DIR`、`DATA_DIR`、`SYSTEM_DATABASE_URL`、`PRODUCT_DATABASE_URL` 配置项
- [ ] 重构 `database.py`：双引擎 + 双 SessionLocal（`system_engine` / `product_engine`）
- [ ] 将现有 7 张产品表迁移至 `product_knowledge.db`，草稿表和用户表留在 `system.db`
- [ ] 更新 `product_service.py`、`draft_service.py` 使用对应的 Session
- [ ] 创建 `product_knowledge/` 目录结构模板

### Phase 1：后端知识库生成服务
- [ ] 创建 `backend/app/services/knowledge_exporter.py`
  - `export_product_to_filesystem(db, sku)` — 单产品导出
  - `export_all_products(db)` — 全量导出
  - `delete_product_knowledge(sku)` — 删除单个产品文件夹
- [ ] 实现 L1~L5 Markdown 生成函数
- [ ] 实现 L6 子文件夹结构创建
- [ ] 实现 `_index.json` 全局索引更新逻辑
- [ ] 添加 API 端点：
  - `POST /api/products/{sku}/export` — 手动导出单个产品
  - `GET /api/knowledge-base/index` — 获取全局索引
  - `POST /api/knowledge-base/export-all` — 全量导出

### Phase 2：后端上传流程重构
- [ ] 修改 `POST /api/products/images/upload` 端点
  - 接收额外参数：素材类型、角度/场景、渠道、语言、版本、状态
  - 按命名规则生成文件名
  - 写入 `product_knowledge/{sku}/L6/{层级}/{子文件夹}/` 对应位置
  - 默认值策略：版本=V1、状态=Internal、渠道=Global、语言=NoText
- [ ] 同样重构视频上传端点
- [ ] 添加文件重命名/移动的 API（支持后期调整）

### Phase 3：前端上传组件重构
- [ ] 重构 `ProductCreate.tsx` 的媒体上传区域
  - 按 5 层 20+ 子文件夹结构组织上传格子/插槽
  - 每个上传格子自动携带对应的素材类型标签
- [ ] 添加上传时的附加信息填写（角度/场景、渠道、语言、版本、状态）
  - 角度/场景：必填输入
  - 渠道：下拉选择（Global/Amazon/Tmall/JD/Instagram/TikTok/小红书/抖音/Internal）
  - 语言：下拉选择（NoText/EN/CN/JA）
  - 版本：输入（默认 V1）
  - 状态：下拉选择（Approved/Internal/AIReview/Archive/Forbidden，默认 Internal）
- [ ] 前端 media 状态调整为存储文件路径而非 URL
- [ ] 文件名预览（实时显示生成的完整文件名）

### Phase 4：发布流程集成
- [ ] 修改 `product_service.create_product()` 和 `draft_service.publish_draft()`
  - 产品发布成功后自动调用 `export_product_to_filesystem()`
- [ ] 在产品管理界面添加"重新导出到知识库"按钮
- [ ] 添加知识库导出状态提示（成功/失败/进行中）

### Phase 5：兼容与迁移
- [ ] 保持当前 `uploads/` 结构在过渡期并存
- [ ] 提供一键迁移脚本，将现有 SKU 数据导出为新格式
- [ ] 添加知识库目录的静态文件服务（供前端预览图片）

### Phase 6：Docker 适配
- [ ] 更新 `docker-compose.yml` 添加知识库卷挂载
- [ ] 更新 `.env.example` 添加 `KNOWLEDGE_BASE_DIR` 配置
- [ ] 确保容器内路径权限正确

### Phase 7：AI Agent 基础
- [ ] AI Agent 获得 `product_knowledge/` 目录的读取权限
- [ ] Agent 工具函数：
  - `list_skus()` — 列所有 SKU
  - `read_product_md(sku, layer)` — 读指定层级 Markdown
  - `search_media(sku, material_type, channel)` — glob 媒体文件
  - `get_global_index()` — 读取 _index.json
- [ ] （Phase 2）向量化 + RAG 检索

---

## 八、决策记录

| # | 问题 | 选择 |
|---|------|------|
| 1 | AI Agent 核心用户 | 9 个角色全覆盖 |
| 2 | 文件夹子结构 | 按前端上传分层（原始素材/AI/渠道/社媒/参考辅助） |
| 3 | L1~L5 Markdown 格式 | C（混合型：表格 + 自然语言叙述） |
| 4 | L6 文件夹结构 | 按素材类别分子文件夹（5 层 20+ 子文件夹） |
| 5 | 文件命名规则 | 9 段式：品牌_产品ID_SKU_类型_角度_渠道_语言_版本_日期_状态 |
| 6 | AI Agent 技术路径 | Phase 1 直接文件系统 → Phase 2 RAG |
| 7 | 存储位置策略 | D（SKU 文件夹 + 可配置路径 + Docker 卷挂载） |
| 8 | 数据库 vs 文件系统 | A（数据库为主源，文件系统为导出产物） |
| 9 | 生成时机 | D（发布自动 + 手动导出按钮） |
| 10 | 上传标签策略 | 上传到指定格子，系统自动推断类型，用户补填角度/渠道/语言等 |
| 11 | 数据库分离 | B（系统库 + 产品知识库双 SQLite，产品库放入知识库卷自包含） |
| 12 | 数据库引擎 | 保持 SQLite，不做 PostgreSQL/MySQL 迁移 |
