# 开放端口供同事访问测试方案

## 一、当前状态分析

| 项目 | 当前配置 |
|------|----------|
| **本机IP地址** | `192.168.3.109` |
| **后端服务端口** | `8000`（已绑定 `0.0.0.0`） |
| **前端服务端口** | `5174`（已绑定 `--host`） |
| **防火墙状态** | 需开放端口 |

## 二、实施步骤

### 步骤 1：配置 Windows 防火墙规则

需要开放两个端口：
- **8000**：后端 API 服务
- **5174**：前端网页服务

```powershell
# 开放后端端口 8000
New-NetFirewallRule -DisplayName "AI Tool Backend (8000)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private

# 开放前端端口 5174
New-NetFirewallRule -DisplayName "AI Tool Frontend (5174)" -Direction Inbound -Protocol TCP -LocalPort 5174 -Action Allow -Profile Private
```

### 步骤 2：配置前端 API 基础地址

当前前端 `api.ts` 中配置的是相对路径 `/api`，需要修改为绝对地址：

**修改文件**: `frontend/src/services/api.ts`

```typescript
// 修改前
const BASE_URL = '/api'

// 修改后
const BASE_URL = 'http://192.168.3.109:8000/api'
```

### 步骤 3：通知同事访问

同事需要在同一局域网内，访问以下地址：

| 服务 | 访问地址 |
|------|----------|
| **前端网页** | `http://192.168.3.109:5174` |
| **后端 API** | `http://192.168.3.109:8000` |
| **API 文档** | `http://192.168.3.109:8000/docs` |

## 三、风险与注意事项

| 风险 | 说明 | 应对措施 |
|------|------|----------|
| **IP 地址变化** | 重启后 IP 可能改变 | 建议设置静态 IP 或使用主机名 |
| **防火墙阻止** | Windows 防火墙可能阻止连接 | 添加入站规则 |
| **跨域问题** | 前端调用后端可能有 CORS 限制 | FastAPI 默认允许跨域 |
| **安全风险** | 端口暴露在局域网内 | 仅在内部测试使用，生产需配置安全措施 |

## 四、预期结果

✅ 同事可以在浏览器中访问 `http://192.168.3.109:5174`  
✅ 文生图和图生图功能正常使用  
✅ API 文档可通过 `http://192.168.3.109:8000/docs` 访问