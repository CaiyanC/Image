import { useState, useEffect, useCallback } from 'react'
import { api } from '../services/api'
import type { GenerationRecord, GenerationStats } from '../types'
import { useAuthStore } from '../store/authStore'
import Lightbox from '../components/Lightbox'
import { SecureImage, SecureVideo } from '../components/SecureFile'

export default function History() {
  const [records, setRecords] = useState<GenerationRecord[]>([])
  const [stats, setStats] = useState<GenerationStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)
  const [selected, setSelected] = useState<GenerationRecord | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [isAdminView, setIsAdminView] = useState(false)
  const [lightboxImages, setLightboxImages] = useState<string[]>([])
  const [lightboxIndex, setLightboxIndex] = useState(-1)
  const user = useAuthStore((state) => state.user)
  const isAdmin = useAuthStore((s) => s.isManagement)

  const loadHistory = useCallback(async () => {
    setLoading(true)
    try {
      let data: GenerationRecord[]
      if (isAdmin && isAdminView) {
        data = (await api.history.adminList(0, 200, searchQuery || undefined, dateFrom || undefined, dateTo || undefined)) as GenerationRecord[]
      } else {
        data = (await api.history.list(0, 200, searchQuery || undefined, dateFrom || undefined, dateTo || undefined)) as GenerationRecord[]
      }
      setRecords(data)
    } catch (err) {
      console.error('Failed to load history', err)
    } finally {
      setLoading(false)
    }
  }, [searchQuery, dateFrom, dateTo, isAdmin, isAdminView])

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const data = (await api.history.stats()) as GenerationStats
      setStats(data)
    } catch (err) {
      console.error('Failed to load stats', err)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHistory()
    loadStats()
  }, [loadHistory, loadStats])

  async function handleDelete(id: string) {
    try {
      await api.history.delete(id)
      setRecords((prev) => prev.filter((r) => r.id !== id))
      if (selected?.id === id) setSelected(null)
      loadStats()
    } catch (err) {
      console.error('Failed to delete', err)
    }
  }

  const typeLabels: Record<string, string> = {
    txt2img: '文生图',
    img2img: '图生图',
    txt2vid: '文生视频',
  }

  const statusLabels: Record<string, { text: string; className: string }> = {
    completed: { text: '已完成', className: 'bg-green-100 text-green-700' },
    failed: { text: '失败', className: 'bg-red-100 text-red-600' },
    processing: { text: '处理中', className: 'bg-blue-100 text-blue-600' },
    pending: { text: '等待中', className: 'bg-gray-100 text-gray-600' },
  }

  const qualityLabels: Record<string, string> = {
    low: '低',
    medium: '中',
    high: '高',
    auto: '自动',
  }

  const formatParams = (params: Record<string, unknown>) => {
    const displayParams: { label: string; value: string }[] = []
    
    if (params.size) displayParams.push({ label: '尺寸', value: String(params.size) })
    if (params.n) displayParams.push({ label: '数量', value: String(params.n) })
    if (params.quality) displayParams.push({ label: '质量', value: qualityLabels[String(params.quality)] || String(params.quality) })
    if (params.output_format) displayParams.push({ label: '格式', value: String(params.output_format).toUpperCase() })
    if (params.background) displayParams.push({ label: '背景', value: String(params.background) })
    
    return displayParams.length > 0 ? displayParams : null
  }

  const handleSearch = () => {
    loadHistory()
  }

  const handleReset = () => {
    setSearchQuery('')
    setDateFrom('')
    setDateTo('')
    loadHistory()
  }

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text tracking-tight">生成历史</h1>
        {isAdmin && (
          <button
            onClick={() => {
              setIsAdminView(!isAdminView)
              setSelected(null)
            }}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              isAdminView
                ? 'bg-blue-500 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {isAdminView ? '查看我的记录' : '查看全部记录'}
          </button>
        )}
      </div>

      {stats && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="glass rounded-xl p-4">
            <div className="text-sm text-apple-gray-medium mb-1">总生成次数</div>
            <div className="text-3xl font-bold text-apple-text">{stats.total}</div>
          </div>
          <div className="glass rounded-xl p-4">
            <div className="text-sm text-apple-gray-medium mb-1">文生图</div>
            <div className="text-3xl font-bold text-blue-600">{stats.by_type.txt2img}</div>
          </div>
          <div className="glass rounded-xl p-4">
            <div className="text-sm text-apple-gray-medium mb-1">图生图</div>
            <div className="text-3xl font-bold text-purple-600">{stats.by_type.img2img}</div>
          </div>
          <div className="glass rounded-xl p-4">
            <div className="text-sm text-apple-gray-medium mb-1">成功率</div>
            <div className="text-3xl font-bold text-green-600">{stats.success_rate}%</div>
          </div>
        </div>
      )}

      <div className="glass rounded-xl p-4 mb-6">
        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex-1 min-w-[200px]">
            <label className="text-xs font-medium text-apple-gray-dark block mb-1.5">搜索提示词</label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="输入关键词搜索..."
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="min-w-[140px]">
            <label className="text-xs font-medium text-apple-gray-dark block mb-1.5">日期从</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <div className="min-w-[140px]">
            <label className="text-xs font-medium text-apple-gray-dark block mb-1.5">日期到</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
          <div className="flex gap-2 pt-5">
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors"
            >
              搜索
            </button>
            <button
              onClick={handleReset}
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
            >
              重置
            </button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 animate-pulse-soft text-apple-gray-medium">加载中...</div>
      ) : records.length === 0 ? (
        <div className="glass p-12 text-center">
          <svg className="w-16 h-16 mx-auto mb-4 text-apple-gray-medium/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={0.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.41a2.25 2.25 0 013.182 0l2.909 2.91m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
          </svg>
          <p className="text-apple-gray-medium">暂无生成记录</p>
          <p className="text-sm text-apple-gray-medium/60 mt-1">开始创作后，结果将显示在这里</p>
        </div>
      ) : (
        <div className="grid grid-cols-[280px_1fr] gap-4">
          <div className="glass divide-y divide-black/5 max-h-[calc(100vh-10rem)] overflow-y-auto scrollbar-thin rounded-xl">
            {records.map((record) => (
              <button
                key={record.id}
                onClick={() => setSelected(record)}
                className={`w-full text-left p-4 transition-colors duration-150 hover:bg-black/[0.02] ${
                  selected?.id === record.id ? 'bg-blue-50/50' : ''
                }`}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-black/5 text-apple-gray-dark">
                    {typeLabels[record.type] || record.type}
                  </span>
                  {statusLabels[record.status] && (
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusLabels[record.status].className}`}>
                      {statusLabels[record.status].text}
                    </span>
                  )}
                  {record.result_images && record.result_images.length > 1 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-purple-100 text-purple-600">
                      {record.result_images.length} 张图
                    </span>
                  )}
                </div>
                <p className="text-sm text-apple-text line-clamp-2 mb-1">{record.prompt}</p>
                <p className="text-xs text-apple-gray-medium">
                  {new Date(record.created_at).toLocaleString('zh-CN')}
                </p>
              </button>
            ))}
          </div>

          <div className="glass rounded-xl h-[calc(100vh-10rem)] overflow-y-auto scrollbar-thin">
            {selected ? (
              <div className="p-6 animate-fade-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold text-apple-text">详情</h2>
                  <button onClick={() => handleDelete(selected.id)} className="text-sm text-red-500 hover:text-red-600 transition-colors font-medium">删除</button>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-medium text-apple-gray-dark">提示词</label>
                    <p className="text-sm text-apple-text mt-1 bg-black/[0.02] rounded-xl p-3">{selected.prompt}</p>
                  </div>

                  {selected.negative_prompt && (
                    <div>
                      <label className="text-xs font-medium text-apple-gray-dark">反向提示词</label>
                      <p className="text-sm text-apple-text mt-1 bg-black/[0.02] rounded-xl p-3">{selected.negative_prompt}</p>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-apple-gray-dark">模型</label>
                      <p className="text-sm text-apple-text mt-1">{selected.model_name}</p>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-apple-gray-dark">状态</label>
                      <p className={`text-sm mt-1 ${statusLabels[selected.status]?.className.replace('bg-', 'text-').replace('-100', '-600') || 'text-apple-text'}`}>
                        {statusLabels[selected.status]?.text || selected.status}
                      </p>
                    </div>
                  </div>

                  {selected.parameters && formatParams(selected.parameters) && (
                    <div>
                      <label className="text-xs font-medium text-apple-gray-dark">参数设置</label>
                      <div className="mt-1 grid grid-cols-2 gap-2">
                        {formatParams(selected.parameters)?.map((param, index) => (
                          <div key={index} className="bg-black/[0.02] rounded-lg px-3 py-2">
                            <span className="text-xs text-apple-gray-medium">{param.label}</span>
                            <p className="text-sm text-apple-text">{param.value}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {(selected.result_images && selected.result_images.length > 0 || selected.result_image_path || selected.result_video_path) && (
                    <div>
                      <label className="text-xs font-medium text-apple-gray-dark mb-2 block">生成结果</label>
                      {selected.result_video_path ? (
                        <SecureVideo src={selected.result_video_path} controls className="w-full rounded-xl" />
                      ) : selected.result_images && selected.result_images.length > 1 ? (
                        <div className="grid grid-cols-2 gap-2">
                          {selected.result_images.map((url: string, idx: number) => (
                            <button
                              key={idx}
                              onClick={() => { setLightboxImages(selected.result_images || []); setLightboxIndex(idx) }}
                              className="relative aspect-square rounded-xl overflow-hidden cursor-pointer"
                            >
                              <SecureImage src={url} alt={`result ${idx + 1}`} className="w-full h-full object-cover" />
                              <span className="absolute top-1.5 left-1.5 text-[10px] bg-black/60 text-white px-1.5 rounded">#{idx + 1}</span>
                            </button>
                          ))}
                        </div>
                      ) : selected.result_images && selected.result_images.length === 1 ? (
                        <SecureImage src={selected.result_images[0]} alt="Result" className="w-full rounded-xl" />
                      ) : (
                        <SecureImage src={selected.result_image_path || ''} alt="Result" className="w-full rounded-xl" />
                      )}
                    </div>
                  )}

                  {selected.error_message && (
                    <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-sm">
                      {selected.error_message}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center text-apple-gray-medium text-sm">
                选择一条记录查看详情
              </div>
            )}
          </div>
        </div>
      )}
      {lightboxImages.length > 0 && lightboxIndex >= 0 && lightboxIndex < lightboxImages.length && (
        <Lightbox
          images={lightboxImages}
          currentIndex={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
          onNavigate={setLightboxIndex}
        />
      )}
    </div>
  )
}
