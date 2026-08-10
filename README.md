# AI Tool — 企业级 AI 图像/视频生成平台

基于 [dmxapi.cn](https://www.dmxapi.cn) 第三方大模型聚合平台，集成了多种 AI 图像和视频生成模型，提供用户管理、模型配置和统一生成工作流。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.10+) |
| 数据库 | SQLite (SQLAlchemy 2.0 ORM) |
| 认证 | JWT + bcrypt |
| 前端框架 | React 18 + TypeScript |
| 样式 | Tailwind CSS (液态玻璃设计) |
| 状态管理 | Zustand |
| 构建工具 | Vite 5 |

## 支持的模型

通过 dmxapi.cn 聚合平台支持以下 AI 模型（需配置对应 API Key）：

- **GPT Image 1 / 2 / 2 SSVIP** — OpenAI 最新图像生成
- **DALL·E 3** — OpenAI 经典图像生成
- **Seedream 3 / 4** — 字节跳动文生图
- **Flux 1.1 Pro / Ultra** — Black Forest Labs 旗舰模型
- **Nano Banana** — 轻量快速图像生成
- **CogView 4** — 智谱图像生成
- **Kolors** — 快手图像生成

## 环境要求

- Python 3.10 或更高版本
- Node.js 20.19 或更高版本（也支持 22.12+）
- npm 或 pnpm

## 快速开始

### 1. 克隆仓库

```bash
git clone <你的仓库地址>
cd AItool
```

### 2. 配置环境变量

```bash
# 生产配置模板
cp backend/.env.example backend/.env

# 开发配置模板（Windows 可使用 copy 命令）
cp backend/.env.dev.example backend/.env.dev

# 编辑对应的本地 env 文件，填入你的真实配置：
#   - SECRET_KEY：JWT 签名密钥（必填，任意随机字符串）
#   - MODEL_CREDENTIAL_ENCRYPTION_KEY：模型 API Key 的独立 Fernet 密钥（推荐）
#   - DEFAULT_ADMIN_PASSWORD：默认管理员密码（必填）
#   - DMXAPI_API_KEY：dmxapi.cn 的 API Key（可选，可在后台设置中按模型配置）
```

`backend/.env` 和 `backend/.env.dev` 都包含敏感信息，已被 Git 忽略；不要提交真实配置。
后台模型密钥只以密文保存和掩码展示；若未配置独立 Fernet 密钥，后端会暂时从
`SECRET_KEY` 派生加密密钥，因此轮换 `SECRET_KEY` 前应先配置并备份独立密钥。

### 3. 启动后端

```bash
cd backend

# 创建虚拟环境（仅首次）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动开发环境
cd ..
start-dev.bat
```

后端 API 文档：启动后访问 http://localhost:8001/docs

### 4. 启动前端

```bash
cd frontend

# 安装依赖（仅首次）
npm install

# 启动开发服务器
npm run dev:dev
```

前端访问地址：http://localhost:5276

### 5. 登录

- 默认管理员账号：`admin`
- 密码：你在 `.env` 中设置的 `DEFAULT_ADMIN_PASSWORD`

## 项目结构

```
AItool/
├── backend/
│   ├── app/
│   │   ├── api/            # API 路由（auth, admin, generation, history, users）
│   │   ├── core/           # 核心配置（config, database, security）
│   │   ├── models/         # 数据库模型（user, system_config, generation）
│   │   ├── schemas/        # Pydantic 请求/响应模型
│   │   ├── services/       # 业务逻辑（dmxapi_service, generation_service）
│   │   ├── utils/          # 工具函数（file_storage）
│   │   └── main.py         # FastAPI 入口
│   ├── uploads/            # 生成的图像文件（不提交到 Git）
│   ├── .env.example        # 环境变量模板
│   └── requirements.txt    # Python 依赖
├── frontend/
│   ├── src/
│   │   ├── components/     # 共用组件
│   │   ├── pages/          # 页面组件
│   │   ├── services/       # API 请求封装
│   │   ├── store/          # Zustand 状态管理
│   │   └── styles/         # 全局样式
│   ├── package.json
│   └── vite.config.ts
├── start_backend.bat       # Windows 后端快捷启动脚本
├── start_frontend.bat      # Windows 前端快捷启动脚本
└── .gitignore
```

## 模型配置（dmxapi.cn）

登录后进入 **管理 → 设置** 页面，每个模型可单独配置：

- **API Key**：来自 dmxapi.cn 的密钥
- **API Base URL**：默认为 `https://www.dmxapi.cn`（注意：只需填写域名，不需要路径）

配置完成后，在 **工作区** 页面选择模型并生成图像。

## 安全注意事项

- `.env` 文件**绝不提交到 Git**（已通过 `.gitignore` 排除）
- `app.db` 数据库文件**绝不提交**（含 API Key，已通过 `*.db` 规则排除）
- 建议将 GitHub 仓库设为**私有（Private）**
- 首次 clone 后需自行创建 `.env` 文件

## 换电脑继续开发

```bash
git clone <仓库地址>
cd AItool
cp backend/.env.example backend/.env   # 然后编辑填入密钥
cd backend && python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt
cd ..\frontend && npm install && npm run dev
```
