# 项目 GitHub 操作完整指南

> 本文档整合了安全配置、分支工作流、首次发布、日常开发循环和新电脑搭建的完整流程，作为项目 Git/GitHub 操作的知识库。

---

## 目录

- [一、项目信息速览](#一项目信息速览)
- [二、安全配置](#二安全配置)
  - [2.1 .gitignore 规则](#21-gitignore-规则)
  - [2.2 .env 敏感信息保护](#22-env-敏感信息保护)
  - [2.3 .env.example 模板](#23-envexample-模板)
  - [2.4 config.py 硬编码回退值清理](#24-configpy-硬编码回退值清理)
  - [2.5 GitHub Personal Access Token](#25-github-personal-access-token)
- [三、Git 分支工作流规范](#三git-分支工作流规范)
  - [3.1 Feature Branch 工作流（推荐）](#31-feature-branch-工作流推荐)
  - [3.2 单人开发的简化流程](#32-单人开发的简化流程)
  - [3.3 分支命名规范](#33-分支命名规范)
  - [3.4 Commit 信息规范](#34-commit-信息规范)
- [四、首次发布到 GitHub](#四首次发布到-github)
  - [4.1 创建 README.md](#41-创建-readmemd)
  - [4.2 初始化仓库并提交](#42-初始化仓库并提交)
  - [4.3 创建 GitHub 远程仓库并推送](#43-创建-github-远程仓库并推送)
- [五、日常开发循环](#五日常开发循环)
  - [5.1 开发前（每次必须）](#51-开发前每次必须)
  - [5.2 开发中](#52-开发中)
  - [5.3 推送当前代码到 GitHub](#53-推送当前代码到-github)
  - [5.4 换电脑开发注意事项](#54-换电脑开发注意事项)
- [六、新电脑环境搭建指南](#六新电脑环境搭建指南)
  - [6.1 安装基础软件](#61-安装基础软件)
  - [6.2 克隆项目](#62-克隆项目)
  - [6.3 配置后端](#63-配置后端)
  - [6.4 配置前端](#64-配置前端)
  - [6.5 启动运行](#65-启动运行)
  - [6.6 首次启动后配置模型 API Key](#66-首次启动后配置模型-api-key)
- [七、项目目录结构](#七项目目录结构)
- [八、常见问题排查](#八常见问题排查)
- [九、Git 分支推送故障深度排查](#九git-分支推送故障深度排查)

---

## 一、项目信息速览

| 项目 | 详情 |
|------|------|
| **仓库地址** | `https://github.com/oliveryou326-crypto/Image-Generation.git` |
| **技术栈** | 后端 FastAPI + SQLite / 前端 React + Vite + TypeScript + Tailwind CSS |
| **API 供应商** | dmxapi.cn（文生图 + 图生图） |
| **推荐本地目录** | `D:\AItool`（多台电脑保持一致，启动脚本无需修改） |

---

## 二、安全配置

### 2.1 .gitignore 规则

以下内容**绝不提交**到 Git：

```gitignore
# 环境变量（含密钥、密码）
.env
backend/.env

# SQLite 数据库（含真实 API Key）
*.db
*.sqlite
*.sqlite3

# 生成/上传的图像文件
uploads/
backend/uploads/

# Python 虚拟环境
venv/
backend/venv/
env/
.venv/

# Python 编译缓存
__pycache__/
*.py[cod]
*.pyo
*.egg-info/
dist/
build/

# Node 依赖（前端）
frontend/node_modules/

# IDE 配置
.vscode/
.idea/
*.swp
*.swo

# 操作系统杂项
.DS_Store
Thumbs.db

# Trae IDE — 只排除配置和缓存，保留 documents/ 文档目录
.trae/rules/
.trae/settings/
.trae/cache/
```

> ⚠️ 关键点：`.trae/documents/` **不在排除列表中**，项目规划文档会随代码一起提交到 GitHub，作为团队知识库使用。

### 2.2 .env 敏感信息保护

`.env` 文件已在 `.gitignore` 中排除，以下内容**不会泄露**：
- `SECRET_KEY`（JWT 签名密钥）
- `DEFAULT_ADMIN_PASSWORD`（默认管理员密码）
- `DMXAPI_API_KEY`（dmxapi.cn 的 API 密钥）
- 数据库连接字符串中的敏感信息

### 2.3 .env.example 模板

提交 `backend/.env.example` 模板文件（**不含真实密钥**），方便新电脑快速配置：

```env
# Backend Configuration
DEBUG=true
SECRET_KEY=请在这里填写一个随机密钥
DATABASE_URL=sqlite:///./app.db
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Default Admin Account (首次启动自动创建)
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_EMAIL=admin@example.com
DEFAULT_ADMIN_PASSWORD=请修改默认密码

# dmxapi.cn Configuration
DMXAPI_BASE_URL=https://www.dmxapi.cn
DMXAPI_API_KEY=请填写你的 dmxapi.cn API Key
```

### 2.4 config.py 硬编码回退值清理

修改 `backend/app/core/config.py`，移除敏感默认值：
- `SECRET_KEY` 回退值 → 改为空字符串，启动时若为空则报错提示
- `DEFAULT_ADMIN_PASSWORD` 回退值 → 改为空字符串，若为空则跳过自动创建管理员

这样即使有人获取到源码，没有 `.env` 文件也无法获得任何默认凭据。

### 2.5 GitHub Personal Access Token

GitHub 已不支持密码推送，必须使用 Personal Access Token（classic）：

1. 打开 https://github.com/settings/tokens
2. 点击 **Generate new token (classic)**
3. Note 填 `dev-machine`
4. Expiration 选 **No expiration**（或自定义日期）
5. 勾选权限：
   - ✅ `repo`（全部仓库权限）
   - ✅ `workflow`（如果需要 GitHub Actions）
6. 点击 **Generate token**
7. ⚠️ **立即复制保存**（只显示一次！）

> 强烈建议用 SSH Key 或 Git Credential Manager 管理认证，避免 token 硬编码在 remote URL 中。

---

## 三、Git 分支工作流规范

### 3.1 Feature Branch 工作流（推荐）

```
main ─────●──────────●──────────●──────────●
           \         /          /          /
feature-a   ●──●──●─┘          /          /
                              /          /
feature-b                   ●──●──●────┘
```

- **`main` 分支**：始终保持稳定、可运行的代码
- **`feature-xxx` 分支**：每个新功能创建一个独立分支，开发完成后再合并回 `main`

**操作流程：**

```bash
# 1. 确保在 main 分支，并且是最新代码
git checkout main
git pull origin main

# 2. 从 main 创建新功能分支
git checkout -b feature-add-video-generation

# 3. 正常写代码、测试...

# 4. 提交更改
git add .
git commit -m "feat: 添加视频生成功能"

# 5. 推送功能分支到 GitHub
git push -u origin feature-add-video-generation

# 6. 功能完成并测试通过后，合并回 main
git checkout main
git pull origin main
git merge feature-add-video-generation
git push origin main

# 7. 删除已合并的分支（可选）
git branch -d feature-add-video-generation
git push origin --delete feature-add-video-generation
```

### 3.2 单人开发的简化流程

一个人开发时可以直接在 `main` 上操作：

```bash
git checkout main
git pull origin main     # 先拉取最新（换电脑开发时必须！）
# ... 写代码 ...
git add .
git commit -m "feat: 添加新功能"
git push origin main
```

### 3.3 分支命名规范

| 类型 | 命名格式 | 示例 |
|------|----------|------|
| 新功能 | `feature-简短描述` | `feature-v2`、`feature-video-generation` |
| Bug 修复 | `fix-简短描述` | `fix-image-upload-error` |
| 重构 | `refactor-简短描述` | `refactor-api-client` |
| 实验性改动 | `experiment-简短描述` | `experiment-new-prompt-format` |

> ⚠️ **Windows 下避免使用含 `/` 的分支名**（如 `feature/xxx`）。详见第九章故障排查。

### 3.4 Commit 信息规范

遵循 Conventional Commits 格式：

```
feat: 添加视频生成功能，支持 txt2vid 模型
fix: 修复 PNG 格式下 output_compression 参数错误
refactor: 重构 dmxapi_service.py，提取公共 URL 拼接逻辑
docs: 更新 README，添加 API 配置说明
chore: 更新依赖版本，调整 .gitignore
```

---

## 四、首次发布到 GitHub

### 4.1 创建 README.md

在项目根目录创建 `README.md`，包含：
- 项目简介
- 技术栈说明
- 环境要求（Python 3.10+, Node.js 18+）
- 快速开始指南（clone → 配置.env → 安装依赖 → 启动）
- 项目结构说明
- dmxapi.cn API 配置说明
- 换电脑后的恢复步骤

### 4.2 初始化仓库并提交

```bash
cd D:\AItool
git init
git add .
git status        # 检查确认没有敏感文件被加入
git commit -m "Initial commit: AI 图像/视频生成平台"
```

### 4.3 创建 GitHub 远程仓库并推送

1. 在 GitHub 上创建新仓库（建议设为**私有仓库**）
2. 关联远程仓库并推送：

```bash
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

---

## 五、日常开发循环

### 5.1 开发前（每次必须）

```powershell
cd D:\AItool
git pull origin main
```

> 如果旧电脑上提交了新代码，不拉取就直接写代码会导致冲突。

### 5.2 开发中

```powershell
# 正常写代码...

# 查看改了哪些文件
git status

# 添加更改
git add -A

# 提交
git commit -m "feat: 添加了xxx功能"

# 推送
git push origin main
```

### 5.3 推送当前代码到 GitHub

当本地有大量未提交的改动时：

```bash
cd D:\AItool
git add -A
git commit -m "feat: stable txt2img + img2img with multi-image support"
git push origin main
```

如果因为另一台电脑已推送导致普通 push 被拒绝（单人开发时可 force push）：

```bash
git push origin main --force
```

> ⚠️ 多人协作时**禁止** force push，应该用 `git pull --rebase` 解决。

### 5.4 换电脑开发注意事项

```bash
# ❌ 错误做法：换电脑后直接 push
git push origin main    # 本地落后于远程，会被拒绝！

# ✅ 正确做法：先拉取再推送
git pull origin main    # 先同步远程最新代码
git push origin main    # 再推送
```

---

## 六、新电脑环境搭建指南

### 6.1 安装基础软件

#### Python 3.10+
- 下载地址：https://www.python.org/downloads/
- **必须勾选** ✅ **「Add Python to PATH」**
- 验证：`python --version`

#### Node.js 18+（LTS）
- 下载地址：https://nodejs.org/en/download
- 选择 **LTS** 版本
- 验证：`node --version` 和 `npm --version`

#### Git
- 下载地址：https://git-scm.com/download/win
- 安装选项全部默认
- 验证：`git --version`

#### Git 配置用户信息（仅首次）

```powershell
git config --global user.name "oliveryou326-crypto"
git config --global user.email "你的邮箱"
```

### 6.2 克隆项目

```powershell
cd D:\
git clone https://github.com/oliveryou326-crypto/Image-Generation.git AItool
cd D:\AItool
```

> 克隆后应看到 `backend\`、`frontend\`、`start_backend.bat`、`start_frontend.bat`、`README.md` 等文件。

### 6.3 配置后端

```powershell
cd D:\AItool\backend

# 创建 Python 虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate

# 安装 Python 依赖
pip install -r requirements.txt

# 从模板创建 .env 配置文件
copy .env.example .env
```

编辑 `D:\AItool\backend\.env`，填入真实值：

```env
DEBUG=true
SECRET_KEY=在这随便打一串英文数字比如a8f5s9d3f2j1k4l7qw6e9r
DATABASE_URL=sqlite:///./app.db
ACCESS_TOKEN_EXPIRE_MINUTES=1440

DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_EMAIL=admin@example.com
DEFAULT_ADMIN_PASSWORD=你自己设置的管理员密码

DMXAPI_BASE_URL=https://www.dmxapi.cn
DMXAPI_API_KEY=你的dmxapi.cn的API密钥
```

### 6.4 配置前端

```powershell
cd D:\AItool\frontend
npm install
```

> 这步可能需要 1-3 分钟，取决于网络速度。如果慢，可换淘宝镜像：`npm config set registry https://registry.npmmirror.com`

### 6.5 启动运行

**终端窗口 1 — 启动后端：**

```powershell
cd D:\AItool\backend
venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

成功标志：`INFO:     Uvicorn running on http://0.0.0.0:8000`

**终端窗口 2 — 启动前端：**

```powershell
cd D:\AItool\frontend
npx vite --port 5174 --host
```

成功标志：`➜  Local:   http://localhost:5174/`

浏览器访问 **http://localhost:5174**

### 6.6 首次启动后配置模型 API Key

数据库不会被 Git 提交，新电脑首次启动后数据库中还没有 API Key 配置：

1. 用默认管理员账号登录
2. 进入**后台管理**页面
3. 在模型配置中填写 dmxapi.cn 的 API Key
4. 保存后即可正常使用文生图和图生图

---

## 七、项目目录结构

```
D:\AItool\
├── backend\                    # Python 后端
│   ├── app\
│   │   ├── api\               # API 路由（generation.py, auth.py 等）
│   │   ├── core\              # 核心配置（config.py, security.py）
│   │   ├── models\            # SQLAlchemy 数据模型
│   │   ├── schemas\           # Pydantic 请求/响应模式
│   │   ├── services\          # 业务逻辑（dmxapi_service.py, generation_service.py）
│   │   └── main.py            # FastAPI 入口
│   ├── venv\                  # Python 虚拟环境（不提交）
│   ├── .env                   # 环境配置（不提交）
│   ├── .env.example           # 配置模板（提交）
│   ├── requirements.txt       # Python 依赖列表
│   └── app.db                 # SQLite 数据库（不提交）
├── frontend\                   # React 前端
│   ├── src\
│   │   ├── pages\             # 页面组件
│   │   ├── services\          # API 调用（api.ts）
│   │   ├── store\             # 状态管理（Zustand）
│   │   └── components\        # 通用组件
│   ├── node_modules\          # npm 依赖（不提交）
│   ├── package.json           # npm 配置
│   └── vite.config.ts         # Vite 配置
├── .trae\
│   └── documents\             # 项目文档（提交，作为知识库）
├── .gitignore                 # Git 忽略规则
├── README.md                  # 项目说明
├── start_backend.bat          # 后端启动脚本
└── start_frontend.bat         # 前端启动脚本
```

> ⚠️ `start_backend.bat` 和 `start_frontend.bat` 硬编码了目录路径，如果克隆到不同目录需要手动修改。

---

## 八、常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `python` 不是内部命令 | Python 未安装或未加 PATH | 重新安装 Python，勾选 Add to PATH |
| `pip install` 失败 | 虚拟环境未激活 | 先执行 `venv\Scripts\activate` |
| `npm install` 很慢 | 网络问题 | 换淘宝镜像：`npm config set registry https://registry.npmmirror.com` |
| `bcrypt` 安装报错 | 缺少 C++ 编译器 | 指定版本：`pip install bcrypt==4.0.1` |
| 前端无法访问后端 | 后端未启动或端口不一致 | 确认后端在 8000 端口运行 |
| `git push` 401 认证失败 | Token 过期或未配置 | 重新生成 GitHub Token |
| 文生图/图生图报 401 | 模型 API Key 未配置 | 去后台管理页面设置模型 API Key |
| 数据库找不到配置 | 新电脑数据库为空 | 首次启动自动创建表，需手动配置模型 API Key |
| push 被拒（non-fast-forward） | 本地落后于远程 | 先 `git pull origin main` 再 push |
| `git push` 报 refspec 不存在 | 分支引用未持久化到 refs/heads | 参见第九章深度排查流程 |
| `git log` / `git branch` 返回空 | .git 元数据损坏或引用丢失 | 检查 `.git/refs/heads` 和 `.git/HEAD` |
| 含 `/` 的分支名无法使用 | Windows 子目录创建失败 | 改用 `-` 分隔的无层级分支名 |

---

## 九、Git 分支推送故障深度排查

> ⚠️ 本节记录了实际 push 过程中遇到的一个隐蔽故障及其完整诊断过程，对 Windows 环境下的 Git 操作尤其有参考价值。

### 9.1 故障现象

在完成 `git add` + `git commit` 后执行 `git push`，报错：

```
error: src refspec feature/v2-product-updates does not match any
error: failed to push some refs to ...
```

然而 `git status` 显示当前就在 `feature/v2-product-updates` 分支上，`git commit` 的输出也正常显示了 `root-commit` 和完整的文件列表。

### 9.2 根因分析

通过以下命令逐层诊断：

```powershell
# 1. 查看本地分支 — 返回空！
git branch
# 输出：(空)

# 2. 查看提交历史 — 报错 "no commits yet"
git log --oneline
# fatal: your current branch does not have any commits yet

# 3. 检查分支引用文件 — 只有 master，新分支不存在
dir .git/refs/heads
# feature/v2-product-updates 文件不存在

# 4. 检查 HEAD — 指向了新分支但引用文件不存在
Get-Content .git/HEAD
# ref: refs/heads/feature/v2-product-updates
```

**最终定位：提交对象已创建**（`git show <hash>` 正常），但 **分支引用文件未写入** `.git/refs/heads/`。这是一个**悬空提交（dangling commit）**：commit 存在于对象数据库中，但没有任何分支指向它。

**根因**：Windows 下创建带 `/` 的分支名（如 `feature/v2-product-updates`）时，Git 需要在 `.git/refs/heads/` 下创建子目录 `feature/` 再写入引用文件。如果 `.git` 目录元数据状态异常，子目录创建会静默失败，导致 `git checkout -b` 和 `git commit` 看似成功但分支引用实际未被持久化。

### 9.3 修复步骤（已验证有效）

**方案一：使用无斜杠的分支名 + commit hash（推荐）**

```powershell
# 找到悬空提交的 hash
git fsck --lost-found    # 或从 git commit 输出中记下 hash

# 直接基于 hash 创建无斜杠分支
git checkout -b feature-v2 <commit-hash>

# 推送
git push origin feature-v2
```

**方案二：手动写入分支引用**

```powershell
# 直接用 update-ref 创建分支引用
git update-ref refs/heads/your-branch <commit-hash>

# 验证
git checkout your-branch
git push origin your-branch
```

**方案三：用 raw push 绕过本地分支**

```powershell
# 直接将 commit hash 推送到远程分支（不依赖本地分支引用）
git push origin <commit-hash>:refs/heads/your-branch
```

### 9.4 验证推送是否真正的成功

推送后 **不要只看命令返回值**，必须用 `git ls-remote` 确认：

```powershell
# 列出远程所有分支及其 commit hash
git ls-remote origin
```

看到类似输出才算成功：
```
7d2623ea2e9c...    refs/heads/feature-v2
```

### 9.5 经验总结

| 问题 | 症状 | 检查方法 | 修复 |
|------|------|----------|------|
| 分支引用未写入 | `git push` 报 refspec 不存在，但 git commit 成功了 | `dir .git/refs/heads` 检查文件是否存在 | 用 `git checkout -b <简单名> <hash>` 重建 |
| 提交已创建但无分支指向 | `git log` 报 no commits，但 `git show <hash>` 正常 | `git fsck --lost-found` 找悬空对象 | `git update-ref` 手动绑定 |
| 含 `/` 分支名创建失败 | checkout -b 成功但 refs 目录无对应文件 | 检查 `refs/heads/<一级>/` 子目录是否创建 | 改无斜杠纯名称 |
| 推送返回码为 0 但实际未推送 | 远程看不到分支 | `git ls-remote origin` 确认 | 用 raw push 重新推送 |
