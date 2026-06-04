import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, type CategoryItem } from '../services/api'
import type { Product, ProductMediaItem } from '../types'
import L1L4Importer from '../components/ProductImport/L1L4Importer'
import L5Importer from '../components/ProductImport/L5Importer'

export default function ProductManagement() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Product | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [categoryOptions, setCategoryOptions] = useState<CategoryItem[]>([])
  const [deleteConfirmSku, setDeleteConfirmSku] = useState<string | null>(null)
  const [activeLayer, setActiveLayer] = useState<string>('L1')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [advancedFilters, setAdvancedFilters] = useState({
    brand: '',
    series: '',
    category: '',
    sub_category: '',
    product_level: '',
    lifecycle_status: '',
    person_in_charge: '',
    quality_note: '',
    capacity: '',
    body_material: '',
    color: '',
    heat_source: '',
    gross_weight_min: '',
    gross_weight_max: '',
    channel: '',
    region: '',
    certification: '',
    search_keyword: '',
  })

  useEffect(() => {
    loadProducts()
  }, [])

  useEffect(() => {
    const skuFromUrl = searchParams.get('sku')
    if (!skuFromUrl) return
    selectProductBySku(skuFromUrl)
  }, [searchParams])

  useEffect(() => {
    const layerFromUrl = searchParams.get('layer')
    if (!layerFromUrl) return
    setActiveLayer(layerFromUrl)
  }, [searchParams])

  useEffect(() => {
    api.categories.list().then(setCategoryOptions).catch(() => {})
  }, [])

  async function loadProducts() {
    setLoading(true)
    try {
      const result = await api.products.list(0, 100)
      setProducts(result.items)
      const skuFromUrl = searchParams.get('sku')
      if (skuFromUrl) {
        await selectProductBySku(skuFromUrl, result.items)
      }
    } catch (err) {
      console.error('Failed to load products:', err)
    } finally {
      setLoading(false)
    }
  }

  async function selectProductBySku(sku: string, currentProducts = products) {
    const normalized = sku.trim()
    if (!normalized) return
    const existing = currentProducts.find((p) => p.sku.toLowerCase() === normalized.toLowerCase())
    if (existing && selected?.sku !== existing.sku) {
      setSelected(existing)
    }
    try {
      const detail = await api.products.get(normalized)
      setSelected(detail)
      setProducts((prev) => {
        if (prev.some((p) => p.sku === detail.sku)) {
          return prev.map((p) => p.sku === detail.sku ? { ...p, ...detail } : p)
        }
        return [detail, ...prev]
      })
    } catch (err) {
      console.error('Failed to load selected product:', err)
    }
  }

  function handleSelectProduct(product: Product) {
    setSelected(product)
    const next = new URLSearchParams(searchParams)
    next.set('sku', product.sku)
    setSearchParams(next, { replace: true })
    selectProductBySku(product.sku)
  }

  async function handleDelete(sku: string) {
    try {
      await api.products.delete(sku)
      setProducts(products.filter(p => p.sku !== sku))
      if (selected?.sku === sku) setSelected(null)
      setDeleteConfirmSku(null)
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  async function handleAdvancedSearch() {
    setLoading(true)
    try {
      const payload: Record<string, unknown> = {
        keyword: searchQuery,
        skip: 0,
        limit: 100,
        sort_by: 'updated_at',
        sort_order: 'desc',
      }
      Object.entries(advancedFilters).forEach(([key, value]) => {
        if (value !== '') payload[key] = value
      })
      if (payload.gross_weight_min) payload.gross_weight_min = Number(payload.gross_weight_min)
      if (payload.gross_weight_max) payload.gross_weight_max = Number(payload.gross_weight_max)
      const result = await api.products.advancedSearch(payload)
      setProducts(result.items as Product[])
      setSelected(null)
      const next = new URLSearchParams(searchParams)
      next.delete('sku')
      setSearchParams(next, { replace: true })
    } catch (err) {
      console.error('Advanced search failed:', err)
    } finally {
      setLoading(false)
    }
  }

  function updateAdvancedFilter(key: keyof typeof advancedFilters, value: string) {
    setAdvancedFilters((prev) => ({ ...prev, [key]: value }))
  }

  async function resetAdvancedSearch() {
    setAdvancedFilters({
      brand: '',
      series: '',
      category: '',
      sub_category: '',
      product_level: '',
      lifecycle_status: '',
      person_in_charge: '',
      quality_note: '',
      capacity: '',
      body_material: '',
      color: '',
      heat_source: '',
      gross_weight_min: '',
      gross_weight_max: '',
      channel: '',
      region: '',
      certification: '',
      search_keyword: '',
    })
    setSearchQuery('')
    setCategoryFilter('')
    const next = new URLSearchParams(searchParams)
    next.delete('sku')
    setSearchParams(next, { replace: true })
    await loadProducts()
  }

  const filteredProducts = products.filter(p => {
    const matchesSearch = p.sku.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.product_name_cn?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.product_name_en?.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesCategory = !categoryFilter || p.category === categoryFilter
    return matchesSearch && matchesCategory
  })

  const getImageUrl = (img: string) => {
    if (img.startsWith('http')) return img
    if (img.startsWith('/')) return `http://192.168.3.109:8000${img}`
    return img
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text tracking-tight">产品管理</h1>
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/products/drafts')}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors">
            📋 草稿箱
          </button>
          <button onClick={() => navigate('/products/create')}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors">
            + 新增产品
          </button>
          <L1L4Importer onImportComplete={loadProducts} />
          <L5Importer onImportComplete={loadProducts} />
        </div>
      </div>

      <div className="flex gap-3 mb-4">
        <input
          type="text"
          placeholder="搜索产品 SKU 或名称..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 px-4 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="w-44 px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
        >
          <option value="">全部品类</option>
          {categoryOptions.map(cat => (
            <option key={cat.id} value={cat.category_name}>{cat.category_name}</option>
          ))}
        </select>
        <button
          onClick={() => setAdvancedOpen(!advancedOpen)}
          className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
        >
          数据库查询
        </button>
      </div>

      {advancedOpen && (
        <div className="glass rounded-xl p-4 mb-4">
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
            <SearchField label="品牌" value={advancedFilters.brand} onChange={(v) => updateAdvancedFilter('brand', v)} />
            <SearchField label="系列" value={advancedFilters.series} onChange={(v) => updateAdvancedFilter('series', v)} />
            <SearchField label="类目" value={advancedFilters.category} onChange={(v) => updateAdvancedFilter('category', v)} />
            <SearchField label="子类目" value={advancedFilters.sub_category} onChange={(v) => updateAdvancedFilter('sub_category', v)} />
            <SearchField label="产品等级" value={advancedFilters.product_level} onChange={(v) => updateAdvancedFilter('product_level', v)} />
            <SearchField label="生命周期" value={advancedFilters.lifecycle_status} onChange={(v) => updateAdvancedFilter('lifecycle_status', v)} />
            <SearchField label="负责人" value={advancedFilters.person_in_charge} onChange={(v) => updateAdvancedFilter('person_in_charge', v)} />
            <SearchField label="品质情况" value={advancedFilters.quality_note} onChange={(v) => updateAdvancedFilter('quality_note', v)} />
            <SearchField label="容量" value={advancedFilters.capacity} onChange={(v) => updateAdvancedFilter('capacity', v)} />
            <SearchField label="材质" value={advancedFilters.body_material} onChange={(v) => updateAdvancedFilter('body_material', v)} />
            <SearchField label="颜色" value={advancedFilters.color} onChange={(v) => updateAdvancedFilter('color', v)} />
            <SearchField label="适用热源" value={advancedFilters.heat_source} onChange={(v) => updateAdvancedFilter('heat_source', v)} />
            <SearchField label="最小重量g" value={advancedFilters.gross_weight_min} onChange={(v) => updateAdvancedFilter('gross_weight_min', v)} />
            <SearchField label="最大重量g" value={advancedFilters.gross_weight_max} onChange={(v) => updateAdvancedFilter('gross_weight_max', v)} />
            <SearchField label="渠道" value={advancedFilters.channel} onChange={(v) => updateAdvancedFilter('channel', v)} />
            <SearchField label="地区" value={advancedFilters.region} onChange={(v) => updateAdvancedFilter('region', v)} />
            <SearchField label="认证" value={advancedFilters.certification} onChange={(v) => updateAdvancedFilter('certification', v)} />
            <SearchField label="关键词" value={advancedFilters.search_keyword} onChange={(v) => updateAdvancedFilter('search_keyword', v)} />
          </div>
          <div className="flex items-center gap-3 mt-4">
            <button onClick={handleAdvancedSearch} className="btn-primary px-5 py-2 text-sm">查询产品</button>
            <button onClick={resetAdvancedSearch} className="px-4 py-2 text-sm text-apple-gray-dark hover:text-apple-text">清空条件</button>
            <span className="text-sm text-apple-gray-medium">查询结果会直接显示在下方产品列表中。</span>
          </div>
        </div>
      )}

      {filteredProducts.length === 0 ? (
        <div className="glass p-12 text-center">
          <p className="text-apple-gray-medium">暂无产品数据</p>
          <p className="text-sm text-apple-gray-medium/60 mt-1">点击右上角"+ 新增产品"开始录入</p>
        </div>
      ) : (
        <div className="grid grid-cols-[280px_1fr] gap-4">
          <div className="glass divide-y divide-black/5 min-h-0 h-[calc(100vh-10rem)] flex flex-col rounded-xl">
            <div className="flex-1 overflow-y-auto scrollbar-thin divide-y divide-black/5">
              {filteredProducts.map((product) => (
                <div
                  key={product.sku}
                  onClick={() => handleSelectProduct(product)}
                  className={`p-3 cursor-pointer transition-colors ${selected?.sku === product.sku ? 'bg-blue-50' : 'hover:bg-white/50'}`}
                >
                  <div className="flex items-center gap-2">
                    <div className="font-medium text-apple-text text-sm">{product.sku}</div>
                    {product.category && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded-full font-medium">{product.category}</span>
                    )}
                  </div>
                  <div className="text-xs text-apple-gray-medium mt-0.5">
                    {product.product_name_cn || product.product_name_en || '未命名'}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {selected ? (
            <div className="glass rounded-xl flex flex-col min-h-0 h-[calc(100vh-10rem)]">
              {/* Sticky header with edit/delete */}
              <div className="flex items-center justify-between p-5 pb-3 border-b border-gray-100 shrink-0">
                <div>
                  <h2 className="text-lg font-semibold text-apple-text">{selected.sku}</h2>
                  <p className="text-sm text-apple-gray-medium mt-0.5">{selected.product_name_cn || selected.product_name_en || '-'}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => navigate(`/products/edit/${selected.sku}`)} className="px-3 py-1.5 text-sm text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors">编辑</button>
                  <button onClick={() => setDeleteConfirmSku(selected.sku)} className="px-3 py-1.5 text-sm text-red-500 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors">删除</button>
                </div>
              </div>

              {deleteConfirmSku === selected.sku && (
                <div className="bg-red-50 border-b border-red-200 px-5 py-3 shrink-0">
                  <p className="text-sm text-red-600">确认删除产品 {selected.sku} 吗？此操作不可撤销。</p>
                  <div className="flex justify-end gap-2 mt-2">
                    <button onClick={() => setDeleteConfirmSku(null)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">取消</button>
                    <button onClick={() => handleDelete(selected.sku)} className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-100 rounded-lg">确认删除</button>
                  </div>
                </div>
              )}

              {/* Horizontal layer tabs */}
              <div className="flex gap-0 px-3 border-b border-gray-100 shrink-0 overflow-x-auto scrollbar-thin">
                {[
                  { id: 'L1', icon: '🏷️', label: '产品身份' },
                  { id: 'L2', icon: '📐', label: '物理规格' },
                  { id: 'L3', icon: '💼', label: '商业价值' },
                  { id: 'L4', icon: '📝', label: '内容素材' },
                  { id: 'L5', icon: '📚', label: '知识库' },
                  { id: 'L6', icon: '🖼️', label: '多媒体' },
                  { id: 'L7', icon: '🎯', label: '内容生成' },
                ].map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => {
                      setActiveLayer(tab.id)
                      const next = new URLSearchParams(searchParams)
                      if (selected?.sku) next.set('sku', selected.sku)
                      next.set('layer', tab.id)
                      setSearchParams(next, { replace: true })
                    }}
                    className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium whitespace-nowrap border-b-2 transition-colors ${
                      activeLayer === tab.id
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-apple-gray-medium hover:text-apple-text hover:border-gray-300'
                    }`}
                  >
                    <span>{tab.icon}</span>
                    <span className="hidden sm:inline">{tab.label}</span>
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-y-auto scrollbar-thin p-5">
                {activeLayer === 'L1' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">🏷️ L1 - 产品身份</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">条形码</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.barcode || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">商品中文名称</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.product_name_cn || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">商品英文名称</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.product_name_en || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-gray-medium">上架渠道</div>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selected.channels?.length ? selected.channels.map((ch, i) => (
                            <span key={i} className="px-2 py-0.5 bg-blue-100 text-blue-600 text-xs rounded-full">{ch.channel_name}</span>
                          )) : <span className="text-sm text-apple-gray-medium">-</span>}
                        </div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-gray-medium">售卖地区</div>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selected.regions?.length ? selected.regions.map((r, i) => (
                            <span key={i} className="px-2 py-0.5 bg-green-100 text-green-600 text-xs rounded-full">{r.region_name}</span>
                          )) : <span className="text-sm text-apple-gray-medium">-</span>}
                        </div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">品牌</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.brand || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">系列</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.series || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">系统分类</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.category || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">商品分级</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.product_level || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">上市时间</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.launch_date || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">生命周期</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.lifecycle_status || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">负责人</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.person_in_charge || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">品质情况</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.quality_note || '-'}</div>
                      </div>
                    </div>
                  </div>
                )}

                {activeLayer === 'L2' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">📐 L2 - 物理规格</h3>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">毛重</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.gross_weight_g ? `${selected.specs.gross_weight_g} g` : '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">材质</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.body_material || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">表面处理</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.surface_finish || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">主色系</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.color || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">热源类型</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.heat_source || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">功率</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.specs?.power || '-'}</div>
                      </div>
                    </div>
                    {(selected.specs?.size_info != null) && (
                      <div className="mt-3 bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text mb-2">尺寸规格</div>
                        <div className="text-sm text-apple-text whitespace-pre-wrap">{typeof selected.specs.size_info === 'string' ? selected.specs.size_info : JSON.stringify(selected.specs.size_info, null, 2)}</div>
                      </div>
                    )}
                    {selected.certifications?.length ? (
                      <div className="mt-3 bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-gray-medium mb-2">认证信息</div>
                        <div className="flex flex-wrap gap-2">
                          {selected.certifications.map((cert, i) => (
                            <span key={i} className="px-2 py-1 bg-blue-50 text-blue-600 text-xs rounded-full">{cert.certification_name}</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {(selected.specs?.technical_advantages != null) && (
                      <div className="mt-3 bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text mb-2">技术优势</div>
                        <div className="text-sm text-apple-text whitespace-pre-wrap">{typeof selected.specs.technical_advantages === 'string' ? selected.specs.technical_advantages : Array.isArray(selected.specs.technical_advantages) ? selected.specs.technical_advantages.join(', ') : JSON.stringify(selected.specs.technical_advantages)}</div>
                      </div>
                    )}
                    {selected.specs?.capacity != null && (
                      <div className="mt-3 bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text mb-2">容量信息</div>
                        <div className="text-sm text-apple-text whitespace-pre-wrap">{typeof selected.specs.capacity === 'string' ? selected.specs.capacity : JSON.stringify(selected.specs.capacity, null, 2)}</div>
                      </div>
                    )}
                    {selected.specs?.usage_instruction && (
                      <div className="mt-3 bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text mb-2">使用说明</div>
                        <div className="text-sm text-apple-text whitespace-pre-wrap">{selected.specs.usage_instruction}</div>
                      </div>
                    )}
                  </div>
                )}

                {activeLayer === 'L3' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">💼 L3 - 商业价值</h3>
                    <div className="space-y-3">
                      {(selected.business?.top_selling_points != null) && (
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-gray-medium mb-2">核心卖点</div>
                          <div className="text-sm text-apple-text whitespace-pre-wrap">{Array.isArray(selected.business.top_selling_points) ? selected.business.top_selling_points.filter(Boolean).join(', ') : String(selected.business.top_selling_points)}</div>
                        </div>
                      )}
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text">目标人群</div>
                          <div className="text-sm font-medium text-apple-text mt-1">{(selected.business?.target_audience || '').split(',').filter(Boolean).join(', ') || '-'}</div>
                        </div>
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text">差异化定位</div>
                          <div className="text-sm font-medium text-apple-text mt-1">{selected.business?.positioning || '-'}</div>
                        </div>
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text">价格定位</div>
                          <div className="text-sm font-medium text-apple-text mt-1">{selected.business?.price_positioning || '-'}</div>
                        </div>
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text">情感价值</div>
                          <div className="text-sm font-medium text-apple-text mt-1">{selected.business?.emotional_value || '-'}</div>
                        </div>
                      </div>
                      {(Array.isArray(selected.business?.usage_scenarios) && (selected.business?.usage_scenarios as string[]).filter(Boolean).length > 0) && (
                        <div className="mt-3 bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-gray-medium mb-2">使用场景</div>
                          <div className="text-sm text-apple-text whitespace-pre-wrap">{(selected.business!.usage_scenarios as string[]).filter(Boolean).join(', ')}</div>
                        </div>
                      )}
                      {(Array.isArray(selected.business?.competitor_benchmark) && (selected.business?.competitor_benchmark as any[]).length > 0) && (
                        <div className="mt-3 bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-gray-medium mb-2">竞品对标</div>
                          <div className="text-sm text-apple-text whitespace-pre-wrap">{typeof selected.business.competitor_benchmark === 'string' ? selected.business.competitor_benchmark : JSON.stringify(selected.business.competitor_benchmark)}</div>
                        </div>
                      )}
                      {!(selected.business?.top_selling_points != null || selected.business?.target_audience || selected.business?.positioning || selected.business?.price_positioning || selected.business?.emotional_value || (Array.isArray(selected.business?.usage_scenarios) && (selected.business?.usage_scenarios as string[]).filter(Boolean).length > 0) || (Array.isArray(selected.business?.competitor_benchmark) && (selected.business?.competitor_benchmark as any[]).length > 0)) && (
                        <div className="text-sm text-apple-gray-medium">暂无商业价值数据</div>
                      )}
                    </div>
                  </div>
                )}

                {activeLayer === 'L4' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">📝 L4 - 内容素材</h3>
                    <div className="space-y-3">
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">标题（英文）</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.content?.title_en || selected.content?.amazon_title || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">标题（中文）</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.content?.title_cn || selected.content?.website_title || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">产品长描述（英文）</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.content?.long_description_en || '-'}</div>
                      </div>
                      <div className="bg-white/50 rounded-lg p-3">
                        <div className="text-xs text-apple-text">产品长描述（中文）</div>
                        <div className="text-sm font-medium text-apple-text mt-1">{selected.content?.long_description_cn || '-'}</div>
                      </div>
                      {(Array.isArray(selected.content?.bullet_points) && (selected.content?.bullet_points as string[]).filter(Boolean).length > 0) && (
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text mb-2">5 点描述</div>
                          <div className="text-sm text-apple-text whitespace-pre-wrap">{(selected.content!.bullet_points as string[]).filter(Boolean).map((b: string, i: number) => `${i + 1}. ${b}`).join('\n')}</div>
                        </div>
                      )}
                      {(Array.isArray(selected.content?.search_keywords) && (selected.content?.search_keywords as any[]).length > 0) && (
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-gray-medium mb-2">搜索关键词库</div>
                          <div className="flex flex-wrap gap-2">
                            {(selected.content!.search_keywords as any[]).map((kw: any, i: number) => (
                              <span key={i} className={`px-2 py-1 text-xs rounded-full ${
                                typeof kw === 'object' && kw.priority === 'A' ? 'bg-red-50 text-red-600' :
                                typeof kw === 'object' && kw.priority === 'B' ? 'bg-yellow-50 text-yellow-600' :
                                typeof kw === 'object' && kw.priority === 'C' ? 'bg-green-50 text-green-600' :
                                'bg-green-50 text-green-600'
                              }`}>
                                {typeof kw === 'string' ? kw : `${kw.keyword} [${kw.priority}]`}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {activeLayer === 'L5' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">📚 L5 - 知识库层</h3>
                    <div className="space-y-3">
                      {(selected.qa_items?.length || 0) > 0 && (
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text mb-2">常见问题 Q&A 库</div>
                          <div className="space-y-2">
                            {selected.qa_items!.map((qa, i) => (
                              <div key={i} className="text-sm">
                                <span className="text-blue-600 font-medium">Q{i + 1}: {qa.question}</span>
                                <span className="block mt-0.5 text-apple-gray-medium">A: {qa.answer}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {selected.qa_negative && (
                        <div className="bg-white/50 rounded-lg p-3">
                          <div className="text-xs text-apple-text mb-2">差评高频词及应对话术</div>
                          <div className="text-sm text-apple-text whitespace-pre-wrap">
                            <div><span className="font-medium text-red-500">高频差评词: </span>{selected.qa_negative.high_freq_negative_words || '-'}</div>
                            <div className="mt-1"><span className="font-medium text-green-600">应对话术: </span>{selected.qa_negative.response_tone || '-'}</div>
                          </div>
                        </div>
                      )}
                      {!((selected.qa_items?.length || 0) > 0 || selected.qa_negative) && (
                        <div className="text-sm text-apple-gray-medium">暂无知识库数据</div>
                      )}
                    </div>
                  </div>
                )}

                {activeLayer === 'L6' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">🖼️ L6 - 多媒体资产</h3>
                    <div className="space-y-3">
                      {selected.media?.length ? (
                        (() => {
                          const layerLabels: Record<string, string> = {
                            source: '原始素材层', ai: 'AI 生成图层', channel: '渠道层',
                            social: '社媒层', ref: '参考辅助层',
                          }
                          const grouped = new Map<string, ProductMediaItem[]>()
                          for (const m of selected.media) {
                            const layer = m.media_layer || 'source'
                            if (!grouped.has(layer)) grouped.set(layer, [])
                            grouped.get(layer)!.push(m)
                          }
                          return Array.from(grouped.entries()).map(([layer, items]) => (
                            <div key={layer} className="bg-white/50 rounded-lg p-3">
                              <div className="text-xs font-semibold text-apple-text mb-2">{layerLabels[layer] || layer}</div>
                              <div className="grid grid-cols-4 gap-2">
                                {items.map((m) => (
                                  <div key={m.id} className="relative group">
                                    {m.file_url ? (
                                      <img src={getImageUrl(m.file_url)} alt={m.file_name} className="w-full aspect-square object-cover rounded-lg" />
                                    ) : (
                                      <div className="w-full aspect-square bg-gray-100 rounded-lg flex items-center justify-center text-xs text-apple-gray-medium">{m.file_name || '-'}</div>
                                    )}
                                    <div className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[10px] px-1 py-0.5 rounded-b-lg truncate">
                                      {m.media_group}{m.channel_name ? ` · ${m.channel_name}` : ''}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))
                        })()
                      ) : (
                        <div className="text-sm text-apple-gray-medium">暂无多媒体资产</div>
                      )}
                    </div>
                  </div>
                )}

                {activeLayer === 'L7' && (
                  <div>
                    <h3 className="text-sm font-semibold text-apple-text mb-3">🎯 L7 - 内容生成层</h3>
                    <div className="space-y-3">
                      {selected.prompts?.length ? (
                        (() => {
                          const imagePrompts = selected.prompts.filter(p => p.prompt_type === 'image')
                          const videoPrompts = selected.prompts.filter(p => p.prompt_type === 'video')
                          return (
                            <>
                              {imagePrompts.length > 0 && (
                                <div className="bg-white/50 rounded-lg p-3">
                                  <div className="text-xs font-semibold text-apple-text mb-2">🖼️ 图像提示词模板</div>
                                  <div className="space-y-2">
                                    {imagePrompts.map((p, i) => (
                                      <div key={p.id} className="bg-gray-50 rounded p-2">
                                        <div className="text-sm font-medium text-apple-text">{p.prompt_name || `模板${i + 1}`}{p.version ? ` (v${p.version})` : ''}</div>
                                        <div className="text-xs text-apple-gray-medium mt-1 whitespace-pre-wrap">{p.prompt_text || '-'}</div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {videoPrompts.length > 0 && (
                                <div className="bg-white/50 rounded-lg p-3">
                                  <div className="text-xs font-semibold text-apple-text mb-2">🎬 视频提示词模板</div>
                                  <div className="space-y-2">
                                    {videoPrompts.map((p, i) => (
                                      <div key={p.id} className="bg-gray-50 rounded p-2">
                                        <div className="text-sm font-medium text-apple-text">{p.prompt_name || `模板${i + 1}`}{p.version ? ` (v${p.version})` : ''}</div>
                                        <div className="text-xs text-apple-gray-medium mt-1 whitespace-pre-wrap">{p.prompt_text || '-'}</div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </>
                          )
                        })()
                      ) : (
                        <div className="text-sm text-apple-gray-medium">暂无提示词模板</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="glass rounded-xl p-12 text-center">
              <p className="text-apple-gray-medium">选择左侧产品查看详情</p>
            </div>
          )}
        </div>
      )}

    </div>
  )
}

function SearchField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="block text-[11px] font-medium text-apple-gray-dark mb-1">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} className="glass-input w-full px-3 py-2 text-sm" />
    </label>
  )
}
