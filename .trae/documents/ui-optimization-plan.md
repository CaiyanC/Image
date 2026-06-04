# UI 优化计划（修订版）

## 〇、参考图像清单

UI参考图像位于 `E:\trea\AItool\.trae\documents\UI`，共 5 张：

| 序号 | 文件名          | 对应页面用途                                    |
| -- | ------------ | ----------------------------------------- |
| 1  | `登录.png`     | 登录/注册页（Login / Register）                  |
| 2  | `登录后的看板.png` | 登录后主看板/首页（Dashboard / 主布局）                |
| 3  | `文生图.png`    | 创作工作台-文生图模式（Workspace: text-to-image）     |
| 4  | `图生图.png`    | 创作工作台-图生图模式（Workspace: image-to-image）    |
| 5  | `视频生成.png`   | 创作工作台-视频生成模式（Workspace: video generation） |

***

## 〇·重要约束

> **只修改UI视觉层（颜色、间距、卡片、按钮、输入框、布局），不修改任何业务逻辑和数据表单结构。**
>
> ⚠️ **ProductManagement.tsx 的 L1-L6 数据表单字段、Section 组件、Field/TextareaField/KV/EditableKV 组件逻辑完全不动。** 仅替换其样式类名和容器视觉。

***

## 一、设计分析

### 1.1 参考UI图像风格特征（提炼自5张参考图 + 用户提供的Design Token）

- **整体气质**：温暖、专业、极简、高端感——像Notion/Linear的混合体
- **背景**：极浅暖灰白 `#F2F2F0`，纯色无渐变，无任何彩色光晕装饰
- **卡片**：半透明磨砂玻璃质感 `rgba(255,255,255,0.72)` + `backdrop-filter: blur()`，大圆角 `24px`，白色边缘 `border: 1px solid rgba(255,255,255,0.6)`，极淡阴影 `0 4px 12px rgba(0,0,0,0.03)`
- **色彩体系**：整体主色调从 Apple 蓝切换到暖灰白 `#F2F2F0`（背景），品牌强调用深橄榄绿 `#4C534B`，点缀暗红 `#B4221C`，暖棕 `#9B8572` 作辅助
- **保留玻璃拟态**：保留 backdrop-filter blur 效果的半透明卡片，底色从冷白调整为暖灰白 `rgba(255,255,255,0.72)`
- **边框极淡**：`rgba(0,0,0,0.05)` 的极细分隔线，几乎不可见
- **排版**：小号灰色标签 + 深色大号内容，层级通过字重和大小区分
- **按钮**：深色填充为主（`#4C534B`），`12px` 圆角，幽灵按钮用边框+深字

### 1.2 当前项目UI核心问题

| 问题     | 现状                                         | 目标                                   |
| ------ | ------------------------------------------ | ------------------------------------ |
| 玻璃色彩偏冷 | `.glass` 使用冷白半透明底 + 蓝色调阴影 | 保留玻璃效果，底色改为暖灰白 `rgba(255,255,255,0.72)`，阴影和边框融入新暖色系 |                          |
| 背景花哨   | `bg-gradient-subtle` + 蓝紫光晕球               | 纯 `#F2F2F0`                          |
| 主色冷蓝调  | Apple蓝 `#0071e3` 主导整体视觉                    | 暖灰白 `#F2F2F0` 为背景主色调，`#4C534B` 作品牌强调 |
| 圆角混乱   | 10px/12px/14px/16px/20px 并存                | 统一 24px(卡片) / 14px(输入) / 12px(按钮)    |
| 阴影过重   | `0 8px 32px rgba(0,0,0,0.08)`              | `0 4px 12px rgba(0,0,0,0.03)`        |
| 文字颜色冷  | `#1d1d1f` / `#86868b`                      | `#2E3133` / `#6B6B6B`                |

***

## 二、优化步骤（8步）

***

### Step 1：全局 Design Token 重构

**文件**：`tailwind.config.js` + `index.css`

#### 1.1 tailwind.config.js

```js
// 替换 colors.apple → 新色彩体系
colors: {
  ui: {
    bg: '#F2F2F0',       // 页面背景
    card: '#FFFFFF',     // 卡片背景
    text: '#2E3133',     // 主文字
    muted: '#6B6B6B',    // 次要文字
    border: 'rgba(0,0,0,0.05)', // 边框
    brand: '#4C534B',    // 主色（按钮/链接）
    accent: '#B4221C',   // 强调（删除/危险）
    warm: '#9B8572',     // 暖色点缀
  }
},
borderRadius: {
  card: '24px',
  input: '14px',
  button: '12px',
},
boxShadow: {
  card: '0 4px 12px rgba(0,0,0,0.03)',
}
```

#### 1.2 index.css - 更新现有类 + 新建

**更新 · 现有 glass 系列**（保留玻璃拟态，仅更新色彩）：

```css
/* old: rgba(255,255,255,0.65) + 蓝色调阴影 + 蓝色边框高光 */
/* new: rgba(255,255,255,0.72) + 暖灰调阴影 + 白色边缘高光 */
.glass {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
  border-radius: 24px;
}
.glass-dark {
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.4);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}
.glass-input {
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 14px;
  padding: 10px 16px;
  transition: all 0.2s ease;
}
.glass-input:focus {
  outline: none;
  border-color: #4C534B;
  box-shadow: 0 0 0 3px rgba(76, 83, 75, 0.1);
  background: rgba(255, 255, 255, 0.85);
}
```

**删除**：
- `.bg-gradient-subtle` `.bg-gradient-accent` 渐变背景类
- `.btn-primary` `.btn-glass` `.btn-glass.active` 旧版按钮类
- 任何带有 Apple 蓝色系的 shadow/border 定义

**新建**：
```css
body { background: #F2F2F0; color: #2E3133; }

.btn-brand {
  background: #4C534B; color: #FFF; border-radius: 12px;
  padding: 10px 24px; font-weight: 500; border: none;
  cursor: pointer; transition: all 0.2s ease;
}
.btn-brand:hover { background: #3D423C; }
.btn-brand:disabled { background: #A8ACA8; cursor: not-allowed; }
.btn-outline {
  background: rgba(255,255,255,0.55); color: #2E3133;
  border: 1px solid rgba(0,0,0,0.08); border-radius: 12px;
}
.btn-ghost {
  background: transparent; color: #6B6B6B;
  border: none; border-radius: 12px;
}
.btn-ghost:hover { background: rgba(0,0,0,0.04); color: #2E3133; }
.btn-danger { background: #B4221C; color: #FFF; border-radius: 12px; }
.badge {
  display: inline-flex; align-items: center; padding: 2px 10px;
  border-radius: 100px; font-size: 12px; font-weight: 500;
}
.tag {
  background: rgba(0,0,0,0.04); color: #6B6B6B;
  border-radius: 8px; padding: 4px 10px; font-size: 13px;
}
```

> **关键**：`.glass` / `.glass-dark` / `.glass-input` 全部保留，仅更新其 rgba 底色、边框颜色、阴影值。页面组件中原有的 `glass` className 无需改动，CSS 更新后自动生效。

***

### Step 2：布局框架（Layout.tsx + Header.tsx）

**参考图像**：`登录后的看板.png`（主看板布局）

#### Layout.tsx 修改：

```
删除：<div className="fixed inset-0 ..."> 两个光晕球 div
删除：className="min-h-screen bg-gradient-subtle"
新增：className="min-h-screen bg-[#F2F2F0]"
main：保持 pt-14 layout，padding 改为 px-6 py-4
```

- 背景纯 `#F2F2F0`，无任何装饰元素

#### Header.tsx 修改：

```
保留 className="glass-dark ..."（CSS 已全局更新色彩，无需改类名）
仅需更新内联颜色类和交互色：
```

- 导航栏保留 glass-dark 磨砂半透明效果，背景改为暖白半透明
- 通顶显示，底部带 `border-[rgba(0,0,0,0.05)]` 细分隔线
- Logo "AI 创作平台" 保持，颜色改为 `#2E3133`
- 导航项激活态：`bg-[#4C534B] text-white`（深底白字 pill）
- 导航项默认态：`text-[#6B6B6B] hover:text-[#2E3133] hover:bg-[rgba(0,0,0,0.04)]`
- 用户头像下拉/管理下拉：保留 glass 卡片 + 24px 大圆角
- 下拉中的分隔线从 `border-black/5` 改为 `border-[rgba(0,0,0,0.05)]`
- 头像图标背景从 `bg-apple-blue` 改为 `bg-[#4C534B]`

***

### Step 3：登录/注册页（Login.tsx + Register.tsx）

**参考图像**：`登录.png`

```
删除：<div className="fixed inset-0 ..."> 两个光晕球
删除：className="min-h-screen bg-gradient-subtle"
新增：className="min-h-screen bg-[#F2F2F0] flex items-center justify-center p-4"

卡片：`className="glass p-8 space-y-5"` → 保持 glass 不替换（CSS 已全局更新），外层可加 `w-full max-w-md`
标题颜色："text-apple-text" → "text-[#2E3133]"
副标题颜色："text-apple-gray-medium" → "text-[#6B6B6B]"

输入框：`className="glass-input w-full px-4 py-3 ..."` → 保持 glass-input（CSS 已更新）
标签颜色："text-apple-text" → "text-[#6B6B6B] text-xs font-medium uppercase tracking-wider"

登录按钮：className="btn-primary w-full" → className="btn-brand w-full py-3"
注册链接颜色："text-apple-blue" → "text-[#4C534B]"

错误提示："bg-red-50 border-red-200 text-red-600" → "bg-[#FEF2F2] border-[#FECACA] text-[#B4221C]"
```

Register.tsx 同理以上映射。

***

### Step 4：创作工作台（Workspace.tsx）

**参考图像**：`文生图.png` / `图生图.png` / `视频生成.png` — 核心AI生成页面（三种模式）

这是最重要的页面，需要深度重构视觉：

#### 整体容器：

```
删除：className="flex h-[calc(100vh-3.5rem)] p-4 gap-4"
新增：className="flex h-[calc(100vh-3.5rem)] p-6 gap-6"
```

#### 左侧控制面板（40%列）：
```
外层容器：保持 className="glass"（CSS 已全局更新为暖白 + 白色边缘 + 大圆角）
内部子卡片（模型、提示词、高级参数）：保持 className="glass"
间距统一：gap-4 → gap-5，p-4 → p-5
```

**模式切换 pill**：

```
激活态：className="bg-apple-blue text-white shadow-sm" → className="bg-[#4C534B] text-white"
默认态：className="text-apple-gray-dark hover:text-apple-text hover:bg-black/3" → className="text-[#6B6B6B] hover:text-[#2E3133] hover:bg-[rgba(0,0,0,0.04)]"
圆角：rounded-[10px] → rounded-[12px]
```

**模型选择器**：
```
select：保持 className="glass-input ..."（CSS 已更新），增加自定义下拉箭头图标
```

**提示词 textarea**：
```
保持 className="glass-input ..."（CSS 已更新），min-h-[140px] resize-none
placeholder 颜色：placeholder:text-apple-gray-medium → placeholder:text-[#9E9E9E]
```

**高级参数折叠区**：

```
标题：text-apple-text → text-[#2E3133]
各参数标签：text-apple-gray-dark → text-[#6B6B6B] text-xs
各参数 select/input：保持 glass-input（CSS 已更新）
Range input：保持原生样式，accent-color 设为 #4C534B
```

**生成按钮**：

```
className="btn-primary w-full py-3.5 text-base" → className="btn-brand w-full py-3.5 text-base font-medium"
```

**错误提示**：

```
className="bg-red-50 border border-red-200 text-red-600 ..." → className="border border-[#FECACA] bg-[#FEF2F2] text-[#B4221C] rounded-[14px] px-4 py-3 text-sm"
```

#### 右侧预览面板：
```
外层：保持 className="glass p-1.5"（CSS 已更新），增加 flex flex-col
预览区：保持 className="rounded-xl overflow-hidden bg-black/[0.02]"，增加 flex-1
图生图参考图容器：保持 className="glass px-5 py-3 ..."（CSS 已更新）
```

***

### Step 5：历史记录页（History.tsx）

**参考图像**：`登录后的看板.png`

#### 统计卡片区：
```
卡片容器：保持 className="glass rounded-xl p-4"（CSS 已更新）
标签：className="text-sm text-apple-gray-medium" → className="text-xs text-[#6B6B6B] uppercase tracking-wider"
数值：className="text-3xl font-bold text-apple-text" → className="text-3xl font-bold text-[#2E3133]"
类型计数颜色去掉（blue-600/purple-600/green-600），统一用 text-[#2E3133]，靠顶部彩色小条区分
```

#### 搜索过滤区：
```
className="glass rounded-xl p-4" → 保持 glass（CSS 已更新），p-4 → p-5
输入框：保持 glass-input 类名
按钮：className="bg-blue-500 text-white rounded-lg ..." → className="btn-brand"
按钮（重置）：className="bg-gray-100 text-gray-700 ..." → className="btn-outline"
```

#### 左侧列表：
```
容器：保持 className="glass ... rounded-xl"（CSS 已更新），增加 divide-y divide-[rgba(0,0,0,0.05)]
列表项 hover：hover:bg-black/[0.02] → hover:bg-[rgba(0,0,0,0.02)]
选中态：bg-blue-50/50 → bg-[rgba(76,83,75,0.06)]（淡橄榄绿）
类型标签：bg-black/5 → bg-[rgba(0,0,0,0.04)]
状态标签颜色保留但调整饱和度
```

#### 右侧详情：
```
容器：保持 className="glass rounded-xl"（CSS 已更新），增加 p-6
标签：text-apple-gray-dark → text-[#6B6B6B]
描述区：bg-black/[0.02] rounded-xl → bg-[rgba(0,0,0,0.02)] rounded-[14px]
删除按钮颜色：text-red-500 → text-[#B4221C]
```

***

### Step 6：产品管理页（ProductManagement.tsx）

**参考图像**：`登录后的看板.png`

> ⚠️ **核心约束：只改样式，不动 L1-L6 数据表单结构和交互逻辑。**

#### 页面标题区：

```
标题：text-apple-text → text-[#2E3133]
新增按钮：bg-blue-500 text-white rounded-lg → btn-brand px-5 py-2.5
```

#### 搜索区：
```
搜索卡片：保持 className="glass rounded-xl p-4"（CSS 已更新）
输入框：保持 glass-input 类名，增加 flex-1
搜索按钮 → btn-brand
```

#### 新建产品表单（showCreate区域）：
```
整体容器：保持 className="glass rounded-xl p-6 ..."（CSS 已更新）
Section 组件：保持现有 <details> 结构不动，仅修改内部样式

样式映射：
- summary：text-apple-text → text-[#2E3133]
- Field 内的 input：保持 glass-input 类名（CSS 已更新），宽度类保持
- TextareaField 内的 textarea：同上
- select：同上保持 glass-input
- checkbox：保持原有
- 创建/取消按钮 → btn-brand / btn-outline
- 图片上传按钮：bg-blue-500 → btn-brand 风格
- 上传图片网格边框 border-gray-200 → border-[rgba(0,0,0,0.05)]

产品名称输入区（name_zh/name_en/name_ja）：input 类名保持 glass-input（CSS 已更新）
分类下拉面板：bg-white border-gray-200 → bg-white border-[rgba(0,0,0,0.05)]
```

#### 左侧产品列表：
```
容器：保持 className="glass ... rounded-xl"（CSS 已更新）
列表项选中：bg-blue-50/50 → bg-[rgba(76,83,75,0.06)]
分页区：保持结构，按钮颜色调整
```

#### 右侧详情（selected 区域）：
```
容器：保持 className="glass rounded-xl"（CSS 已更新）
L1-L6 标题：text-[#2E3133] text-sm font-semibold
KV 组件容器：bg-black/[0.02] rounded-xl → bg-[rgba(0,0,0,0.02)] rounded-[14px]
KV 标签：text-apple-gray-dark → text-[#6B6B6B]
KV 值：text-apple-text → text-[#2E3133]
编辑按钮：bg-blue-500 → btn-brand px-3 py-1.5
取消按钮：bg-gray-100 → btn-outline px-3 py-1.5
编辑模式 input/select/textarea：保持 glass-input（CSS 已更新）
删除按钮：text-red-400 hover:text-red-600 → text-[#B4221C]/70 hover:text-[#B4221C]
认证标签：bg-green-50 text-green-700 → 保持或用品牌色微调
技术优势标签：bg-blue-50 text-blue-700 → bg-[rgba(76,83,75,0.08)] text-[#4C534B]
使用场景标签：bg-purple-50 text-purple-700 → bg-[rgba(155,133,114,0.08)] text-[#9B8572]
竞品标签：bg-yellow-50 text-yellow-700 → 同上暖色系
关键词标签：bg-cyan-50 text-cyan-700 → 保持微调饱和度
评价标签：bg-orange-50 text-orange-700 → 保持微调饱和度
```

> 以上所有修改仅替换 className，不改变任何组件 props、state、交互逻辑。

***

### Step 7：管理后台页（AdminUsers + AdminGroups + AdminSettings）

**参考图像**：`登录后的看板.png`

#### AdminUsers.tsx：
```
页面标题：text-apple-text → text-[#2E3133]
新增按钮 → btn-brand text-sm
新增表单卡片：保持 className="glass p-4 ... rounded-xl"（CSS 已更新）
输入框：保持 glass-input（CSS 已更新）
表格容器：保持 className="glass rounded-xl overflow-hidden"（CSS 已更新）
表格头部：border-b border-black/5 → 不变，文字改为 text-[#6B6B6B]
表格行 hover：hover:bg-black/[0.01] → hover:bg-[rgba(0,0,0,0.02)]
头像图标：bg-apple-blue/10 text-apple-blue → bg-[#4C534B]/10 text-[#4C534B]
角色标签：bg-purple-100 text-purple-700 → bg-[rgba(180,34,28,0.08)] text-[#B4221C] (super_admin)
                  bg-gray-100 text-gray-600 → bg-[rgba(0,0,0,0.04)] text-[#6B6B6B] (user)
团队标签：bg-blue-50 text-blue-600 → bg-[rgba(76,83,75,0.08)] text-[#4C534B]
状态：text-green-600 → text-[#4C534B]，text-red-500 → text-[#B4221C]
编辑/删除链接：text-apple-blue / text-red-500 → text-[#4C534B] / text-[#B4221C]
编辑 select：保持 glass-input（CSS 已更新）
```

#### AdminGroups.tsx：
```
新建团队按钮：bg-blue-500 → btn-brand
创建/编辑表单：保持 className="glass rounded-xl p-6"（CSS 已更新）
输入框/textarea：保持 glass-input（CSS 已更新）
团队卡片：保持 className="glass rounded-xl overflow-hidden"（CSS 已更新）
团队首字母图标：bg-blue-100 text-blue-600 → bg-[#4C534B]/10 text-[#4C534B]
预置标签：bg-amber-50 text-amber-600 → bg-[rgba(155,133,114,0.1)] text-[#9B8572]
按钮：bg-black/[0.04] → btn-ghost，bg-blue-500 → btn-brand，bg-red-50 → bg-[#FEF2F2] text-[#B4221C]
成员卡片：bg-white/40 → bg-[rgba(0,0,0,0.01)]
成员选择器 select → 保持 glass-input
```

#### AdminSettings.tsx：
```
标题按钮：btn-primary → btn-brand
模型卡片：保持 className="glass rounded-2xl"（CSS 已更新）
标题文字 → text-[#2E3133]
类型标签：bg-blue-50 text-blue-600 → bg-[rgba(76,83,75,0.08)] text-[#4C534B]
状态圆点：bg-green-400 / bg-red-300 保持不变
展开图标：保持
输入框：保持 glass-input（CSS 已更新）
select：保持 glass-input（CSS 已更新）
新增模型区：保持 className="glass rounded-2xl p-5"（CSS 已更新）
新增按钮：btn-primary → btn-brand
```

***

### Step 8：全局细节打磨

| 细节项                                                     | 处理方式                                                              |
| ------------------------------------------------------- | ----------------------------------------------------------------- |
| 所有页面的 `text-apple-text`                                 | → `text-[#2E3133]`                                                |
| 所有页面的 `text-apple-gray-dark` / `text-apple-gray-medium` | → `text-[#6B6B6B]`                                                |
| 所有 `glass` 容器 | → 保持类名不变（CSS 已全局更新为暖白半透明底 + 白色边缘 + 大圆角） |
| 所有 `glass-input` | → 保持类名不变（CSS 已更新：暖白半透明底 + 淡边框 + 聚焦橄榄绿 ring） |
| 所有蓝色系按钮 `bg-blue-500` / `btn-primary`                   | → `btn-brand` 或 `bg-[#4C534B]`                                    |
| 所有分割线 `border-black/5`                                  | → `border-[rgba(0,0,0,0.05)]`                                     |
| 滚动条                                                     | 保持 `.scrollbar-thin`，颜色更新为 `rgba(0,0,0,0.1)`                      |
| 空状态                                                     | 保持现有文案，样式保留 glass 容器                                            |
| 加载状态                                                    | 保持现有 spinner 和文字，颜色从 `text-apple-gray-medium` → `text-[#6B6B6B]`  |
| 错误提示                                                    | 统一为 `bg-[#FEF2F2] border-[#FECACA] text-[#B4221C] rounded-[14px]` |
| 过渡动画                                                    | 保持 `animate-fade-in` / `animate-slide-up`，时长不变                    |
| 字体                                                      | 保持系统字体栈 `-apple-system, ...`，不修改                                  |
| `ImageUploader` 组件                                      | 同步替换内部样式类名                                                        |

***

## 三、色彩映射速查表

> **核心主色调变化**：整体从冷蓝调 (`#0071e3` / `#f5f5f7`) 切换到暖灰白基调 (`#F2F2F0`)，品牌交互点用 `#4C534B` 深橄榄绿。

| 旧类名/token                                         | 旧值                                | 新值/新类名                                      |
| ------------------------------------------------- | --------------------------------- | ------------------------------------------- |
| `bg-apple` / `bg-gradient-subtle`                 | `#f5f5f7`+渐变                      | `bg-[#F2F2F0]`                              |
| `glass` / `.glass-dark` / `.glass-light`          | rgba(255,255,255,0.65)+冷蓝调 blur  | 保持类名，CSS 更新：底 `rgba(255,255,255,0.72)`，白边 `border: 1px solid rgba(255,255,255,0.6)` |
| `text-apple-text`                                 | `#1d1d1f`                         | `text-[#2E3133]`                            |
| `text-apple-gray-dark` / `text-apple-gray-medium` | `#6e6e73` / `#86868b`             | `text-[#6B6B6B]`                            |
| `btn-primary` / `bg-apple-blue` / `bg-blue-500`   | `#0071e3`                         | `btn-brand` / `bg-[#4C534B]`                |
| `text-apple-blue`                                 | `#0071e3`                         | `text-[#4C534B]`                            |
| `text-red-500` / `bg-red-50`                      | 红色系                               | `text-[#B4221C]` / `bg-[#FEF2F2]`           |
| `border-black/5`                                  | `rgba(0,0,0,0.05)`                | `border-[rgba(0,0,0,0.05)]`                 |
| `glass-input`                                     | rgba+blur+蓝色聚焦 ring               | 保持类名，CSS 更新：底 `rgba(255,255,255,0.55)`，聚焦 `border-color:#4C534B` + olive ring |
| `rounded-xl` / `rounded-2xl`                      | 12px/16px                         | `rounded-[24px]`（卡片）/ `rounded-[14px]`（输入）  |
| `rounded-lg`（按钮）                                  | 8px                               | `rounded-[12px]`                            |
| `shadow-glass` / box-shadow on `.glass`           | `0 8px 32px rgba(0,0,0,0.06~0.1)` | 保持类名，CSS 更新：`0 4px 12px rgba(0,0,0,0.03)` |
| `bg-blue-50/50`（选中态）                              | 蓝色淡底                              | `bg-[rgba(76,83,75,0.06)]`（橄榄绿淡底）           |

***

## 四、文件修改清单（共12个文件）

| #  | 文件路径                                        | 修改内容                            | 是否动逻辑 |
| -- | ------------------------------------------- | ------------------------------- | ----- |
| 1  | `frontend/tailwind.config.js`               | 替换 color/radius/shadow 全部 token | 否     |
| 2  | `frontend/src/styles/index.css`             | 更新 glass/glass-dark/glass-input 色彩值，删除渐变背景类，新建 btn-brand/btn-outline/btn-ghost/btn-danger/badge/tag 类 | 否     |
| 3  | `frontend/src/components/layout/Layout.tsx` | 背景纯色，删光晕球，保留玻璃布局                       | 否     |
| 4  | `frontend/src/components/layout/Header.tsx` | 保留 glass-dark，更新内联颜色类 + 品牌色映射          | 否     |
| 5  | `frontend/src/pages/Login.tsx`              | 保留 glass/glass-input，仅颜色映射 + 清除光晕球装饰    | 否     |
| 6  | `frontend/src/pages/Register.tsx`           | 保留 glass/glass-input，仅颜色映射 + 清除光晕球装饰    | 否     |
| 7  | `frontend/src/pages/Workspace.tsx`          | 保留所有 glass/glass-input 类名，仅颜色映射 + 间距微调   | 否     |
| 8  | `frontend/src/pages/History.tsx`            | 保留所有 glass/glass-input 类名，仅颜色映射           | 否     |
| 9  | `frontend/src/pages/ProductManagement.tsx`  | 保留所有 glass/glass-input，**仅颜色映射**，L1-L6 不动 | **否** |
| 10 | `frontend/src/pages/AdminUsers.tsx`         | 保留 glass/glass-input 类名，表格/标签/按钮颜色映射   | 否     |
| 11 | `frontend/src/pages/AdminGroups.tsx`        | 保留 glass/glass-input 类名，卡片/标签/按钮颜色映射   | 否     |
| 12 | `frontend/src/pages/AdminSettings.tsx`      | 保留 glass/glass-input 类名，卡片/输入框/标签颜色映射  | 否     |

***

## 五、设计原则（六条铁律）

1. **极简优先**：去除所有渐变背景和彩色光晕装饰，保留玻璃拟态但更新为暖白半透明底色
2. **留白即设计**：用间距（gap/padding）而非线条来区分区域
3. **色彩克制**：只用 3-4 个颜色 —— 深橄榄绿 `#4C534B`、暗红 `#B4221C`、暖棕 `#9B8572`、以及中性灰 `#6B6B6B`
4. **圆角统一**：大卡片 `24px`，输入框 `14px`，按钮 `12px`，小型标签 `8px`
5. **阴影极淡**：`0 4px 12px rgba(0,0,0,0.03)`，靠留白区分层级而非靠阴影
6. **零逻辑改动**：所有页面只替换 `className` 和样式类，不修改任何 `useState`、事件处理、API 调用、数据结构

