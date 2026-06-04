# 修复 dmxapi.cn 408 超时错误

## 问题描述

调用 dmxapi.cn API 时返回 HTTP 408 超时错误：
```
HTTPStatusError: dmxapi.cn: 408 — {"error":{"message":"The operation was timeout.","type":"rix_api_error","param":"","code":"Timeout"}}
```

## 根因分析

| 问题 | 严重性 | 位置 |
|---|---|---|
| **txt2img 完全没有 408 重试逻辑**（img2img 已有） | 🔴 高 | `generation_service.py` `create_txt2img` |
| 图片压缩 1024px + JPEG Q75 可能仍不够激进 | 🟡 中 | `generation_service.py` `_compress_image` |
| 前端 img2img 超时(600s) = 后端 httpx read 超时(600s)，无容差 | 🟡 中 | `api.ts` vs `dmxapi_service.py` |
| 超时值全部硬编码，不可配置 | 🟢 低 | `dmxapi_service.py` |

## 修复方案

### 步骤 1：为 txt2img 添加 408 重试逻辑

**文件**：`backend/app/services/generation_service.py`

在 `create_txt2img` 函数中，参照 `create_img2img` 已有的重试模式，添加对 408/429/5xx 的重试循环。

改动点：
- 在 `create_txt2img` 的 `try/except` 块中，将 `httpx.HTTPStatusError` 的捕获改为带重试的循环
- 重试参数：最多重试 2 次（`TXT2IMG_MAX_RETRIES = 2`）
- 等待策略：`(attempt + 1) * 5` 秒（第一次重试等 5s，第二次等 10s）
- 对 `408, 429, 500, 502, 503, 504` 状态码进行重试
- 记录重试日志

### 步骤 2：使图片压缩更激进

**文件**：`backend/app/services/generation_service.py`

调整 `_compress_image` 中的压缩参数：
- `MAX_IMAGE_DIMENSION`: `1024` → `768`
- `JPEG_QUALITY`: `75` → `60`

这可以减少上传到 dmxapi.cn 的图片体积，降低服务器端处理时间和超时概率。

### 步骤 3：增加前端超时容差

**文件**：`frontend/src/services/api.ts`

- img2img 前端超时从 `600000` (600s) 增加到 `660000` (660s)，比后端 httpx read 超时的 600s 多 60s 余量
- txt2img 前端超时保持 `330000` (330s)，已经比后端 300s 多 30s 容差

### 步骤 4：添加可配置的超时参数

**文件**：`backend/app/core/config.py` + `backend/app/services/dmxapi_service.py`

在配置类中添加环境变量支持的超时参数：
- `DMXAPI_TXT2IMG_TIMEOUT`：默认 `300`（秒）
- `DMXAPI_IMG2IMG_READ_TIMEOUT`：默认 `600`（秒）
- `DMXAPI_IMG2IMG_CONNECT_TIMEOUT`：默认 `30`（秒）

在 `dmxapi_service.py` 中使用这些配置值替代硬编码。

### 步骤 5：验证

- 检查代码无语法错误
- 确保 lint 通过
- 重启后端服务

## 涉及文件清单

| 文件 | 改动类型 |
|---|---|
| `backend/app/services/generation_service.py` | 修改（添加 txt2img 重试 + 调整压缩参数） |
| `backend/app/core/config.py` | 修改（添加超时配置项） |
| `backend/app/services/dmxapi_service.py` | 修改（使用可配置超时） |
| `frontend/src/services/api.ts` | 修改（增加 img2img 前端超时） |
