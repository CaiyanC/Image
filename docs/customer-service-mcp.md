# 企业客服 MCP 试用指南

客服使用现有内部 SKU 查询产品知识。京东、淘宝、天猫和抖音可以各自使用平台标题和商品页，管理员把这些商品页关联到已经存在的 SKU。

## 员工接入

当前公网试用入口使用服务器统一连接，员工连接 MCP 后即可使用，设置 `CAIYAN_CUSTOMER_SERVICE_ANONYMOUS=1`。查询、会话和 QA 草稿统一记录到「客服 MCP 公网试用共享账号」，审核入口由后台人员管理。持有公网地址的人均可调用这些功能。

在支持 stdio MCP 的客户端中配置以下服务。脚本只依赖 Python 标准库。开发机可填本机网关地址，团队共用时填管理员提供的 HTTPS 主机地址。

```json
{
  "mcpServers": {
    "caiyan-customer-service": {
      "command": "python",
      "args": ["D:\\CaiYan\\Image-Generation-feature-v5\\backend\\scripts\\customer_service_mcp_server.py"],
      "env": {
        "CAIYAN_CUSTOMER_SERVICE_API": "http://127.0.0.1:18101",
        "CAIYAN_CUSTOMER_SERVICE_ANONYMOUS": "1"
      }
    }
  }
}
```

临时公网隧道重开后，使用新分配的 HTTPS 地址。

| 员工操作 | MCP 工具 | 返回内容 |
|---|---|---|
| 粘贴商品链接或输入商品名、SKU | `find_customer_products` | 已关联的 SKU 或商品名称候选。多规格由员工选定 |
| 查这个商品有没有相同问题 | `search_customer_qa` | 同 SKU 的已审核 QA 和来源 ID。相似候选需要核对适用条件 |
| 让 AI 参考该 SKU 的平台商品页 | `search_product_listing` | 已核对的页面摘录、来源链接及保存时间 |
| 用现有商品知识起草回复 | `ask_customer_service` | 答复、来源、会话 ID 和答复 ID。追问沿用会话 ID |
| 把当前问答存成 QA | `save_customer_qa_draft` | QA 编号和审核入口。重复提交返回原记录 |

例如，员工可以说「把这条保存为 SKU CS-G25 的 QA，问题和答案按我刚才确认的版本」。客户端提交已确认的通用问题和标准答案，有答复 ID 时一并提交。审核人打开返回的 `review_path`，核对规格、渠道和来源，点击「提交审核」。通过现有同 SKU 审核并完成索引后，客服问答即可复用这条记录。客户姓名、地址、订单号等内容应在收录前去掉。

## 数据存储

开发试用的商品数据、会话和审核状态存放在 PostgreSQL 的 `product_knowledge_dev` 数据库。

| 内容 | 数据表 |
|---|---|
| 商品及规格 | `products`、`product_specs`、`product_content` |
| QA 原文及审核状态 | `product_qa` |
| 检索文档及向量 | `knowledge_documents`、`knowledge_chunks` |
| 客服会话及消息 | `customer_service_conversations`、`customer_service_messages` |
| 平台商品 ID 映射及已核对页面摘录 | `customer_product_links` |
| 操作记录及连接令牌哈希 | `operation_logs`、`workbuddy_customer_service_tokens` |

## 商品链接维护

有产品编辑权限的人员在「添加产品 QA → 维护平台商品链接」选定已有 SKU，粘贴商品详情长链接并关联。平台商品 ID 相同的链接可带不同的分享参数。一个 SKU 可关联多个平台链接，一个链接可关联多个内部规格 SKU。

点击「读取商品页预览」可尝试读取公开页面提供的结构化资料。需要登录、网页由浏览器动态加载或平台未提供结构化资料时，由商品负责人从页面粘贴规格、配置和使用说明。核对所选 SKU 后点击「保存商品页资料」。员工按商品名或 SKU 提问也可以使用这些资料。商品页摘录仅补充页面口径，涉及规格冲突时核对产品主档。

当前解析京东桌面及移动商品长链接、淘宝和天猫商品详情长链接，以及含商品 ID 的抖音精选联盟详情长链接。平台短链请使用打开后的商品详情长链接。建议由渠道负责人提供「平台商品链接 → 内部 SKU」清单，从高频商品开始核对。不同平台的标题用于找候选，关联以渠道负责人核对的 SKU 为准。

## 公网接入

员工继续使用本地 stdio MCP 脚本，将 `CAIYAN_CUSTOMER_SERVICE_API` 改为管理员提供的 HTTPS 主机地址。地址末尾无需添加 `/api` 或 `/mcp`。公网试用入口的服务器连接配置保存在当前系统用户本地应用目录，客户端无需填写令牌。若需要按员工区分会话和审计，可在「智能客服 → WorkBuddy 智能客服接入」生成个人令牌，并使用 `CAIYAN_CUSTOMER_SERVICE_TOKEN` 接入。

将隧道或反向代理接到只监听回环地址的客服网关。在开发机的 `backend` 目录启动网关，默认上游是本机试用 API 的 18001 端口。

```powershell
.\venv\Scripts\python.exe -m uvicorn customer_service_public_gateway:app --app-dir scripts --host 127.0.0.1 --port 18101 --limit-concurrency 24 --no-access-log
```

公网 HTTPS 的上游设为 `http://127.0.0.1:18101`。网关只接受客服查询、问答和 QA 草稿接口，登录、令牌管理及审核界面继续通过公司的管理入口访问。正式使用时，给网关配置公司域名和稳定运行的隧道或 HTTPS 反向代理。[Cloudflare Tunnel 官方说明](https://developers.cloudflare.com/tunnel/)

## 团队试用优先检查

1. 收集真实客服问题，把未命中区分为商品没关联、同 SKU 缺事实、已有 QA 排名靠后和订单实时信息。按原因分派给商品、客服或订单负责人。
2. 用历史问题验证 SKU 命中、答案证据和追问体验。重点覆盖跨平台同款、多规格同链接、配件兼容、售后和安全问题。
3. 为待审核 QA 建立处理人和时限，定期回看被拒绝的问答与重复问题。商品规格、活动和售后政策变化时，按来源和 SKU 回查受影响的知识。
4. 价格、库存和物流接入各渠道受控实时接口后再提供具体结果。团队入口使用内部 HTTPS，客服保留回复确认权。
