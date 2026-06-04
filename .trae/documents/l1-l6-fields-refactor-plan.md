# L1-L6 字段重构实施计划

## 变更概览

按用户定义的新字段列表重构全部 6 层，先更新文档后更新前端。

---

## 第一部分：更新架构文档

### 文件：`.trae/documents/system-architecture-and-ai-integration-plan.md`

#### 步骤 1：更新 L1 字段表（产品身份层）

**删除字段：** `name_ja`、`sub_category`、`retail_price`、`online_price`、`retail_prices`、`online_prices`、`is_active`、`sync_stock`、`creator_id`

**新增字段：** `上架渠道`、`售卖地区`

**保留字段：** `sku`、`barcode`、`name_zh`→商品中文名称、`name_en`→商品英文名称、`brand`、`series`、`category`→系统分类、`grade`→商品分级、`launch_date`→上市时间、`lifecycle`→生命周期、`person_in_charge`→负责人

**L1 新字段表（13个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `sku` | VARCHAR(64) | 主键 |
| 2 | `barcode` | VARCHAR(64) | |
| 3 | `name_zh` | VARCHAR(256) | |
| 4 | `name_en` | VARCHAR(256) | |
| 5 | `channels` | TEXT(JSON) | |
| 6 | `sales_regions` | TEXT(JSON) | |
| 7 | `brand` | VARCHAR(128) | |
| 8 | `series` | VARCHAR(128) | |
| 9 | `category` | VARCHAR(128) | |
| 10 | `grade` | VARCHAR(32) | |
| 11 | `launch_date` | DATE | |
| 12 | `lifecycle` | VARCHAR(32) | |
| 13 | `person_in_charge` | VARCHAR(64) | |

#### 步骤 2：更新 L2 字段表（物理规格层）

**删除字段：** `specs_json`

**从 L3 移入：** `main_color`→主色系、`heat_source`→适用热源、`tech_advantages`→技术优势

**从 L4 移入：** `usage_instructions`→使用说明

**新增字段：** `power_wattage`→功率（炉具类）

**保留字段：** `dimension_lines`→尺寸信息、`capacity_lines`→容量大小、`gross_weight`→毛重(g)、`material`→主体材质、`surface_finish`→表面处理、`certifications`→认证信息

**L2 新字段表（12个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `dimension_lines` | TEXT(JSON) | |
| 2 | `capacity_lines` | TEXT(JSON) | |
| 3 | `gross_weight` | FLOAT | |
| 4 | `material` | VARCHAR(256) | |
| 5 | `main_color` | VARCHAR(128) | |
| 6 | `surface_finish` | VARCHAR(128) | |
| 7 | `heat_source` | VARCHAR(128) | |
| 8 | `power_wattage` | VARCHAR(128) | |
| 9 | `tech_advantages` | TEXT(JSON) | |
| 10 | `certifications` | TEXT(JSON) | |
| 11 | `usage_instructions` | TEXT | |

#### 步骤 3：更新 L3 字段表（商业价值层）

**删除字段：** `main_color`、`heat_source`、`tech_advantages`

**从 L4 移入：** `amazon_title`→标题（英文）、`website_title`→标题（中文）、`listing_en`→产品长描述（英文）、`listing_zh`→产品长描述（中文）、`search_keywords`→搜索关键词库

**新增字段：** `core_selling_points`→核心卖点 TOP5、`differentiation`→差异化定位

**保留字段：** `target_audience`→目标人群、`price_positioning`→价格定位带、`emotional_value`→情感价值、`use_scenarios`→使用场景、`competitors`→竞品对标

**L3 新字段表（12个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `core_selling_points` | TEXT(JSON) | |
| 2 | `target_audience` | VARCHAR(256) | |
| 3 | `differentiation` | TEXT | |
| 4 | `price_positioning` | VARCHAR(64) | |
| 5 | `emotional_value` | TEXT | |
| 6 | `use_scenarios` | TEXT(JSON) | |
| 7 | `competitors` | TEXT(JSON) | |
| 8 | `amazon_title` | VARCHAR(512) | |
| 9 | `website_title` | VARCHAR(512) | |
| 10 | `listing_en` | TEXT | |
| 11 | `listing_zh` | TEXT | |
| 12 | `search_keywords` | TEXT(JSON) | |

#### 步骤 4：更新 L4 字段表（知识库层，原名"内容素材层"）

**层名称变更：** `内容素材层` → `知识库层`

**删除所有旧字段：** `amazon_title`、`website_title`、`five_bullets`、`listing_en`、`listing_zh`、`listing_ja`、`a_plus_content`、`search_keywords`、`usage_instructions`、`qa_items`、`review_tags`

**新增字段：** `qa_library`→常见问题Q&A库、`negative_review_tactics`→差评高频词及应对话术

**L4 新字段表（2个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `qa_library` | TEXT(JSON) | |
| 2 | `negative_review_tactics` | TEXT(JSON) | |

#### 步骤 5：更新 L5 字段表（多媒体资产层）

**删除字段：** `channel_media`

**新增字段：** `raw_assets`→原始素材、`channel_images_v1`→各渠道上架图像V1、`channel_images_v2`→各渠道上架图像V2、`social_media_tags`→社媒内容标签库

**L5 新字段表（4个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `raw_assets` | TEXT(JSON) | |
| 2 | `channel_images_v1` | TEXT(JSON) | |
| 3 | `channel_images_v2` | TEXT(JSON) | |
| 4 | `social_media_tags` | TEXT(JSON) | |

#### 步骤 6：更新 L6 字段表（内容生成层）

**删除所有旧字段：** `template_name`、`prompt_text`、`parameters`、`version`、`usage_count`

**新增字段：** `image_prompt_template`→图像提示词模板、`video_prompt_template`→视频提示词模板

**L6 新字段表（2个字段）：**

| # | 字段 | 类型 | 必填 |
|---|------|------|------|
| 1 | `image_prompt_template` | TEXT | |
| 2 | `video_prompt_template` | TEXT | |

#### 步骤 7：更新文档中的 Architecture 层级总揽图

更新文档中的 Mermaid 图表（如有）和层级总揽描述，反映 L4 名称变更及各层字段重分配。

#### 步骤 8：更新 L1-L6 UX 描述

根据字段变更清理各层 UX 描述中不再适用的部分（如多币种价格行、日文名称等），补充新字段的 UX 说明。

#### 步骤 9：更新后端数据库模型对应表

更新文档第八节数据库文件对照清单，反映字段变更。

---

## 第二部分：更新前端代码

### 步骤 10：更新 TypeScript 类型定义

**文件：** `frontend/src/types/index.ts`

需要更新的类型：

1. **`Product` 聚合接口** — 删除已移除字段，新增字段，更新 L2-L6 子对象名称

2. **`ProductSpecs`** — 删除 `specs_json`，新增 `main_color`、`heat_source`、`tech_advantages`、`power_wattage`、`usage_instructions`

3. **`ProductBusiness`** — 删除 `main_color`、`heat_source`、`tech_advantages`，新增 `core_selling_points`、`differentiation`、`amazon_title`、`website_title`、`listing_en`、`listing_zh`、`search_keywords`

4. **`ProductContent`** → 重写为 `ProductKnowledge`，仅含 `qa_library`、`negative_review_tactics`

5. **`ProductMedia`** — 删除 `channel_media`，新增 `raw_assets`、`channel_images_v1`、`channel_images_v2`、`social_media_tags`

6. **`ProductPrompts`** — 删除旧字段，新增 `image_prompt_template`、`video_prompt_template`

7. **`ChannelMediaItem` / `MediaAssets` / `ChannelMedia`** — 删除

8. **`ProductDraft`** — 同步更新所有字段

### 步骤 11：更新产品创建页面

**文件：** `frontend/src/pages/ProductCreate.tsx`

- 删除已移除字段的表单控件
- 新增字段的表单控件（上架渠道、售卖地区、功率、核心卖点等）
- L2 新增从 L3/L4 移入的字段控件
- L3 新增从 L4 移入的字段控件
- L4 表单区域重写为知识库表单（Q&A、差评话术）
- L5 表单重建（原始素材、V1、V2、社媒标签）
- L6 表单精简（图像模板、视频模板）
- 更新 `buildCreatePayload` 提交逻辑

### 步骤 12：更新产品列表/详情页面

**文件：** `frontend/src/pages/ProductManagement.tsx`

- 更新列定义和渲染
- 删除旧字段显示
- 新增字段显示

### 步骤 13：更新 API 层

**文件：** `frontend/src/services/api.ts`

- 更新产品 CRUD 接口的类型签名
- 删除 `uploadImage` 中与旧 L5 相关的逻辑（如果仍需要图片上传，保留通用部分）

### 步骤 14：验证编译

`node node_modules/typescript/bin/tsc --noEmit` 确保零错误

---

## 涉及文件总览

| 文件 | 改动范围 |
|------|----------|
| `.trae/documents/system-architecture-and-ai-integration-plan.md` | L1-L6 字段表、层级总揽、UX描述、数据库对照表 |
| `frontend/src/types/index.ts` | Product/ProductSpecs/ProductBusiness/ProductKnowledge/ProductMedia/ProductPrompts/ProductDraft |
| `frontend/src/pages/ProductCreate.tsx` | 表单控件增删改、提交逻辑 |
| `frontend/src/pages/ProductManagement.tsx` | 列表列定义 |
| `frontend/src/services/api.ts` | API 签名更新 |
