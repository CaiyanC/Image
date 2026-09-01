import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { SecureImage, SecureVideo } from '../components/SecureFile'
import type { AssetTags, AssetTaxonomy, ProductAsset, ProductListItem } from '../types'
import {
  AMAZON_SLOTS,
  ASSET_CATEGORIES,
  MULTI_ANGLE_SLOTS,
  PLATFORM_DETAIL_SLOTS,
  STATUS_OPTIONS,
  TAG_DIMENSIONS,
  TAG_PRESETS,
  getCategoryName,
  getMaterialType,
  getSubCategories,
} from './assetLibraryConfig'
import {
  addTag,
  buildNamingFormat,
  cloneTags,
  getMaterialColor,
  removeTag,
  sortAssets,
} from './assetLibraryHelpers'

type EditForm = Partial<ProductAsset>

export default function AssetLibrary() {
  const [products, setProducts] = useState<ProductListItem[]>([])
  const [searchResults, setSearchResults] = useState<ProductListItem[]>([])
  const initialSku = new URLSearchParams(window.location.search).get('sku') || ''
  const [searchSku, setSearchSku] = useState(initialSku)
  const [selectedSku, setSelectedSku] = useState(initialSku)
  const [selectedProductName, setSelectedProductName] = useState('')
  const [activeCategory, setActiveCategory] = useState('01')
  const [activeSubCategory, setActiveSubCategory] = useState<string | null>(null)
  const [assets, setAssets] = useState<ProductAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [editingAsset, setEditingAsset] = useState<ProductAsset | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({})
  const [lightboxAsset, setLightboxAsset] = useState<ProductAsset | null>(null)
  const [editingTagsAssetId, setEditingTagsAssetId] = useState<string | null>(null)
  const [customTagInputs, setCustomTagInputs] = useState<Record<string, string>>({})
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set())
  const [batchTagsOpen, setBatchTagsOpen] = useState(false)
  const [pendingBatchTags, setPendingBatchTags] = useState<Array<{ key: string; tag: string }>>([])
  const [batchCustomInputs, setBatchCustomInputs] = useState<Record<string, string>>({})
  const [confirmClearOpen, setConfirmClearOpen] = useState(false)
  const [promptText, setPromptText] = useState('')
  const [taxonomy, setTaxonomy] = useState<AssetTaxonomy | null>(null)
  const [tagPresets, setTagPresets] = useState(TAG_PRESETS)

  useEffect(() => {
    api.products.list(0, 100).then(result => setProducts(result.items)).catch(() => setProducts([]))
  }, [])

  useEffect(() => {
    if (!selectedSku) {
      setSelectedProductName('')
      return
    }
    const localProduct = products.find(product => product.sku === selectedSku)
    if (localProduct) {
      setSelectedProductName(localProduct.product_name_cn || localProduct.product_name_en || '')
      return
    }
    let cancelled = false
    api.products.getBySku(selectedSku)
      .then(product => {
        if (!cancelled) setSelectedProductName(product.product_name_cn || product.product_name_en || '')
      })
      .catch(() => {
        if (!cancelled) setSelectedProductName('')
      })
    return () => {
      cancelled = true
    }
  }, [products, selectedSku])

  useEffect(() => {
    api.assets.taxonomy().then(data => {
      setTaxonomy(data)
      setTagPresets(current => {
        const next = { ...current }
        for (const [key, dimension] of Object.entries(data.dimensions)) next[key] = dimension.values
        return next
      })
    }).catch(() => {
      // Keep bundled presets as a safe UI fallback if the API is unavailable.
    })
  }, [])

  useEffect(() => {
    const keyword = searchSku.trim()
    if (!keyword) {
      setSearchResults([])
      return
    }
    const timer = window.setTimeout(() => {
      api.products.search(keyword)
        .then(result => setSearchResults(result.items))
        .catch(() => setSearchResults([]))
    }, 200)
    return () => window.clearTimeout(timer)
  }, [searchSku])

  const loadAssets = useCallback(async () => {
    if (!selectedSku) {
      setAssets([])
      return
    }
    setLoading(true)
    try {
      const result = await api.assets.list(selectedSku)
      setAssets(result)
    } catch {
      // Never leave the previous SKU's assets visible after a failed reload.
      setAssets([])
    } finally {
      setLoading(false)
    }
  }, [selectedSku])

  useEffect(() => {
    loadAssets()
  }, [loadAssets])

  const filteredProducts = useMemo(() => {
    const keyword = searchSku.trim().toLowerCase()
    const source = searchResults.length > 0 ? searchResults : products
    if (!keyword) return source.slice(0, 20)
    return source.filter(product => {
      return (
        product.sku.toLowerCase().includes(keyword) ||
        (product.product_name_cn || '').toLowerCase().includes(keyword) ||
        (product.product_name_en || '').toLowerCase().includes(keyword)
      )
    }).slice(0, 30)
  }, [products, searchResults, searchSku])

  const categoryAssets = useMemo(() => {
    const filtered = assets.filter(asset => {
      if (asset.category_code !== activeCategory) return false
      if (activeSubCategory && asset.sub_category !== activeSubCategory) return false
      return true
    })
    return sortAssets(filtered, activeSubCategory)
  }, [assets, activeCategory, activeSubCategory])

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const asset of assets) counts[asset.category_code] = (counts[asset.category_code] || 0) + 1
    return counts
  }, [assets])

  const subCategories = getSubCategories(activeCategory)
  const activeCategoryName = getCategoryName(activeCategory)
  const activeMaterialType = getMaterialType(activeCategory, activeSubCategory)

  const handleSkuSelect = (sku: string) => {
    setSelectedSku(sku)
    setSearchSku(sku)
    setSearchResults([])
    setAssets([])
    setSelectedAssetIds(new Set())
    setUploadError('')
  }

  const uploadFiles = async (files: FileList | File[], materialOverride?: string, notesOverride?: string) => {
    if (!selectedSku) return
    const fileArray = Array.from(files)
    if (!fileArray.length) return
    setUploading(true)
    setUploadError('')
    try {
      const subCategory = activeCategory === '06' ? '视频' : activeSubCategory
      const materialType = activeCategory === '06' ? 'video' : materialOverride || activeMaterialType
      const response = await api.assets.upload(selectedSku, {
        files: fileArray,
        category_code: activeCategory,
        category_name: activeCategoryName,
        sub_category: subCategory,
        material_type: materialType,
        notes: notesOverride || undefined,
      })
      setAssets(prev => [...prev, ...response.items])
      setPromptText('')
    } catch (error) {
      // Upload failures used to become unhandled promise rejections while
      // the UI only stopped the spinner. Keep the selected SKU/assets intact
      // and show the server's actionable message to the operator.
      setUploadError(error instanceof Error ? error.message : '素材上传失败，请稍后重试')
    } finally {
      setUploading(false)
    }
  }

  const openEdit = (asset: ProductAsset) => {
    setEditingAsset(asset)
    setEditForm({ ...asset })
  }

  const saveEdit = async () => {
    if (!selectedSku || !editingAsset) return
    const updated = await api.assets.update(selectedSku, editingAsset.id, editForm)
    setAssets(prev => prev.map(asset => asset.id === updated.id ? updated : asset))
    setEditingAsset(null)
  }

  const deleteAsset = async (asset: ProductAsset) => {
    if (!selectedSku) return
    if (!window.confirm(`删除素材 ${buildNamingFormat(asset)}？`)) return
    await api.assets.delete(selectedSku, asset.id)
    setAssets(prev => prev.filter(item => item.id !== asset.id))
    setSelectedAssetIds(prev => {
      const next = new Set(prev)
      next.delete(asset.id)
      return next
    })
  }

  const persistTags = async (assetId: string, tags: AssetTags) => {
    if (!selectedSku) return
    const updated = await api.assets.updateTags(selectedSku, assetId, tags)
    setAssets(prev => prev.map(asset => asset.id === assetId ? updated : asset))
  }

  const handleAddTag = async (asset: ProductAsset, key: string, tag: string) => {
    const next = addTag(asset.tags, key, tag)
    setAssets(prev => prev.map(item => item.id === asset.id ? { ...item, tags: next } : item))
    await persistTags(asset.id, next)
  }

  const handleRemoveTag = async (asset: ProductAsset, key: string, tag: string) => {
    const next = removeTag(asset.tags, key, tag)
    setAssets(prev => prev.map(item => item.id === asset.id ? { ...item, tags: next } : item))
    await persistTags(asset.id, next)
  }

  const toggleSelect = (assetId: string) => {
    setSelectedAssetIds(prev => {
      const next = new Set(prev)
      if (next.has(assetId)) next.delete(assetId)
      else next.add(assetId)
      return next
    })
  }

  const selectAll = () => setSelectedAssetIds(new Set(categoryAssets.map(asset => asset.id)))
  const clearSelection = () => {
    setSelectedAssetIds(new Set())
    setBatchTagsOpen(false)
    setPendingBatchTags([])
  }

  const togglePendingTag = (key: string, tag: string) => {
    setPendingBatchTags(prev => {
      const exists = prev.some(item => item.key === key && item.tag === tag)
      return exists ? prev.filter(item => !(item.key === key && item.tag === tag)) : [...prev, { key, tag }]
    })
  }

  const commitBatchTags = async () => {
    if (!selectedSku || pendingBatchTags.length === 0) return
    for (const assetId of selectedAssetIds) {
      const asset = assets.find(item => item.id === assetId)
      if (!asset) continue
      let next = cloneTags(asset.tags)
      for (const item of pendingBatchTags) {
        next = addTag(next, item.key, item.tag)
      }
      setAssets(prev => prev.map(current => current.id === assetId ? { ...current, tags: next } : current))
      await api.assets.updateTags(selectedSku, assetId, next)
    }
    clearSelection()
  }

  const clearBatchTags = async () => {
    if (!selectedSku) return
    for (const assetId of selectedAssetIds) {
      await api.assets.updateTags(selectedSku, assetId, {})
      setAssets(prev => prev.map(asset => asset.id === assetId ? { ...asset, tags: {} } : asset))
    }
    setConfirmClearOpen(false)
    clearSelection()
  }

  const lightboxListRef = useRef(categoryAssets)
  useEffect(() => {
    lightboxListRef.current = categoryAssets
  }, [categoryAssets])
  useEffect(() => {
    if (!lightboxAsset) return
    const handleKey = (event: KeyboardEvent) => {
      const visibleAssets = lightboxListRef.current.filter(asset => asset.asset_type === 'image' || asset.asset_type === 'video')
      const index = visibleAssets.findIndex(asset => asset.id === lightboxAsset.id)
      if (event.key === 'ArrowLeft' && index > 0) setLightboxAsset(visibleAssets[index - 1])
      if (event.key === 'ArrowRight' && index < visibleAssets.length - 1) setLightboxAsset(visibleAssets[index + 1])
      if (event.key === 'Escape') setLightboxAsset(null)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [lightboxAsset])

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 pb-10 sm:px-6">
          <section className="glass px-5 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="eyebrow">L6 Asset Library</p>
            <h1 className="mt-1 text-2xl font-black text-apple-text">视觉素材库</h1>
          </div>
          <div className="w-full lg:w-[520px]">
            <label className="mb-1 block text-xs font-bold text-apple-gray-medium">SKU / 产品名称</label>
            <input
              className="glass-input h-11 w-full px-4 text-sm"
              value={searchSku}
              onChange={event => setSearchSku(event.target.value)}
              onKeyDown={event => {
                if (event.key !== 'Enter') return
                const exactMatch = filteredProducts.find(product => product.sku.toLowerCase() === searchSku.trim().toLowerCase())
                const firstMatch = exactMatch || filteredProducts[0]
                if (firstMatch) {
                  event.preventDefault()
                  handleSkuSelect(firstMatch.sku)
                }
              }}
              placeholder="搜索 SKU 后选择产品"
            />
            {searchSku && (
              <div className="mt-2 max-h-48 overflow-auto rounded-xl border border-black/5 bg-white/80 p-1 shadow-lg">
                {filteredProducts.map(product => (
                  <button
                    key={product.sku}
                    onClick={() => handleSkuSelect(product.sku)}
                    className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition hover:bg-teal-50 ${
                      selectedSku === product.sku ? 'bg-teal-100 text-teal-800' : 'text-apple-text'
                    }`}
                  >
                    <span className="font-black">{product.sku}</span>
                    <span className="ml-2 text-apple-gray-medium">{product.product_name_cn || product.product_name_en}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        {selectedSku && (
          <div
            data-testid="asset-selected-product"
            className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-teal-200 bg-teal-50/80 px-4 py-3 text-sm"
          >
            <span className="font-bold text-teal-700">当前素材范围</span>
            <span className="rounded-full bg-white px-3 py-1 font-black text-teal-900">SKU：{selectedSku}</span>
            {selectedProductName && <span className="font-bold text-teal-800">{selectedProductName}</span>}
            <button
              type="button"
              className="ml-auto rounded-full bg-white px-3 py-1 text-xs font-bold text-apple-gray-dark hover:bg-teal-100"
              onClick={() => {
                setSelectedSku('')
                setSearchSku('')
                setAssets([])
                setSelectedAssetIds(new Set())
              }}
            >
              更换 SKU
            </button>
          </div>
        )}
      </section>

      {!selectedSku ? (
        <section className="glass flex min-h-[360px] items-center justify-center p-8 text-center">
          <div>
            <div className="text-4xl">📦</div>
            <h2 className="mt-3 text-lg font-black">选择一个 SKU 开始管理素材</h2>
          </div>
        </section>
      ) : (
        <>
          <section className="glass p-3">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
              {ASSET_CATEGORIES.map(category => (
                <button
                  key={category.code}
                  onClick={() => {
                    setActiveCategory(category.code)
                    setActiveSubCategory(null)
                    setSelectedAssetIds(new Set())
                  }}
                  className={`rounded-xl border px-3 py-3 text-left transition ${
                    activeCategory === category.code
                      ? 'border-teal-300 bg-teal-50 text-teal-800'
                      : 'border-black/5 bg-white/55 text-apple-text hover:bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-lg">{category.icon}</span>
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs font-bold">{categoryCounts[category.code] || 0}</span>
                  </div>
                  <div className="mt-1 text-sm font-black">{category.name}</div>
                </button>
              ))}
            </div>
          </section>

          <section className="glass p-4">
            <div className="mb-4 flex flex-wrap gap-2">
              <button
                onClick={() => setActiveSubCategory(null)}
                className={`rounded-full px-3 py-1.5 text-sm font-bold ${!activeSubCategory ? 'bg-teal-600 text-white' : 'bg-white/70 text-apple-gray-dark'}`}
              >
                全部 ({assets.filter(asset => asset.category_code === activeCategory).length})
              </button>
              {subCategories.map(sub => (
                <button
                  key={`${sub.categoryCode}-${sub.name}`}
                  onClick={() => setActiveSubCategory(sub.name)}
                  className={`rounded-full px-3 py-1.5 text-sm font-bold ${activeSubCategory === sub.name ? 'bg-teal-600 text-white' : 'bg-white/70 text-apple-gray-dark'}`}
                >
                  {sub.name} ({assets.filter(asset => asset.category_code === activeCategory && asset.sub_category === sub.name).length})
                </button>
              ))}
            </div>

            <UploadArea
              activeCategory={activeCategory}
              activeSubCategory={activeSubCategory}
              uploading={uploading}
              promptText={promptText}
              setPromptText={setPromptText}
              uploadFiles={uploadFiles}
            />
            {uploadError && (
              <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-700">
                {uploadError}
              </div>
            )}

            {selectedAssetIds.size > 0 && (
              <BatchToolbar
                count={selectedAssetIds.size}
                total={categoryAssets.length}
                allSelected={selectedAssetIds.size === categoryAssets.length}
                onSelectAll={selectAll}
                onClearSelection={clearSelection}
                onOpenTags={() => setBatchTagsOpen(true)}
                onOpenClear={() => setConfirmClearOpen(true)}
              />
            )}

            {batchTagsOpen && (
              <BatchTagPanel
                pending={pendingBatchTags}
                customInputs={batchCustomInputs}
                setCustomInputs={setBatchCustomInputs}
                tagPresets={tagPresets}
                onToggle={togglePendingTag}
                onCommit={commitBatchTags}
                onCancel={() => setBatchTagsOpen(false)}
              />
            )}

            {confirmClearOpen && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4">
                <div className="text-sm font-black text-red-700">确认清除 {selectedAssetIds.size} 项素材的全部标签？</div>
                <div className="mt-3 flex gap-2">
                  <button className="rounded-full bg-red-600 px-4 py-2 text-sm font-bold text-white" onClick={clearBatchTags}>确认清除</button>
                  <button className="rounded-full bg-white px-4 py-2 text-sm font-bold" onClick={() => setConfirmClearOpen(false)}>取消</button>
                </div>
              </div>
            )}

            {loading ? (
              <div className="py-16 text-center text-sm font-bold text-apple-gray-medium">素材加载中...</div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
                {categoryAssets.map(asset => (
                  <AssetCard
                    key={asset.id}
                    asset={asset}
                    selected={selectedAssetIds.has(asset.id)}
                    editingTags={editingTagsAssetId === asset.id}
                    customInputs={customTagInputs}
                    setCustomInputs={setCustomTagInputs}
                    tagPresets={tagPresets}
                    onToggleSelect={() => toggleSelect(asset.id)}
                    onOpenLightbox={() => setLightboxAsset(asset)}
                    onEdit={() => openEdit(asset)}
                    onDelete={() => deleteAsset(asset)}
                    onToggleTags={() => setEditingTagsAssetId(editingTagsAssetId === asset.id ? null : asset.id)}
                    onAddTag={handleAddTag}
                    onRemoveTag={handleRemoveTag}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {editingAsset && (
        <EditModal
          asset={editingAsset}
          form={editForm}
          setForm={setEditForm}
          qualityStatuses={taxonomy?.quality_statuses || ['usable', 'pending_tagging', 'suspected_duplicate', 'invalid', 'archived']}
          duplicateStatuses={taxonomy?.duplicate_statuses || ['unique', 'cross_sku_reuse', 'suspected_duplicate']}
          onClose={() => setEditingAsset(null)}
          onSave={saveEdit}
        />
      )}

      {lightboxAsset && (
        <Lightbox asset={lightboxAsset} assets={categoryAssets} onClose={() => setLightboxAsset(null)} onChange={setLightboxAsset} />
      )}
    </div>
  )
}

function UploadArea({
  activeCategory,
  activeSubCategory,
  uploading,
  promptText,
  setPromptText,
  uploadFiles,
}: {
  activeCategory: string
  activeSubCategory: string | null
  uploading: boolean
  promptText: string
  setPromptText: (value: string) => void
  uploadFiles: (files: FileList | File[], materialOverride?: string, notesOverride?: string) => Promise<void>
}) {
  const inputId = `asset-upload-${activeCategory}-${activeSubCategory || 'all'}`
  if (activeSubCategory === '多角度图') {
    return <SlotUploadGrid slots={MULTI_ANGLE_SLOTS} uploading={uploading} uploadFiles={uploadFiles} />
  }
  if (activeSubCategory === 'Amazon') {
    return <SlotUploadGrid slots={AMAZON_SLOTS} uploading={uploading} uploadFiles={uploadFiles} />
  }
  if (activeSubCategory === '天猫' || activeSubCategory === '京东') {
    return <SlotUploadGrid slots={PLATFORM_DETAIL_SLOTS} uploading={uploading} uploadFiles={uploadFiles} />
  }
  if (activeSubCategory === 'AI 提示词模板') {
    return (
      <div className="mb-5 grid gap-3 rounded-xl border border-dashed border-teal-300 bg-teal-50/50 p-4 md:grid-cols-[1fr_1.2fr]">
        <label className="flex min-h-32 cursor-pointer items-center justify-center rounded-lg bg-white/80 text-sm font-bold text-teal-700">
          选择提示词图片
          <input type="file" accept="image/*" className="hidden" onChange={event => {
            const input = event.currentTarget
            const files = input.files
            if (!files) return
            void uploadFiles(files, 'aiPrompt', promptText).finally(() => { input.value = '' })
          }} />
        </label>
        <textarea
          className="glass-input min-h-32 p-3 text-sm"
          value={promptText}
          onChange={event => setPromptText(event.target.value)}
          placeholder="输入 AI 提示词，保存图片时写入备注"
        />
      </div>
    )
  }
  return (
    <label className="mb-5 flex min-h-28 cursor-pointer items-center justify-center rounded-xl border border-dashed border-teal-300 bg-white/50 text-center text-sm font-bold text-teal-700 transition hover:bg-teal-50">
      {uploading ? '上传中...' : activeCategory === '06' ? '点击上传视频素材' : '点击上传图片素材'}
      <input
        id={inputId}
        type="file"
        multiple
        accept={activeCategory === '06' ? 'video/mp4,video/webm,video/quicktime,.mov' : 'image/*'}
        className="hidden"
        onChange={event => {
          const input = event.currentTarget
          const files = input.files
          if (!files) return
          void uploadFiles(files).finally(() => { input.value = '' })
        }}
      />
    </label>
  )
}

function SlotUploadGrid({
  slots,
  uploading,
  uploadFiles,
}: {
  slots: Array<{ key: string; label: string; accept: string }>
  uploading: boolean
  uploadFiles: (files: FileList | File[], materialOverride?: string) => Promise<void>
}) {
  return (
    <div className="mb-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {slots.map(slot => (
        <label key={slot.key} className="flex min-h-28 cursor-pointer items-center justify-center rounded-xl border border-dashed border-teal-300 bg-white/55 text-center text-sm font-black text-teal-700 hover:bg-teal-50">
          {uploading ? '上传中...' : slot.label}
          <input type="file" multiple accept={slot.accept} className="hidden" onChange={event => {
            const input = event.currentTarget
            const files = input.files
            if (!files) return
            void uploadFiles(files, slot.key).finally(() => { input.value = '' })
          }} />
        </label>
      ))}
    </div>
  )
}

function BatchToolbar({ count, total, allSelected, onSelectAll, onClearSelection, onOpenTags, onOpenClear }: {
  count: number
  total: number
  allSelected: boolean
  onSelectAll: () => void
  onClearSelection: () => void
  onOpenTags: () => void
  onOpenClear: () => void
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-teal-600 p-3 text-sm font-bold text-white">
      <span>已选 {count} 项</span>
      {!allSelected && <button className="rounded-full bg-white/18 px-3 py-1.5" onClick={onSelectAll}>全选 ({total})</button>}
      <button className="rounded-full bg-white/18 px-3 py-1.5" onClick={onOpenTags}>批量打标签</button>
      <button className="rounded-full bg-red-500 px-3 py-1.5" onClick={onOpenClear}>清除标签</button>
      <button className="rounded-full bg-white px-3 py-1.5 text-teal-700" onClick={onClearSelection}>取消选择</button>
    </div>
  )
}

function BatchTagPanel({ pending, customInputs, setCustomInputs, tagPresets, onToggle, onCommit, onCancel }: {
  pending: Array<{ key: string; tag: string }>
  customInputs: Record<string, string>
  setCustomInputs: (value: Record<string, string>) => void
  tagPresets: Record<string, string[]>
  onToggle: (key: string, tag: string) => void
  onCommit: () => void
  onCancel: () => void
}) {
  return (
    <div className="mb-4 rounded-xl border border-teal-200 bg-white/70 p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {pending.map(item => (
          <button key={`${item.key}-${item.tag}`} className="rounded-full bg-teal-100 px-2.5 py-1 text-xs font-bold text-teal-700" onClick={() => onToggle(item.key, item.tag)}>
            {item.tag} ×
          </button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {TAG_DIMENSIONS.map(dim => (
          <div key={dim.key} className="rounded-lg bg-white/70 p-3">
            <div className="mb-2 text-xs font-black text-apple-gray-medium">{dim.label}</div>
            <div className="flex flex-wrap gap-1.5">
                {(tagPresets[dim.key] || []).map(tag => {
                const active = pending.some(item => item.key === dim.key && item.tag === tag)
                return (
                  <button key={tag} className={`rounded-full px-2 py-1 text-xs font-bold ${active ? 'bg-teal-600 text-white' : dim.color}`} onClick={() => onToggle(dim.key, tag)}>
                    {tag}
                  </button>
                )
              })}
            </div>
            <div className="mt-2 flex gap-1">
              <input className="glass-input h-8 min-w-0 flex-1 px-2 text-xs" value={customInputs[dim.key] || ''} onChange={event => setCustomInputs({ ...customInputs, [dim.key]: event.target.value })} />
              <button className="rounded-lg bg-teal-600 px-2 text-xs font-bold text-white" onClick={() => {
                const value = customInputs[dim.key]?.trim()
                if (value) onToggle(dim.key, value)
                setCustomInputs({ ...customInputs, [dim.key]: '' })
              }}>+</button>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-2">
        <button className="rounded-full bg-teal-600 px-4 py-2 text-sm font-bold text-white" onClick={onCommit}>保存 ({pending.length})</button>
        <button className="rounded-full bg-white px-4 py-2 text-sm font-bold" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}

function AssetCard({ asset, selected, editingTags, customInputs, setCustomInputs, tagPresets, onToggleSelect, onOpenLightbox, onEdit, onDelete, onToggleTags, onAddTag, onRemoveTag }: {
  asset: ProductAsset
  selected: boolean
  editingTags: boolean
  customInputs: Record<string, string>
  setCustomInputs: (value: Record<string, string>) => void
  tagPresets: Record<string, string[]>
  onToggleSelect: () => void
  onOpenLightbox: () => void
  onEdit: () => void
  onDelete: () => void
  onToggleTags: () => void
  onAddTag: (asset: ProductAsset, key: string, tag: string) => Promise<void>
  onRemoveTag: (asset: ProductAsset, key: string, tag: string) => Promise<void>
}) {
  return (
    <article className={`group relative overflow-visible rounded-xl border bg-white/72 p-2 shadow-sm transition ${selected ? 'border-teal-400 ring-2 ring-teal-200' : 'border-black/5'}`}>
      <button className={`absolute right-3 top-3 z-10 h-6 w-6 rounded-md border text-xs font-black ${selected ? 'border-teal-600 bg-teal-600 text-white' : 'border-white bg-white/80 text-transparent group-hover:text-teal-700'}`} onClick={onToggleSelect}>
        ✓
      </button>
      <button className="relative block aspect-square w-full overflow-hidden rounded-lg bg-stone-100" onClick={onOpenLightbox}>
        {asset.asset_type === 'video' ? (
          <div className="flex h-full flex-col items-center justify-center px-4 text-center">
            <div className="text-3xl">🎬</div>
            <div className="mt-2 text-sm font-black text-stone-700">{asset.notes || '视频素材'}</div>
          </div>
        ) : (
          <SecureImage src={asset.thumbnail_url || asset.url} alt={buildNamingFormat(asset)} className="h-full w-full object-cover" />
        )}
        <span className={`absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[11px] font-black ${getMaterialColor(asset.material_type)}`}>
          {asset.material_type || 'unknown'}
        </span>
      </button>
      <div className="mt-2 min-w-0">
        <div className="truncate text-xs font-black text-apple-text" title={buildNamingFormat(asset)}>{buildNamingFormat(asset)}</div>
        <div className="mt-1 text-[11px] font-bold text-apple-gray-medium">{asset.sub_category || '未分类'} · {asset.status_tag || '待审核'}</div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1 text-[10px] font-bold text-stone-600">
        <span className="rounded-full bg-stone-100 px-2 py-0.5">质量：{asset.quality_status || 'usable'}</span>
        <span className="rounded-full bg-stone-100 px-2 py-0.5">重复：{asset.duplicate_status || 'unique'}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {TAG_DIMENSIONS.flatMap(dim => (asset.tags?.[dim.key] || []).map(tag => (
          <button key={`${dim.key}-${tag}`} onClick={() => onRemoveTag(asset, dim.key, tag)} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${dim.color}`}>
            {tag} ×
          </button>
        )))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <button className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-teal-700" onClick={onToggleTags}>+ 标签</button>
        <div className="flex gap-1">
          <button className="rounded-full bg-white px-3 py-1.5 text-xs font-bold" onClick={onEdit}>编辑</button>
          <button className="rounded-full bg-red-50 px-3 py-1.5 text-xs font-bold text-red-600" onClick={onDelete}>删除</button>
        </div>
      </div>
      {editingTags && (
        <div className="absolute left-2 right-2 top-[calc(100%-0.25rem)] z-20 rounded-xl border border-black/5 bg-white p-3 shadow-xl">
          {TAG_DIMENSIONS.map(dim => (
            <div key={dim.key} className="mb-3 last:mb-0">
              <div className="mb-1 text-[10px] font-black text-apple-gray-medium">{dim.label}</div>
              <div className="flex flex-wrap gap-1">
                {(tagPresets[dim.key] || []).slice(0, 8).map(tag => (
                  <button key={tag} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${dim.color}`} onClick={() => onAddTag(asset, dim.key, tag)}>{tag}</button>
                ))}
              </div>
              <div className="mt-1 flex gap-1">
                <input className="glass-input h-7 min-w-0 flex-1 px-2 text-xs" value={customInputs[`${asset.id}-${dim.key}`] || ''} onChange={event => setCustomInputs({ ...customInputs, [`${asset.id}-${dim.key}`]: event.target.value })} />
                <button className="rounded-md bg-teal-600 px-2 text-xs font-bold text-white" onClick={() => {
                  const inputKey = `${asset.id}-${dim.key}`
                  const value = customInputs[inputKey]?.trim()
                  if (value) onAddTag(asset, dim.key, value)
                  setCustomInputs({ ...customInputs, [inputKey]: '' })
                }}>+</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

function EditModal({ asset, form, setForm, qualityStatuses, duplicateStatuses, onClose, onSave }: {
  asset: ProductAsset
  form: EditForm
  setForm: (value: EditForm) => void
  qualityStatuses: string[]
  duplicateStatuses: string[]
  onClose: () => void
  onSave: () => void
}) {
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4">
      <div className="glass max-h-[90vh] w-full max-w-3xl overflow-auto p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-black">编辑素材</h2>
          <button className="rounded-full bg-white px-3 py-1 text-sm font-bold" onClick={onClose}>关闭</button>
        </div>
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <div className="aspect-square overflow-hidden rounded-xl bg-stone-100">
            {asset.asset_type === 'image' ? <SecureImage src={asset.thumbnail_url || asset.url} className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-3xl">🎬</div>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="品牌" value={form.brand || ''} onChange={value => setForm({ ...form, brand: value })} />
            <Field label="素材类型" value={form.material_type || ''} onChange={value => setForm({ ...form, material_type: value })} />
            <Field label="二级分类" value={form.sub_category || ''} onChange={value => setForm({ ...form, sub_category: value })} />
            <Field label="角度/场景" value={form.angle_scene || ''} onChange={value => setForm({ ...form, angle_scene: value })} />
            <Field label="渠道" value={form.channel || ''} onChange={value => setForm({ ...form, channel: value })} />
            <Field label="语言" value={form.language_tag || ''} onChange={value => setForm({ ...form, language_tag: value })} />
            <Field label="版本" value={form.version_tag || ''} onChange={value => setForm({ ...form, version_tag: value })} />
            <Field label="日期" value={form.date_tag || ''} onChange={value => setForm({ ...form, date_tag: value })} />
            <label className="text-xs font-bold text-apple-gray-medium">
              质量状态
              <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.quality_status || 'usable'} onChange={event => setForm({ ...form, quality_status: event.target.value })}>
                {qualityStatuses.map(status => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
            <label className="text-xs font-bold text-apple-gray-medium">
              重复状态
              <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.duplicate_status || 'unique'} onChange={event => setForm({ ...form, duplicate_status: event.target.value })}>
                {duplicateStatuses.map(status => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
            <Field label="质量说明" value={form.quality_reason || ''} onChange={value => setForm({ ...form, quality_reason: value || null })} />
            <Field label="重复源素材 ID" value={form.duplicate_of_asset_id || ''} onChange={value => setForm({ ...form, duplicate_of_asset_id: value || null })} />
            <label className="text-xs font-bold text-apple-gray-medium">
              状态
              <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.status_tag || ''} onChange={event => setForm({ ...form, status_tag: event.target.value })}>
                {STATUS_OPTIONS.map(status => <option key={status} value={status}>{status}</option>)}
              </select>
            </label>
            <Field label="备注" value={form.notes || ''} onChange={value => setForm({ ...form, notes: value })} />
          </div>
        </div>
        <div className="mt-4 rounded-xl bg-white/60 p-3 text-xs font-black text-apple-text">{buildNamingFormat({ ...asset, ...form })}</div>
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded-full bg-white px-4 py-2 text-sm font-bold" onClick={onClose}>取消</button>
          <button className="rounded-full bg-teal-600 px-4 py-2 text-sm font-bold text-white" onClick={onSave}>保存</button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs font-bold text-apple-gray-medium">
      {label}
      <input className="glass-input mt-1 h-10 w-full px-3 text-sm" value={value} onChange={event => onChange(event.target.value)} />
    </label>
  )
}

function Lightbox({ asset, assets, onClose, onChange }: {
  asset: ProductAsset
  assets: ProductAsset[]
  onClose: () => void
  onChange: (asset: ProductAsset) => void
}) {
  const visible = assets.filter(item => item.asset_type === 'image' || item.asset_type === 'video')
  const index = visible.findIndex(item => item.id === asset.id)
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/88 p-4">
      <button className="absolute right-5 top-5 rounded-full bg-white px-4 py-2 text-sm font-black" onClick={onClose}>关闭</button>
      {index > 0 && <button className="absolute left-5 rounded-full bg-white px-4 py-3 text-xl font-black" onClick={() => onChange(visible[index - 1])}>←</button>}
      <div className="max-h-[86vh] max-w-[86vw]">
        {asset.asset_type === 'video' ? (
          <SecureVideo src={asset.url} controls className="max-h-[86vh] max-w-[86vw] rounded-xl" />
        ) : (
          <SecureImage src={asset.url} alt={buildNamingFormat(asset)} className="max-h-[86vh] max-w-[86vw] rounded-xl object-contain" />
        )}
        <div className="mt-3 text-center text-sm font-bold text-white">{buildNamingFormat(asset)}</div>
      </div>
      {index < visible.length - 1 && <button className="absolute right-5 rounded-full bg-white px-4 py-3 text-xl font-black" onClick={() => onChange(visible[index + 1])}>→</button>}
    </div>
  )
}
