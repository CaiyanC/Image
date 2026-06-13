import { useState, useEffect, useCallback } from 'react'
import { api } from '../services/api'
import { ImagePreview } from '../components/ImageUploader/ImageUploader'
import Lightbox from '../components/Lightbox'

type GenerationMode = 'txt2img' | 'img2img' | 'txt2vid'

interface ModelInfo {
  id: string
  name: string
  type: string
  description: string
  api_format: string
}

export default function Workspace() {
  const [mode, setMode] = useState<GenerationMode>('txt2img')
  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegativePrompt] = useState('')
  const [sourceFiles, setSourceFiles] = useState<File[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [resultUrls, setResultUrls] = useState<string[]>([])
  const [toastMsg, setToastMsg] = useState('')
  const [lightboxIndex, setLightboxIndex] = useState(-1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState('gpt-image-2-ssvip')
  const [showParams, setShowParams] = useState(true)
  const [params, setParams] = useState<Record<string, any>>({
    size: '1152x2048', n: 1, quality: 'medium', output_format: 'png', output_compression: 85, moderation: 'low', background: 'auto',
  })

  const loadModels = useCallback(async () => {
    try {
      const data = await api.generation.models()
      setModels(data)
      if (data.length > 0 && !data.find((m: ModelInfo) => m.id === selectedModel)) {
        setSelectedModel(data[0].id)
      }
    } catch { }
  }, [])

  useEffect(() => {
    loadModels()
  }, [loadModels])

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError('请输入提示词')
      return
    }
    setError('')
    setLoading(true)
    setResultUrls([])

    try {
      let result: any

      if (mode === 'txt2img') {
        result = await api.generation.txt2img({
          prompt: prompt.trim(),
          model_name: selectedModel,
          negative_prompt: negativePrompt.trim() || undefined,
          params,
        })
      } else if (mode === 'img2img') {
        if (sourceFiles.length === 0) {
          setError('请上传参考图像')
          setLoading(false)
          return
        }
        if (isGemini) {
          result = await api.generation.img2imgGemini({
            prompt: prompt.trim(),
            model_name: selectedModel,
            negative_prompt: negativePrompt.trim() || undefined,
            params: { n: params.n, aspect_ratio: params.aspect_ratio || '1:1', image_size: params.image_size || '1K' },
            images: sourceFiles,
          })
        } else {
          result = await api.generation.img2img({
            prompt: prompt.trim(),
            model_name: selectedModel,
            negative_prompt: negativePrompt.trim() || undefined,
            size: params.size,
            images: sourceFiles,
            n: params.n,
            quality: params.quality,
            output_format: params.output_format,
            output_compression: params.output_compression,
            moderation: params.moderation,
            background: params.background,
          })
        }
      } else {
        result = await api.generation.txt2vid({
          prompt: prompt.trim(),
          model_name: selectedModel,
          negative_prompt: negativePrompt.trim() || undefined,
          params,
        })
      }

      if (result.result_images && result.result_images.length > 0) {
      setResultUrls(result.result_images)
    } else if (result.result_image_path) {
      setResultUrls([result.result_image_path])
    } else if (result.result_video_path) {
      setResultUrls([result.result_video_path])
      } else if (result.status === 'failed') {
        setError(result.error_message || '生成失败')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成请求失败')
    } finally {
      setLoading(false)
    }
  }

  const filteredModels = models.filter((m) => {
    if (mode === 'txt2vid') return m.type === 'video'
    return m.type === 'image'
  })

  const currentModel = models.find(m => m.id === selectedModel)
  const isGemini = currentModel?.api_format === 'gemini'

  useEffect(() => {
    if (isGemini) {
      setParams({ n: 1, aspect_ratio: '1:1', image_size: '1K' })
    } else {
      setParams({ size: '1152x2048', n: 1, quality: 'medium', output_format: 'png', output_compression: 85, moderation: 'low', background: 'auto' })
    }
  }, [selectedModel, mode])

  const modes: { key: GenerationMode; label: string }[] = [
    { key: 'txt2img', label: '文生图' },
    { key: 'img2img', label: '图生图' },
    { key: 'txt2vid', label: '文生视频' },
  ]

  function handleClearResult() {
    setResultUrls([])
  }

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
    const imageFiles = files.filter(f => f.type.startsWith('image/'))
    if (imageFiles.length === 0) return

    const available = 4 - sourceFiles.length
    if (available <= 0) {
      setToastMsg('最多4张参考图')
      setTimeout(() => setToastMsg(''), 2000)
      return
    }
    const toAdd = imageFiles.slice(0, available)
    if (imageFiles.length > available) {
      setToastMsg(`最多4张参考图，已添加${toAdd.length}张`)
      setTimeout(() => setToastMsg(''), 2000)
    }
    setSourceFiles(prev => prev.concat(toAdd))
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] gap-4 p-4 md:h-[calc(100vh-5rem)]">
      <div className="w-[40%] flex flex-col gap-4 min-w-[380px]">
        <div className="glass p-1.5 flex gap-1">
          {modes.map((m) => (
            <button
              key={m.key}
              onClick={() => {
                setMode(m.key)
                setResultUrls([])
                if (m.key === 'img2img') {
                  setSourceFiles([])
                }
              }}
              className={`flex-1 py-2 px-3 rounded-[10px] text-sm font-medium transition-all duration-300 ${
                mode === m.key
                  ? 'bg-apple-blue text-white shadow-sm'
                  : 'text-apple-gray-dark hover:text-apple-text hover:bg-black/3'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="glass p-4">
          <label className="block text-xs font-medium text-apple-gray-dark mb-2">模型</label>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="glass-input w-full px-4 py-2.5 text-sm text-apple-text appearance-none cursor-pointer"
          >
            {filteredModels.length === 0 && (
              <option value="">加载中...</option>
            )}
            {filteredModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} - {m.description}
              </option>
            ))}
          </select>
        </div>

        <div className="glass p-4 flex-1 flex flex-col">
          <label className="block text-xs font-medium text-apple-gray-dark mb-2">提示词</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="描述你想要生成的图像或视频..."
            className="glass-input w-full flex-1 px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium resize-none min-h-[120px]"
          />
          <div className="mt-2">
            <label className="block text-xs font-medium text-apple-gray-dark mb-1.5">反向提示词（可选）</label>
            <input
              type="text"
              value={negativePrompt}
              onChange={(e) => setNegativePrompt(e.target.value)}
              placeholder="不想出现的内容..."
              className="glass-input w-full px-3 py-2 text-sm text-apple-text placeholder:text-apple-gray-medium"
            />
          </div>
        </div>

        <div className="glass">
          <button
            onClick={() => setShowParams(!showParams)}
            className="w-full px-4 py-3 flex items-center justify-between text-sm font-medium text-apple-text"
          >
            <span>高级参数</span>
            <svg
              className={`w-4 h-4 text-apple-gray-medium transition-transform duration-300 ${showParams ? 'rotate-180' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          {showParams && (
            <div className="px-4 pb-4 grid grid-cols-2 gap-3 animate-fade-in">
              {isGemini ? (
                <>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">宽高比</label>
                    <select value={params.aspect_ratio || '1:1'}
                      onChange={(e) => setParams({ ...params, aspect_ratio: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="1:1">1:1（正方形）</option>
                      <option value="16:9">16:9（横版）</option>
                      <option value="9:16">9:16（竖版）</option>
                      <option value="4:3">4:3</option>
                      <option value="3:2">3:2</option>
                      <option value="2:3">2:3</option>
                      <option value="3:4">3:4</option>
                      <option value="4:5">4:5</option>
                      <option value="5:4">5:4</option>
                      <option value="21:9">21:9（超宽）</option>
                      <option value="9:21">9:21（超高）</option>
                      <option value="1:4">1:4</option>
                      <option value="4:1">4:1</option>
                      <option value="1:8">1:8</option>
                      <option value="8:1">8:1</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">分辨率</label>
                    <select value={params.image_size || '1K'}
                      onChange={(e) => setParams({ ...params, image_size: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="1K">1K</option>
                      <option value="2K">2K</option>
                      <option value="4K">4K</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">生成张数</label>
                    <select value={params.n}
                      onChange={(e) => setParams({ ...params, n: Number(e.target.value) })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      {[1,2,3,4].map(v => (
                        <option key={v} value={v}>{v} 张</option>
                      ))}
                    </select>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">尺寸</label>
                    <select value={params.size}
                      onChange={(e) => setParams({ ...params, size: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="auto">自动（默认）</option>
                      <option value="1024x1024">1024×1024（正方形）</option>
                      <option value="1536x1024">1536×1024（横版）</option>
                      <option value="1024x1536">1024×1536（竖版）</option>
                      <option value="2048x2048">2048×2048（2K 方形 1:1）</option>
                      <option value="2048x1152">2048×1152（2K 横版 16:9）</option>
                      <option value="1152x2048">1152×2048（2K 竖版 9:16）</option>
                      <option value="3840x2160">3840×2160（4K 横版 16:9）</option>
                      <option value="2160x3840">2160×3840（4K 竖版 9:16）</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">生成张数</label>
                    <select value={params.n}
                      onChange={(e) => setParams({ ...params, n: Number(e.target.value) })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      {[1,2,3,4].map(v => (
                        <option key={v} value={v}>{v} 张</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">画质</label>
                    <select value={params.quality}
                      onChange={(e) => setParams({ ...params, quality: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="auto">自动</option>
                      <option value="high">高</option>
                      <option value="medium">中</option>
                      <option value="low">低</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">输出格式</label>
                    <select value={params.output_format}
                      onChange={(e) => setParams({ ...params, output_format: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="png">PNG</option>
                      <option value="jpeg">JPEG (更快)</option>
                      <option value="webp">WebP</option>
                    </select>
                  </div>
                  <div>
                    <label className={`block text-xs mb-1 ${params.output_format === 'png' ? 'text-apple-gray-medium' : 'text-apple-gray-dark'}`}>
                      压缩率 {params.output_format === 'png' ? '—' : params.output_compression}
                    </label>
                    <input type="range" min="0" max="100"
                      value={params.output_format === 'png' ? 100 : params.output_compression}
                      disabled={params.output_format === 'png'}
                      onChange={(e) => setParams({ ...params, output_compression: Number(e.target.value) })}
                      className={`w-full ${params.output_format === 'png' ? 'opacity-30 cursor-not-allowed' : ''}`} />
                    <div className="flex justify-between text-[10px] text-apple-gray-dark">
                      <span>0</span>
                      <span className={params.output_format === 'png' ? 'opacity-60' : ''}>
                        {params.output_format === 'png' ? 'PNG 不支持压缩' : '(仅 JPEG/WebP 生效)'}
                      </span>
                      <span>100</span>
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-apple-gray-dark mb-1">内容审核</label>
                    <select value={params.moderation}
                      onChange={(e) => setParams({ ...params, moderation: e.target.value })}
                      className="glass-input w-full px-3 py-2 text-sm">
                      <option value="auto">自动</option>
                      <option value="low">宽松</option>
                    </select>
                  </div>
                  {mode === 'img2img' && (
                    <div>
                      <label className="block text-xs text-apple-gray-dark mb-1">背景模式</label>
                      <select value={params.background || 'auto'}
                        onChange={(e) => setParams({ ...params, background: e.target.value })}
                        className="glass-input w-full px-3 py-2 text-sm">
                        <option value="auto">自动</option>
                        <option value="opaque">不透明</option>
                      </select>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-sm animate-fade-in">
            {error}
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={loading || !prompt.trim()}
          className="btn-primary w-full py-3.5 text-base"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              生成中...
            </span>
          ) : (
            '生成'
          )}
        </button>
      </div>

      <div className="flex-1 glass p-1.5 flex flex-col min-w-[400px]">
        <div className="flex-1 rounded-xl overflow-hidden bg-black/[0.02]">
          {mode === 'img2img' && resultUrls.length === 0 ? (
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`w-full h-full flex flex-col items-center justify-center p-6 gap-4 transition-all ${isDragging ? 'border-2 border-dashed border-blue-400 rounded-xl bg-blue-50/30' : ''}`}
            >
              <div className="flex flex-wrap gap-3 justify-center">
                {sourceFiles.map((file, idx) => (
                  <div key={idx} className="relative group">
                    <img
                      src={URL.createObjectURL(file)}
                      alt={`参考图 ${idx + 1}`}
                      className="w-32 h-32 object-cover rounded-xl border border-white/20 shadow-sm"
                    />
                    <button
                      onClick={() => setSourceFiles(sourceFiles.filter((_, i) => i !== idx))}
                      className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow"
                    >
                      ×
                    </button>
                    <span className="absolute bottom-1 left-1 text-[10px] bg-black/60 text-white px-1.5 rounded">
                      {idx + 1}/{sourceFiles.length}
                    </span>
                  </div>
                ))}
              </div>
              {sourceFiles.length < 4 && (
                <label className={`cursor-pointer glass px-5 py-3 rounded-xl text-sm font-medium transition-all hover:scale-[1.02] ${sourceFiles.length === 0 ? 'text-apple-blue' : 'text-apple-gray-dark'}`}>
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => {
                      const files = Array.from(e.target.files || [])
                      setSourceFiles((prev) => prev.concat(files).slice(0, 4))
                    }}
                  />
                  {isDragging ? '释放以添加参考图' : sourceFiles.length === 0 ? '拖拽图片到此处或点击上传（最多4张）' : '+ 添加更多'}
                </label>
              )}
              {sourceFiles.length > 0 && (
                <button
                  onClick={() => setSourceFiles([])}
                  className="text-xs text-apple-gray-medium hover:text-red-500 transition-colors"
                >
                  清空全部
                </button>
              )}
              {toastMsg && (
                <div className="absolute bottom-4 bg-black/80 text-white text-xs px-3 py-1.5 rounded-lg animate-fade-in">
                  {toastMsg}
                </div>
              )}
            </div>
          ) : resultUrls.length > 1 ? (
            <div className="w-full h-full flex flex-col animate-fade-in">
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-xs text-apple-gray-dark">共 {resultUrls.length} 张</span>
                <div className="flex gap-2">
                  <button onClick={handleClearResult} className="text-xs text-apple-gray-medium hover:text-red-500 transition-colors">清除全部</button>
                </div>
              </div>
              <div className="flex-1 overflow-auto px-3 pb-3">
                <div className="grid grid-cols-2 gap-2">
                  {resultUrls.map((url, idx) => (
                    <button
                      key={idx}
                      onClick={() => { setLightboxIndex(idx) }}
                      className="relative aspect-square rounded-xl overflow-hidden group cursor-pointer"
                    >
                      <img src={url} alt={`生成 ${idx + 1}`} className="w-full h-full object-cover" />
                      <span className="absolute top-1.5 left-1.5 text-[10px] bg-black/60 text-white px-1.5 rounded">#{idx + 1}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : mode === 'txt2vid' && resultUrls.length === 1 ? (
            <div className="w-full h-full flex items-center justify-center">
              <video src={resultUrls[0]} controls className="max-w-full max-h-full rounded-xl" />
            </div>
          ) : (
            <ImagePreview imageUrl={resultUrls[0] || null} onClear={handleClearResult} />
          )}
        </div>
      </div>
      {lightboxIndex >= 0 && resultUrls.length > 0 && lightboxIndex < resultUrls.length && (
        <Lightbox
          images={resultUrls}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
          onNavigate={setLightboxIndex}
        />
      )}
    </div>
  )
}
