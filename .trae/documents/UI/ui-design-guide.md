# Clarity AI + PIM — UI 设计规范文档

> 基于项目截图与代码实现，总结全局设计准则与各页面 UI 要点。  
> 文档路径：`e:\trea\AItool\.trae\documents\UI\ui-design-guide.md`

---

## 一、全局设计准则

### 1.1 设计语言

| 维度 | 规范 |
|------|------|
| **风格** | Apple 生态设计语言 — 极简、通透、毛玻璃质感 |
| **密度** | 低密度（Low Density），大量留白，信息层级清晰 |
| **圆角** | 全局统一 `12px` / `14px` / `16px`，无直角元素 |
| **动效** | 缓动曲线 `cubic-bezier(0.4, 0, 0.2, 1)`，过渡时长 `0.3s` |

### 1.2 色彩体系

| Token | 色值 | 用途 |
|-------|------|------|
| `apple-bg` | `#f5f5f7` | 全局页面背景 |
| `apple-text` | `#1d1d1f` | 主标题、正文 |
| `apple-blue` | `#0071e3` | 主按钮、激活态、选中态、链接 |
| `apple-gray-light` | `#e8e8ed` | 边框、分割线、次级背景 |
| `apple-gray-medium` | `#86868b` | 副标题、占位符、次要文字 |
| `apple-gray-dark` | `#6e6e73` | 辅助说明、时间戳 |
| 白色（glass） | `rgba(255,255,255,0.65)` | 卡片面板背景 |

### 1.3 字体规范

| 层级 | 字号 | 字重 | 字色 |
|------|------|------|------|
| 页面标题 | `24px` | 600 | `#1d1d1f` |
| 区块标题 | `18px` | 600 | `#1d1d1f` |
| 卡片标题 | `15px` | 500 | `#1d1d1f` |
| 正文 | `14px` | 400 | `#1d1d1f` |
| 辅助文字 | `13px` | 400 | `#86868b` |
| 标签文字 | `12px` | 400 | `#86868b` |

- 字体栈：`-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
- 全局开启 `-webkit-font-smoothing: antialiased`

### 1.4 布局规范

| 元素 | 规范 |
|------|------|
| 页面边距 | `24px`（桌面端） |
| 卡片间距 | `16px` ~ `24px` |
| 卡片内边距 | `20px` ~ `24px` |
| 输入框高度 | `44px`（标准），`36px`（紧凑） |
| 按钮高度 | `44px`（主按钮），`36px`（次级按钮） |
| 最大内容宽度 | `1440px`（居中自适应） |

### 1.5 核心组件规范

#### Glass 卡片（毛玻璃面板）

```css
background: rgba(255, 255, 255, 0.65);
backdrop-filter: blur(20px) saturate(180%);
border: 1px solid rgba(255, 255, 255, 0.5);
border-radius: 16px;
box-shadow: 0 8px 32px rgba(0, 0, 0, 0.06);
```

#### 主按钮（Primary Button）

```css
background: #0071e3;
color: white;
border-radius: 12px;
padding: 12px 28px;
font-size: 15px;
font-weight: 500;
/* hover */
transform: translateY(-1px);
box-shadow: 0 4px 16px rgba(0, 113, 227, 0.35);
```

#### Glass 输入框

```css
background: rgba(255, 255, 255, 0.5);
border: 1px solid rgba(0, 0, 0, 0.08);
border-radius: 12px;
/* focus */
border-color: #0071e3;
box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.15);
background: rgba(255, 255, 255, 0.75);
```

#### 导航栏 Tab

- 未激活：文字 `#86868b`，无下划线
- 激活：文字 `#1d1d1f` + 底部 `2px` 蓝色下划线 `#0071e3`
- 悬停：文字颜色加深

### 1.6 滚动条规范

```css
scrollbar-width: thin;
scrollbar-color: rgba(0, 0, 0, 0.15) transparent;
/* WebKit */
width: 6px;
border-radius: 3px;
```

---

## 二、页面级 UI 设计要点

### 2.1 登录页（登录.png）

| 要点 | 说明 |
|------|------|
| **布局** | 左右分屏 — 左侧品牌展示区（深色渐变背景 + 产品 Slogan），右侧登录表单区（浅色背景） |
| **表单卡片** | 居中 Glass 卡片，宽度约 `420px`，圆角 `16px` |
| **输入框** | 全宽 Glass 输入框，图标前缀（用户/锁），聚焦蓝色光晕 |
| **主按钮** | 全宽蓝色按钮，"Sign in"，hover 微上浮 + 阴影 |
| **品牌区** | 大标题 + 副标题 + 装饰性产品图，营造高级感 |
| **底部链接** | "Don't have an account? Register" 小号灰色文字 |

---

### 2.2 登录后看板 / 首页（登录后的看板.png）

| 要点 | 说明 |
|------|------|
| **布局** | 顶部固定导航栏 + 下方内容区（多卡片网格） |
| **导航栏** | 左侧 Logo + 品牌名，中间水平 Tab 导航（AI creation / Asset library / Workflow / History / Products / Analytics / System settings），右侧用户头像 + 通知铃铛 |
| **卡片网格** | 2~3 列响应式网格，每张卡片为 Glass 面板 |
| **卡片内容** | 顶部图标/缩略图 + 标题 + 描述 + 操作按钮 |
| **快捷入口** | 常用功能（文生图、图生图、视频生成）以大卡片突出展示 |
| **最近活动** | 底部横向滚动列表，展示最近生成的内容缩略图 |

---

### 2.3 文生图（文生图.png）

| 要点 | 说明 |
|------|------|
| **布局** | 三栏布局 — 左侧参数面板（`320px` 固定）+ 中间主预览区（自适应）+ 右侧历史/变体栏（可选） |
| **左侧面板** | 垂直堆叠的参数组：Model 选择器、Prompt 文本域（带字符计数 `128/1000`）、Negative prompt、Style 选择（横向缩略图卡片）、Aspect ratio（横向按钮组）、Lighting 下拉、Seed 输入 |
| **主预览区** | 顶部状态栏（"Generating image..." + 进度条 `65%` + Cancel 按钮），中央大图展示，底部操作栏（Variations / Upscale / Download / Add to library） |
| **历史栏** | 底部横向缩略图条，带左右翻页箭头，当前选中项有蓝色边框高亮 |
| **生成按钮** | 左侧面板底部固定，全宽黑色/深色主按钮 "Generate image"，带 sparkle 图标 |

**关键交互：**
- Prompt 文本域实时显示字符计数
- Style 选择为横向缩略图卡片，选中态蓝色边框
- Aspect ratio 为紧凑按钮组，选中态填充蓝色
- 生成过程中主预览区显示进度条和取消按钮

---

### 2.4 图生图（图生图.png）

| 要点 | 说明 |
|------|------|
| **布局** | 与文生图一致的三栏布局，左侧参数面板 + 中间对比预览区 + 底部历史栏 |
| **左侧面板** | 新增 Reference image 上传区（拖拽/点击上传，支持 JPG/PNG/WebP up to 20MB），Style strength 滑块（`0%` ~ `100%`），Composition control（Maintain / Adapt / Enhance 三态按钮），Lighting adaptation 下拉，Material consistency 滑块 |
| **对比预览区** | 顶部 Tab 切换（Before / After | Side by side），双图并排对比展示，中间有过渡箭头 |
| **生成版本** | 底部横向缩略图条，每张卡片右上角有 "..." 更多操作菜单 |
| **细节工具** | 预览区底部工具栏 — Enhance details / Sharpen / Reduce noise / Upscale 2x / Adjust lighting / Download / Add to library |
| **参考管理** | 左侧底部 Reference management 横向缩略图 + "View all" 按钮 |

**关键交互：**
- 上传区支持拖拽，hover 显示上传提示
- Style strength 滑块实时显示百分比
- Composition control 三态切换，选中态填充高亮
- Before/After 支持左右滑动对比

---

### 2.5 视频生成（视频生成.png）

| 要点 | 说明 |
|------|------|
| **布局** | 三栏扩展布局 — 左侧参数面板 + 中间 Storyboard 时间轴 + 右侧预览与渲染队列 |
| **左侧面板** | Model 选择器、Prompt / Negative prompt 文本域、Video settings（Duration / Resolution / FPS 下拉）、AI settings（Motion quality / Creativity 滑块、Camera movement 图标按钮组）、Audio（Voiceover / Background music 下拉） |
| **Storyboard** | 中间垂直时间轴，每个场景为卡片（缩略图 + 标题 + 描述 + 时长标签如 `2.5s`），支持拖拽排序，顶部 "+ Add scene" 按钮 |
| **预览区** | 右侧上部，视频播放器样式（播放按钮 + 时间进度 `0:03 / 0:10` + 全屏按钮），下方分栏：Motion & Camera（Camera movement / Movement strength / Stability / Focus behavior / Depth of field）、Audio（Voiceover / Background music / Music volume / Audio ducking / Fade in/out 开关） |
| **渲染队列** | 右侧下部，列表形式展示排队任务（项目名称 + 进度条 + 状态如 `65%` / `Queued`），底部 "View all" |
| **生成历史** | 底部横向缩略图条，带时长标签（如 `10s` / `8s`） |
| **生成按钮** | 左侧面板底部 "Generate video" 全宽深色按钮 |

**关键交互：**
- Storyboard 场景卡片可拖拽重排
- 每个场景卡片右上角有编辑/删除菜单
- 视频预览支持播放控制
- 渲染队列实时显示进度和状态
- Audio ducking / Fade in-out 为 Toggle 开关（红色 = 开启）

---

## 三、组件复用清单

| 组件 | 复用页面 | 实现文件 |
|------|----------|----------|
| Glass 卡片 | 全部 | `index.css` `.glass` |
| Glass 输入框 | 登录、注册、全部表单 | `index.css` `.glass-input` |
| 主按钮 | 全部 | `index.css` `.btn-primary` |
| 导航栏 | 全部（除登录/注册） | `Header.tsx` |
| 页面布局框架 | 全部 | `Layout.tsx` |
| 图片上传器 | 图生图、产品管理 L5 | `ImageUploader.tsx` |
| 底部历史条 | 文生图、图生图、视频生成 | 各页面内联实现 |
| 分页控件 | 产品管理、历史 | `ProductManagement.tsx` / `History.tsx` |

---

## 四、响应式断点

| 断点 | 宽度 | 布局调整 |
|------|------|----------|
| 桌面大屏 | `>= 1440px` | 三栏完整展示，最大宽度 `1440px` 居中 |
| 桌面 | `1024px ~ 1439px` | 三栏布局，比例微调 |
| 平板 | `768px ~ 1023px` | 左侧参数面板收起为抽屉，主内容区全宽 |
| 移动端 | `< 768px` | 单栏堆叠，底部固定导航 |

---

## 五、设计资产

| 资产 | 路径 |
|------|------|
| 登录页截图 | `e:\trea\AItool\.trae\documents\UI\登录.png` |
| 登录后看板截图 | `e:\trea\AItool\.trae\documents\UI\登录后的看板.png` |
| 文生图截图 | `e:\trea\AItool\.trae\documents\UI\文生图.png` |
| 图生图截图 | `e:\trea\AItool\.trae\documents\UI\图生图.png` |
| 视频生成截图 | `e:\trea\AItool\.trae\documents\UI\视频生成.png` |
| 全局样式 | `frontend/src/styles/index.css` |
| Tailwind 配置 | `frontend/tailwind.config.js` |
