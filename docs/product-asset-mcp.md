# 产品素材 MCP（本机只读）

项目提供一个本机 stdio MCP 适配器，让 WorkBuddy、Codex 等 MCP 客户端可以按 SKU/标签查找素材，并直接收到图片内容。

默认行为：

- 只连接 `backend/.env.dev`，避免误读生产库；
- 只返回 `review_status=approved`、`quality_status=usable`、`authorization_status` 已明确、`is_public=true`、`ai_reference_usable=true` 且不是待确认重复的素材；
- 读取结果包含素材元数据和 MCP `image` 内容，不暴露主机绝对路径；
- 适配器只读，不会新增、修改、删除数据库记录或文件；
- 素材文件仍由系统上传接口保存到 `backend/uploads_dev/assets/{SKU}/`，数据库 `product_assets.url` 只保存 `/uploads/assets/...` 相对地址。

## WorkBuddy 配置

在 WorkBuddy 的 MCP 配置中加入一个本地 server（Windows JSON 中反斜杠需要转义）：

```json
{
  "mcpServers": {
    "caiyan-product-assets-dev": {
      "command": "D:\\CaiYan\\Image-Generation-feature-v5\\backend\\venv\\Scripts\\python.exe",
      "args": [
        "D:\\CaiYan\\Image-Generation-feature-v5\\backend\\scripts\\product_asset_mcp_server.py",
        "--env-file",
        "D:\\CaiYan\\Image-Generation-feature-v5\\backend\\.env.dev"
      ]
    }
  }
}
```

重启 MCP 客户端后，可使用两个工具：

- `list_product_assets`：按 `sku`、`category_code`、`channel`、素材表达/卖点/场景/氛围标签检索；
- `read_product_asset`：传入 `sku` 和 `asset_id`，返回元数据及图片。

也可以读取动态资源 URI：`caiyan://product-assets/{sku}/{asset_id}`。

正式环境必须单独配置正式环境文件，并在确认权限、备份和发布流程后显式增加 `--allow-non-dev`；开发阶段不要使用该参数。
