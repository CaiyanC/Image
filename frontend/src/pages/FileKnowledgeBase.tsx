import { useEffect, useMemo, useState, type ChangeEvent, type DragEvent } from 'react'
import type { ProductListItem } from '../types'
import { api } from '../services/api'
import {
  getSelectedSkuSet,
  normalizeSkuText,
  parseManualSkuInput,
  useFileKnowledgeStore,
} from '../store/fileKnowledgeStore'

const MAX_FILE_SIZE = 20 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['txt', 'docx', 'pptx', 'xlsx', 'pdf']
const SEARCH_DELAY_MS = 250

export default function FileKnowledgeBase() {
  const files = useFileKnowledgeStore((state) => state.files)
  const skuQuery = useFileKnowledgeStore((state) => state.skuQuery)
  const selectedSkus = useFileKnowledgeStore((state) => state.selectedSkus)
  const results = useFileKnowledgeStore((state) => state.results)
  const addFiles = useFileKnowledgeStore((state) => state.addFiles)
  const removeFile = useFileKnowledgeStore((state) => state.removeFile)
  const clearFiles = useFileKnowledgeStore((state) => state.clearFiles)
  const setSkuQuery = useFileKnowledgeStore((state) => state.setSkuQuery)
  const addSku = useFileKnowledgeStore((state) => state.addSku)
  const removeSku = useFileKnowledgeStore((state) => state.removeSku)
  const setResults = useFileKnowledgeStore((state) => state.setResults)
  const resetDraft = useFileKnowledgeStore((state) => state.resetDraft)

  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [skuSearching, setSkuSearching] = useState(false)
  const [skuSuggestions, setSkuSuggestions] = useState<ProductListItem[]>([])
  const [skuSearchError, setSkuSearchError] = useState('')
  const [dragging, setDragging] = useState(false)

  const selectedSkuSet = useMemo(() => getSelectedSkuSet(selectedSkus), [selectedSkus])

  useEffect(() => {
    const query = skuQuery.trim()
    if (!query) {
      setSkuSuggestions([])
      setSkuSearchError('')
      setSkuSearching(false)
      return
    }

    let active = true
    const timer = window.setTimeout(async () => {
      setSkuSearching(true)
      setSkuSearchError('')
      try {
        const response = await api.products.search(query)
        if (!active) return
        setSkuSuggestions((response.items || []).slice(0, 8))
      } catch (err) {
        if (!active) return
        setSkuSuggestions([])
        setSkuSearchError(err instanceof Error ? err.message : '搜索失败')
      } finally {
        if (active) setSkuSearching(false)
      }
    }, SEARCH_DELAY_MS)

    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [skuQuery])

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFiles = Array.from(event.target.files || [])
    if (nextFiles.length > 0) {
      addFiles(nextFiles)
      setError('')
    }
    event.currentTarget.value = ''
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const nextFiles = Array.from(event.dataTransfer.files || [])
    if (nextFiles.length > 0) {
      addFiles(nextFiles)
      setError('')
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(true)
  }

  function handleDragLeave() {
    setDragging(false)
  }

  function handleAddManualSku() {
    const text = skuQuery.trim()
    if (!text) return
    const items = parseManualSkuInput(text)
    if (!items.length) return
    for (const sku of items) {
      addSku({ sku: normalizeSkuText(sku), label: normalizeSkuText(sku) })
    }
    setSkuQuery('')
    setSkuSuggestions([])
    setSkuSearchError('')
  }

  function handleAddSku(item: ProductListItem) {
    const sku = normalizeSkuText(item.sku)
    const label = item.product_name_cn || item.product_name_en || sku
    addSku({ sku, label })
    setSkuQuery('')
    setSkuSuggestions([])
    setSkuSearchError('')
  }

  async function handleUpload() {
    setError('')
    setResults([])

    if (!files.length) {
      setError('请先选择要上传的文件')
      return
    }

    const invalidFile = files.find((file) => !isAllowedFile(file.name))
    if (invalidFile) {
      setError('仅支持 txt、docx、pptx、xlsx、pdf 文件')
      return
    }

    const oversized = files.find((file) => file.size > MAX_FILE_SIZE)
    if (oversized) {
      setError(`文件 ${oversized.name} 超过 20MB，不能上传`)
      return
    }

    setUploading(true)
    try {
      const response = await api.knowledgeBase.uploadFiles(
        files,
        selectedSkus.map((item) => item.sku),
      )
      setResults(response.items || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败，请稍后重试')
    } finally {
      setUploading(false)
    }
  }

  function handleResetDraft() {
    resetDraft()
    setError('')
    setSkuSearchError('')
    setSkuSuggestions([])
    setDragging(false)
  }

  return (
    <div className="mx-auto max-w-6xl p-4">
      <div className="mb-5 overflow-hidden rounded-[2rem] border border-white/70 bg-white/60 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur-xl">
        <p className="text-xs font-black uppercase tracking-[0.24em] text-teal-700/70">资料维护</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">产品资料库</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-apple-gray-dark">
          用于上传产品说明书、使用手册和资料附件。上传后系统会自动解析并进入知识库流程，后续可供智能客服检索使用。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-4">
          <div className="glass rounded-3xl p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-black text-apple-text">上传文件</h2>
                <p className="mt-1 text-sm text-apple-gray-medium">支持批量选择文件，单个文件不超过 20MB。</p>
              </div>
              <button
                type="button"
                onClick={handleResetDraft}
                className="rounded-full bg-white/70 px-4 py-2 text-xs font-bold text-apple-gray-dark hover:bg-white"
              >
                清空草稿
              </button>
            </div>

            <div
              className={`mt-5 rounded-3xl border-2 border-dashed p-6 transition-colors ${
                dragging ? 'border-teal-400 bg-teal-50/70' : 'border-black/10 bg-white/55'
              }`}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
            >
              <input
                id="file-knowledge-input"
                type="file"
                accept=".txt,.docx,.pptx,.xlsx,.pdf"
                multiple
                onChange={handleFileChange}
                className="hidden"
              />
              <div className="flex flex-col items-center justify-center gap-4 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-600/10 text-teal-700">
                  <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                </div>
                <div>
                  <p className="text-base font-bold text-apple-text">拖拽文件到这里，或点击选择文件</p>
                  <p className="mt-1 text-sm text-apple-gray-medium">
                    支持 txt、docx、pptx、xlsx、pdf，可一次选择多个文件
                  </p>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <label
                    htmlFor="file-knowledge-input"
                    className="btn-primary cursor-pointer px-5 py-2.5 text-sm"
                  >
                    选择文件
                  </label>
                  <span className="text-sm text-apple-gray-medium">单文件大小限制：20MB</span>
                </div>
              </div>
            </div>

            {files.length > 0 && (
              <div className="mt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-apple-text">已选择文件</span>
                  <button type="button" onClick={clearFiles} className="text-xs font-semibold text-teal-700 hover:underline">
                    清空文件
                  </button>
                </div>
                <div className="space-y-2">
                  {files.map((file, index) => (
                    <div key={`${file.name}-${index}`} className="flex items-center justify-between rounded-2xl bg-white/70 px-4 py-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-apple-text">{file.name}</p>
                        <p className="mt-0.5 text-xs text-apple-gray-medium">
                          {formatSize(file.size)} · {getFileSuffix(file.name)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFile(index)}
                        className="ml-3 rounded-full px-3 py-1 text-xs font-semibold text-red-600 hover:bg-red-50"
                      >
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="glass rounded-3xl p-5">
            <h2 className="text-lg font-black text-apple-text">上传说明</h2>
            <ul className="mt-3 space-y-2 text-sm leading-6 text-apple-gray-dark">
              <li>1. 可批量上传多个产品资料文件。</li>
              <li>2. 同一份文件重复上传时，系统会自动复用已有文档。</li>
              <li>3. 上传成功后，资料会继续进入向量化流程。</li>
            </ul>
          </div>
        </section>

        <aside className="space-y-4">
          <div className="glass rounded-3xl p-5">
            <h2 className="text-lg font-black text-apple-text">关联 SKU</h2>
            <p className="mt-1 text-sm text-apple-gray-medium">可按产品名或 SKU 搜索选择，支持多选。</p>

            <div className="mt-4">
              <div className="relative">
                <input
                  value={skuQuery}
                  onChange={(event) => setSkuQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      handleAddManualSku()
                    }
                  }}
                  className="glass-input w-full px-4 py-3 text-sm"
                  placeholder="搜索产品名或 SKU，回车可直接添加"
                />
                <div className="mt-2 text-xs text-apple-gray-medium">已选 {selectedSkus.length} 个 SKU</div>

                {(skuSearching || skuSuggestions.length > 0 || skuSearchError) && (
                  <div className="absolute left-0 right-0 top-[calc(100%+8px)] z-20 max-h-72 overflow-auto rounded-2xl border border-black/10 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.12)]">
                    {skuSearching && <div className="px-4 py-3 text-sm text-apple-gray-medium">搜索中...</div>}
                    {!skuSearching && skuSearchError && <div className="px-4 py-3 text-sm text-red-600">{skuSearchError}</div>}
                    {!skuSearching && !skuSearchError && skuSuggestions.length === 0 && skuQuery.trim() && (
                      <div className="px-4 py-3 text-sm text-apple-gray-medium">
                        未找到匹配结果，回车可直接按当前内容添加。
                      </div>
                    )}
                    {!skuSearching &&
                      !skuSearchError &&
                      skuSuggestions.map((item) => {
                        const sku = normalizeSkuText(item.sku)
                        const label = item.product_name_cn || item.product_name_en || sku
                        const disabled = selectedSkuSet.has(sku)
                        return (
                          <button
                            key={sku}
                            type="button"
                            onClick={() => handleAddSku(item)}
                            disabled={disabled}
                            className={`block w-full border-b border-black/5 px-4 py-3 text-left transition-colors last:border-b-0 ${
                              disabled ? 'cursor-not-allowed bg-teal-50/60' : 'hover:bg-teal-50/80'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-apple-text">{label}</p>
                                <p className="mt-0.5 text-xs text-apple-gray-medium">SKU: {sku}</p>
                              </div>
                              <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-xs font-bold text-teal-700">
                                {disabled ? '已添加' : '选择'}
                              </span>
                            </div>
                          </button>
                        )
                      })}
                  </div>
                )}
              </div>
            </div>

            {selectedSkus.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {selectedSkus.map((item) => (
                  <button
                    key={item.sku}
                    type="button"
                    onClick={() => removeSku(item.sku)}
                    className="group rounded-full bg-teal-50 px-3 py-1 text-left text-xs font-bold text-teal-700 transition-colors hover:bg-teal-100"
                  >
                    <span className="block max-w-48 truncate">{item.label}</span>
                    <span className="block text-[10px] font-semibold text-teal-600/80">{item.sku} · 点击移除</span>
                  </button>
                ))}
              </div>
            )}

            <div className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              这些 SKU 会写入关联关系，方便后续按产品查看资料。
            </div>
          </div>

          <div className="glass rounded-3xl p-5">
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={handleUpload}
                disabled={uploading}
                className="btn-primary px-5 py-2.5 text-sm disabled:opacity-50"
              >
                {uploading ? '上传中...' : '上传并入库'}
              </button>
              <span className="text-sm text-apple-gray-medium">
                {files.length ? `已选择 ${files.length} 个文件` : '未选择文件'}
              </span>
            </div>
          </div>

          {results.length > 0 && (
            <div className="glass rounded-3xl p-5">
              <h2 className="text-lg font-black text-apple-text">上传结果</h2>
              <div className="mt-4 space-y-3">
                {results.map((item) => (
                  <div key={item.document_id} className="rounded-2xl bg-white/65 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-apple-text">{item.file_name}</p>
                        <p className="mt-0.5 text-xs text-apple-gray-medium">文档 ID: {item.document_id}</p>
                      </div>
                      <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-bold ${uploadResultBadgeClass(item)}`}>
                        {uploadResultBadgeText(item)}
                      </span>
                    </div>

                    {item.duplicate && (
                      <div className="mt-3 rounded-2xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-800">
                        {item.message || uploadResultMessage(item)}
                      </div>
                    )}

                    {item.message && !item.duplicate && (
                      <div className="mt-3 rounded-2xl border border-teal-100 bg-teal-50 px-4 py-3 text-sm text-teal-800">
                        {item.message}
                      </div>
                    )}

                    <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                      <InfoRow label="文件类型" value={item.file_type} />
                      <InfoRow label="解析状态" value={item.parse_status} />
                      <InfoRow label="分片数量" value={String(item.chunk_count)} />
                      <InfoRow label="关联 SKU" value={(item.related_skus || []).join(', ') || '-'} />
                      <InfoRow label="重复文件" value={item.duplicate ? '是' : '否'} />
                      {item.reused_document_id && <InfoRow label="复用文档 ID" value={item.reused_document_id} />}
                      {item.parse_error && <InfoRow label="错误信息" value={item.parse_error} tone="danger" />}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

function isAllowedFile(name: string): boolean {
  const suffix = name.split('.').pop()?.toLowerCase() || ''
  return ALLOWED_EXTENSIONS.includes(suffix)
}

function getFileSuffix(name: string): string {
  return name.split('.').pop()?.toUpperCase() || '-'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function uploadResultBadgeText(item: { duplicate: boolean; parse_status: string }): string {
  if (item.parse_status === 'processing') return '处理中'
  if (item.parse_status === 'error') return '解析失败'
  return item.duplicate ? '已复用' : '已入库'
}

function uploadResultBadgeClass(item: { duplicate: boolean; parse_status: string }): string {
  if (item.parse_status === 'processing') return 'bg-blue-50 text-blue-700'
  if (item.parse_status === 'error') return 'bg-red-50 text-red-700'
  return item.duplicate ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'
}

function uploadResultMessage(item: { parse_status: string }): string {
  if (item.parse_status === 'processing') return '该文件正在处理中'
  if (item.parse_status === 'error') return '文件解析失败，请查看错误信息'
  return '文件已存在，已复用'
}

function InfoRow({
  label,
  value,
  tone = 'normal',
}: {
  label: string
  value: string
  tone?: 'normal' | 'danger'
}) {
  return (
    <div className="rounded-2xl bg-white/60 px-4 py-3">
      <div className="text-xs font-bold uppercase tracking-[0.14em] text-apple-gray-medium">{label}</div>
      <div className={`mt-1 break-all text-sm font-medium ${tone === 'danger' ? 'text-red-700' : 'text-apple-text'}`}>
        {value || '-'}
      </div>
    </div>
  )
}
