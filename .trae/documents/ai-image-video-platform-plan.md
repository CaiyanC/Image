# AI 图像/视频生成平台 — 实施计划

## 一、项目概述

为公司内部搭建一个调用第三方 AI 模型聚合平台（[dmxapi.cn](https://www.dmxapi.cn/rmb)）API 的图像/视频生成网站。

* **用户管理**：支持注册、登录、JWT 认证，用户角色（管理员/普通用户）

* **核心功能**：文生图、图生图、视频生成

* **设计风格**：极简苹果风格 + 液态玻璃效果（Glassmorphism）

***

## 二、技术选型

| 层级       | 技术                                  | 说明            |
| -------- | ----------------------------------- | ------------- |
| 前端框架     | React 18 + TypeScript               | SPA 应用        |
| 构建工具     | Vite                                | 快速开发构建        |
| UI 样式    | Tailwind CSS + 自定义 Glassmorphism 样式 | 极简苹果风格        |
| 状态管理     | Zustand（轻量）或 React Context          | 全局状态（用户/生成任务） |
| 路由       | React Router v6                     | 页面路由          |
| 后端框架     | Python FastAPI                      | 高性能异步框架       |
| ORM      | SQLAlchemy + Alembic                | 数据库迁移         |
| 数据库      | PostgreSQL（生产）/ SQLite（开发）          | 持久化存储         |
| 认证       | JWT (python-jose)                   | Token 认证      |
| 文件存储     | 本地文件系统（初期）+ 目录结构化存储                 | 图像/视频文件管理     |
| HTTP 客户端 | httpx (后端) / fetch (前端)             | 调用第三方 API     |

***

## 三、项目目录结构

```
AItool/
├── frontend/                    # React 前端
│   ├── public/
│   ├── src/
│   │   ├── components/          # 可复用组件
│   │   │   ├── ui/              # 基础 UI 组件（Button, Input, Modal...）
│   │   │   ├── layout/          # 布局组件（Sidebar, Header, Workspace）
│   │   │   ├── ImageUploader/   # 图像上传组件
│   │   │   ├── ImagePreview/    # 图像预览组件
│   │   │   ├── PromptInput/     # 提示词输入组件
│   │   │   └── HistoryPanel/    # 历史记录面板
│   │   ├── pages/               # 页面
│   │   │   ├── Login.tsx
│   │   │   ├── Register.tsx
│   │   │   ├── Workspace.tsx    # 主工作区（生图页面）
│   │   │   └── History.tsx      # 历史记录页面
│   │   ├── hooks/               # 自定义 hooks
│   │   ├── services/            # API 调用服务
│   │   ├── store/               # 状态管理
│   │   ├── styles/              # 全局样式
│   │   ├── types/               # TypeScript 类型定义
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── api/                 # API 路由
│   │   │   ├── auth.py          # 认证相关接口
│   │   │   ├── users.py         # 用户管理接口
│   │   │   ├── generation.py    # 图像/视频生成接口
│   │   │   └── history.py       # 历史记录接口
│   │   ├── core/
│   │   │   ├── config.py        # 配置（环境变量等）
│   │   │   ├── security.py      # JWT 认证逻辑
│   │   │   └── database.py      # 数据库连接
│   │   ├── models/              # SQLAlchemy 数据模型
│   │   │   ├── user.py
│   │   │   └── generation.py    # 生成任务记录模型
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   │   ├── user.py
│   │   │   └── generation.py
│   │   ├── services/            # 业务逻辑层
│   │   │   ├── user_service.py
│   │   │   ├── generation_service.py
│   │   │   └── dmxapi_service.py  # 封装 dmxapi.cn 调用
│   │   ├── utils/               # 工具函数
│   │   │   └── file_storage.py  # 文件存储工具
│   │   └── main.py              # FastAPI 入口
│   ├── uploads/                 # 上传文件目录
│   │   ├── images/
│   │   └── generated/
│   ├── alembic/                 # 数据库迁移
│   ├── requirements.txt
│   └── alembic.ini
│
└── docker-compose.yml           # （可选）容器化部署
```

***

## 四、数据库模型设计

### 4.1 users 表

| 字段               | 类型           | 说明              |
| ---------------- | ------------ | --------------- |
| id               | UUID         | 主键              |
| username         | VARCHAR(50)  | 用户名，唯一          |
| email            | VARCHAR(100) | 邮箱，唯一           |
| hashed\_password | VARCHAR(255) | 加密密码            |
| role             | VARCHAR(20)  | 角色：admin / user |
| is\_active       | BOOLEAN      | 是否激活            |
| created\_at      | TIMESTAMP    | 创建时间            |
| updated\_at      | TIMESTAMP    | 更新时间            |

### 4.2 generations 表（生成记录）

| 字段                  | 类型           | 说明                                           |
| ------------------- | ------------ | -------------------------------------------- |
| id                  | UUID         | 主键                                           |
| user\_id            | UUID (FK)    | 关联用户                                         |
| type                | VARCHAR(20)  | 类型：txt2img / img2img / txt2vid               |
| prompt              | TEXT         | 提示词                                          |
| negative\_prompt    | TEXT         | 反向提示词（可选）                                    |
| source\_image\_path | VARCHAR(500) | 上传参考图路径（可选）                                  |
| result\_image\_path | VARCHAR(500) | 生成结果路径                                       |
| result\_video\_path | VARCHAR(500) | 生成视频路径（可选）                                   |
| model\_name         | VARCHAR(100) | 使用的模型名称                                      |
| parameters          | JSON         | 生成参数（尺寸、步数等）                                 |
| status              | VARCHAR(20)  | 状态：pending / processing / completed / failed |
| error\_message      | TEXT         | 错误信息（可选）                                     |
| created\_at         | TIMESTAMP    | 创建时间                                         |

***

## 五、API 接口设计

### 5.1 认证模块 `/api/auth`

| 方法   | 路径                   | 说明          |
| ---- | -------------------- | ----------- |
| POST | `/api/auth/register` | 用户注册        |
| POST | `/api/auth/login`    | 用户登录，返回 JWT |
| GET  | `/api/auth/me`       | 获取当前用户信息    |

### 5.2 用户管理 `/api/users`（管理员）

| 方法     | 路径                | 说明   |
| ------ | ----------------- | ---- |
| GET    | `/api/users`      | 用户列表 |
| GET    | `/api/users/{id}` | 用户详情 |
| PUT    | `/api/users/{id}` | 更新用户 |
| DELETE | `/api/users/{id}` | 删除用户 |

### 5.3 生成接口 `/api/generation`

| 方法   | 路径                        | 说明       |
| ---- | ------------------------- | -------- |
| POST | `/api/generation/txt2img` | 文生图      |
| POST | `/api/generation/img2img` | 图生图      |
| POST | `/api/generation/txt2vid` | 文生视频     |
| GET  | `/api/generation/models`  | 获取可用模型列表 |
| POST | `/api/generation/upload`  | 上传参考图像   |

### 5.4 历史记录 `/api/history`

| 方法     | 路径                  | 说明           |
| ------ | ------------------- | ------------ |
| GET    | `/api/history`      | 当前用户生成历史（分页） |
| GET    | `/api/history/{id}` | 单条记录详情       |
| DELETE | `/api/history/{id}` | 删除记录         |

***

## 六、前端页面与组件设计

### 6.1 路由设计

| 路径             | 页面            | 认证 |
| -------------- | ------------- | -- |
| `/login`       | 登录页           | 否  |
| `/register`    | 注册页           | 否  |
| `/`            | 主工作区（图像/视频生成） | 是  |
| `/history`     | 历史记录页         | 是  |
| `/admin/users` | 用户管理（管理员）     | 是  |

### 6.2 主工作区布局（`/`）

```
┌──────────────────────────────────────────────────────┐
│  Header（Logo + 用户头像下拉菜单 + 导航）             │
├────────────────────┬─────────────────────────────────┤
│  左侧面板（40%）    │  右侧面板（60%）                  │
│                    │                                  │
│  ┌──────────────┐  │  ┌────────────────────────────┐ │
│  │ 生成模式选择   │  │  │                            │ │
│  │ [文生图][图生图]│  │  │   上传区域 / 生成结果预览    │ │
│  │ [文生视频]    │  │  │                            │ │
│  └──────────────┘  │  │   (拖拽上传 + 点击上传)       │ │
│                    │  │                            │ │
│  ┌──────────────┐  │  │   或                        │ │
│  │ 模型选择      │  │  │                            │ │
│  │ [下拉菜单]    │  │  │   [生成的图像/视频展示]       │ │
│  └──────────────┘  │  │                            │ │
│                    │  │   (支持放大/下载)             │ │
│  ┌──────────────┐  │  └────────────────────────────┘ │
│  │ 提示词输入    │  │                                  │
│  │ ┌──────────┐ │  │  ┌────────────────────────────┐ │
│  │ │ prompt    │ │  │  │ 参数设置（可选折叠）         │ │
│  │ │          │ │  │  │  尺寸 / 步数 / 种子 / CFG   │ │
│  │ └──────────┘ │  │  └────────────────────────────┘ │
│  └──────────────┘  │                                  │
│                    │                                  │
│  ┌──────────────┐  │                                  │
│  │ [🚀 生成]    │  │                                  │
│  └──────────────┘  │                                  │
└────────────────────┴──────────────────────────────────┘
```

### 6.3 设计系统

* **配色方案**：

  * 背景：半透明磨砂效果 `rgba(255,255,255,0.1)` \~ `rgba(255,255,255,0.3)`

  * 主色调：苹果风格灰白 `#f5f5f7` 背景，`#1d1d1f` 文字

  * 强调色：苹果蓝 `#0071e3`

  * 卡片：白色半透明 + `backdrop-filter: blur(20px)` + 微妙边框

* **液态玻璃效果**（Glassmorphism）：

  * `background: rgba(255, 255, 255, 0.2)`

  * `backdrop-filter: blur(20px) saturate(180%)`

  * `border: 1px solid rgba(255, 255, 255, 0.3)`

  * `border-radius: 16px`

  * `box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1)`

* **字体**：系统原生字体栈 `-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI"...`

* **动画**：微妙过渡 `transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1)`

***

## 七、实施步骤

### 第一阶段：项目初始化与环境搭建

1. 创建项目根目录结构
2. 初始化前端项目（Vite + React + TypeScript + Tailwind CSS）
3. 初始化后端项目（FastAPI + 虚拟环境）
4. 配置 Tailwind CSS 自定义主题（苹果风格 + Glassmorphism 工具类）
5. 配置数据库（SQLite 开发用，PostgreSQL 生产用）

### 第二阶段：后端核心开发

1. 实现数据库模型（User + Generation）
2. 实现用户认证模块（注册/登录/JWT）
3. 实现用户管理 API（管理员功能）
4. 实现文件上传服务
5. 封装 dmxapi.cn 调用服务（文生图、图生图、文生视频）— **需用户提供代码示例**
6. 实现生成接口 API
7. 实现历史记录 API

### 第三阶段：前端核心开发

1. 搭建基础布局组件（Header、Glassmorphism 卡片等 UI 组件）
2. 实现登录/注册页面
3. 实现主工作区页面

   * PromptInput 组件（提示词输入）

   * ImageUploader 组件（拖拽上传 + 预览）

   * ImagePreview 组件（生成结果展示）

   * 参数设置面板
4. 实现历史记录页面
5. 实现认证状态管理（JWT 存储 + 路由守卫）
6. 前后端联调

### 第四阶段：优化与完善

1. 添加生成进度提示（loading 状态、轮询或 SSE）
2. 响应式适配
3. 错误处理与用户提示优化
4. 管理后台用户管理页面

***

## 八、待确认事项

* [ ] dmxapi.cn 的文生图 / 图生图 API 代码示例（用户将提供）

* [ ] 是否需要“文生视频”功能，还是先只做图像生成？

* [ ] 管理员账号是否需要预设脚本自动创建？

* [ ] 是否需要 Docker 容器化部署支持？

* [ ] 生成结果是否需要支持多张同时生成？

* [ ] 是否需要生成任务队列（用户可能同时提交多个任务）？

***

## 九、开发启动命令

```bash
# 后端
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```

