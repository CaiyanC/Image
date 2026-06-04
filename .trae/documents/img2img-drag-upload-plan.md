# 图生图拖拽上传功能实施计划

## 需求总结

在 Workspace.tsx 的图生图模式中，右侧预览面板（空状态时）增加拖拽上传参考图功能（支持多张）。

## 设计决策

| 决策项 | 方案 |
|--------|------|
| 拖拽区域 | 右侧整个预览面板作为 drop zone |
| 视觉反馈 | 简洁：仅边框颜色变化 + 文案提示，无背景遮罩 |
| 多图合并 | 追加到已有参考图末尾，超出 4 张时 toast 提示"最多4张参考图"并拒绝超出部分 |
| 非图片处理 | 静默过滤，自动跳过非 `image/*` 类型文件 |
| 有结果时拖拽 | 有生成结果时不响应拖拽，仅空状态响应 |
| 实现方式 | 内联到 Workspace.tsx，不引入额外组件/hook |

## 实施步骤

### 步骤 1：添加拖拽状态

- 文件：`frontend/src/pages/Workspace.tsx`
- 新增状态：`const [isDragging, setIsDragging] = useState(false)`
- 位置：紧跟现有 `sourceFiles` 状态声明之后（约 L20-L21 区域）

### 步骤 2：添加拖拽事件处理函数

在 `Workspace.tsx` 组件内部（handleGenerate 之后、JSX 之前），新增三个函数：

```typescript
const handleDragOver = (e: React.DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  setIsDragging(true)
}

const handleDragLeave = (e: React.DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  setIsDragging(false)
}

const handleDrop = (e: React.DragEvent) => {
  e.preventDefault()
  e.stopPropagation()
  setIsDragging(false)

  const files = Array.from(e.dataTransfer.files)
  // 1. 静默过滤非图片文件
  const imageFiles = files.filter(f => f.type.startsWith('image/'))
  if (imageFiles.length === 0) return

  // 2. 追加合并，超出4张拒绝
  const available = 4 - sourceFiles.length
  if (available <= 0) {
    // toast: "最多4张参考图"
    return
  }
  const toAdd = imageFiles.slice(0, available)
  // 如有被截断的，toast 提示
  if (imageFiles.length > available) {
    // toast: `最多4张参考图，已添加${toAdd.length}张`
  }
  setSourceFiles(prev => prev.concat(toAdd))
}
```

### 步骤 3：在预览面板 JSX 中绑定拖拽事件

- 文件：`frontend/src/pages/Workspace.tsx`
- 位置：`mode === 'img2img' && resultUrls.length === 0` 的外层 div（约 L387-L388）
- 绑定三个事件处理：`onDragOver={handleDragOver}` `onDragLeave={handleDragLeave}` `onDrop={handleDrop}`

### 步骤 4：添加拖拽视觉反馈

在同一 div 上根据 `isDragging` 状态切换样式：

```tsx
className={`w-full h-full flex flex-col items-center justify-center p-6 gap-4
  ${isDragging ? 'border-2 border-dashed border-blue-400 rounded-xl' : ''}`}
```

同时根据 `isDragging` 切换上传按钮/当前无参考图时的提示文案：

- 无参考图时：显示"拖拽图片到此处或点击上传"
- 有参考图时：显示"释放以添加参考图"
- 拖入中：显示"释放以添加参考图"

### 步骤 5：添加 toast 提示（超量拒绝时）

在 `handleDrop` 中，当拖入图片超过可用数量时调用 toast 通知。复用项目中已有的 toast 机制，提示文案示例：
- 已满 4 张时：`"最多4张参考图"`
- 部分被截断时：`"最多4张参考图，已添加 N 张"`

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `frontend/src/pages/Workspace.tsx` | 新增拖拽状态 + 事件处理 + JSX 绑定 + 样式切换 |

## 验证方法

1. 切换到图生图模式，确认右侧面板为预览区域空状态
2. 从文件管理器拖拽 1 张图片到预览面板，确认缩略图出现
3. 拖拽 3 张图片，确认全部追加（共 4 张），再次拖拽应有 toast 提示
4. 拖入包含非图片文件（如混杂 PDF），确认只接受图片
5. 拖入时观察边框变为蓝色虚线 + 文案变化
6. 拖出面板时边框恢复正常
7. 生成后（有结果展示），拖拽不响应
8. 现有的点击上传功能不受影响
