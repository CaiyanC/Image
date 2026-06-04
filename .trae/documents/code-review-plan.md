# 代码审查报告 + 图生图 408 问题诊断报告

---

## 🔴 图生图 408 超时问题诊断（用户核心诉求）

### 现象
图生图使用 `gpt-image-2-ssvip` 模型始终失败，错误信息：
> HTTPStatusError: dmxapi.cn: 408 — {"error":{"message":"The operation was timeout.","type":"rix_api_error","param":"","code":"Timeout"}}

### 408 错误根因分析

**408 是 dmxapi.cn 服务端返回的超时错误**，含义是 dmxapi.cn 向 OpenAI 上游转发请求后，OpenAI 后端处理超时。

**根本原因：dmxapi.cn 的 `v1/images/edits`（图编辑）端点目前官方仅支持 gpt-image-1 系列模型**。

查证结果：
| 来源 | 结论 |
|------|------|
| [dmxapi.cn 图编辑文档](https://doc.dmxapi.cn/gpt-image-edit.html) | 支持的模型仅列出：`gpt-image-1.5`、`gpt-image-1`、`gpt-image-1-mini`，**无 gpt-image-2** |
| Qiita 技术文章 (2026-04-22) | gpt-image-2 的 edits 端点「2026年5月提供開始予定」，当前可能仍处于灰度/不稳定阶段 |

gpt-image-2-ssvip 在 dmxapi.cn 平台上用于 generations（文生图）端点应该是正常的，但用于 edits（图编辑）端点**尚未正式支持或仍在 unstable 阶段**，导致请求被转发到上游后超时。

### 修复方案

**方案1（推荐 — 最小改动）**：图生图模式自动降级使用 gpt-image-1.5

修改 [generation.py:L33-L59](file:///e:/trea/AItool/backend/app/api/generation.py#L33-L59)，当用户发送的 `model_name` 以 `gpt-image-2` 开头时，自动替换为 `gpt-image-1.5`，并返回提示信息：

```python
# img2img 端点中检测并替换不支持的模型
IMG2IMG_UNSUPPORTED_PREFIXES = ["gpt-image-2", "dall-e-3"]
if any(model_name.startswith(p) for p in IMG2IMG_UNSUPPORTED_PREFIXES):
    original_model = model_name
    model_name = "gpt-image-1.5"
    # 可选：在响应或日志中提示模型已被替换
```

**方案2**：前端层面过滤，Workspace 切换到 img2img 时只显示支持的模型

修改 [Workspace.tsx:L98-L101](file:///e:/trea/AItool/frontend/src/pages/Workspace.tsx#L98-L101)，img2img 模式下只过滤 `gpt-image-1` 系列的模型：

```typescript
const filteredModels = models.filter((m) => {
    if (mode === 'txt2vid') return m.type === 'video'
    if (mode === 'img2img') return m.type === 'image' && !m.id.startsWith('gpt-image-2')
    return m.type === 'image'
})
```

---

## 🟠 次要发现：图生图参数丢失

前端在切换到 img2img 模式时重置了 params（quality, output_format, background 等），但后端 API 端点只从前端 FormData 中提取了 `size`，其余参数全部丢失：

| 参数 | 前端 img2img 设置值 | FormData 发送 | 后端接收 | 送达 dmxapi |
|------|---------------------|--------------|----------|-------------|
| `size` | `1024x1024` | ✅ | ✅ | ✅ |
| `quality` | `low` | ❌ 未发送 | ❌ | ❌ |
| `output_format` | `jpeg` | ❌ 未发送 | ❌ | ❌ |
| `output_compression` | `85` | ❌ 未发送 | ❌ | ❌ |
| `moderation` | `low` | ❌ 未发送 | ❌ | ❌ |
| `background` | `auto` | ❌ 未发送 | ❌ | ❌ |

**位置**: 
- 前端: [api.ts:L74-L90](file:///e:/trea/AItool/frontend/src/services/api.ts#L74-L90) 只发送 prompt/model_name/negative_prompt/size/images
- 后端: [generation.py:L50-L54](file:///e:/trea/AItool/backend/app/api/generation.py#L50-L54) 只构造了 `GenerationParams(size=size)`

**修复建议**: 前端将 quality/output_format/output_compression/moderation/background 加入 FormData，后端接收并透传。

---

## 先前审查报告中的其他问题汇总

### 🔴 严重 (Critical)
| # | 问题 | 文件 |
|---|------|------|
| 1 | `ProductPrompts.uuid` 字段不存在但 service 引用了 | product_service.py:L356, product_prompts.py |
| 2 | 前端 BASE_URL 硬编码 IP 绕过 Vite 代理 | api.ts:L1 |
| 3 | gpt-image-2 不支持 edits 端点（即本报告诊断的问题） | dmxapi_service.py:L109 |

### 🟠 高风险 (High)
| # | 问题 | 文件 |
|---|------|------|
| 4 | `get_current_admin_user` 与 `get_current_super_admin` 重复 | security.py:L60-L79 |
| 5 | `loadModels` 过时闭包 (stale closure) | Workspace.tsx:L29-L37 |
| 6 | package.json 缺少 eslint 依赖 | frontend/package.json |
| 7 | 上传接口缺少认证保护 | generation.py:L71-L75 |
| 8 | 更新产品 SKU 时关联表未级联更新 | product_service.py:L254 |

### 🟡 中等 (Medium)
| # | 问题 |
|---|------|
| 9 | 重试逻辑代码重复 (~40行) |
| 10 | history.py 使用了废弃的 `get_current_admin_user` |
| 11 | 上传接口无文件类型/大小校验 |
| 12 | CORS 配置硬编码内网 IP |
| 13 | `@app.on_event("startup")` 已过时 |
| 14 | api.ts Content-Type 处理不够健壮 |

### 🟢 低风险 (Low)
| # | 问题 |
|---|------|
| 15 | serialize_json_str 未处理深层嵌套 |
| 16 | Token schema 未在 login 响应中声明 |
| 17 | ProductPrompts.parameters 列类型不一致 |
| 18 | product_categories 主键类型与其他表不一致 |

---

## 建议执行顺序

1. **立即修复**: 图生图 408 — 降级模型到 gpt-image-1.5（方案1，改动最小）
2. **尽快修复**: 图生图参数丢失 — 补齐 quality/output_format/background 透传
3. **稳定版前修复**: ProductPrompts.uuid 字段缺失（会导致删除提示词功能崩溃）
4. **后续迭代**: 其他中低风险问题按优先级逐步修复
