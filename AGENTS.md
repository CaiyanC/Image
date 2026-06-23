# CaiYan 项目开发规范

## 分支规则（强制）

- `dev` 分支 = 开发环境，所有日常开发、功能修改、bugfix 都在这里进行
- `master` 分支 = 生产环境，**禁止直接提交**，只接受从 dev 合并过来的代码

**每次开始工作前，必须确认当前在 dev 分支：**
```bash
git branch   # 必须显示 * dev
```

如果不在 dev 分支，执行：
```bash
git checkout dev
```

---

## 日常开发流程

```bash
# 1. 确认在 dev
git checkout dev

# 2. 改代码、测试（使用开发环境）
# 后端: http://localhost:8001
# 前端: http://localhost:5276

# 3. 提交
git add .
git commit -m "描述改了什么"
git push origin dev
```

---

## 发布到生产流程（我明确说"发布"或"更新生产"时才执行）

```bash
# 1. 确保 dev 上的改动已全部提交
git checkout dev
git add .
git commit -m "xxx"
git push origin dev

# 2. 合并到 master
git checkout master
git merge dev
git push origin master

# 3. 重启生产服务（在项目根目录执行）
stop-prod.bat
start-prod.bat

# 4. 立刻切回 dev
git checkout dev
```

---

## 禁止行为

- ❌ 不得在 master 分支上直接修改任何文件
- ❌ 不得在 master 分支上执行 git add / git commit
- ❌ 未经我明确指示"发布"，不得执行 merge 到 master 的操作
- ❌ 不得直接重启 start-prod.bat，除非我明确要求发布

---

## 环境对照表

| 项目 | 生产 (master) | 开发 (dev) |
|------|--------------|------------|
| 后端端口 | 8000 | 8001 |
| 前端端口 | 5275 | 5276 |
| 数据库 | product_knowledge | product_knowledge_dev |
| Redis | db=0 | db=1 |
| Celery 队列 | celery_prod | celery_dev |
| 启动脚本 | start-prod.bat | start-dev.bat |
| env 文件 | .env | .env.dev |
