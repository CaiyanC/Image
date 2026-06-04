# Nano Banana 2 (Gemini) 接入计划

## 目标
1. 按 dmxapi.cn 文档正确接入 `gemini-3.1-flash-image-preview`（Nano Banana 2）文生图 + 图生图
2. 前端/后端通过 `api_format` 字段区分 GPT Image 2（openai 格式）和 Gemini（gemini 格式），正确路由 API 调用
3. 前端 Workspace 根据选中模型的 api_format 自动切换参数面板

---

## Step 1: 模型配置新增 api_format 字段

### 1.1 后端 dmxapi_service.py
- `_get_model_config()` 解析第 6 个管道字段 `api_format`，默认 `"openai"`
- `_resolve_model_config()` 返回 `api_format` 字段
- `set_model_config()` 写入时追加 `api_format` 字段
- `get_available_models()` 返回 `api_format` 字段

### 1.2 后端 schemas（新增）
- 新增 `ModelConfig` Pydantic schema，包含 `api_format: str = "openai"`

### 1.3 后端 admin API
- `GET /admin/models` 返回含 `api_format` 的模型列表
- `POST /admin/models` 接收含 `api_format` 的模型配置

### 1.4 前端 AdminSettings.tsx
- `ModelItem` 接口新增 `api_format: string`
- 模型详情面板新增 API 格式下拉选择：`openai` / `gemini`
- 添加新模型表单新增 API 格式选择
- 默认值 `'openai'`

### 1.5 前端类型 index.ts
- `ModelInfo` 类型新增 `api_format?: string`

---

## Step 2: 后端新增 Gemini 原生 API 调用方法

### 2.1 dmxapi_service.py — txt2img_gemini()
**端点**: `{base_url}/v1beta/models/{model_id}:generateContent`

**请求体**:
```json
{
  "contents": [
    {
      "parts": [
        {"text": "提示词"}
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["IMAGE"],
    "imageConfig": {
      "aspectRatio": "1:1",
      "imageSize": "1K"
    }
  }
}
```

**参数映射**:
| 前端参数 | Gemini 参数 | 默认值 |
|---|---|---|
| `aspect_ratio` | `imageConfig.aspectRatio` | `"1:1"` |
| `image_size` | `imageConfig.imageSize` | `"1K"` |
| `n` | 发送 N 个独立请求（Gemini 单次只生成 1 张） | `1` |

**超时**: 300 秒（与现有一致）

### 2.2 dmxapi_service.py — img2img_gemini()
**端点**: 与文生图相同（Gemini 统一端点）

**请求体**:
```json
{
  "contents": [
    {
      "parts": [
        {"text": "提示词"},
        {
          "inlineData": {
            "mimeType": "image/jpeg",
            "data": "<base64>"
          }
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["IMAGE"],
    "imageConfig": {
      "aspectRatio": "1:1",
      "imageSize": "1K"
    }
  }
}
```

**多图**: 多个 `inlineData` 对象追加到 `parts` 数组
**超时**: 1000 秒（base64 编码较大）

---

## Step 3: 后端生成路由分支

### 3.1 dmxapi_service.py — txt2img() 添加路由
```python
if cfg.get("api_format") == "gemini":
    return await txt2img_gemini(...)
else:
    # 现有 openai 格式逻辑
```

### 3.2 dmxapi_service.py — img2img() 添加路由
```python
if cfg.get("api_format") == "gemini":
    return await img2img_gemini(...)
else:
    # 现有 openai 格式逻辑
```

### 3.3 generation_service.py — Gemini 响应解析
- 新增 `_extract_and_save_gemini_response()` 
- 解析路径: `candidates[0].content.parts[]` → `inlineData.data` (base64) → 解码保存
- 支持多张图片（N 个并行请求返回 N 个 part）

### 3.4 向前端传递 aspect_ratio / image_size
- `create_txt2img` 和 `create_img2img` 无需改动签名，`req.params` 已包含所有字段
- Workspace 前端在 `params` 中发送 `aspect_ratio` 和 `image_size`
- 后端从 `params` 中提取并传给 Gemini 方法

---

## Step 4: 前端 Workspace 参数面板适配

### 4.1 判断当前模型格式
```typescript
const currentModel = models.find(m => m.id === selectedModel)
const isGemini = currentModel?.api_format === 'gemini'
```

### 4.2 Gemini 模型 → 显示 Gemini 参数面板
**替代尺寸选择**:
- 宽高比下拉：14 种（1:1 / 16:9 / 9:16 / 4:3 / 3:2 / 2:3 / 3:4 / 4:5 / 5:4 / 21:9 / 9:21 / 1:4 / 4:1 / 1:8 / 8:1）
- 分辨率档位：1K / 2K / 4K

**隐藏不适用参数**: quality、output_format、output_compression、moderation、background（Gemini 不支持）

### 4.3 GPT 模型 → 保持现有多数面板
现有 WxH 尺寸 + quality + output_format + ... 不变

### 4.4 向后端发送
- 始终通过 `params` 对象发送
- Gemini 时传递 `{n, aspect_ratio, image_size}`
- GPT 时传递 `{n, size, quality, output_format, output_compression, moderation}`

### 4.5 模式切换默认参数
- 切换到文生图 + Gemini：`{n: 1, aspect_ratio: '1:1', image_size: '1K'}`
- 切换到图生图 + Gemini：`{n: 1, aspect_ratio: '1:1', image_size: '1K'}`

### 4.6 图生图 FormData 适配
- Gemini 图生图走 JSON body（不含文件上传），图片转 base64 内嵌
- 需修改 `api.ts` 的 `img2img` 方法：Gemini 模式用 JSON body 而非 FormData

---

## Step 5: 前端 api.ts 适配

### 5.1 新增 uploadReferenceAsBase64 辅助函数
```typescript
function fileToBase64(file: File): Promise<{ data: string; mimeType: string }>
```

### 5.2 img2img 方法分支
```typescript
if (data.api_format === 'gemini') {
  // JSON body: { prompt, model_name, images: [{ data, mimeType }], params }
  return request('/generation/img2img', { method: 'POST', body: JSON.stringify(payload) }, 600000)
} else {
  // 现有 FormData 逻辑
}
```

### 5.3 后端 generation.py img2img 端点
- Gemini 模式用 JSON body（Pydantic schema），GPT 模式保持 Form 表单
- 新增 Gemini 专用 schema `Img2ImgGeminiRequest`：
```python
class Img2ImgGeminiRequest(BaseModel):
    prompt: str
    model_name: str = "gemini-3.1-flash-image-preview"
    negative_prompt: Optional[str] = None
    params: Optional[GenerationParams] = None
    images: List[ImagePayload]  # { data: str, mimeType: str }
```

---

## Step 6: 高级参数默认展开

### 6.1 Workspace.tsx — `showParams` 初始值改为 `true`
- 当前代码：`const [showParams, setShowParams] = useState(false)`
- 改为：`const [showParams, setShowParams] = useState(true)`
- 影响：进入生成页面时高级参数面板直接展开，用户无需手动点击

### 6.2 折叠箭头默认朝上
- `showParams ? 'rotate-180'` 逻辑不用改，`true` 时自然会指向上方

---

## Step 7: 验证

### 7.1 TypeScript 编译
```bash
cd frontend && npx tsc --noEmit
```

### 7.2 端到端测试
1. AdminSettings 页 → 添加 Gemini 模型（api_format=gemini）
2. Workspace 页 → 选择 Gemini 模型 → 确认参数面板切换
3. 文生图 → 输入提示词 → 确认返回图片
4. 图生图 → 上传参考图 → 确认返回图片
5. History 页 → 确认记录状态为 completed 且有图片

---

## 影响范围汇总

| 文件 | 操作 | 行数估计 |
|---|---|---|
| `backend/app/services/dmxapi_service.py` | 新增 2 个方法 + 路由分支 + api_format 解析 | +120 行 |
| `backend/app/services/generation_service.py` | 新增 Gemini 响应解析 + 路由 | +30 行 |
| `backend/app/api/generation.py` | 新增 img2img JSON 端点 | +25 行 |
| `backend/app/schemas/generation.py` | 新增 Gemini 请求/响应 schema | +20 行 |
| `frontend/src/services/api.ts` | img2img 分支 + base64 辅助 | +30 行 |
| `frontend/src/pages/Workspace.tsx` | Gemini 参数面板 + 模式切换逻辑 + 高级参数默认展开 | +62 行 |
| `frontend/src/pages/AdminSettings.tsx` | api_format 选择框 | +15 行 |
| `frontend/src/types/index.ts` | ModelInfo 字段 | +3 行 |

**总计**: ~305 行
