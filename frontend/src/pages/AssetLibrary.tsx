import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../services/api'
import { SecureImage, SecureVideo, useSignedFileUrl } from '../components/SecureFile'
import { hasPermission, useAuthStore } from '../store/authStore'
import SourceDocumentLibrary from '../components/SourceDocumentLibrary'
import type { AssetCategoryDefinition, AssetTags, AssetTaxonomy, ProductAsset, ProductAssetOverview } from '../types'
import {
  ASSET_UPLOAD_LIMITS,
  ASSET_FILTER_DIMENSION_KEYS,
  ASSET_FIELD_GUIDE,
  ASSET_CATEGORIES,
  CROSS_BORDER_ECOMMERCE_SLOTS,
  DOMESTIC_ECOMMERCE_SLOTS,
  MULTI_ANGLE_SLOTS,
  STATUS_OPTIONS,
  TAG_DIMENSIONS,
  TAG_PRESETS,
  getCategoryName,
  getCategoryTagLabel,
  getCategoryTagValue,
  getMaterialType,
  getMaterialTypeDisplayName,
  getSubCategories,
  getTagDisplayName,
  getUploadGuidelines,
} from './assetLibraryConfig'
import {
  addTag,
  areExclusiveTags,
  buildNamingFormat,
  changedAssetFields,
  cloneTags,
  getMaterialColor,
  getEffectiveAssetTags,
  removeTag,
  sortAssets,
} from './assetLibraryHelpers'

type EditForm = Partial<ProductAsset>

function matchesAssetCategory(asset: ProductAsset, categoryCode: string, subCategory?: string | null) {
  const effectiveTags = getEffectiveAssetTags(asset)
  const matchesCategory = asset.category_code === categoryCode
    || (effectiveTags.category_tags || []).some(tag => tag.startsWith(`${categoryCode}/`))
  if (!matchesCategory) return false
  if (!subCategory) return true
  return (asset.category_code === categoryCode && asset.sub_category === subCategory)
    || (effectiveTags.category_tags || []).includes(getCategoryTagValue(categoryCode, subCategory))
}

export default function AssetLibrary() {
  const { user } = useAuthStore()
  const canManageAssets = hasPermission(user, 'product.edit') && hasPermission(user, 'media.upload')
  const canEditTags = canManageAssets && hasPermission(user, 'tag.edit')
  const canReviewAssets = hasPermission(user, 'media.review')
  const [products, setProducts] = useState<ProductAssetOverview[]>([])
  const [catalogTotal, setCatalogTotal] = useState(0)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const initialSku = new URLSearchParams(window.location.search).get('sku') || ''
  const [searchSku, setSearchSku] = useState(initialSku)
  const [selectedSku, setSelectedSku] = useState(initialSku)
  const [selectedProductName, setSelectedProductName] = useState('')
  const [activeCategory, setActiveCategory] = useState('01')
  const [activeSubCategory, setActiveSubCategory] = useState<string | null>(null)
  const [assets, setAssets] = useState<ProductAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [assetError, setAssetError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [tagError, setTagError] = useState('')
  const [uploadMaintainer, setUploadMaintainer] = useState('')
  const [uploadRelatedSkus, setUploadRelatedSkus] = useState('')
  const [uploadCategoryTags, setUploadCategoryTags] = useState<string[]>([])
  const [uploadMaterialTags, setUploadMaterialTags] = useState<string[]>([])
  const [uploadSubjects, setUploadSubjects] = useState<string[]>([])
  const [uploadComposition, setUploadComposition] = useState('')
  const [uploadView, setUploadView] = useState('')
  const [uploadScenes, setUploadScenes] = useState<string[]>([])
  const [uploadChannels, setUploadChannels] = useState<string[]>([])
  const [editingAsset, setEditingAsset] = useState<ProductAsset | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({})
  const [editError, setEditError] = useState('')
  const [lightboxAsset, setLightboxAsset] = useState<ProductAsset | null>(null)
  const [editingTagsAssetId, setEditingTagsAssetId] = useState<string | null>(null)
  const [customTagInputs, setCustomTagInputs] = useState<Record<string, string>>({})
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set())
  const [batchTagsOpen, setBatchTagsOpen] = useState(false)
  const [pendingBatchTags, setPendingBatchTags] = useState<Array<{ key: string; tag: string }>>([])
  const [batchCustomInputs, setBatchCustomInputs] = useState<Record<string, string>>({})
  const [confirmClearOpen, setConfirmClearOpen] = useState(false)
  const [assetTagFilters, setAssetTagFilters] = useState<Partial<Record<keyof AssetTags, string[]>>>({})
  // Prompt-template uploads were removed from the visual asset library.
  const [taxonomy, setTaxonomy] = useState<AssetTaxonomy | null>(null)
  const [tagPresets, setTagPresets] = useState(TAG_PRESETS)

  useEffect(() => {
    if (activeCategory !== '04') {
      setUploadScenes([])
      return
    }
    const defaultScene = activeSubCategory === '车露营' ? '车露' : activeSubCategory
    if (!defaultScene || !(tagPresets.scene_tags || []).includes(defaultScene)) return
    setUploadScenes(current => current.includes(defaultScene) ? current : [defaultScene, ...current])
  }, [activeCategory, activeSubCategory, tagPresets.scene_tags])

  const loadProductOverview = useCallback(async () => {
    setCatalogLoading(true)
    setCatalogError('')
    try {
      const result = await api.assets.overview()
      setProducts(result.items)
      setCatalogTotal(result.total)
    } catch {
      setProducts([])
      setCatalogTotal(0)
      setCatalogError('产品素材总览加载失败，请刷新后重试')
    } finally {
      setCatalogLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProductOverview()
  }, [loadProductOverview])

  useEffect(() => {
    if (!selectedSku) {
      setSelectedProductName('')
      return
    }
    const localProduct = products.find(product => product.sku === selectedSku)
    setSelectedProductName(localProduct?.product_name_cn || localProduct?.product_name_en || '')
  }, [products, selectedSku])

  useEffect(() => {
    let active = true
    api.assets.taxonomy().then(data => {
      if (!active) return
      setTaxonomy(data)
      setTagPresets(current => {
        const next = { ...current }
        for (const [key, dimension] of Object.entries(data.dimensions)) next[key] = dimension.values
        return next
      })
    }).catch(() => {
      // Keep bundled presets as a safe UI fallback if the API is unavailable.
    })
    return () => { active = false }
  }, [])

  const loadAssets = useCallback(async () => {
    if (!selectedSku) {
      setAssets([])
      setAssetError('')
      return
    }
    setLoading(true)
    setAssetError('')
    try {
      const result = await api.assets.list(selectedSku)
      setAssets(result)
    } catch (error) {
      // Never leave the previous SKU's assets visible after a failed reload.
      setAssets([])
      setAssetError(error instanceof Error ? error.message : '素材加载失败，请刷新后重试')
    } finally {
      setLoading(false)
    }
  }, [selectedSku])

  useEffect(() => {
    loadAssets()
  }, [loadAssets])

  const filteredProducts = useMemo(() => {
    const keyword = searchSku.trim().toLowerCase()
    if (!keyword) return []
    return products.filter(product => (
      product.sku.toLowerCase().includes(keyword) ||
      (product.product_name_cn || '').toLowerCase().includes(keyword) ||
      (product.product_name_en || '').toLowerCase().includes(keyword) ||
      (product.brand || '').toLowerCase().includes(keyword)
    )).slice(0, 30)
  }, [products, searchSku])

  const overviewProducts = useMemo(() => {
    const keyword = searchSku.trim().toLowerCase()
    if (!keyword) return products
    return products.filter(product => (
      product.sku.toLowerCase().includes(keyword) ||
      (product.product_name_cn || '').toLowerCase().includes(keyword) ||
      (product.product_name_en || '').toLowerCase().includes(keyword) ||
      (product.brand || '').toLowerCase().includes(keyword)
    ))
  }, [products, searchSku])

  const overviewStats = useMemo(() => ({
    totalProducts: catalogTotal || products.length,
    coveredProducts: products.filter(product => product.image_count > 0).length,
    imageCount: products.reduce((sum, product) => sum + product.image_count, 0),
    videoCount: products.reduce((sum, product) => sum + product.video_count, 0),
    totalBytes: products.reduce((sum, product) => sum + (product.total_size_bytes || 0), 0),
  }), [catalogTotal, products])

  const selectedAssetBytes = useMemo(
    () => assets.reduce((sum, asset) => sum + (asset.file_size_bytes || 0), 0),
    [assets],
  )

  const categoryAssets = useMemo(() => {
    const filtered = assets.filter(asset => {
      const effectiveTags = getEffectiveAssetTags(asset)
      if (!matchesAssetCategory(asset, activeCategory, activeSubCategory)) return false
      return Object.entries(assetTagFilters).every(([key, values]) => {
        if (!values?.length) return true
        const assetValues = effectiveTags[key as keyof AssetTags] || []
        return values.some(value => assetValues.includes(value))
      })
    })
    return sortAssets(filtered, activeSubCategory)
  }, [assets, activeCategory, activeSubCategory, assetTagFilters])

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const asset of assets) {
      const categories = new Set<string>([asset.category_code])
      for (const tag of getEffectiveAssetTags(asset).category_tags || []) categories.add(tag.split('/')[0])
      for (const category of categories) counts[category] = (counts[category] || 0) + 1
    }
    return counts
  }, [assets])

  const taxonomyCategories = (taxonomy?.categories || []).filter(category => !category.hidden && category.code !== '07')
  const assetCategories = taxonomyCategories.length
    ? taxonomyCategories.map(category => ({
        code: category.code,
        name: category.name,
        icon: ASSET_CATEGORIES.find(item => item.code === category.code)?.icon || '📁',
      }))
    : ASSET_CATEGORIES
  const activeTaxonomyCategory = taxonomyCategories.find(category => category.code === activeCategory)
  const subCategories = activeTaxonomyCategory
    ? activeTaxonomyCategory.sub_categories.map(item => ({
        categoryCode: activeCategory,
        name: item.name,
        materialType: item.material_type,
      }))
    : getSubCategories(activeCategory)
  const activeCategoryName = assetCategories.find(category => category.code === activeCategory)?.name || getCategoryName(activeCategory)
  const activeMaterialType = subCategories.find(item => item.name === activeSubCategory)?.materialType || getMaterialType(activeCategory, activeSubCategory)
  const categoryTagOptions = useMemo(() => {
    const serverDefinitions = (taxonomy?.categories || []).filter(category => !category.hidden && category.code !== '07')
    const definitions = serverDefinitions.length
      ? serverDefinitions
      : ASSET_CATEGORIES.map(category => ({
          code: category.code,
          name: category.name,
          sub_categories: getSubCategories(category.code).map(sub => ({ name: sub.name, material_type: sub.materialType })),
        }))
    return definitions.flatMap(category => category.sub_categories.map(sub => ({
      value: getCategoryTagValue(category.code, sub.name),
      categoryCode: category.code,
      categoryName: category.name,
      subCategory: sub.name,
    })))
  }, [taxonomy])
  const handleSkuSelect = (sku: string) => {
    setSelectedSku(sku)
    setUploadMaintainer('')
    setUploadRelatedSkus('')
    setUploadCategoryTags([])
    setUploadMaterialTags([])
    setUploadSubjects([])
    setUploadComposition('')
    setUploadView('')
    setUploadScenes([])
    setUploadChannels([])
    setSearchSku(sku)
    setAssets([])
    setSelectedAssetIds(new Set())
    setAssetTagFilters({})
    setAssetError('')
    setUploadError('')
  }

  const uploadFiles = async (files: FileList | File[], materialOverride?: string, notesOverride?: string) => {
    if (!selectedSku) return
    const fileArray = Array.from(files)
    if (!fileArray.length) return
    const mediaKind = activeCategory === '06' ? 'video' : 'image'
    const limits = ASSET_UPLOAD_LIMITS[mediaKind]
    if (fileArray.length > limits.maxFiles) {
      setUploadError(`每次最多上传 ${limits.maxFiles} 个${mediaKind === 'video' ? '视频' : '图片'}文件`)
      return
    }
    const oversized = fileArray.find(file => file.size > limits.maxBytes)
    if (oversized) {
      setUploadError(`${oversized.name} 超过单文件 ${formatBytes(limits.maxBytes)} 的限制`)
      return
    }
    setUploading(true)
    setUploadError('')
    try {
      const subCategory = activeSubCategory || (activeCategory === '06' ? '视频' : null)
      const materialType = materialOverride || activeMaterialType || (activeCategory === '06' ? 'video' : null)
      const categoryTags = Array.from(new Set([
        getCategoryTagValue(activeCategory, subCategory),
        ...uploadCategoryTags,
      ].filter(Boolean)))
      const response = await api.assets.upload(selectedSku, {
        files: fileArray,
        category_code: activeCategory,
        category_name: activeCategoryName,
        sub_category: subCategory,
        material_type: materialType,
        category_tags: categoryTags,
        maintainer: uploadMaintainer.trim() || undefined,
        related_skus: uploadRelatedSkus.split(/[,，\s]+/).filter(Boolean),
        material_type_tags: uploadMaterialTags,
        subject_tags: uploadSubjects,
        composition_tags: uploadComposition ? [uploadComposition] : [],
        view_tags: activeSubCategory === '多角度图' && materialOverride ? [] : uploadView ? [uploadView] : [],
        scene_tags: activeCategory === '04' ? uploadScenes : [],
        channel_tags: uploadChannels,
        notes: notesOverride || undefined,
      })
      setAssets(prev => [...prev, ...response.items])
      void loadProductOverview()
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
    setEditError('')
    setEditingAsset(asset)
    setEditForm({ ...asset })
  }

  const saveEdit = async () => {
    if (!selectedSku || !editingAsset) return
    setEditError('')
    try {
      const changes = changedAssetFields(editingAsset, editForm)
      if (!Object.keys(changes).length) {
        setEditingAsset(null)
        return
      }
      const updated = await api.assets.update(editingAsset.sku, editingAsset.id, changes)
      setAssets(prev => prev.map(asset => asset.id === updated.id ? updated : asset))
      setEditingAsset(null)
    } catch (error) {
      setEditError(error instanceof Error ? error.message : '素材保存失败，请检查字段后重试')
    }
  }

  const deleteAsset = async (asset: ProductAsset) => {
    if (!selectedSku) return
    if (!window.confirm(`删除素材 ${buildNamingFormat(asset)}？`)) return
    try {
      if (asset.sku !== selectedSku) { setAssetError(`这是 ${asset.sku} 的共享素材，请回到主归档产品管理或解除关联`); return }
      await api.assets.delete(selectedSku, asset.id)
      setAssets(prev => prev.filter(item => item.id !== asset.id))
      void loadProductOverview()
      setSelectedAssetIds(prev => {
        const next = new Set(prev)
        next.delete(asset.id)
        return next
      })
    } catch (error) {
      setAssetError(error instanceof Error ? error.message : '素材删除失败，请稍后重试')
    }
  }

  const persistTags = async (assetId: string, tags: AssetTags) => {
    if (!selectedSku) return false
    setTagError('')
    try {
      const updated = await api.assets.updateTags(selectedSku, assetId, tags)
      setAssets(prev => prev.map(asset => asset.id === assetId ? updated : asset))
      return true
    } catch (error) {
      setTagError(`标签保存失败：${error instanceof Error ? error.message : '请稍后重试'}。失败项未改动；批量操作中已经保存的项目保留，请核对后重试。`)
      return false
    }
  }

  const handleAddTag = async (asset: ProductAsset, key: string, tag: string) => {
    const next = addTag(asset.tags, key, tag)
    await persistTags(asset.id, { [key]: next[key as keyof AssetTags] || [] })
  }

  const handleRemoveTag = async (asset: ProductAsset, key: string, tag: string) => {
    const next = removeTag(asset.tags, key, tag)
    await persistTags(asset.id, { [key]: next[key as keyof AssetTags] || [] })
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
      return exists ? prev.filter(item => !(item.key === key && item.tag === tag))
        : [...prev.filter(item => item.key !== key || !areExclusiveTags(key, item.tag, tag)), { key, tag }]
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
      const changes = Object.fromEntries(pendingBatchTags.map(item => [item.key, next[item.key as keyof AssetTags]]))
      if (!await persistTags(assetId, changes)) return
    }
    clearSelection()
  }

  const clearBatchTags = async () => {
    if (!selectedSku) return
    for (const assetId of selectedAssetIds) {
      const changes = Object.fromEntries(TAG_DIMENSIONS
        .filter(dim => canReviewAssets || !['risk_tags', 'quality_check_tags'].includes(dim.key))
        .map(dim => [dim.key, []]))
      if (!await persistTags(assetId, changes)) return
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
      {hasPermission(user, 'knowledge.files.manage') && <SourceDocumentLibrary />}
          <section className="glass px-5 py-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="eyebrow">L6 Asset Library</p>
            <h1 className="mt-1 text-2xl font-black text-apple-text">素材库</h1>
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
                {filteredProducts.length > 0 ? filteredProducts.map(product => (
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
                )) : <div className="px-3 py-2 text-sm text-apple-gray-medium">未找到匹配产品</div>}
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
            <span className="rounded-full bg-white px-3 py-1 font-bold text-teal-800">当前容量：{formatBytes(selectedAssetBytes)}</span>
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
        <ProductOverview
          products={overviewProducts}
          loading={catalogLoading}
          error={catalogError}
          stats={overviewStats}
          onSelect={handleSkuSelect}
          onRetry={() => void loadProductOverview()}
        />
      ) : (
        <>
          <section className="glass p-3">
            <div className="mb-3 rounded-xl border border-teal-100 bg-teal-50/70 px-4 py-3">
              <div className="text-sm font-black text-teal-900">① 主归档位置（单选）</div>
              <p className="mt-1 text-xs leading-5 text-teal-800">先选一个一级分类，再选一个二级分类，作为这次上传的默认归档位置。它不是图片唯一身份；同一张图片要出现在其他分类，请在上传标签里添加“其他归属分类”。</p>
              <div className="mt-2 inline-flex rounded-full bg-white px-3 py-1 text-xs font-black text-teal-800">
                当前主归档：{activeCategoryName} / {activeSubCategory || '未选二级分类'}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
              {assetCategories.map(category => (
                <button
                  key={category.code}
                  onClick={() => {
                    setActiveCategory(category.code)
                    setActiveSubCategory(null)
                    setAssetTagFilters({})
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
            <div className="mb-2 text-xs font-black text-apple-gray-medium">主归档的二级分类（单选）</div>
            <div className="mb-4 flex flex-wrap gap-2">
              <button
                onClick={() => setActiveSubCategory(null)}
                className={`rounded-full px-3 py-1.5 text-sm font-bold ${!activeSubCategory ? 'bg-teal-600 text-white' : 'bg-white/70 text-apple-gray-dark'}`}
              >
                全部 ({assets.filter(asset => matchesAssetCategory(asset, activeCategory)).length})
              </button>
              {subCategories.map(sub => (
                <button
                  key={`${sub.categoryCode}-${sub.name}`}
                  onClick={() => setActiveSubCategory(sub.name)}
                  className={`rounded-full px-3 py-1.5 text-sm font-bold ${activeSubCategory === sub.name ? 'bg-teal-600 text-white' : 'bg-white/70 text-apple-gray-dark'}`}
                >
                  {sub.name} ({assets.filter(asset => matchesAssetCategory(asset, activeCategory, sub.name)).length})
                </button>
                ))}
            </div>

            <section className="mb-4 rounded-2xl border border-teal-200 bg-white/60 p-3">
              <div className="text-sm font-black text-teal-900">② 素材标签管理</div>
              <p className="mt-1 text-xs leading-5 text-teal-800">下面两块使用同一套标签：上面查找已有素材，下面给新上传的图片预设标签；它们不是重复操作。默认收起，点击标题即可展开或收起。</p>
              <AssetTagFilterBar
                filters={assetTagFilters}
                tagPresets={tagPresets}
                onToggle={(key, tag) => setAssetTagFilters(current => {
                  const values = current[key] || []
                  const nextValues = values.includes(tag) ? values.filter(value => value !== tag) : [...values, tag]
                  const next = { ...current }
                  if (nextValues.length) next[key] = nextValues
                  else delete next[key]
                  return next
                })}
                onClear={() => setAssetTagFilters({})}
              />

              {assetError && (
              <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <span>{assetError}</span>
                <button type="button" className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-red-700" onClick={() => void loadAssets()}>
                  重新加载
                </button>
              </div>
              )}

              {canManageAssets ? (
              <>
              <details className="mt-4 border-t border-teal-100 pt-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-black text-teal-800">
                  <span>上传新图片时设置归属与标签（可选，不填也能上传）</span>
                  <span className="shrink-0 text-xs font-bold text-teal-600">点击展开 / 收起</span>
                </summary>
                <div className="pt-2">
                  <p className="mt-2 text-xs leading-5 text-apple-gray-medium">上面的“主归档位置”只选一个；下面可以给同一张图片添加多个“其他归属分类”。文件只上传一份，保存后会在这些分类入口和标签筛选中同时出现。</p>
                  <label className="mt-3 block text-sm font-bold text-apple-gray-medium">
                    素材维护人（可选）
                    <input className="glass-input mt-1 h-10 w-full px-3" value={uploadMaintainer} maxLength={100} onChange={event => setUploadMaintainer(event.target.value)} placeholder="负责收集、更新此批素材的人，不等同于上传操作人" />
                    <label className="block mt-3 text-xs">其他关联SKU（一次上传，多产品共用）<input className="glass-input mt-1 h-10 w-full px-3" value={uploadRelatedSkus} onChange={event => setUploadRelatedSkus(event.target.value)} placeholder="输入已存在的SKU，用逗号或空格分隔" /></label>
                  </label>
                <fieldset className="mt-3 rounded-xl border border-teal-100 bg-teal-50/45 p-3 text-sm text-apple-gray-medium">
                  <legend className="px-1 font-black text-teal-800">其他归属分类（可多选）</legend>
                  <p className="mt-1 text-xs leading-5">例如：主归档选“产品标准图 / 白底图”，这里再勾选“电商与品牌图 / 国内电商”，上传一次即可两处找到。</p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                    {categoryTagOptions.filter(option => option.value !== getCategoryTagValue(activeCategory, activeSubCategory)).map(option => (
                      <label key={option.value} className="flex items-start gap-2 rounded-lg bg-white/80 px-2.5 py-2 text-xs font-bold">
                        <input
                          type="checkbox"
                          checked={uploadCategoryTags.includes(option.value)}
                          disabled={uploading}
                          onChange={event => setUploadCategoryTags(current => event.target.checked
                            ? [...current, option.value]
                            : current.filter(value => value !== option.value))}
                        />
                        <span>{option.categoryName} / {option.subCategory}</span>
                      </label>
                    ))}
                  </div>
                  {uploadCategoryTags.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5 text-xs font-bold text-teal-800">
                    已选其他归属：{uploadCategoryTags.map(tag => <span key={tag} className="rounded-full bg-white px-2 py-0.5">{getCategoryTagLabel(tag)}</span>)}
                  </div>}
                </fieldset>
                <fieldset className="mt-3 text-sm text-apple-gray-medium">
                  <legend className="font-bold">素材形式标签（可多选，补充图片特征）</legend>
                  <p className="mt-1 text-xs font-normal">不用为了上传重复选择主归档；主归档会自动成为对应的归属和形式标签。这里用于补充白底图、配件图、多角度图等图片特征。</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(tagPresets.material_type_tags || []).map(tag => <label key={tag} className="flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-xs font-bold"><input type="checkbox" checked={uploadMaterialTags.includes(tag)} disabled={uploading} onChange={event => setUploadMaterialTags(event.target.checked ? [...uploadMaterialTags, tag] : uploadMaterialTags.filter(value => value !== tag))} />{getTagDisplayName(tag)}</label>)}
                  </div>
                </fieldset>
                <fieldset className="mt-3 text-sm text-apple-gray-medium">
                  <legend className="font-bold">拍摄对象（可多选）</legend>
                  <div className="mt-2 flex flex-wrap gap-3">
                    {(tagPresets.subject_tags || []).map(subject => <label key={subject} className="flex items-center gap-1"><input type="checkbox" checked={uploadSubjects.includes(subject)} disabled={uploading} onChange={event => setUploadSubjects(event.target.checked ? [...uploadSubjects, subject] : uploadSubjects.filter(value => value !== subject))} />{subject}</label>)}
                  </div>
                </fieldset>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="text-sm font-bold text-apple-gray-medium">
                    人物构成（可选）
                    <select className="glass-input mt-1 h-9 w-full px-3" value={uploadComposition} disabled={uploading} onChange={event => setUploadComposition(event.target.value)}>
                      <option value="">未标注</option>
                      {(tagPresets.composition_tags || []).map(value => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </label>
                  <label className="text-sm font-bold text-apple-gray-medium">
                    多角度子标签（可选）
                    <select className="glass-input mt-1 h-9 w-full px-3" value={uploadView} disabled={uploading || activeSubCategory === '多角度图'} onChange={event => setUploadView(event.target.value)}>
                      <option value="">未标注 / 按上传槽位</option>
                      {(tagPresets.view_tags || []).map(value => <option key={value} value={value}>{getTagDisplayName(value)}</option>)}
                    </select>
                  </label>
                </div>
                {activeCategory === '04' && <fieldset className="mt-3 text-sm text-apple-gray-medium">
                  <legend className="font-bold">场景环境（可多选）</legend>
                  <div className="mt-2 flex flex-wrap gap-3">
                    {(tagPresets.scene_tags || []).map(scene => <label key={scene} className="flex items-center gap-1"><input type="checkbox" checked={uploadScenes.includes(scene)} disabled={uploading} onChange={event => setUploadScenes(event.target.checked ? [...uploadScenes, scene] : uploadScenes.filter(value => value !== scene))} />{scene}</label>)}
                  </div>
                </fieldset>}
                <fieldset className="mt-3 text-sm text-apple-gray-medium">
                  <legend className="font-bold">适用渠道（可多选）</legend>
                  <div className="mt-2 flex flex-wrap gap-3">
                    {(tagPresets.channel_tags || []).map(channel => <label key={channel} className="flex items-center gap-1"><input type="checkbox" checked={uploadChannels.includes(channel)} disabled={uploading} onChange={event => setUploadChannels(event.target.checked ? [...uploadChannels, channel] : uploadChannels.filter(value => value !== channel))} />{channel}</label>)}
                  </div>
                  <p className="mt-1 text-xs font-normal">第一个渠道同时作为兼容旧素材的主渠道；不填渠道也可以上传。</p>
                  </fieldset>
                </div>
              </details>
              <UploadArea
                activeCategory={activeCategory}
                activeSubCategory={activeSubCategory}
                uploading={uploading}
                uploadFiles={uploadFiles}
              />
              </>
            ) : (
              <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-600">
                当前账号仅可查看素材。上传、编辑和删除需要产品编辑与素材上传权限。
              </div>
              )}
            </section>
            {uploadError && (
              <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-700">
                {uploadError}
              </div>
            )}
            {tagError && <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{tagError}</div>}

            {canEditTags && selectedAssetIds.size > 0 && (
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
                canReview={canReviewAssets}
                onToggle={togglePendingTag}
                onCommit={commitBatchTags}
                onCancel={() => setBatchTagsOpen(false)}
              />
            )}

            {confirmClearOpen && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4">
                <div className="text-sm font-black text-red-700">确认清除 {selectedAssetIds.size} 项素材可编辑的业务标签？视频测量数据保留；无审核权限时也保留检查及风险记录。</div>
                <div className="mt-3 flex gap-2">
                  <button className="rounded-full bg-red-600 px-4 py-2 text-sm font-bold text-white" onClick={clearBatchTags}>确认清除</button>
                  <button className="rounded-full bg-white px-4 py-2 text-sm font-bold" onClick={() => setConfirmClearOpen(false)}>取消</button>
                </div>
              </div>
            )}

            {loading ? (
              <div className="py-16 text-center text-sm font-bold text-apple-gray-medium">素材加载中...</div>
            ) : categoryAssets.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-white/55 px-4 py-16 text-center">
                <div className="text-sm font-black text-apple-text">当前筛选下暂无素材</div>
                <p className="mt-2 text-xs leading-5 text-apple-gray-medium">
                  {assetTagFilters && Object.keys(assetTagFilters).length > 0
                    ? '可以清除标签筛选，或给已有图片补充标签后再筛选。'
                    : canManageAssets
                      ? '可以直接上传图片，上传后再补充素材形式、场景和视角标签。'
                      : '当前账号只有查看权限，暂无可显示的素材。'}
                </p>
              </div>
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
                    canManage={canManageAssets}
                    canEditTags={canEditTags}
                    canReview={canReviewAssets}
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
          error={editError}
          setForm={setEditForm}
          qualityStatuses={taxonomy?.quality_statuses || ['usable', 'pending_tagging', 'suspected_duplicate', 'invalid', 'archived']}
          duplicateStatuses={taxonomy?.duplicate_statuses || ['unique', 'cross_sku_reuse', 'suspected_duplicate']}
          reviewStatuses={taxonomy?.review_statuses || ['pending', 'approved', 'rejected', 'disabled', 'archived']}
          authorizationStatuses={taxonomy?.authorization_statuses || ['unknown', 'pending', 'internal_test', 'approved', 'authorized', 'rejected', 'denied', 'revoked', 'unapproved']}
          taxonomyCategories={taxonomyCategories}
          canReview={canReviewAssets}
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

function ProductOverview({ products, loading, error, stats, onSelect, onRetry }: {
  products: ProductAssetOverview[]
  loading: boolean
  error: string
  stats: {
    totalProducts: number
    coveredProducts: number
    imageCount: number
    videoCount: number
    totalBytes: number
  }
  onSelect: (sku: string) => void
  onRetry: () => void
}) {
  return (
    <section className="glass p-5">
      <div className="flex flex-col gap-4 border-b border-black/5 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">PRODUCT COVERAGE</p>
          <h2 className="mt-1 text-xl font-black text-apple-text">按产品查看素材</h2>
          <p className="mt-2 text-sm leading-6 text-apple-gray-medium">
            先看每个 SKU 的产品封面和覆盖数量，再进入对应产品继续上传、分类或审核。封面优先使用当前产品标准正视图，不使用历史、禁用、AI 或竞品素材。
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
          <OverviewMetric label="产品 SKU" value={stats.totalProducts} />
          <OverviewMetric label="已覆盖 SKU" value={stats.coveredProducts} suffix="个" />
          <OverviewMetric label="图片总数" value={stats.imageCount} suffix="张" />
          <OverviewMetric label="视频总数" value={stats.videoCount} suffix="个" />
          <OverviewTextMetric label="素材容量" value={formatBytes(stats.totalBytes)} />
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 gap-4 pt-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {Array.from({ length: 8 }).map((_, index) => <div key={index} className="h-72 animate-pulse rounded-2xl bg-white/55" />)}
        </div>
      ) : error ? (
        <div className="py-16 text-center">
          <div className="text-sm font-bold text-red-700">{error}</div>
          <button type="button" className="mt-4 rounded-full bg-teal-600 px-4 py-2 text-sm font-bold text-white" onClick={onRetry}>重新加载</button>
        </div>
      ) : products.length === 0 ? (
        <div className="py-16 text-center text-sm font-bold text-apple-gray-medium">没有匹配的产品 SKU</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 pt-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {products.map(product => {
            const cover = product.cover_thumbnail_url || product.cover_url
            return (
              <article key={product.sku} className="group overflow-hidden rounded-2xl border border-black/5 bg-white/70 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg">
                <button
                  type="button"
                  className="block w-full text-left"
                  data-testid={`asset-product-card-${product.sku}`}
                  onClick={() => onSelect(product.sku)}
                >
                  <div className="relative aspect-[4/3] overflow-hidden bg-gradient-to-br from-stone-100 to-stone-200">
                    {cover ? (
                      <SecureImage src={cover} alt={`${product.sku} 产品封面`} className="h-full w-full object-contain transition duration-300 group-hover:scale-[1.02]" />
                    ) : (
                      <div className="flex h-full flex-col items-center justify-center text-center text-stone-500">
                        <div className="text-4xl">{product.video_count > 0 ? '🎬' : '📦'}</div>
                        <div className="mt-2 text-xs font-bold">{product.image_count > 0 ? '暂无符合封面规则的图片' : product.video_count > 0 ? '暂无图片，仅有视频素材' : '暂无图片'}</div>
                      </div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-2 bg-gradient-to-t from-black/65 via-black/20 to-transparent px-3 pb-3 pt-8 text-white">
                      <span className="text-xs font-black">{product.image_count} 张图片</span>
                      {product.video_count > 0 && <span className="text-[11px] font-bold">另有 {product.video_count} 个视频</span>}
                    </div>
                  </div>
                  <div className="p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-black text-apple-text" title={product.product_name_cn || product.product_name_en || ''}>
                          {product.product_name_cn || product.product_name_en || '未命名产品'}
                        </div>
                        <div className="mt-1 truncate text-xs font-bold text-teal-700">{product.sku}</div>
                      </div>
                      <span className="shrink-0 rounded-full bg-teal-50 px-2 py-1 text-[11px] font-black text-teal-700">进入管理 →</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-bold text-apple-gray-medium">
                      <span className="rounded-full bg-stone-100 px-2 py-1">共 {product.asset_count} 个素材</span>
                      {product.cover_sub_category && <span className="rounded-full bg-stone-100 px-2 py-1">封面 · {product.cover_sub_category}</span>}
                    </div>
                  </div>
                </button>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function OverviewMetric({ label, value, suffix }: { label: string; value: number; suffix?: string }) {
  return (
    <div className="rounded-xl border border-black/5 bg-white/60 px-3 py-2">
      <div className="text-[11px] font-bold text-apple-gray-medium">{label}</div>
      <div className="mt-1 text-base font-black text-apple-text">{value}{suffix && <span className="ml-0.5 text-xs">{suffix}</span>}</div>
    </div>
  )
}

function OverviewTextMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-black/5 bg-white/60 px-3 py-2">
      <div className="text-[11px] font-bold text-apple-gray-medium">{label}</div>
      <div className="mt-1 text-base font-black text-apple-text">{value}</div>
    </div>
  )
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 MB'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  return `${(bytes / 1024 ** 2).toFixed(bytes >= 10 * 1024 ** 2 ? 0 : 1)} MB`
}

function AssetTagFilterBar({ filters, tagPresets, onToggle, onClear }: {
  filters: Partial<Record<keyof AssetTags, string[]>>
  tagPresets: Record<string, string[]>
  onToggle: (key: keyof AssetTags, tag: string) => void
  onClear: () => void
}) {
  const dimensions = TAG_DIMENSIONS.filter(dim => (ASSET_FILTER_DIMENSION_KEYS as readonly string[]).includes(dim.key))
  const activeCount = Object.values(filters).reduce((sum, values) => sum + (values?.length || 0), 0)
  return (
    <details className="rounded-xl border border-teal-100 bg-teal-50/45 p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-black text-teal-800">
        <span>
          筛选已有素材（标签可多选）{activeCount > 0 && <span className="ml-2 rounded-full bg-teal-600 px-2 py-0.5 text-xs text-white">已选 {activeCount}</span>}
        </span>
        <span className="shrink-0 text-xs font-bold text-teal-600">点击展开 / 收起</span>
      </summary>
      <div className="pt-2">
        <p className="mt-1 text-xs leading-5 text-apple-gray-medium">这里是查找当前 SKU 已经上传的图片，不会改变图片标签。</p>
        <div className="mt-3 space-y-3">
        {dimensions.map(dim => {
          const selected = filters[dim.key as keyof AssetTags] || []
          return (
            <div key={dim.key}>
              <div className="mb-1 text-[11px] font-black text-apple-gray-medium">{dim.label}</div>
              {dim.key === 'view_tags' && <div className="mb-1 text-[10px] text-apple-gray-medium">多角度图的下一级标签；正面、侧面等筛选会与素材形式标签组合。</div>}
              <div className="flex flex-wrap gap-1.5">
                {(tagPresets[dim.key] || []).map(tag => (
                  <button
                    key={tag}
                    type="button"
                    className={`rounded-full px-2.5 py-1 text-xs font-bold ${selected.includes(tag) ? 'bg-teal-600 text-white' : dim.color}`}
                    onClick={() => onToggle(dim.key as keyof AssetTags, tag)}
                  >
                    {getTagDisplayName(tag)}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
        {activeCount > 0 && <button type="button" className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-teal-700" onClick={onClear}>清除标签筛选</button>}
        </div>
      </div>
    </details>
  )
}

function UploadArea({
  activeCategory,
  activeSubCategory,
  uploading,
  uploadFiles,
}: {
  activeCategory: string
  activeSubCategory: string | null
  uploading: boolean
  uploadFiles: (files: FileList | File[], materialOverride?: string, notesOverride?: string) => Promise<void>
}) {
  const inputId = `asset-upload-${activeCategory}-${activeSubCategory || 'all'}`
  const mediaKind = activeCategory === '06' ? 'video' : 'image'
  const limits = ASSET_UPLOAD_LIMITS[mediaKind]
  const guidelines = getUploadGuidelines(activeCategory, activeSubCategory)
  const uploadDisabled = uploading
  const uploadNotice = (
    <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-sm text-amber-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-black">上传图片{activeCategory === '06' ? ' / 视频' : ''}</div>
        <div className="rounded-full bg-white/80 px-3 py-1 text-xs font-bold text-amber-800">
           单文件 ≤ {formatBytes(limits.maxBytes)} · 每次 ≤ {limits.maxFiles} 个
        </div>
      </div>
      <p className="mt-2 leading-6">先确认上方的主归档位置，再直接选择文件上传。图片只保存一份；“其他归属分类”和标签会随上传一起保存，也可以上传后再补。</p>
      <details className="mt-2 rounded-lg bg-white/55 p-2">
        <summary className="cursor-pointer text-xs font-bold text-amber-900">查看当前分类建议与字段定义</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5">
          {guidelines.map(item => <li key={item}>{item}</li>)}
        </ul>
        <AssetFieldGuide />
      </details>
    </div>
  )
  if (activeSubCategory === '多角度图') {
    return <>{uploadNotice}<SlotUploadGrid slots={MULTI_ANGLE_SLOTS} uploading={uploading} disabled={uploadDisabled} uploadFiles={uploadFiles} /></>
  }
  if (activeSubCategory === '跨境电商') {
    return <>{uploadNotice}<SlotUploadGrid slots={CROSS_BORDER_ECOMMERCE_SLOTS} uploading={uploading} disabled={uploadDisabled} uploadFiles={uploadFiles} /></>
  }
  if (activeSubCategory === '国内电商') {
    return <>{uploadNotice}<SlotUploadGrid slots={DOMESTIC_ECOMMERCE_SLOTS} uploading={uploading} disabled={uploadDisabled} uploadFiles={uploadFiles} /></>
  }
  return (
    <>{uploadNotice}<label className={`mb-5 flex min-h-28 items-center justify-center rounded-xl border border-dashed border-teal-300 bg-white/50 text-center text-sm font-bold text-teal-700 transition ${uploadDisabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-teal-50'}`}>
      {uploading ? '上传中...' : activeCategory === '06' ? '点击上传视频素材' : '点击上传图片素材'}
      <input
        id={inputId}
        type="file"
        multiple
        disabled={uploadDisabled}
        accept={activeCategory === '06' ? 'video/mp4,video/webm,video/quicktime,.mov' : activeCategory === '03' ? 'image/*,application/pdf,.pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx' : 'image/*'}
        className="hidden"
        onChange={event => {
          const input = event.currentTarget
          const files = input.files
          if (!files) return
          void uploadFiles(files).finally(() => { input.value = '' })
        }}
      />
    </label></>
  )
}

function SlotUploadGrid({
  slots,
  uploading,
  disabled,
  uploadFiles,
}: {
  slots: Array<{ key: string; label: string; accept: string }>
  uploading: boolean
  disabled: boolean
  uploadFiles: (files: FileList | File[], materialOverride?: string) => Promise<void>
}) {
  return (
    <div className="mb-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {slots.map(slot => (
        <label key={slot.key} className={`flex min-h-28 items-center justify-center rounded-xl border border-dashed border-teal-300 bg-white/55 text-center text-sm font-black text-teal-700 ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-teal-50'}`}>
          {uploading ? '上传中...' : slot.label}
          <input type="file" multiple accept={slot.accept} disabled={disabled} className="hidden" onChange={event => {
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

function BatchTagPanel({ pending, customInputs, setCustomInputs, tagPresets, canReview, onToggle, onCommit, onCancel }: {
  pending: Array<{ key: string; tag: string }>
  customInputs: Record<string, string>
  setCustomInputs: (value: Record<string, string>) => void
  tagPresets: Record<string, string[]>
  canReview: boolean
  onToggle: (key: string, tag: string) => void
  onCommit: () => void
  onCancel: () => void
}) {
  return (
    <div className="mb-4 rounded-xl border border-teal-200 bg-white/70 p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {pending.map(item => (
          <button key={`${item.key}-${item.tag}`} className="rounded-full bg-teal-100 px-2.5 py-1 text-xs font-bold text-teal-700" onClick={() => onToggle(item.key, item.tag)}>
            {getTagDisplayName(item.tag)} ×
          </button>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {TAG_DIMENSIONS.filter(dim => canReview || !['risk_tags', 'quality_check_tags'].includes(dim.key)).map(dim => (
            <div key={dim.key} className="rounded-lg bg-white/70 p-3">
              <div className="mb-2 text-xs font-black text-apple-gray-medium">{dim.label}</div>
              {dim.key === 'view_tags' && <div className="mb-2 text-[10px] leading-4 text-apple-gray-medium">多角度图的子标签，一张图选择一个视角。</div>}
              <div className="flex flex-wrap gap-1.5">
                {(tagPresets[dim.key] || []).map(tag => {
                const active = pending.some(item => item.key === dim.key && item.tag === tag)
                return (
                  <button key={tag} className={`rounded-full px-2 py-1 text-xs font-bold ${active ? 'bg-teal-600 text-white' : dim.color}`} onClick={() => onToggle(dim.key, tag)}>
                    {getTagDisplayName(tag)}
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

function AssetCard({ asset, selected, editingTags, customInputs, setCustomInputs, tagPresets, canManage, canEditTags, canReview, onToggleSelect, onOpenLightbox, onEdit, onDelete, onToggleTags, onAddTag, onRemoveTag }: {
  asset: ProductAsset
  selected: boolean
  editingTags: boolean
  customInputs: Record<string, string>
  setCustomInputs: (value: Record<string, string>) => void
  tagPresets: Record<string, string[]>
  canManage: boolean
  canEditTags: boolean
  canReview: boolean
  onToggleSelect: () => void
  onOpenLightbox: () => void
  onEdit: () => void
  onDelete: () => void
  onToggleTags: () => void
  onAddTag: (asset: ProductAsset, key: string, tag: string) => Promise<void>
  onRemoveTag: (asset: ProductAsset, key: string, tag: string) => Promise<void>
}) {
  const editableTagDimensions = TAG_DIMENSIONS.filter(dim => canReview || !['risk_tags', 'quality_check_tags'].includes(dim.key))
  const effectiveTags = getEffectiveAssetTags(asset)
  const categoryTags = effectiveTags.category_tags || []
  const materialTags = effectiveTags.material_type_tags || []
  const viewTags = effectiveTags.view_tags || []
  const renderTag = (key: string, tag: string) => {
    const dimension = TAG_DIMENSIONS.find(dim => dim.key === key)
    const color = dimension?.color || 'bg-stone-100 text-stone-700'
    const storedValues = (asset.tags as Record<string, string[]> | undefined)?.[key] || []
    const removable = storedValues.includes(tag)
    return canEditTags && removable && (canReview || !['risk_tags', 'quality_check_tags'].includes(key)) ? (
      <button key={`${key}-${tag}`} onClick={() => onRemoveTag(asset, key, tag)} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${color}`}>
        {getTagDisplayName(tag)} ×
      </button>
    ) : (
      <span key={`${key}-${tag}`} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${color}`}>
        {getTagDisplayName(tag)}
      </span>
    )
  }
  return (
    <article className={`group relative overflow-visible rounded-xl border bg-white/72 p-2 shadow-sm transition ${selected ? 'border-teal-400 ring-2 ring-teal-200' : 'border-black/5'}`}>
      {canEditTags && <button className={`absolute right-3 top-3 z-10 h-6 w-6 rounded-md border text-xs font-black ${selected ? 'border-teal-600 bg-teal-600 text-white' : 'border-white bg-white/80 text-transparent group-hover:text-teal-700'}`} onClick={onToggleSelect}>
          ✓
        </button>}
      <button className="relative block aspect-square w-full overflow-hidden rounded-lg bg-stone-100" onClick={onOpenLightbox}>
        {asset.asset_type === 'document' ? <div className="flex h-full items-center justify-center text-sm">📖 说明与客服资料</div> : asset.asset_type === 'video' ? (
          <div className="flex h-full flex-col items-center justify-center px-4 text-center">
            <div className="text-3xl">🎬</div>
            <div className="mt-2 text-sm font-black text-stone-700">{asset.notes || '视频素材'}</div>
          </div>
        ) : (
          <SecureImage src={asset.thumbnail_url || asset.url} alt={buildNamingFormat(asset)} className="h-full w-full object-cover" />
        )}
        <span className={`absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[11px] font-black ${getMaterialColor(asset.material_type)}`}>
          {getMaterialTypeDisplayName(asset.material_type)}
        </span>
      </button>
      <div className="mt-2 min-w-0">
        {asset.asset_type === 'document' && <ManualPreview url={asset.url} />}
        <div className="text-[11px] text-stone-600">关联SKU：{(asset.related_skus || [asset.sku]).join('、')}</div>
        <div className="truncate text-xs font-black text-apple-text" title={buildNamingFormat(asset)}>{buildNamingFormat(asset)}</div>
        <div className="mt-1 text-[11px] font-bold text-apple-gray-medium">{asset.sub_category || '未分类'} · {asset.status_tag || '待审核'}</div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1 text-[10px] font-bold text-stone-600">
        <span className="rounded-full bg-stone-100 px-2 py-0.5">质量：{asset.quality_status || 'usable'}</span>
        <span className="rounded-full bg-stone-100 px-2 py-0.5">重复：{asset.duplicate_status || 'unique'}</span>
        {asset.maintainer && <span className="rounded-full bg-stone-100 px-2 py-0.5">维护：{asset.maintainer}</span>}
        {asset.asset_type === 'video' && <span className="rounded-full bg-stone-100 px-2 py-0.5">时长：{effectiveTags.video_duration_status?.[0] === 'measured' ? `${effectiveTags.video_duration_seconds?.[0]} 秒` : '未验证'}</span>}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {categoryTags.length > 0 && <span className="flex items-center gap-1 rounded-lg border border-teal-100 bg-teal-50 px-1.5 py-0.5">
          <span className="text-[10px] font-black text-teal-700">归属</span>
          {categoryTags.map(tag => renderTag('category_tags', tag))}
        </span>}
        {materialTags.map(tag => renderTag('material_type_tags', tag))}
        {viewTags.length > 0 && <span className="flex items-center gap-1 rounded-lg border border-sky-100 bg-sky-50 px-1.5 py-0.5">
          <span className="text-[10px] font-black text-sky-700">{materialTags.includes('多角度图') ? '多角度子标签' : '视角'}</span>
          {viewTags.map(tag => renderTag('view_tags', tag))}
        </span>}
        {TAG_DIMENSIONS.filter(dim => !['category_tags', 'material_type_tags', 'view_tags'].includes(dim.key)).flatMap(dim => (effectiveTags[dim.key as keyof AssetTags] || []).map(tag => renderTag(dim.key, tag)))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        {canEditTags ? <button className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-teal-700" onClick={onToggleTags}>+ 标签</button> : <span />}
        {canManage && <div className="flex gap-1">
            <button className="rounded-full bg-white px-3 py-1.5 text-xs font-bold" onClick={onEdit}>编辑</button>
            <button className="rounded-full bg-red-50 px-3 py-1.5 text-xs font-bold text-red-600" onClick={onDelete}>删除</button>
          </div>}
      </div>
      {editingTags && (
        <div className="absolute left-2 right-2 top-[calc(100%-0.25rem)] z-20 rounded-xl border border-black/5 bg-white p-3 shadow-xl">
          {editableTagDimensions.map(dim => (
           <div key={dim.key} className="mb-3 last:mb-0">
              <div className="mb-1 text-[10px] font-black text-apple-gray-medium">{dim.label}</div>
              {dim.key === 'view_tags' && <div className="mb-1 text-[10px] leading-4 text-apple-gray-medium">多角度图的子标签，一张图选择一个视角。</div>}
              <div className="flex flex-wrap gap-1">
                {(tagPresets[dim.key] || []).slice(0, 8).map(tag => (
                  <button key={tag} className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${dim.color}`} onClick={() => onAddTag(asset, dim.key, tag)}>{getTagDisplayName(tag)}</button>
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

function AssetFieldGuide() {
  return <details className="my-3 rounded-xl border border-black/5 bg-white/70 p-3 text-sm">
    <summary className="cursor-pointer font-bold">素材字段定义与填写说明</summary>
    <dl className="mt-3 space-y-3">{ASSET_FIELD_GUIDE.map(field => <div key={field.name}><dt className="font-bold">{field.name}</dt><dd className="mt-1 text-xs leading-5 text-stone-600">{field.definition}</dd></div>)}</dl>
  </details>
}

function EditModal({ asset, form, error, setForm, qualityStatuses, duplicateStatuses, reviewStatuses, authorizationStatuses, taxonomyCategories, canReview, onClose, onSave }: {
  asset: ProductAsset
  form: EditForm
  error: string
  setForm: (value: EditForm) => void
  qualityStatuses: string[]
  duplicateStatuses: string[]
  reviewStatuses: string[]
  authorizationStatuses: string[]
  taxonomyCategories?: AssetCategoryDefinition[]
  canReview: boolean
  onClose: () => void
  onSave: () => void
}) {
  const categoryCode = form.category_code || asset.category_code
  const taxonomyCategory = taxonomyCategories?.find(item => item.code === categoryCode)
  const subCategories = taxonomyCategory
    ? taxonomyCategory.sub_categories.map(item => ({
        categoryCode,
        name: item.name,
        materialType: item.material_type,
      }))
    : getSubCategories(categoryCode)
  const currentSubCategory = form.sub_category || ''
  const currentIsKnown = subCategories.some(item => item.name === currentSubCategory)
  const placementSlots = currentSubCategory === '国内电商' ? DOMESTIC_ECOMMERCE_SLOTS
    : currentSubCategory === '跨境电商' ? CROSS_BORDER_ECOMMERCE_SLOTS : []
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4">
      <div className="glass max-h-[90vh] w-full max-w-3xl overflow-auto p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-black">编辑素材</h2>
          <button className="rounded-full bg-white px-3 py-1 text-sm font-bold" onClick={onClose}>关闭</button>
        </div>
        <AssetFieldGuide />
        {error && <div role="alert" className="mb-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <div className="aspect-square overflow-hidden rounded-xl bg-stone-100">
            {asset.asset_type === 'image' ? <SecureImage src={asset.thumbnail_url || asset.url} className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-3xl">🎬</div>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="品牌" value={form.brand || ''} onChange={value => setForm({ ...form, brand: value })} />
            <label className="text-xs font-bold text-apple-gray-medium">二级分类
              <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={currentSubCategory} onChange={event => {
                const selected = subCategories.find(item => item.name === event.target.value)
                if (selected) {
                  const language = selected.materialType === 'manualZh' ? 'CN' : selected.materialType === 'manualEn' ? 'EN' : null
                  setForm({ ...form, sub_category: selected.name, material_type: selected.materialType,
                    ...(language ? { language_tag: language, tags: { ...form.tags, language_tags: [language === 'CN' ? '中文' : '英文'] } } : {}) })
                }
              }}>
                {!currentIsKnown && <option value={currentSubCategory}>{currentSubCategory || '未分类'}（历史值，保留）</option>}
                {subCategories.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
              </select>
            </label>
            <div className="text-xs font-bold text-apple-gray-medium">素材形式 / 版位代码
              <div className="mt-1 rounded-lg bg-stone-50 px-3 py-3">{form.material_type || '未标注'}</div>
              <div className="mt-1 text-[11px] font-normal">随分类联动；电商版位单独选择，不混作渠道。</div>
            </div>
            {placementSlots.length > 0 && <label className="text-xs font-bold text-apple-gray-medium">电商版位
              <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.material_type || ''} onChange={event => setForm({ ...form, material_type: event.target.value })}>
                {!placementSlots.some(slot => slot.key === form.material_type) && <option value={form.material_type || ''}>未指定 / 历史值（保留）</option>}
                {placementSlots.map(slot => <option key={slot.key} value={slot.key}>{slot.label}</option>)}
              </select>
            </label>}
            <Field label="历史角度/场景备注（视角请在拍摄视角标签中标注）" value={form.angle_scene || ''} onChange={value => setForm({ ...form, angle_scene: value })} />
            <Field label="主渠道（兼容旧素材；全部适用渠道请在渠道标签中维护）" value={form.channel || ''} onChange={value => setForm({ ...form, channel: value })} />
            <Field label="语言" value={form.language_tag || ''} onChange={value => setForm({ ...form, language_tag: value })} />
            <Field label="版本" value={form.version_tag || ''} onChange={value => setForm({ ...form, version_tag: value })} />
            <Field label="日期" value={form.date_tag || ''} onChange={value => setForm({ ...form, date_tag: value })} />
            <Field label="素材维护人" value={form.maintainer || ''} onChange={value => setForm({ ...form, maintainer: value || null })} />
            {canReview ? <>
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
              <label className="text-xs font-bold text-apple-gray-medium">
                审核结论
                <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.review_status || 'pending'} onChange={event => setForm({ ...form, review_status: event.target.value })}>
                  {reviewStatuses.map(status => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <label className="text-xs font-bold text-apple-gray-medium">
                使用授权
                <select className="glass-input mt-1 h-10 w-full px-3 text-sm" value={form.authorization_status || 'unknown'} onChange={event => setForm({ ...form, authorization_status: event.target.value })}>
                  {authorizationStatuses.map(status => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <Field label="禁止用途说明" value={form.forbidden_usage || ''} onChange={value => setForm({ ...form, forbidden_usage: value || null })} />
              <div className="sm:col-span-2 rounded-xl border border-teal-100 bg-teal-50/60 p-3 text-xs text-teal-950">
                <div className="font-black">使用范围</div>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <BooleanField label="允许对外公开" checked={Boolean(form.is_public)} onChange={checked => setForm({ ...form, is_public: checked })} />
                  <BooleanField label="允许智能客服使用" checked={Boolean(form.ai_customer_usable)} onChange={checked => setForm({ ...form, ai_customer_usable: checked })} />
                  <BooleanField label="允许 AI 营销使用" checked={Boolean(form.ai_marketing_usable)} onChange={checked => setForm({ ...form, ai_marketing_usable: checked })} />
                  <BooleanField label="允许作为 AI 参考素材" checked={Boolean(form.ai_reference_usable)} onChange={checked => setForm({ ...form, ai_reference_usable: checked })} />
                </div>
                <p className="mt-2 leading-5">只有审核通过、使用授权为 approved/authorized、质量可用且非疑似重复时，系统才会保留公开和 AI 使用开关；否则保存时自动关闭。</p>
              </div>
            </> : <div className="sm:col-span-2 rounded-xl bg-slate-50 px-3 py-3 text-xs leading-5 text-slate-600">质量、重复和审核状态仅可由具备素材审核权限的账号修改。</div>}
            <Field label="备注" value={form.notes || ''} onChange={value => setForm({ ...form, notes: value })} />
            <Field label="关联SKU（主SKU始终保留）" value={(form.related_skus || [asset.sku]).join(', ')} onChange={value => setForm({ ...form, related_skus: value.split(/[,，\s]+/).filter(Boolean) })} />
            <Field label="可用性备注状态" value={form.availability_status || ''} onChange={value => setForm({ ...form, availability_status: value || null })} />
            <Field label="素材层级（兼容原媒体库）" value={form.material_layer || ''} onChange={value => setForm({ ...form, material_layer: value || null })} />
            <BooleanField label="仅参考（不进入AI参考素材）" checked={Boolean(form.reference_only)} onChange={checked => setForm({ ...form, reference_only: checked })} />
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

function ManualPreview({ url }: { url: string }) {
  const file = useSignedFileUrl(url)
  const [open, setOpen] = useState(false)
  if (/\.docx(?:\?|$)/i.test(url)) return <div className="text-sm text-slate-600">Word资料不在浏览器内预览，请使用下载按钮查阅。</div>
  return <div><button className="text-sm text-teal-700" onClick={() => setOpen(!open)}>📖 {open ? '收起说明书' : '预览说明书'}</button>{open && file.url && <iframe title="PDF说明书预览" src={file.url} className="w-full h-96" />}</div>
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs font-bold text-apple-gray-medium">
      {label}
      <input className="glass-input mt-1 h-10 w-full px-3 text-sm" value={value} onChange={event => onChange(event.target.value)} />
    </label>
  )
}

function BooleanField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="flex items-center gap-2 font-bold"><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} />{label}</label>
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
