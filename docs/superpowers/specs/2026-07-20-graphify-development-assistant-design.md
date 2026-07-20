# Graphify 开发辅助工具设计

## 目标

为 Codex 提供本项目的本地代码知识图谱，减少重复全文检索和读取源码所消耗的 token。该工具只服务开发协作，不属于 CaiYan 的产品功能或运行时依赖。

## 边界

- Graphify 作为用户级 CLI 通过 `uv tool install graphifyy` 安装；不写入 `backend/requirements.txt`、`frontend/package.json` 或 Docker 镜像。
- 只在基于 `dev` 已提交版本的独立分析工作树中生成图谱。不会修改当前含未提交变更的 `dev` 工作树，也不会修改 `master`。
- 不启动、停止或重启任何应用服务；开发端口 8001/5276 与生产端口 8000/5275 保持不变。
- 首次范围仅包含 `backend/app`、`frontend/src` 和 `docs` 中的 Markdown 架构/运维资料；排除环境变量、上传文件、日志、报表、产品 QA Excel/Word 文件和依赖目录。
- 不配置 LLM 语义提取后端。首次扫描只使用本地 tree-sitter AST，代码和文档内容不发送到外部 API。

## 设计

1. 创建一个 detached 分析工作树，以当前 `dev` 的提交为基线，目录命名为 `Image-Generation-feature-v5-graphify`。
2. 在该工作树中加入 `.graphifyignore`，明确排除敏感或大体积非代码内容；该文件仅保留在分析工作树，不提交到应用仓库。
3. 安装 Graphify 0.9.20（PyPI 包名 `graphifyy`），并以 `graphify extract` 对限定范围构建 `graphify-out/graph.json`、`GRAPH_REPORT.md` 和 `graph.html`。
4. 进行本地验证：检查 CLI 版本、输出文件存在、报告记录的源文件范围不包含被排除目录，并用 `graphify explain` 查询一个后端模块与一个前端页面。
5. 将 Codex 的 Graphify skill 安装到用户级配置中；不使用 `graphify codex install`，因此不改写项目的 `AGENTS.md`，也不安装 Git hooks 或文件监视器。

## 使用方式

日常开发时，先在分析工作树运行 Graphify 查询，或由 Codex skill 从 `graphify-out/GRAPH_REPORT.md` 和 `graph.json` 导航代码关系；当 `dev` 上的改动稳定后，手动执行一次更新以刷新图谱。图谱仅作为理解和检索加速层，不替代测试、代码审查或实际文件检查。

## 风险与处理

- 图谱对应的是 `dev` 的已提交快照，未提交改动可能尚未包含；这是为了避免干扰当前工作树。稳定后可手动刷新。
- AST 边缘关系可能存在推断误差；关键结论仍回到源文件与测试验证。
- `graphify-out/` 可能较大，因此仅保留在专用分析工作树，不进入 Git。
- Graphify 更新频繁；首次固定验证通过的 0.9.20 版本，后续升级需单独复核。
