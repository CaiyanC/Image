import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, type ProductAuditItem } from '../services/api'
import type { Product } from '../types'
import { useAuthStore } from '../store/authStore'

const BASE_FIELDS = [
  'sku', 'barcode', 'product_name_cn', 'product_name_en', 'brand', 'series',
  'category', 'sub_category', 'product_level', 'launch_date', 'lifecycle_status',
  'person_in_charge', 'active_flag', 'sync_flag', 'quality_note', 'status_note',
]

const SPEC_FIELDS = [
  'size_info', 'capacity', 'gross_weight_g', 'body_material', 'color',
  'surface_finish', 'heat_source', 'power', 'technical_advantages', 'usage_instruction',
]

const BUSINESS_FIELDS = [
  'top_selling_points', 'target_audience', 'positioning', 'price_positioning',
  'emotional_value', 'usage_scenarios', 'competitor_benchmark',
]

const CONTENT_FIELDS = [
  'title_en', 'title_cn', 'long_description_en', 'long_description_cn',
  'long_description_ja', 'amazon_title', 'website_title', 'bullet_points',
  'a_plus_content', 'listing_cn', 'listing_en', 'listing_ja', 'search_keywords',
]

const QA_FIELDS = ['question', 'answer', 'tags', 'priority', 'integrity_status']
const NEGATIVE_QA_FIELDS = ['high_freq_negative_words', 'response_tone', 'priority']
const CHANNEL_FIELDS = ['channel_name']
const REGION_FIELDS = ['region_name']
const CERTIFICATION_FIELDS = ['certification_name', 'certification_code', 'description']
const KEYWORD_FIELDS = ['keyword', 'keyword_level']

const MEDIA_FIELDS = [
  'media_layer', 'media_group', 'media_type', 'channel_name', 'page_type',
  'media_version', 'file_name', 'file_url', 'media_level', 'is_real_product',
  'is_ai_generated', 'is_competitor', 'is_public', 'ai_customer_usable',
  'ai_marketing_usable', 'ai_reference_usable', 'editable_flag', 'review_status',
  'authorization_status', 'forbidden_usage', 'language', 'tag_list',
]

const ASSET_FIELDS = [
  'category_name', 'sub_category', 'asset_type', 'file_name', 'url', 'material_type',
  'angle_scene', 'channel', 'language_tag', 'version_tag', 'product_version',
  'market_version', 'status_tag', 'quality_status', 'quality_reason',
  'duplicate_status', 'asset_level', 'is_real_product', 'is_ai_generated',
  'is_competitor', 'is_latest_version', 'is_public', 'ai_customer_usable',
  'ai_marketing_usable', 'ai_reference_usable', 'editable_flag', 'review_status',
  'authorization_status', 'forbidden_usage', 'maintainer', 'tags', 'notes',
]

const PROMPT_FIELDS = ['prompt_name', 'prompt_type', 'prompt_text', 'version']

const FIELD_LABELS: Record<string, string> = {
  sku: 'SKU', barcode: '条形码', product_name_cn: '中文产品名', product_name_en: '英文产品名',
  brand: '品牌', series: '系列', category: '品类', sub_category: '子品类', product_level: '产品等级',
  launch_date: '上市时间', lifecycle_status: '生命周期', person_in_charge: '负责人',
  active_flag: '启用状态', sync_flag: '知识库同步', quality_note: '质量备注', status_note: '状态备注',
  size_info: '尺寸信息', capacity: '容量信息', gross_weight_g: '毛重（g）', body_material: '主体材质',
  color: '主色系', surface_finish: '表面处理', heat_source: '适用热源', power: '功率',
  technical_advantages: '技术优势', usage_instruction: '使用说明', top_selling_points: '核心卖点',
  target_audience: '目标人群', positioning: '差异化定位', price_positioning: '价格定位',
  emotional_value: '情感价值', usage_scenarios: '使用场景', competitor_benchmark: '竞品对标',
  title_en: '英文标题', title_cn: '中文标题', long_description_en: '英文长描述',
  long_description_cn: '中文长描述', long_description_ja: '日文长描述', amazon_title: 'Amazon 标题',
  website_title: '网站标题', bullet_points: '五点描述', a_plus_content: 'A+ 内容',
  listing_cn: '中文 Listing', listing_en: '英文 Listing', listing_ja: '日文 Listing',
  search_keywords: '搜索关键词', question: '问题', answer: '回答', tags: '标签', priority: '优先级',
  integrity_status: '审核状态', high_freq_negative_words: '高频差评词', response_tone: '应对话术',
  channel_name: '渠道', region_name: '销售地区', certification_name: '认证名称',
  certification_code: '认证编号', description: '说明', keyword: '关键词', keyword_level: '关键词等级',
  media_layer: '素材层', media_group: '素材分组', media_type: '素材类型', page_type: '页面类型',
  media_version: '素材版本', file_name: '文件名', file_url: '文件链接', media_level: '素材等级',
  is_real_product: '真实产品', is_ai_generated: 'AI 生成', is_competitor: '竞品素材',
  is_public: '公开可用', ai_customer_usable: '客服可用', ai_marketing_usable: '营销可用',
  ai_reference_usable: '参考可用', editable_flag: '允许编辑', review_status: '审核状态',
  authorization_status: '授权状态', forbidden_usage: '禁止用途', language: '语言', tag_list: '标签',
  category_name: '素材分类', asset_type: '素材类型', url: '素材链接', material_type: '素材类型标签',
  angle_scene: '角度/场景', channel: '渠道', language_tag: '语言标签', version_tag: '版本标签',
  product_version: '产品版本', market_version: '市场版本', status_tag: '状态标签', quality_status: '质量状态',
  quality_reason: '质量原因', duplicate_status: '重复状态', asset_level: '素材等级',
  is_latest_version: '最新版本', maintainer: '维护人', notes: '备注', prompt_name: '提示词名称',
  prompt_type: '提示词类型', prompt_text: '提示词内容', version: '版本',
}

const HIDDEN_NESTED_FIELDS = new Set(['id', 'product_id', 'created_at', 'updated_at', 'seq', 'sort_order', 'checksum_sha256', 'duplicate_of_asset_id', 'file_path', 'thumbnail_url', 'file_size_bytes', 'mime_type', 'width', 'height', 'resolution', 'aspect_ratio'])

function labelFor(key: string) {
  return FIELD_LABELS[key] || '其他资料'
}

function isLinkField(key: string, value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return false
  return ['url', 'file_url'].includes(key) || value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/uploads/')
}

function formatText(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '暂无'
  if (typeof value === 'boolean') {
    if (key === 'active_flag') return value ? '已启用' : '未启用'
    if (key === 'sync_flag') return value ? '已同步' : '待同步'
    return value ? '是' : '否'
  }
  if (typeof value === 'string') return value.trim() || '暂无'
  if (Array.isArray(value)) {
    if (!value.length) return '暂无'
    if (key === 'bullet_points') return value.map((item, index) => `${index + 1}. ${formatText(key, item)}`).join('\n')
    return value.map((item) => formatText(key, item)).filter((item) => item !== '暂无').join('、') || '暂无'
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value).filter(([nestedKey]) => !HIDDEN_NESTED_FIELDS.has(nestedKey))
    if (!entries.length) return '暂无'
    return entries.map(([nestedKey, nestedValue]) => `${labelFor(nestedKey)}：${formatText(nestedKey, nestedValue)}`).join('\n')
  }
  return String(value)
}

function DisplayValue({ field, value }: { field: string; value: unknown }) {
  if (isLinkField(field, value)) {
    const href = String(value)
    const safeHref = href.startsWith('http://') || href.startsWith('https://') || href.startsWith('/uploads/') ? href : undefined
    return safeHref ? <a href={safeHref} target="_blank" rel="noreferrer" className="font-semibold text-teal-700 underline underline-offset-2">打开链接</a> : <span>暂无</span>
  }
  return <span>{formatText(field, value)}</span>
}

function FieldGrid({ data, fields }: { data: Record<string, unknown> | null | undefined; fields: string[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {fields.map((field) => {
        const value = data?.[field]
        const empty = value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)
        return (
          <div key={field} className={`rounded-2xl border border-black/5 p-3 ${empty ? 'bg-slate-50/70' : 'bg-white/75'}`}>
            <div className="text-xs font-bold text-apple-gray-medium">{labelFor(field)}</div>
            <div className={`mt-1 whitespace-pre-wrap break-words text-sm leading-6 ${empty ? 'text-slate-400' : 'text-apple-text'}`}>
              <DisplayValue field={field} value={value} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl border border-black/5 bg-white/70 p-4 shadow-sm sm:p-5">
      <div className="mb-4 flex flex-wrap items-baseline gap-2">
        <h2 className="text-lg font-black text-apple-text">{title}</h2>
        {hint && <span className="text-xs text-apple-gray-medium">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

function CollectionSection({ title, items, fields, emptyText }: { title: string; items: unknown[] | undefined; fields: string[]; emptyText: string }) {
  return (
    <Section title={`${title}（${items?.length || 0}）`}>
      {items?.length ? (
        <div className="space-y-3">
          {items.map((item, index) => (
            <div key={index} className="rounded-2xl border border-black/5 bg-white/65 p-3">
              {item && typeof item === 'object' ? <FieldGrid data={item as Record<string, unknown>} fields={fields} /> : <div className="whitespace-pre-wrap text-sm">{formatText('', item)}</div>}
            </div>
          ))}
        </div>
      ) : <div className="rounded-2xl bg-slate-50/70 px-4 py-5 text-sm text-apple-gray-medium">{emptyText}</div>}
    </Section>
  )
}

export default function ProductFullView() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user, isManagement } = useAuthStore()
  const [catalog, setCatalog] = useState<ProductAuditItem[]>([])
  const [query, setQuery] = useState('')
  const [product, setProduct] = useState<Product | null>(null)
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [loadingProduct, setLoadingProduct] = useState(false)
  const [error, setError] = useState('')

  const canEdit = isManagement || !!user?.permissions?.includes('product.edit')
  const selectedSku = searchParams.get('sku') || ''
  const filteredCatalog = useMemo(() => {
    const text = query.trim().toLowerCase()
    if (!text) return catalog
    return catalog.filter((item) => [item.sku, item.product_name_cn, item.product_name_en, item.brand].some((value) => String(value || '').toLowerCase().includes(text)))
  }, [catalog, query])

  useEffect(() => {
    let active = true
    setLoadingCatalog(true)
    api.products.auditOverview({ limit: 500 }).then((data) => {
      if (active) setCatalog(data.items)
    }).catch((err) => {
      if (active) setError(err instanceof Error ? err.message : '加载产品目录失败')
    }).finally(() => {
      if (active) setLoadingCatalog(false)
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedSku) {
      setProduct(null)
      return
    }
    let active = true
    setLoadingProduct(true)
    setError('')
    api.products.get(selectedSku).then((data) => {
      if (active) setProduct(data)
    }).catch((err) => {
      if (active) setError(err instanceof Error ? err.message : '加载产品详情失败')
    }).finally(() => {
      if (active) setLoadingProduct(false)
    })
    return () => { active = false }
  }, [selectedSku])

  function chooseProduct(sku: string) {
    const next = new URLSearchParams(searchParams)
    if (sku) next.set('sku', sku)
    else next.delete('sku')
    setSearchParams(next)
  }

  return (
    <main className="mx-auto max-w-[1500px] px-4 pb-12 pt-6 sm:px-6 lg:px-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <div className="text-xs font-black uppercase tracking-[0.2em] text-teal-700">Product Full Record</div>
          <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">产品全字段长视图</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-apple-gray-medium">面向产品核对的业务视图：保留完整业务字段，隐藏系统 ID、时间戳、排序和文件技术元数据，让内容更容易阅读和核对。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => navigate('/products/audit')} className="rounded-xl border border-black/10 bg-white/70 px-4 py-2 text-sm font-semibold text-apple-text">返回产品核对</button>
          {product && canEdit && <button onClick={() => navigate(`/products/edit/${encodeURIComponent(product.sku)}`)} className="btn-primary px-4 py-2 text-sm">编辑此产品</button>}
        </div>
      </div>

      <section className="mt-6 rounded-3xl border border-black/5 bg-white/70 p-4 shadow-sm sm:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-apple-gray-medium">选择产品（全部 {catalog.length || '…'} 个）</div>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 SKU、产品名或品牌" className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none ring-teal-500 focus:ring-2 sm:max-w-sm" />
              <select value={selectedSku} onChange={(event) => chooseProduct(event.target.value)} className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none sm:flex-1">
                <option value="">请选择一个产品</option>
                {filteredCatalog.map((item) => <option key={item.sku} value={item.sku}>{item.sku} · {item.product_name_cn || item.product_name_en || '未命名'}{item.brand ? ` · ${item.brand}` : ''}</option>)}
              </select>
            </div>
          </div>
          {selectedSku && <div className="rounded-2xl bg-teal-50 px-4 py-3 text-sm font-bold text-teal-800">当前：{selectedSku}</div>}
        </div>
        {loadingCatalog && <div className="mt-3 text-xs text-apple-gray-medium">正在加载全部产品目录…</div>}
      </section>

      {error && <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {loadingProduct && <div className="mt-6 rounded-2xl bg-white/70 px-4 py-12 text-center text-sm text-apple-gray-medium">正在加载该产品的全部业务字段…</div>}
      {!loadingProduct && !product && <div className="mt-6 rounded-3xl border border-dashed border-black/10 bg-white/60 px-4 py-16 text-center text-sm text-apple-gray-medium">请先选择一个产品；选择后页面会向下展开完整业务字段。</div>}

      {product && !loadingProduct && (
        <div className="mt-6 space-y-4">
          <Section title="基础身份与管理信息" hint="系统内部 ID、时间戳等技术字段默认不展示"><FieldGrid data={product as unknown as Record<string, unknown>} fields={BASE_FIELDS} /></Section>
          <Section title="物理规格与使用说明"><FieldGrid data={product.specs as unknown as Record<string, unknown> | null | undefined} fields={SPEC_FIELDS} /></Section>
          <Section title="业务定位与卖点"><FieldGrid data={product.business as unknown as Record<string, unknown> | null | undefined} fields={BUSINESS_FIELDS} /></Section>
          <Section title="内容与 Listing 文案"><FieldGrid data={product.content as unknown as Record<string, unknown> | null | undefined} fields={CONTENT_FIELDS} /></Section>
          <CollectionSection title="知识库 QA" items={product.qa_items} fields={QA_FIELDS} emptyText="暂无 QA" />
          <Section title="负面评价与应对话术"><FieldGrid data={product.qa_negative as unknown as Record<string, unknown> | null | undefined} fields={NEGATIVE_QA_FIELDS} /></Section>
          <CollectionSection title="上架渠道" items={product.channels} fields={CHANNEL_FIELDS} emptyText="暂无渠道绑定" />
          <CollectionSection title="销售地区" items={product.regions} fields={REGION_FIELDS} emptyText="暂无地区绑定" />
          <CollectionSection title="认证信息" items={product.certifications} fields={CERTIFICATION_FIELDS} emptyText="暂无认证信息" />
          <CollectionSection title="关键词" items={product.keywords} fields={KEYWORD_FIELDS} emptyText="暂无关键词" />
          <CollectionSection title="媒体记录" items={product.media} fields={MEDIA_FIELDS} emptyText="暂无旧媒体记录" />
          <CollectionSection title="视觉素材" items={product.assets} fields={ASSET_FIELDS} emptyText="暂无视觉素材记录" />
          <CollectionSection title="生成提示词" items={product.prompts} fields={PROMPT_FIELDS} emptyText="暂无生成提示词" />
        </div>
      )}
    </main>
  )
}
