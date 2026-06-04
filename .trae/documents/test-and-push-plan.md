# 📋 测试后代码提交计划

## 背景
- 当前在同时测试 **文生图（txt2img）** 和 **图生图（img2img）**
- 测试满意后，需要将代码推送到 GitHub 的 `main` 分支
- 推送内容需包含 `D:\Trae\AItool\.trae\documents\` 下的项目文档

## 当前状态
| 项目 | 状态 |
|------|------|
| Git 工作区 | ✅ 干净（无未提交更改） |
| .gitignore | ✅ 已配置允许 `.trae/documents/` |
| 文档目录 | ✅ 4 篇文档已在版本控制中 |
| 远程 origin | ✅ `github.com/oliveryou326-crypto/Image-Generation.git` |
| 上次推送 | ✅ `26f1a22` 已推送至 `origin/main` |

`.trae/documents/` 下已有文档：
- `ai-image-video-platform-plan.md` — 项目整体架构规划
- `git-workflow-plan.md` — Git 分支工作流指南
- `github-publish-plan.md` — GitHub 发布步骤
- `push-with-docs-plan.md` — 上次推送计划

---

## 执行步骤

### 第一步：等待/确认测试结果
- 用户在浏览器中测试 **文生图** 和 **图生图** 功能
- 确认两功能均正常生成图片
- 如有参数调整需求，在测试阶段完成后统一修改

### 第二步：检查工作区（测试后）
```bash
git status
```
确认没有意外的未跟踪文件（如测试生成的图片、临时脚本等）

### 第三步：添加所有更改
如果测试期间有代码调整：
```bash
git add -A
```
**排除项**（由 .gitignore 确保）：
- `.env` — 包含 API Key 等敏感信息
- `*.db` — SQLite 数据库文件
- `uploads/` — 用户上传文件
- `__pycache__/`、`node_modules/` — 构建产物

### 第四步：提交
```bash
git commit -m "release: 文生图+图生图功能测试通过，v1.0 正式版"
```
提交将包含：
- 所有源代码文件（前后端）
- `.trae/documents/` 下的项目文档
- `.gitignore` 配置
- 测试期间如有代码调整一并提交

### 第五步：推送到 GitHub
```bash
git push origin main
```
- 推送方式：正常 push（非 force push）
- 目标分支：`main`
- 由于本地领先远程，将直接更新远程 `main` 分支

### 第六步：验证推送结果
```bash
git log --oneline -3
```
确认远程已收到最新提交。

---

## 风险与注意事项
| 风险 | 说明 | 应对 |
|------|------|------|
| 图生图 408 超时 | dmxapi.cn 服务端处理慢，非代码问题 | 使用 low+jpeg 参数降低处理时间 |
| 误提交敏感文件 | .env 包含 API Key | .gitignore 已排除 .env |
| 推送冲突 | 如多设备同时推送 | 先用 `git pull` 同步再 push |

---

## 预期结果
- ✅ GitHub `main` 分支包含最新代码
- ✅ `.trae/documents/` 下的 4 篇文档可见于 GitHub
- ✅ 文生图 + 图生图功能代码均已纳入版本管理
- ✅ 仓库保持干净，无敏感信息泄露
