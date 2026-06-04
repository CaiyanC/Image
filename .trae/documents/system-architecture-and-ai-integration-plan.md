# 产品元数据库架构规划与 AI 图像生成融合方案

## 一、L1-L6 产品元数据架构 (数据库详细规格)

### L1 — 产品身份层

**表名**: `products` | **主键**: `sku` | **关系**: 一对多关联 L2-L6 (通过 sku)

**前端表单特性**：

* 名称（中文/英文/日文）同一行内展示，详情页以国旗标签同行显示

* 系统分类 `category`：下拉可选 + 可新增，数据源来自 `product_categories` 表，用户新增分类全员共享

* 商品分级 `grade`：预设下拉 A类品 / B类品 / C类品 / D类品 / E类品 / 金波专属

* 生命周期 `lifecycle`：下拉可选 未上市新品 / 新品 / 常规品 / 主推品 / 主推新品 / 非主推新品 / 清仓品 / 老款无货不补 / 已无货不补

* 价格支持多币种：`retail_price` / `online_price` 为 RMB 默认行，`retail_prices` / `online_prices` 为 JSON 多币种附加行

* 上市时间 `launch_date`：日期控件 `<input type="date">`

* 库存同步 `sync_stock`：已改为默认手动填写数量

* 上架渠道 `listing_channel`：多选标签（淘宝 / 京东 / 亚马逊 / 独立站 / 抖音 / 拼多多 / 1688 / 全渠道），逗号分隔字符串通过 API 传输，已作为独立列储存在数据库

* 售卖地区 `sales_region`：多选标签（国内 / 日本 / 欧美 / 美国 / 东南亚 / 全球），逗号分隔字符串通过 API 传输，已作为独立列储存在数据库

| 字段                 | 类型           | 必填     | 说明                         | 示例                                   |
| ------------------ | ------------ | ------ | -------------------------- | ------------------------------------ |
| `sku`              | VARCHAR(64)  | ✅      | 🔑 主键，产品唯一标识               | `PRO-2025-001`                       |
| `barcode`          | VARCHAR(64)  | <br /> | 条形码 / UPC / EAN            | `6931234567890`                      |
| `brand`            | VARCHAR(128) | <br /> | 品牌名称                       | `孚盟科技`                               |
| `series`           | VARCHAR(128) | <br /> | 产品系列                       | `Pro 系列`                             |
| `name_zh`          | VARCHAR(256) | <br /> | 产品名称（中文）                   | `智能蓝牙音箱`                             |
| `name_en`          | VARCHAR(256) | <br /> | 产品名称（英文）                   | `Smart Bluetooth Speaker`            |
| `name_ja`          | VARCHAR(256) | <br /> | 产品名称（日文）                   | `スマートBluetoothスピーカー`                 |
| `category`         | VARCHAR(128) | <br /> | 系统分类（下拉+可新增，共享分类表）         | `锅具`                                 |
| `sub_category`     | VARCHAR(128) | <br /> | 商品类目                       | `煎盘`                                 |
| `retail_price`     | FLOAT        | <br /> | 零售价 — RMB 默认（元）            | `199.00`                             |
| `retail_prices`    | TEXT(JSON)   | <br /> | 🆕 零售价多币种附加行               | `[{"currency":"USD","amount":27.5}]` |
| `online_price`     | FLOAT        | <br /> | 电商价 — RMB 默认（元）            | `149.00`                             |
| `online_prices`    | TEXT(JSON)   | <br /> | 🆕 电商价多币种附加行               | `[{"currency":"EUR","amount":18.5}]` |
| `grade`            | VARCHAR(32)  | <br /> | 商品分级（下拉 A类品/B类品/C类品/D类品/E类品/金波专属） | `A类品`                                |
| `is_active`        | BOOLEAN      | ✅      | 是否激活上架                     | `true`                               |
| `sync_stock`       | VARCHAR(16)  | <br /> | 库存数量（手动填写）                 | `200`                                |
| `person_in_charge` | VARCHAR(64)  | <br /> | 负责人                        | `张三`                                 |
| `lifecycle`        | VARCHAR(32)  | <br /> | 产品生命周期（下拉：未上市新品/新品/常规品/主推品/主推新品/非主推新品/清仓品/老款无货不补/已无货不补） | `在售中`                                |
| `launch_date`      | DATE         | <br /> | 上市时间（日期控件）                 | `2025-01-15`                         |
| `creator_id`       | VARCHAR(36)  | <br /> | 🆕 产品创建者，记录录入人             | `用户 UUID`                            |
| `created_at`       | TIMESTAMP    | ✅      | 创建时间                       | 自动生成                                 |
| `updated_at`       | TIMESTAMP    | ✅      | 更新时间                       | 自动更新                                 |

***

### 🆕 系统分类字典表

**表名**: `product_categories` | **独立表**（非层级结构，共享分类池）

| 字段           | 类型          | 必填 | 说明        |
| ------------ | ----------- | -- | --------- |
| `id`         | INTEGER     | ✅  | 自增主键      |
| `name`       | VARCHAR(64) | ✅  | 分类名称，全局唯一 |
| `created_at` | TIMESTAMP   | ✅  | 创建时间      |

**默认预设 19 个分类**：餐具、餐具配件、茶具、炊具配件、待分类、登山杖、电商专供、锅具、户外家具、煎盘、经销商专供、咖啡器具、炉具、配件、水壶、套锅、营火设备、转接器、桌椅

**API 接口**：

| 方法       | 路径                     | 说明           | 权限   |
| -------- | ---------------------- | ------------ | ---- |
| `GET`    | `/api/categories`      | 获取所有分类列表     | 无需登录 |
| `POST`   | `/api/categories`      | 新增自定义分类      | 登录用户 |
| `DELETE` | `/api/categories/{id}` | 删除分类（仅管理员可用） | 登录用户 |

> 📌 前端 `category` 下拉框为 **CreatableSelect 模式**：从该表加载已有分类 + 允许输入新名称即时创建，新增分类全员可见。

***

### L2 — 物理规格层

**表名**: `product_specs` | **关系**: `sku` → `products.sku`

**前端表单特性**：

* 尺寸改为动态多行表单：每行包含 **描述**（可选 datalist 候选项：展开尺寸、折叠尺寸、直径、长、宽、高、厚度、内径、外径）+ **数值** + **单位下拉**（厘米/英寸/毫米，默认厘米）

* 容量改为动态多行表单：每行包含 **描述**（如"大锅""小锅"）+ **容量值**（如"3L""1.5L"）

* 毛重 / 主体材质 / 表面处理为固定独立字段

* 认证信息为动态多行（每行一个 input + 删除按钮，逐个添加）

* 扩展规格 `specs_json`：后端模型已定义，前端暂无单独表单 UI，当前通过 JSON 序列化传入

| 字段                | 类型           | 必填  | 说明                     | 示例                                                                                           | 前端渲染                                                                                       |
| ----------------- | ------------ | --- | ---------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `id`              | UUID         | ✅   | 规格记录 ID               | <br />                                                                                       | <br />                                                                                     |
| `sku`             | VARCHAR(64)  | ✅   | 关联产品 SKU              | `PRO-2025-001`                                                                               | <br />                                                                                     |
| `dimension_lines` | TEXT(JSON)   |     | 🆕 尺寸多行数据（描述+数值+单位）    | `[{"label":"展开尺寸","value":"120×60×45","unit":"厘米"},{"label":"直径","value":"30","unit":"厘米"}]` | ✅ **L2 动态行**：描述 input + 数值 input + 单位 select                                               |
| `gross_weight`    | FLOAT        |     | 毛重（g）                  | `2500`                                                                                       | ✅ **L2 固定 input**                                                                          |
| `material`        | VARCHAR(256) |     | 主体材质                   | `铝合金`                                                                                        | ✅ **L2 固定 input**                                                                          |
| `surface_finish`  | VARCHAR(128) |     | 表面处理工艺                 | `喷涂` / `氧化` / `电镀`                                                                           | ✅ **L2 固定 input**                                                                          |
| `capacity_lines`  | TEXT(JSON)   |     | 🆕 容量多行数据（描述+容量值）      | `[{"label":"大锅","value":"3L"},{"label":"小锅","value":"1.5L"}]`                                | ✅ **L2 动态行**：描述 input + 容量值 input                                                        |
| `main_color`      | VARCHAR(128) |     | ✅ 主色系（已从 L3 迁入）         | `黑色` / `白色`                                                                                 | ✅ **L2 表单**（固定 input） |
| `heat_source`     | VARCHAR(128) |     | ✅ 适用热源（已从 L3 迁入）       | `电磁炉` / `燃气灶`                                                                              | ✅ **L2 表单**（固定 input + placeholder） |
| `min_power`       | VARCHAR(128) |     | 🆕 最小功率（炉具类）              | `800W`                                                                                       | ✅ **L2 表单**（`grid grid-cols-2` 双输入框并排） |
| `max_power`       | VARCHAR(128) |     | 🆕 最大功率（炉具类）              | `2000W`                                                                                      | ✅ **L2 表单**（与最小功率同行） |
| `tech_advantages` | TEXT(JSON)   |     | ✅ 技术优势（已从 L3 迁入，字符串数组） | `["不粘涂层","快速加热","节能省电"]`                                                                  | ✅ **L2 表单**（动态行：序号+input+删除） |
| `usage_instructions` | TEXT      |     | ✅ 使用说明（已从 L4 迁入）       | `首次使用前请清洗...`                                                                              | ✅ **L2 表单**（textarea） |
| `certifications`  | TEXT(JSON)   |     | 认证信息列表                 | `["CE","FCC","RoHS"]`                                                                        | ✅ **L2 动态行**：每行一个 input + 删除按钮                                                            |
| `specs_json`      | TEXT(JSON)   |     | 🆕 扩展规格（自由键值对）         | `{"防水等级":"IPX5","电池寿命":"12h"}`                                                               | ⚠️ 后端模型已定义，前端暂无独立表单 UI                                                                     |
| `created_at`      | TIMESTAMP    | ✅   | <br />                 | <br />                                                                                       | <br />                                                                                     |
| `updated_at`      | TIMESTAMP    | ✅   | <br />                 | <br />                                                                                       | <br />                                                                                     |

> 📌 **迁移状态**：12 个字段已全部在前端表单就位。其中 6 个为原有字段（dimension_lines / gross_weight / material / surface_finish / capacity_lines / certifications），4 个从 L3/L4 迁入（main_color / heat_source / tech_advantages / usage_instructions），2 个为新增字段（min_power / max_power 替代旧 power_wattage）。`specs_json` 后端模型已定义，前端暂无独立表单 UI。数据库 `product_specs` 表结构迁移已完成（含向后兼容保留旧 `power_wattage` 列）。

***

### L3 — 商业价值层

**表名**: `product_business` | **关系**: `sku` → `products.sku`

**前端表单特性**：

* 核心卖点 TOP5 `core_selling_points`：动态行表单（序号 + input + 删除），默认 5 行空槽

* 目标人群 `target_audience`：**标签输入**（input + 添加按钮 + 回车快捷，蓝色圆角标签展示，点击 × 删除），以逗号分隔字符串形式存储

* 差异化定位 `differentiation`：单行 input

* 价格定位带 `price_positioning`：**下拉选择**（请选择 / 入门款 / 中端 / 高端）

* 情感价值 `emotional_value`：单行 input

* 使用场景 `use_scenarios`：**标签输入**（input + 添加按钮 + 回车快捷，绿色圆角标签展示，点击 × 删除），JSON 数组存储

* 竞品对标 `competitors`：动态行表单，每行包含**名称 input + 链接 input（选填）+ 删除按钮**，JSON 对象数组 `[{name, url}]` 存储

| 字段                  | 类型           | 必填     | 说明                | 示例                                                  | 前端渲染 | 
| ------------------- | ------------ | ------ | ----------------- | --------------------------------------------------- | --- |
| `id`                | UUID         | ✅      | <br />            | <br />                                              | <br /> |
| `sku`               | VARCHAR(64)  | ✅      | 关联产品 SKU          | <br />                                              | <br /> |
| `core_selling_points` | TEXT(JSON) | <br /> | 🆕 核心卖点 TOP5（字符串数组，默认 5 槽） | `["不粘涂层","快速加热","节能省电","轻量化","易收纳"]` | ✅ **L3 表单**（动态行，5 行默认） |
| `target_audience`   | VARCHAR(256) | <br /> | 目标人群（标签输入，逗号分隔） | `18-35岁,注重生活品质,宝妈`                              | ✅ **L3 标签**（蓝色标签 + input + 添加按钮） |
| `differentiation`   | TEXT         | <br /> | 🆕 差异化定位           | `市面上最轻的钛合金炊具套装`                                      | ✅ **L3 表单**（固定 input） |
| `price_positioning` | VARCHAR(64)  | <br /> | 价格定位带（下拉选择）     | `中端`                                                 | ✅ **L3 下拉**（入门款/中端/高端） |
| `emotional_value`   | TEXT         | <br /> | 情感价值（单行 input） | `家庭温馨、健康生活方式的象征`                                    | ✅ **L3 表单**（固定 input） |
| `use_scenarios`     | TEXT(JSON)   | <br /> | 使用场景（标签输入）     | `["户外运动","家庭聚会","办公桌搭","浴室"]`                       | ✅ **L3 标签**（绿色标签 + input + 添加按钮） |
| `competitors`       | TEXT(JSON)   | <br /> | 竞品对标 `[{name, url}]` | `[{"name":"JBL Flip 6","url":"https://..."}]`        | ✅ **L3 表单**（名称 + 链接双 input） |
| `created_at`        | TIMESTAMP    | ✅      | <br />            | <br />                                              | <br /> |
| `updated_at`        | TIMESTAMP    | ✅      | <br />            | <br />                                              | <br /> |

> 📌 `main_color`、`heat_source`、`tech_advantages` 已迁入 L2 物理规格层，L3 数据库模型和表单 UI 已同步移除对应字段。

***

### L4 — 内容素材层

**表名**: `product_content` | **关系**: `sku` → `products.sku`

| 字段                   | 类型           | 必填     | 说明                   | 示例                                                   |
| -------------------- | ------------ | ------ | -------------------- | ---------------------------------------------------- |
| `id`                 | UUID         | ✅      | <br />               | <br />                                               |
| `sku`                | VARCHAR(64)  | ✅      | 关联产品 SKU             | <br />                                               |
| `amazon_title`       | VARCHAR(512) | <br /> | 🔴 亚马逊标题             | `Premium Cookware Set...`                            |
| `website_title`      | VARCHAR(512) | <br /> | 🔴 独立站标题             | `High Quality Kitchen Set...`                        |
| `five_bullets`       | TEXT(JSON)   | <br /> | 🔴 五点卖点，字符串数组        | `["Premium quality","Easy to use","Durable design"]` |
| `listing_zh`         | TEXT         | <br /> | 🔴 Listing 文案（中文）    | 完整的亚马逊/电商 Listing 文案                                 |
| `listing_en`         | TEXT         | <br /> | 🔴 Listing 文案（英文）    | <br />                                               |
| `listing_ja`         | TEXT         | <br /> | 🔴 Listing 文案（日文）    | <br />                                               |
| `a_plus_content`     | TEXT         | <br /> | 🔴 A+ 页面内容（HTML/富文本） | 图文版产品详情                                              |
| `search_keywords`    | TEXT(JSON)   | <br /> | 🔴 搜索关键词，`[{keyword, priority}]` 对象数组 | `[{"keyword":"kitchen","priority":"A"},{"keyword":"cookware","priority":"B"}]` |
| `usage_instructions` | TEXT         | <br /> | 🔀 已迁入 L2（L4 表单 UI 已移除）  | —                                        |
| `qa_items`           | TEXT(JSON)   | <br /> | 🔴 Q\&A 库，问答对象数组     | `[{"q":"防水吗？","a":"IPX5 等级..."}]`                    |
| `review_tags`        | TEXT(JSON)   | <br /> | 🔴 评价标签，字符串数组        | `["音质好","颜值高","续航长"]`                                |
| `negative_review_coping` | TEXT(JSON) | <br /> | 🆕 差评应对，对象数组 | `[{"序号":1,"问题":"...","应对":"..."}]` |
| `created_at`         | TIMESTAMP    | ✅      | <br />               | <br />                                               |
| `updated_at`         | TIMESTAMP    | ✅      | <br />               | <br />                                               |

***

### L5 — 多媒体资产层

**表名**: `product_media` | **关系**: `sku` → `products.sku`

**前端表单特性**：

* 多图上传：支持一次选择多张图片，通过 `POST /api/products/images/upload` 上传到服务端 `uploads/images/` 目录

* 图片预览网格：上传后以缩略图网格形式展示

* 图片灯箱查看器：点击图片放大弹窗显示，支持 ← → 键盘切换前一张/后一张、ESC 关闭、下载原图、页码指示

* `ai_prompts` 字段已从表单和类型定义中移除（Prompt 管理统一归入 L6）

| 字段               | 类型          | 必填     | 说明             | 示例                                                    |
| ---------------- | ----------- | ------ | -------------- | ----------------------------------------------------- |
| `id`             | UUID        | ✅      | <br />         | <br />                                                |
| `sku`            | VARCHAR(64) | ✅      | 关联产品 SKU       | <br />                                                |
| `main_images`    | TEXT(JSON)  | <br /> | 🔴 主图 URL 列表   | `["https://cdn.xxx/p1.jpg","https://cdn.xxx/p2.jpg"]` |
| `detail_images`  | TEXT(JSON)  | <br /> | 🔴 细节图 URL 列表  | <br />                                                |
| `scene_images`   | TEXT(JSON)  | <br /> | 🔴 场景图 URL 列表  | <br />                                                |
| `video_urls`     | TEXT(JSON)  | <br /> | 🔴 视频链接列表      | <br />                                                |
| `model_3d_paths` | TEXT(JSON)  | <br /> | 🔴 3D 模型文件路径列表 | <br />                                                |
| `ai_prompts`       | TEXT(JSON)  | <br /> | AI 生成提示词历史（保留兼容） | `[{"prompt":"...","generated_url":"..."}]` |
| `channel_media`    | TEXT(JSON)  | <br /> | 渠道定制素材（保留兼容） | `{"amazon":["/amazon/p1.jpg"],"shopee":[...]}` |
| `source_white_bg`      | TEXT(JSON) | <br /> | 🔵 原始素材 — 白底图 | `["/raw/white_bg_001.jpg"]` |
| `source_multi_angle`   | TEXT(JSON) | <br /> | 🔵 原始素材 — 多角度图 | `["/raw/angle_001.jpg"]` |
| `source_structure`     | TEXT(JSON) | <br /> | 🔵 原始素材 — 结构图 | `["/raw/struct_001.jpg"]` |
| `source_exploded`      | TEXT(JSON) | <br /> | 🔵 原始素材 — 爆炸图 | `["/raw/exploded_001.jpg"]` |
| `source_size`          | TEXT(JSON) | <br /> | 🔵 原始素材 — 尺寸图 | `["/raw/size_001.jpg"]` |
| `source_function`      | TEXT(JSON) | <br /> | 🔵 原始素材 — 功能图 | `["/raw/func_001.jpg"]` |
| `source_usage_steps`   | TEXT(JSON) | <br /> | 🔵 原始素材 — 使用步骤图 | `["/raw/steps_001.jpg"]` |
| `source_storage`       | TEXT(JSON) | <br /> | 🔵 原始素材 — 收纳图 | `["/raw/storage_001.jpg"]` |
| `source_accessories`   | TEXT(JSON) | <br /> | 🔵 原始素材 — 配件图 | `["/raw/acc_001.jpg"]` |
| `source_bundle`        | TEXT(JSON) | <br /> | 🔵 原始素材 — 套装图 | `["/raw/bundle_001.jpg"]` |
| `source_3d`            | TEXT(JSON) | <br /> | 🔵 原始素材 — 3D模型 | `["/raw/model_001.glb"]` |
| `source_outdoor`       | TEXT(JSON) | <br /> | 🔵 原始素材 — 户外场景图 | `["/raw/outdoor_001.jpg"]` |
| `ai_generated`         | TEXT(JSON) | <br /> | 🟢 AI 生成层 — AI 生成素材 | `[{"prompt":"...","url":"..."}]` |
| `channel_versions`     | TEXT(JSON) | <br /> | 🟡 渠道版本层 — 各渠道版素材 | `{"amazon":["..."]}` |
| `social_media`         | TEXT(JSON) | <br /> | 🟠 社媒素材层 — 社媒图片 | `["/social/post_001.jpg"]` |
| `social_ads`           | TEXT(JSON) | <br /> | 🟠 社媒素材层 — 广告图 | `["/social/ad_001.jpg"]` |
| `social_video_urls`    | TEXT(JSON) | <br /> | 🟠 社媒素材层 — 视频链接 | `["/social/video_001.mp4"]` |
| `ref_packaging`        | TEXT(JSON) | <br /> | 🔴 参考辅助 — 包装参考 | `["/ref/pkg_001.jpg"]` |
| `ref_manual`           | TEXT(JSON) | <br /> | 🔴 参考辅助 — 说明书参考 | `["/ref/manual_001.jpg"]` |
| `ref_certification`    | TEXT(JSON) | <br /> | 🔴 参考辅助 — 认证参考 | `["/ref/cert_001.jpg"]` |
| `ref_dealer`           | TEXT(JSON) | <br /> | 🔴 参考辅助 — 经销商素材 | `["/ref/dealer_001.jpg"]` |
| `ref_brand_style`      | TEXT(JSON) | <br /> | 🔴 参考辅助 — 品牌风格 | `["/ref/brand_001.jpg"]` |
| `ref_competitor`       | TEXT(JSON) | <br /> | 🔴 参考辅助 — 竞品参考 | `["/ref/comp_001.jpg"]` |
| `ref_archive`          | TEXT(JSON) | <br /> | 🔴 参考辅助 — 存档素材 | `["/ref/archive_001.jpg"]` |
| `ref_banned`           | TEXT(JSON) | <br /> | 🔴 参考辅助 — 禁用素材 | `["/ref/banned_001.jpg"]` |
| `created_at`     | TIMESTAMP   | ✅      | <br />         | <br />                                                |
| `updated_at`     | TIMESTAMP   | ✅      | <br />         | <br />                                                |

**🆕 图像上传 API**：

| 方法     | 路径                            | 说明              | 权限   |
| ------ | ----------------------------- | --------------- | ---- |
| `POST` | `/api/products/images/upload` | 上传产品图片（支持多文件上传） | 登录用户 |

> 📌 上传流程：前端 `<input type="file" multiple>` 选择多图 → `FormData` 发送到后端 → 后端保存至 `uploads/images/` 目录并通过 `StaticFiles` 挂载为 `/uploads` 路由 → 返回 URL 列表 → 前端更新图片预览网格。

> 📌 灯箱查看器：`viewerIndex` 状态管理当前展示图片索引，`useEffect` 监听 `keydown` 事件实现 ←/→ 切换和 ESC 关闭。

***

### L6 — 内容生成层（AI Prompt 基础层）

**表名**: `product_prompts` | **关系**: `sku` → `products.sku` (一个产品可有多个 Prompt 模板)

| 字段              | 类型           | 必填     | 说明                        | 示例                                                             |
| --------------- | ------------ | ------ | ------------------------- | -------------------------------------------------------------- |
| `id`            | UUID         | ✅      | 模板记录 ID                   | <br />                                                         |
| `sku`           | VARCHAR(64)  | ✅      | 关联产品 SKU                  | <br />                                                         |
| `template_name` | VARCHAR(128) | <br /> | 🔴 模板名称                   | `"电商主图生成"` / `"Instagram 营销图"`                                 |
| `prompt_text`   | TEXT         | <br /> | 🔴 基础提示词内容，可包含 `{变量}` 占位符 | `"{name_zh}，{material}材质，{color}色，白底棚拍，商业摄影，超高分辨率"`            |
| `parameters`    | TEXT(JSON)   | <br /> | 🔴 默认生成参数                 | `{"size":"1024x1024","quality":"high","output_format":"jpeg"}` |
| `version`       | INT          | <br /> | 版本号，每次修改自增                | `3`                                                            |
| `usage_count`   | INT          | <br /> | 使用次数统计                    | `128`                                                          |
| `created_at`    | TIMESTAMP    | ✅      | <br />                    | <br />                                                         |
| `updated_at`    | TIMESTAMP    | ✅      | <br />                    | <br />                                                         |

> 📌 L5 专注于多媒体资产的文件存储与展示（图片/视频/3D），通过上传 API 管理文件。L6 的 `prompt_text` 为可复用的 AI Prompt 模板，支持变量占位符，用于批量自动化生成。

> 📌 **前端状态结构**：`ProductCreate` 和 `ProductManagement` 中 prompts 数据以 dict 结构管理：`{ image_templates: [{template_name, prompt_text, ...}], video_templates: [{template_name, prompt_text, ...}] }`。通过 API 传输时以 `prompts_data` 字段（dict 类型）发送，后端逐条拆分为 `product_prompts` 表行（`parameters` JSON 中含 `{"type": "image"}` 或 `{"type": "video"}` 标识模板类型）。前端预览面板（L7）分"图像提示词模板"和"视频提示词模板"两个分区展示。

***

## 前端产品管理页面 UX 特性

### 产品管理页面 (`ProductManagement.tsx`)

全功能单页应用，左侧产品列表 + 右侧详情/表单，支持 L1-L6 六个层级折叠表单创建产品。

#### L1 表单专项优化

| 特性                       | 实现方式                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| **名称同行展示**               | 中文/英文/日文三个 input 置于同一 3 列 grid 内，详情页以 🇨🇳/🇬🇧/🇯🇵 标签同行显示                                     |
| **系统分类 CreatableSelect** | 输入框带下拉面板，加载 `api.categories.list()` 已有分类；输入新名称时出现"添加 'xxx'"按钮，调用 `api.categories.create()` 即时入库 |
| **商品分级下拉**               | `<select>` 预设 A类品 / B类品 / C类品                                                                   |
| **生命周期下拉**               | `<select>` 预设 新品开发中 / 在售中 / 断货 / 清仓                                                             |
| **多币种价格**                | 零售价/电商价各含 RMB 默认输入框 + 动态币种行（币种代码 + 金额 + 删除按钮），通过"**+ 添加币种**"扩展                                  |
| **日期控件**                 | 上市时间使用 `<input type="date">`                                                                    |
| **库存手动填写**               | sync\_stock 的 placeholder 标注"手动填写数量"                                                            |

#### L2 表单专项优化

| 特性         | 实现方式                                                                                                                              |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **动态尺寸行**  | 每行 3 列：描述 input（带 `<datalist>` 候选项：展开尺寸/折叠尺寸/直径/长/宽/高/厚度/内径/外径）+ 数值 input + 单位 `<select>`（厘米/英寸/毫米，默认厘米），可选"**+ 添加尺寸**"增加新行、✕ 删除行 |
| **动态容量行**  | 每行 2 列：描述 input（如"大锅"）+ 容量值 input（如"3L"），可选"**+ 添加容量**"增加新行、✕ 删除行                                                                 |
| **固定独立字段** | 毛重(g)、主体材质、表面处理、主色系、热源类型为固定 `<input>`；最小功率 + 最大功率为 `grid grid-cols-2` 双输入框并排；使用说明为 `<textarea>` |
| **认证信息**   | 多行 `<textarea>`，每行一条认证                                                                                                            |
| **技术优势**   | 动态行，序号 + `<input>` + 删除按钮                                                                                                            |

#### 删除确认

| 特性               | 实现方式                                                         |
| ---------------- | ------------------------------------------------------------ |
| **React 受控确认面板** | 点击"删除"按钮后，原地展开红色确认面板（含"确认"/"取消"按钮），替代不可靠的 `window.confirm()` |

#### 已发布产品二次编辑

| 特性               | 实现方式                                                         |
| ---------------- | ------------------------------------------------------------ |
| **编辑按钮** | 右侧详情面板标题栏蓝色"编辑"按钮，点击跳转 `/products/edit/{sku}` |
| **编辑页加载** | `ProductCreate` 组件通过 `useParams` 读取 `sku` 参数，调用 `api.products.get(sku)` 加载已有产品数据填满 L1-L7 表单 |
| **保存草稿** | 编辑模式下保存草稿 → `api.drafts.create()` 新建独立草稿，不覆盖原产品 |
| **发布更新** | 编辑模式下发布 → `api.products.updateFull(sku, data)` 全量覆盖 L1-L7 |
| **后端接口** | `PUT /api/products/{sku}/full` — `update_product_full()` 实现，接受 `ProductCreate` schema，upsert 各子表 + 级联替换 prompts |

#### 预览面板 (L1-L7 右侧详情)

产品管理页右侧预览面板按 L1-L7 层级折叠展示，数据与 `ProductCreate` 表单完全对齐：
- **L1** 基本信息含上架渠道/售卖地区标签
- **L2** 12 格 grid：尺寸/容量/毛重(g)/材质/表面处理/主色系/热源类型/最小功率/最大功率 + 技术优势 + 使用说明
- **L3** 核心卖点 tags + 差异化定位
- **L4** 标题中英/长描述 + search_keywords (A/B/C 颜色标签)
- **L5** Q&A库 + 差评应对（序号展示）
- **L6** 5 子层展开：原始素材层 / AI 生成层 / 渠道版本层 / 社媒素材层 / 参考辅助层
- **L7** 图像提示词模板 + 视频提示词模板分区

#### L5 图像上传 + 灯箱查看器

| 特性                 | 实现方式                                                                                                                                                        |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **多图上传**           | 使用 `<input type="file" multiple accept="image/*">` 选择多图，通过 `FormData` 发送到 `POST /api/products/images/upload`，后端保存至 `uploads/images/` 并通过 `StaticFiles` 对外服务 |
| **预览网格**           | 上传完成后返回的 URL 数组以 3 列网格缩略图展示                                                                                                                                 |
| **灯箱查看器**          | `viewerIndex` 状态 + `fixed inset-0` 全屏遮罩弹窗，展示原图尺寸，底部工具栏含页码指示 + 下载按钮                                                                                          |
| **键盘导航**           | `useEffect` 监听 `keydown` → `ArrowLeft` 上一张 / `ArrowRight` 下一张 / `Escape` 关闭灯箱                                                                               |
| **移除 ai\_prompts** | `ai_prompts` 字段从前端表单、TypeScript 类型定义和 `buildCreatePayload` 中彻底移除（Prompt 管理统一归入 L6）                                                                          |

#### 草稿系统

| 特性                 | 实现方式                                                                                                                                                        |
| ---------------- | ------------------------------------------------------------ |
| **草稿表** | `product_drafts` 表存储 L1-L7 全层数据（JSON dict），与产品表结构平行 |
| **草稿箱页面** | `DraftBox.tsx` 展示所有草稿列表，每个草稿含"编辑"/"发布"/"删除"按钮 |
| **新建草稿** | `ProductCreate` → 填写部分字段 → 保存草稿 → `POST /api/products/drafts` |
| **编辑草稿** | 草稿箱"编辑" → `/products/create/{draftId}` → `api.drafts.get(draftId)` 加载后填满表单 |
| **发布草稿** | 草稿箱"发布" → `POST /api/products/drafts/{id}/publish` 或 ProductCreate 表单中点击"发布" |
| **编辑已发布产品** | `/products/edit/{sku}` → `api.products.get(sku)` 加载 → 保存草稿不走 draft 路径，发布走 `PUT /products/{sku}/full` |
| **saved 标志** | 新建模式下保存草稿后在表单标题区展示草稿已保存指示（`draftId` 状态留存） |

#### Schema 类型定义

```typescript
// 后端序列化 → 前端结构
interface DimensionLine { label: string; value: string; unit: string }
interface CapacityLine  { label: string; value: string }
interface PriceLine     { currency: string; amount: number }

interface Product {
  // L1
  retail_prices?: PriceLine[]
  online_prices?: PriceLine[]
  grade: string          // "A类品" | "B类品" | "C类品"
  lifecycle: string      // "新品开发中" | "在售中" | "断货" | "清仓"
  launch_date: string    // ISO date

  // L2
  dimension_lines?: DimensionLine[]   // JSON TEXT 字段
  capacity_lines?:  CapacityLine[]    // JSON TEXT 字段
}
```

***

## 二、当前实现状态 vs 目标对比

### ✅ 已实现（架构已完成迁移）

| 层级 | 表                    | 当前字段                                                                                                                                                                                                                                       | 状态            |
| -- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------- |
| L1 | `products`           | sku, barcode, brand, series, name\_zh, name\_en, name\_ja, category, sub\_category, retail\_price, retail\_prices, online\_price, online\_prices, grade, listing\_channel, sales\_region, person\_in\_charge, lifecycle, launch\_date, creator\_id | ✅ 多币种/下拉/日期控件 + 上架渠道/售卖地区 |
| 🆕 | `product_categories` | id, name                                                                                                                                                                                                                                   | ✅ 19个预设分类+可新增 |
| L2 | `product_specs`      | dimension\_lines (JSON), gross\_weight, material, surface\_finish, capacity\_lines (JSON), main\_color, heat\_source, min\_power, max\_power, tech\_advantages (JSON), usage\_instructions, certifications (JSON), specs\_json (JSON) | ✅ 12字段就位，双功率输入框 |
| L3 | `product_business`   | core\_selling\_points (JSON), target\_audience, differentiation, price\_positioning, emotional\_value, use\_scenarios (JSON), competitors (JSON)                                                                                           | ✅ 已对齐  |
| L4 | `product_content`    | amazon\_title, website\_title, five\_bullets (JSON), listing\_zh, listing\_en, listing\_ja, a\_plus\_content, search\_keywords (JSON, `[{keyword,priority}]`), qa\_items (JSON), review\_tags (JSON), negative\_review\_coping (JSON) | ✅ 已对齐  |
| L5 | `product_media`      | main\_images, detail\_images, scene\_images, video\_urls, model\_3d\_paths, ai\_prompts, channel\_media, source\_white\_bg, source\_multi\_angle, source\_structure, source\_exploded, source\_size, source\_function, source\_usage\_steps, source\_storage, source\_accessories, source\_bundle, source\_3d, source\_outdoor, ai\_generated, channel\_versions, social\_media, social\_ads, social\_video\_urls, ref\_packaging, ref\_manual, ref\_certification, ref\_dealer, ref\_brand\_style, ref\_competitor, ref\_archive, ref\_banned | ✅ 35字段就位：5子层 |
| L6 | `product_prompts`    | template\_name, prompt\_text, parameters, version, usage\_count                                                                                                                                                                            | ✅ 已对齐         |

### ⚠️ 需要修改（权限体系重构）

| 文件                                          | 修改内容                                                      | 原因            |
| ------------------------------------------- | --------------------------------------------------------- | ------------- |
| `backend/app/models/user.py`                | `role` 字段值域扩展：`super_admin` / `user`                      | 区分系统级管理员与普通用户 |
| `backend/app/schemas/user.py`               | `UserResponse` 增加 `groups` 字段                             | 前端获取用户团队信息    |
| `backend/app/core/security.py`              | 新增 `get_current_super_admin`、`require_product_permission` | 团队权限准入控制      |
| `backend/app/api/products.py`               | 所有写操作接口加 `require_product_permission` 依赖                  | 按团队校验增/改/删权限  |
| `backend/app/api/auth.py`                   | `/auth/me` 返回用户团队列表                                       | 前端初始化权限上下文    |
| `backend/app/services/product_service.py`   | 创建产品时自动记录 `creator_id`                                    | 审计追踪          |
| `frontend/src/types/index.ts`               | `User` 类型增加 `groups` 字段，新增 `UserGroup` 类型                 | 类型同步          |
| `frontend/src/store/authStore.ts`           | 存储用户团队信息                                                  | 全局权限状态        |
| `frontend/src/App.tsx`                      | `AdminRoute` → `SuperAdminRoute`，新增 `TeamRoute`           | 按角色/团队路由守卫    |
| `frontend/src/components/layout/Header.tsx` | 按团队角色显示导航项                                                | 导航权限适配        |
| `frontend/src/pages/AdminUsers.tsx`         | 增加用户分配团队 UI                                               | 超级管理员管理团队归属   |

### 🆕 需要新增

| 文件                                      | 内容                | 说明                                      |
| --------------------------------------- | ----------------- | --------------------------------------- |
| `backend/app/models/group.py`           | 🆕 `Group` 模型     | 团队定义表                                   |
| `backend/app/models/user_group.py`      | 🆕 `UserGroup` 模型 | 用户-团队关联表                                |
| `backend/app/services/group_service.py` | 🆕 团队管理服务层        | 团队 CRUD + 成员管理                          |
| `backend/app/api/groups.py`             | 🆕 团队管理 API 路由    | `POST/GET/PUT/DELETE /api/admin/groups` |
| `backend/app/db/seed.py`                | 🆕 数据库种子脚本        | 预置产品团队/设计团队                             |
| `frontend/src/pages/AdminGroups.tsx`    | 🆕 团队管理页面         | 超级管理员管理团队与成员                            |
| `frontend/src/pages/ProductDetail.tsx`  | 产品详情页（独立页面，非抽屉）   | 更好的浏览体验                                 |

***

## 三、团队权限体系（重磅升级）

> 🎯 **设计目标**：产品管理系统由各部门协作填写，以团队(组)为单位管理权限。用户通过加入团队自动继承团队权限，每个团队区分组管理员和普通成员。超级管理员拥有全部权限。未来支持动态创建/管理用户组。

***

### 3.1 权限模型架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                        系统角色 (system_role)                         │
│                                                                      │
│   super_admin (超级管理员)          user (普通用户)                     │
│   ├─ 拥有全部权限                   ├─ 权限由所属团队决定               │
│   ├─ 用户管理/系统设置              ├─ 可属于多个团队                   │
│   ├─ 团队管理 (CRUD)               └─ 每个团队内有一个组角色             │
│   └─ 无条件全操作                                                  │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                       团队 (groups) - 可扩展                           │
│                                                                      │
│   ┌─────────────────────┐    ┌─────────────────────┐                 │
│   │    产品团队          │    │    设计团队          │                 │
│   │    (Product Team)    │    │    (Design Team)     │                 │
│   ├─────────────────────┤    ├─────────────────────┤                 │
│   │ 组管理员 (admin)      │    │ 组管理员 (admin)      │                 │
│   │ ├─ AI 生成 ✅        │    │ ├─ AI 生成 ✅        │                 │
│   │ ├─ 产品添加 ✅        │    │ ├─ 产品添加 ✅        │                 │
│   │ ├─ 产品修改 ✅        │    │ ├─ 产品修改 ✅        │                 │
│   │ └─ 产品删除 ✅        │    │ └─ 产品删除 ❌        │                 │
│   ├─────────────────────┤    ├─────────────────────┤                 │
│   │ 普通成员 (member)     │    │ 普通成员 (member)     │                 │
│   │ ├─ AI 生成 ✅        │    │ ├─ AI 生成 ✅        │                 │
│   │ ├─ 产品添加 ✅        │    │ ├─ 产品添加 ✅        │                 │
│   │ ├─ 产品修改 ✅        │    │ ├─ 产品修改 ✅        │                 │
│   │ └─ 产品删除 ❌        │    │ └─ 产品删除 ❌        │                 │
│   └─────────────────────┘    └─────────────────────┘                 │
│                                                                      │
│   🆕 未来扩展：运营团队、市场团队...  (超级管理员可动态创建)           │
└──────────────────────────────────────────────────────────────────────┘
```

***

### 3.2 数据库模型设计

#### 3.2.1 团队表 `groups`

| 字段            | 类型          | 必填     | 说明                        |
| ------------- | ----------- | ------ | ------------------------- |
| `id`          | UUID        | ✅      | 团队唯一标识                    |
| `name`        | VARCHAR(64) | ✅      | 团队名称，全局唯一（如 `产品团队`）       |
| `description` | TEXT        | <br /> | 团队描述                      |
| `is_preset`   | BOOLEAN     | ✅      | 是否为预设团队（预设团队不可删除，默认 True） |
| `created_at`  | TIMESTAMP   | ✅      | <br />                    |
| `updated_at`  | TIMESTAMP   | ✅      | <br />                    |

**预置数据（数据库初始化时自动创建）：**

| name   | description          | is\_preset |
| ------ | -------------------- | ---------- |
| `产品团队` | 产品管理部门，负责产品元数据录入与维护  | True       |
| `设计团队` | 设计部门，负责产品视觉素材与 AI 生成 | True       |

#### 3.2.2 用户-团队关联表 `user_groups`

| 字段           | 类型          | 必填 | 说明                                  |
| ------------ | ----------- | -- | ----------------------------------- |
| `id`         | UUID        | ✅  | 关联记录 ID                             |
| `user_id`    | UUID        | ✅  | FK → users.id                       |
| `group_id`   | UUID        | ✅  | FK → groups.id                      |
| `group_role` | VARCHAR(16) | ✅  | 团队内角色：`admin`（组管理员）/ `member`（普通成员） |
| `created_at` | TIMESTAMP   | ✅  | 加入时间                                |

> **唯一约束**: `(user_id, group_id)` 复合唯一，一个用户在同一团队只有一种身份。

#### 3.2.3 用户表 `users` 修改

| 变更                   | 说明                                               |
| -------------------- | ------------------------------------------------ |
| `role` 字段语义升级        | `super_admin` = 系统超级管理员 / `user` = 普通用户（权限由团队决定） |
| 移除旧 `role="admin"` 值 | 旧管理员迁移为 `super_admin`                            |

> 📌 `User` 模型不变更字段名，仅扩展 `role` 的值域和语义。现有 `admin` 用户通过数据迁移脚本转为 `super_admin`。

***

### 3.3 完整权限矩阵

#### 3.3.1 产品管理权限

| 操作           | super\_admin | 产品团队-组管理员 | 产品团队-普通成员 | 设计团队-组管理员 | 设计团队-普通成员 | 无团队用户 |
| ------------ | :----------: | :-------: | :-------: | :-------: | :-------: | :---: |
| 查看产品列表       |       ✅      |     ✅     |     ✅     |     ✅     |     ✅     |   ❌   |
| 查看产品详情       |       ✅      |     ✅     |     ✅     |     ✅     |     ✅     |   ❌   |
| 创建产品         |       ✅      |     ✅     |     ✅     |     ✅     |     ✅     |   ❌   |
| 修改产品 (L1-L6) |       ✅      |     ✅     |     ✅     |     ✅     |     ✅     |   ❌   |
| 删除产品         |       ✅      |     ✅     |     ❌     |     ❌     |     ❌     |   ❌   |
| 管理 Prompt 模板 |       ✅      |     ✅     |     ✅     |     ✅     |     ✅     |   ❌   |

#### 3.3.2 AI 生成权限

| 操作     | super\_admin |  产品团队  |  设计团队  | 无团队用户 |
| ------ | :----------: | :----: | :----: | :---: |
| 文生图    |       ✅      |    ✅   |    ✅   |   ❌   |
| 图生图    |       ✅      |    ✅   |    ✅   |   ❌   |
| 查看生成历史 |       ✅      | ✅(自己的) | ✅(自己的) |   ❌   |

#### 3.3.3 系统管理权限

| 操作                | super\_admin | 组管理员 | 普通成员 |
| ----------------- | :----------: | :--: | :--: |
| 用户管理 (CRUD)       |       ✅      |   ❌  |   ❌  |
| 用户分配团队            |       ✅      |   ❌  |   ❌  |
| 系统设置 (API 配置)     |       ✅      |   ❌  |   ❌  |
| 团队管理 (创建/编辑/删除团队) |       ✅      |   ❌  |   ❌  |
| 查看全量历史记录          |       ✅      |   ❌  |   ❌  |

***

### 3.4 后端准入控制实现

#### 3.4.1 新增依赖注入函数 (`core/security.py`)

```python
# 1. 获取当前用户（保持不变）
def get_current_user(...) -> User

# 2. 超级管理员校验（替换旧 get_current_admin_user）
def get_current_super_admin(current_user) -> User:
    if current_user.role != "super_admin":
        raise HTTPException(403, "Super admin privileges required")
    return current_user

# 3. 获取用户的团队及角色信息
def get_user_groups(db, user_id) -> list[dict]:
    # 返回: [{"group_id": "...", "group_name": "产品团队", "group_role": "admin"}, ...]

# 4. 产品操作权限校验（关键新增）
def require_product_permission(action: str):
    """
    依赖注入工厂函数，返回一个 FastAPI Depends
    action: "create" | "update" | "delete"
    """
    def checker(current_user, db):
        # super_admin 直接放行
        if current_user.role == "super_admin":
            return current_user
        # 查询用户所属团队
        user_groups = db.query(UserGroup).filter(UserGroup.user_id == current_user.id).all()
        if not user_groups:
            raise HTTPException(403, "You are not in any team")
        # delete 操作：仅产品团队-组管理员 可执行
        if action == "delete":
            for ug in user_groups:
                group = db.query(Group).filter(Group.id == ug.group_id).first()
                if group.name == "产品团队" and ug.group_role == "admin":
                    return current_user
            raise HTTPException(403, "Delete requires Product Team admin role")
        # create / update 操作：产品团队或设计团队成员均可
        for ug in user_groups:
            group = db.query(Group).filter(Group.id == ug.group_id).first()
            if group.name in ("产品团队", "设计团队"):
                return current_user
        raise HTTPException(403, "Product management requires team membership")
    return checker
```

#### 3.4.2 API 路由权限映射

| API 端点                             | 当前依赖                     | 改为                                     |
| ---------------------------------- | ------------------------ | -------------------------------------- |
| `GET /api/products`                | `get_current_user`       | ✅ 保持不变（列表查看无需团队限制）                     |
| `GET /api/products/{sku}`          | `get_current_user`       | ✅ 保持不变                                 |
| `POST /api/products`               | `get_current_user`       | `require_product_permission("create")` |
| `PUT /api/products/{sku}`          | `get_current_user`       | `require_product_permission("update")` |
| `PUT /api/products/{sku}/full`    | `get_current_user`       | `require_product_permission("update")` |
| `DELETE /api/products/{sku}`       | `get_current_user`       | `require_product_permission("delete")` |
| `PUT /api/products/{sku}/specs`    | `get_current_user`       | `require_product_permission("update")` |
| `PUT /api/products/{sku}/business` | `get_current_user`       | `require_product_permission("update")` |
| `PUT /api/products/{sku}/content`  | `get_current_user`       | `require_product_permission("update")` |
| `PUT /api/products/{sku}/media`    | `get_current_user`       | `require_product_permission("update")` |
| `POST /api/products/images/upload` | `get_current_user`       | `require_product_permission("update")` |
| `POST /api/products/{sku}/prompts` | `get_current_user`       | `require_product_permission("update")` |
| `GET/POST /api/admin/*`            | `get_current_admin_user` | `get_current_super_admin`              |
| `GET /api/auth/me`                 | `get_current_user`       | 增强：返回用户团队信息                            |

***

### 3.5 前端路由与导航改造

#### 3.5.1 路由守卫变更

```typescript
// App.tsx - 新增守卫组件

// 超级管理员守卫（替换旧 AdminRoute）
function SuperAdminRoute({ children }) {
  const { token, user } = useAuthStore()
  if (!token) return <Navigate to="/login" />
  if (user?.role !== 'super_admin') return <Navigate to="/" />
  return <>{children}</>
}

// 团队守卫：检查用户是否在任意产品相关团队
function TeamRoute({ children }) {
  const { token, user, groups } = useAuthStore()
  if (!token) return <Navigate to="/login" />
  const hasTeamAccess = groups?.some(g => 
    g.group_name === '产品团队' || g.group_name === '设计团队'
  )
  if (!hasTeamAccess) return <Navigate to="/" />
  return <>{children}</>
}
```

#### 3.5.2 路由表更新

| 路径                | 旧守卫              | 新守卫               | 原因            |
| ----------------- | ---------------- | ----------------- | ------------- |
| `/products`       | `AdminRoute`     | `TeamRoute`       | 产品/设计团队成员均可访问 |
| `/admin/users`    | `AdminRoute`     | `SuperAdminRoute` | 仅超级管理员        |
| `/admin/settings` | `AdminRoute`     | `SuperAdminRoute` | 仅超级管理员        |
| `/admin/groups`   | —                | `SuperAdminRoute` | 🆕 团队管理页      |
| `/`               | `ProtectedRoute` | `TeamRoute`       | AI 生成需要团队权限   |
| `/history`        | `ProtectedRoute` | `ProtectedRoute`  | 登录即可（看自己的）    |

#### 3.5.3 Header 导航改造

| 导航项  | 当前可见条件                    | 改为                       |
| ---- | ------------------------- | ------------------------ |
| 创作   | 所有用户                      | 团队成员 (产品/设计)             |
| 历史   | 所有用户                      | 所有登录用户                   |
| 产品   | `role === 'admin'` (管理下拉) | 团队成员 (主导航独立显示)           |
| 管理 ▼ | `role === 'admin'`        | `role === 'super_admin'` |
| └ 用户 | 管理下拉                      | 管理下拉                     |
| └ 设置 | 管理下拉                      | 管理下拉                     |
| └ 团队 | —                         | 🆕 管理下拉新增                |

***

### 3.6 权限决策流程图

```
用户请求 DELETE /api/products/{sku}
            │
            ▼
    ┌───────────────────┐
    │ 1. JWT 解析身份    │
    └────────┬──────────┘
             │
             ▼
    ┌───────────────────┐     Yes    ┌──────────┐
    │ 2. role==super_admin? │─────────→│ 允许删除  │
    └────────┬──────────┘           └──────────┘
             │ No
             ▼
    ┌───────────────────────────────┐
    │ 3. 查询 user_groups           │
    │    user_id → [group, role]   │
    └───────────────┬───────────────┘
                    │
                    ▼
    ┌───────────────────────────────┐     Yes    ┌──────────┐
    │ 4. group=产品团队 AND         │─────────→│ 允许删除  │
    │    group_role=admin?          │           └──────────┘
    └───────────────┬───────────────┘
                    │ No
                    ▼
              ┌──────────┐
              │ 403 拒绝  │
              └──────────┘
```

***

### 3.7 未来扩展：动态团队管理

```
当前阶段 (v1)                         未来阶段 (v2)
─────────────────────────         ─────────────────────────
2个预设团队 (产品/设计)    ──→     超级管理员可动态创建团队
团队名硬编码               ──→     团队名自定义，支持中文/英文
is_preset=True 不可删除    ──→     is_preset=False 可删除
无独立权限模板             ──→     每个团队可配置权限模板
                                      (产品权限/AI生成权限 可开关)

API 预留:
  POST   /api/admin/groups          创建团队
  GET    /api/admin/groups          团队列表
  PUT    /api/admin/groups/{id}     编辑团队
  DELETE /api/admin/groups/{id}     删除团队 (仅非预设)
  POST   /api/admin/groups/{id}/users   添加用户到团队
  DELETE /api/admin/groups/{id}/users/{uid}  移除用户
  PUT    /api/admin/groups/{id}/users/{uid}  修改用户在团队中的角色
```

***

## 四、系统架构全景图

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Frontend (React + TypeScript + Vite)                │
│                                                                            │
│  主导航:    创作(/)  │  历史(/history)  │  产品(/products)   │  管理 ▼     │
│                                  │                          │             │
│              ┌───────────────────┴─────────────────────┐    │             │
│              │        Zustand Store (authStore)         │    │             │
│              └───────────────────┬─────────────────────┘    │             │
│                                  │                          │             │
│              ┌───────────────────┴─────────────────────┐    │             │
│              │       api.ts (JWT Bearer Token)          │    │             │
│              └───────────────────┬─────────────────────┘    │             │
└──────────────────────────────────┼────────────────────────────┘
                                   │  HTTP/JSON
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       Backend (Python FastAPI)                             │
│                                                                            │
│  API Routes:                                                              │
│  ┌──────────┬──────────┬─────────────┬──────────┬──────────┬────────┐    │
│  │ /auth    │ /users   │ /generation │ /history │/products │/admin  │    │
│  │ 登录注册 │ 用户管理 │ AI 生成    │ 生成记录  │ 产品元数据│ 系统配置│    │
│  └──────────┴──────────┴─────────────┴──────────┴──────────┴────────┘    │
│                                   │                                       │
│  Services:                                                               │
│  ┌──────────────┬──────────────┬──────────────┬─────────────────────┐    │
│  │ user_service │dmxapi_service│generation_svc│  product_service     │    │
│  └──────────────┴──────────────┴──────────────┴─────────────────────┘    │
│                                   │                                       │
├───────────────────────────────────┼───────────────────────────────────────┤
│                        SQLite Database                                    │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────┬──────────┐     │
│  │  users  │ groups   │ user_    │ product_ │generation│ system   │     │
│  │         │          │ groups   │categories│    s     │ _config  │     │
│  ├─────────┼──────────┼──────────┼──────────┼──────────┼──────────┤     │
│  │ products│ product  │ product  │ product  │ product  │ product  │     │
│  │  (L1)   │ _specs   │_business │_content  │ _media   │_prompts  │     │
│  │ PK:sku  │  (L2)    │   (L3)   │  (L4)    │   (L5)   │  (L6)    │     │
│  └─────────┴──────────┴──────────┴──────────┴──────────┴──────────┘     │
└──────────────────────────────────────────────────────────────────────────┘
                                   │  HTTPS
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      External: dmxapi.cn                                   │
│   POST /v1/images/generations   (文生图)                                  │
│   POST /v1/images/edits         (图生图)                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

***

## 五、AI 图像生成与产品元数据融合方案

### 5.1 数据流全景（按需加载模式）

> 🎯 **核心设计理念**：用户在创作页通过搜索 SKU/关键词定位产品，选中后系统从数据库拉取产品元数据，按模板拼接成完整 Prompt 并回填到前端提示词输入框。**不搜索 = 不拉数据 = 保持空白提示词框，用户自由创作。**

```
┌─────────────────────────────────────────────────────────────────┐
│                     前端创作页 (Workspace)                        │
│                                                                  │
│   ┌──────────────────────────────────────────────────────┐      │
│   │  🔍 搜索产品 SKU/名称...    [下拉匹配列表]   [清空]    │      │
│   └──────────────────────┬───────────────────────────────┘      │
│                          │ ① 用户搜索 → 选择产品                   │
│                          ▼                                       │
│   ┌──────────────────────────────────────────────────────┐      │
│   │  📦 已选产品: PRO-2025-001 智能蓝牙音箱                │      │
│   │  [模板: 电商主图] ▼  [模板: 场景合成] [模板: 社媒营销]  │      │
│   └──────────────────────┬───────────────────────────────┘      │
│                          │ ② 选择生成模板                         │
│                          ▼                                       │
│   ┌──────────────────────────────────────────────────────┐      │
│   │  Prompt: 智能蓝牙音箱，ABS+PC合金材质，深空灰色，        │      │
│   │  白底棚拍，商业摄影，超高分辨率，8K                      │      │
│   │  [可手动编辑]                               [生成]     │      │
│   └──────────────────────────────────────────────────────┘      │
│                          │ ③ 拼接完成 → 用户确认/修改 → 生成      │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                           │  HTTPS (仅在选择产品后触发)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Backend API                                │
│                                                                   │
│  GET /api/products/search?q=蓝牙音箱                              │
│       ↓ 返回匹配产品列表 (sku, name_zh)                             │
│                                                                   │
│  GET /api/products/{sku}/assemble-prompt?template=电商主图          │
│       ↓ Prompt 组装服务 (prompt_builder.py)                        │
│       ↓ ① 查询产品 L1-L6 数据                                     │
│       ↓ ② 根据 template 映射表提取字段                            │
│       ↓ ③ 替换 L6 prompt_text 中的 {变量} 占位符                  │
│       ↓ ④ 返回 assembled_prompt + prompt_text(原始模板)            │
│                                                                   │
│  返回 JSON:                                                       │
│  {                                                                │
│    "assembled_prompt": "智能蓝牙音箱，ABS+PC合金...",               │
│    "template_name": "电商主图",                                    │
│    "variables_used": {"name_zh":"...", "material":"...", ...}     │
│  }                                                                │
└──────────────────────────────────────────────────────────────────┘
```

```
                       交互时序 (无搜索 = 无请求)

  用户不搜索 SKU                用户搜索 + 选择产品
  ──────────────               ──────────────────────
  提示词框空白                  ① 输入关键词 → GET /api/products/search
  用户手写 Prompt               ② 下拉列表展示匹配产品
  直接点击生成                  ③ 点击某个产品 → GET /api/products/{sku}
                               ④ 展示产品摘要 + 可选模板
                               ⑤ 选择模板 → GET /api/products/{sku}/assemble-prompt
                               ⑥ 拼接后的 Prompt 回填到输入框
                               ⑦ 用户可自由编辑
                               ⑧ 点击生成 → 正常走 dmxapi.cn 流程
```

### 5.2 Prompt 智能组装映射表

| 生成目标    | L1          | L2              | L3                    | L4           | L5              | L6     | 说明    |
| ------- | ----------- | --------------- | --------------------- | ------------ | --------------- | ------ | ----- |
| 白底主图    | name\_zh/en | material, color | selling\_points\[0]   | -            | -               | 产品棚拍模板 | 基础商品图 |
| 场景图     | name\_zh    | dimensions      | use\_scenarios\[0]    | -            | -               | 场景合成模板 | 带使用场景 |
| 细节特写    | name\_zh    | material        | selling\_points\[1:3] | -            | detail\_images  | 细节展示模板 | 局部放大  |
| 视频素材    | name\_zh    | color           | use\_scenarios        | -            | video\_urls(参考) | 视频生成模板 | 短视频   |
| Listing | name\_en    | material,color  | selling\_points       | listing\_en  | -               | 文案生成模板 | 电商文案  |
| 社交媒体    | name\_zh    | color           | target\_audience      | review\_tags | scene\_images   | 社媒营销模板 | 种草内容  |

***

## 六、API 接口设计总览

### 7.1 产品 CRUD（L1 身份层）

| 方法       | 路径                            | 说明                  | 权限                      |
| -------- | ----------------------------- | ------------------- | ----------------------- |
| `GET`    | `/api/products`               | 获取产品列表（支持搜索、分页）     | 团队成员                    |
| `GET`    | `/api/products/{sku}`         | 获取产品详情              | 团队成员                    |
| `GET`    | `/api/products/search?q={kw}` | 🔍 按关键词/SKU搜索产品     | 团队成员                    |
| `POST`   | `/api/products`               | 创建产品                | 团队成员                    |
| `PUT`    | `/api/products/{sku}`         | 更新产品基本信息            | 团队成员                    |
| `PUT`    | `/api/products/{sku}/full`    | 🆕 全量更新产品 (L1-L7 全覆盖) | 团队成员                    |
| `DELETE` | `/api/products/{sku}`         | 删除产品（级联删除 L2-L6 数据） | 产品团队-管理员 / super\_admin |

### 7.1b 系统分类管理 🆕

| 方法       | 路径                     | 说明      | 权限   |
| -------- | ---------------------- | ------- | ---- |
| `GET`    | `/api/categories`      | 获取所有分类  | 无需登录 |
| `POST`   | `/api/categories`      | 新增自定义分类 | 登录用户 |
| `DELETE` | `/api/categories/{id}` | 删除分类    | 登录用户 |

### 7.2 规格管理（L2-L6 层级操作）

| 方法       | 路径                                 | 说明                  | 权限                      |
| -------- | ---------------------------------- | ------------------- | ----------------------- |
| `PUT`    | `/api/products/{sku}/specs`        | 更新物理规格 (L2)         | 团队成员                    |
| `PUT`    | `/api/products/{sku}/business`     | 更新商业价值 (L3)         | 团队成员                    |
| `PUT`    | `/api/products/{sku}/content`      | 更新内容素材 (L4)         | 团队成员                    |
| `PUT`    | `/api/products/{sku}/media`        | 更新多媒体资产 (L5)        | 团队成员                    |
| `POST`   | `/api/products/images/upload`      | 🆕 上传产品图片（多文件）      | 团队成员                    |
| `GET`    | `/api/products/{sku}/prompts`      | 获取 Prompt 模板列表 (L6) | 团队成员                    |
| `POST`   | `/api/products/{sku}/prompts`      | 新增 Prompt 模板 (L6)   | 团队成员                    |
| `PUT`    | `/api/products/{sku}/prompts/{id}` | 更新 Prompt 模板 (L6)   | 团队成员                    |
| `DELETE` | `/api/products/{sku}/prompts/{id}` | 删除 Prompt 模板 (L6)   | 产品团队-管理员 / super\_admin |

### 7.3 AI 融合接口

| 方法     | 路径                                                    | 说明              | 权限   |
| ------ | ----------------------------------------------------- | --------------- | ---- |
| `GET`  | `/api/products/{sku}/assemble-prompt?template={name}` | 🆕 按模板拼接 Prompt | 团队成员 |
| `POST` | `/api/products/{sku}/generate`                        | 🆕 产品一键生成（未来）   | 团队成员 |

### 7.4 团队管理接口 🆕

| 方法       | 路径                                   | 说明         | 权限           |
| -------- | ------------------------------------ | ---------- | ------------ |
| `GET`    | `/api/admin/groups`                  | 团队列表       | super\_admin |
| `POST`   | `/api/admin/groups`                  | 创建团队       | super\_admin |
| `PUT`    | `/api/admin/groups/{id}`             | 编辑团队       | super\_admin |
| `DELETE` | `/api/admin/groups/{id}`             | 删除团队（仅非预设） | super\_admin |
| `POST`   | `/api/admin/groups/{id}/users`       | 添加用户到团队    | super\_admin |
| `DELETE` | `/api/admin/groups/{id}/users/{uid}` | 移除用户       | super\_admin |
| `PUT`    | `/api/admin/groups/{id}/users/{uid}` | 修改用户团队角色   | super\_admin |

***

## 七、实施步骤

### 阶段 0：团队权限体系 🔴 当前任务

| 步骤   | 文件                                          | 操作                                                                                        |
| ---- | ------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 0.0  | `backend/app/models/*`                      | 🔧 **Schema 迁移**：L1 去掉 `id` 字段，`sku` 做主键；L2-L6 将 `product_id`(UUID) 改为 `sku`(VARCHAR(64)) |
| 0.1  | `backend/app/models/group.py`               | 🆕 创建 `Group` 模型                                                                          |
| 0.2  | `backend/app/models/user_group.py`          | 🆕 创建 `UserGroup` 关联模型                                                                    |
| 0.3  | `backend/app/db/seed.py`                    | 🆕 数据库种子脚本：预置「产品团队」「设计团队」                                                                 |
| 0.4  | `backend/app/models/user.py`                | 更新 `role` 字段注释/校验，确认 `super_admin` 语义                                                     |
| 0.5  | `backend/app/core/security.py`              | 新增 `get_current_super_admin` + `require_product_permission`                               |
| 0.6  | `backend/app/schemas/user.py`               | `UserResponse` 增加 `groups` 字段                                                             |
| 0.7  | `backend/app/schemas/product.py`            | 更新 Schema：所有路径参数和响应中的 `id` → `sku`                                                        |
| 0.8  | `backend/app/services/product_service.py`   | 更新查询逻辑：`product_id` → `sku`，创建产品自动记录 `creator_id`                                         |
| 0.9  | `backend/app/services/group_service.py`     | 🆕 团队 CRUD + 成员管理服务                                                                       |
| 0.10 | `backend/app/api/products.py`               | 路径参数 `{id}` → `{sku}`，写操作接入 `require_product_permission`                                  |
| 0.11 | `backend/app/api/groups.py`                 | 🆕 团队管理 API 路由                                                                            |
| 0.12 | `backend/app/api/auth.py`                   | `/auth/me` 返回用户所属团队                                                                       |
| 0.13 | `frontend/src/types/index.ts`               | 新增 `UserGroup` 类型，`User` 增加 `groups`，产品 `id` → `sku`                                      |
| 0.14 | `frontend/src/services/api.ts`              | 产品 API 路径更新 `{id}` → `{sku}`                                                              |
| 0.15 | `frontend/src/store/authStore.ts`           | 增加 `groups` 状态，`loadFromStorage` 支持团队持久化                                                  |
| 0.16 | `frontend/src/pages/ProductManagement.tsx`  | 更新页面逻辑：产品标识用 `sku` 替代 `id`                                                                |
| 0.17 | `frontend/src/App.tsx`                      | `AdminRoute` → `SuperAdminRoute` + 新增 `TeamRoute`                                         |
| 0.18 | `frontend/src/components/layout/Header.tsx` | 按团队角色调整导航可见性                                                                              |
| 0.19 | `frontend/src/pages/AdminUsers.tsx`         | 增加用户团队分配 UI                                                                               |
| 0.20 | `frontend/src/pages/AdminGroups.tsx`        | 🆕 团队管理页面                                                                                 |
| 0.21 | 数据迁移脚本                                      | 现有 `admin` 用户 role 迁移为 `super_admin`                                                      |

### 阶段 1：按需 Prompt 组装（搜索 → 加载 → 拼接）

| 步骤  | 文件                                       | 操作                                                               |
| --- | ---------------------------------------- | ---------------------------------------------------------------- |
| 1.1 | `backend/app/services/prompt_builder.py` | 🆕 创建 Prompt 组装服务（按 template 映射表提取 L1-L6 字段 + 替换 L6 模板中的 `{变量}`） |
| 1.2 | `backend/app/api/products.py`            | 🆕 `GET /api/products/{sku}/assemble-prompt?template=电商主图`       |
| 1.3 | `frontend/src/pages/Workspace.tsx`       | 新增产品搜索框（SKU/名称下拉匹配）+ 模板选择器 + 拼接按钮                                |
| 1.4 | `frontend/src/services/api.ts`           | 新增 `searchProducts` + `assemblePrompt` API 调用                    |

### 阶段 2：素材回写闭环

| 步骤 | 文件                                          | 操作                     |
| -- | ------------------------------------------- | ---------------------- |
| 1  | `backend/app/models/product_generations.py` | 🆕 产品-生成关联表            |
| 2  | `backend/app/services/product_service.py`   | 生成完成后回写 product\_media |
| 3  | `frontend/src/pages/ProductDetail.tsx`      | 🆕 展示产品的所有生成素材         |

***

## 八、数据库文件对照清单

| 层级 | 模型文件                                     | 表名                   | 主键              | 关联键                  |
| -- | ---------------------------------------- | -------------------- | --------------- | -------------------- |
| L1 | `backend/app/models/product.py`          | `products`           | `sku` (VARCHAR) | —                    |
| 🆕 | `backend/app/models/product_category.py` | `product_categories` | `id` (INTEGER)  | —                    |
| L2 | `backend/app/models/product_specs.py`    | `product_specs`      | `id` (UUID)     | `sku` → products.sku |
| L3 | `backend/app/models/product_business.py` | `product_business`   | `id` (UUID)     | `sku` → products.sku |
| L4 | `backend/app/models/product_content.py`  | `product_content`    | `id` (UUID)     | `sku` → products.sku |
| L5 | `backend/app/models/product_media.py`    | `product_media`      | `id` (UUID)     | `sku` → products.sku |
| L6 | `backend/app/models/product_prompts.py`  | `product_prompts`    | `id` (UUID)     | `sku` → products.sku |
| 🆕 | `backend/app/models/group.py`            | `groups`             | `id` (UUID)     | —                    |
| 🆕 | `backend/app/models/user_group.py`       | `user_groups`        | `id` (UUID)     | user\_id + group\_id |

## 九、风险与注意事项

| 风险            | 说明                                                     | 应对措施                                 |
| ------------- | ------------------------------------------------------ | ------------------------------------ |
| **Schema 迁移** | L1 去掉 `id` 用 `sku` 做主键，L2-L6 `product_id`→`sku` 是破坏性变更 | 删除旧 db 文件重建（开发阶段数据量小，可接受）            |
| 数据一致性         | 多表关联时，通过 `sku` 字符串关联需确保引用完整性                           | 使用数据库外键 + 事务                         |
| JSON 字段索引     | JSON 文本字段（如 selling\_points）查询效率低                      | 对高频搜索字段建立独立索引或考虑 JSONB               |
| 多语言支持         | 中/英/日三语字段固定列设计                                         | 当前方案可行，未来可扩展为关联表                     |
| 多媒体文件         | 图片/视频 URL 仅存储链接，文件实际存储需外部方案                            | 使用外部存储/CDN，当前仅存 URL                  |
| **权限边界**      | 产品团队-管理员可删产品，设计团队全员不可删                                 | 后端 `require_product_permission` 严格校验 |

***

## 十、总结

| 模块                                       |   已完成  |   进行中  |   待开发  |
| ---------------------------------------- | :----: | :----: | :----: |
| 用户系统 (注册/登录/JWT)                         |    ✅   | <br /> | <br /> |
| AI 图像生成 (文生图+图生图)                        |    ✅   | <br /> | <br /> |
| 生成历史 (搜索+统计看板)                           |    ✅   | <br /> | <br /> |
| 产品元数据库 (L1-L6 7张表，含 product\_categories) |    ✅   | <br /> | <br /> |
| 产品管理页面 (L1-L7 全层级表单+详情+预览面板)          |    ✅   | <br /> | <br /> |
| L1 表单优化 (多币种/下拉/日期/名称同行/上架渠道/售卖地区)   |    ✅   | <br /> | <br /> |
| L2 表单优化 (动态尺寸行/动态容量行/双功率输入框/技术优势)  |    ✅   | <br /> | <br /> |
| L3 表单 (核心卖点/差异化定位/竞品分析)                |    ✅   | <br /> | <br /> |
| L4 表单 (多语言标题/搜索关键词/差评应对)              |    ✅   | <br /> | <br /> |
| L5 表单 (原始素材/AI生成/渠道版本/社媒/参考辅助 5子层) |    ✅   | <br /> | <br /> |
| L6/L7 表单 (图像+视频提示词模板)                    |    ✅   | <br /> | <br /> |
| 删除确认面板 (React 受控)                        |    ✅   | <br /> | <br /> |
| 已发布产品二次编辑 (全量更新API+路由)                |    ✅   | <br /> | <br /> |
| 草稿系统 (DraftBox/保存/编辑/发布)                 |    ✅   | <br /> | <br /> |
| 系统分类 CreatableSelect + 19预设              |    ✅   | <br /> | <br /> |
| 团队权限体系 (2预设团队+RBAC)                      |    ✅   | <br /> | <br /> |
| Prompt 自动组装引擎                            | <br /> | <br /> |   🔴   |
| 产品一键生成 (产品→AI)                           | <br /> | <br /> |   🔴   |
| 素材回写 (AI→产品)                             | <br /> | <br /> |   🟡   |
| L3-L7 表单优化（已完成）                         | <br /> | <br /> |   ✅   |
| 文生视频                                     | <br /> | <br /> |   🟡   |
| Docker 部署                                | <br /> | <br /> |   🟢   |

