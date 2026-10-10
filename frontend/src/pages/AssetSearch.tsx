import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../services/api'
import { hasPermission, useAuthStore } from '../store/authStore'
import type { AssetTags, AssetTaxonomy, ProductAsset } from '../types'
import { TAG_DIMENSIONS, TAG_PRESETS, getMaterialTypeDisplayName, getTagDisplayName } from './assetLibraryConfig'
import { getEffectiveAssetTags } from './assetLibraryHelpers'

type SearchTags = Pick<AssetTags,
  'category_tags' | 'quality_check_tags' | 'expression_tags' | 'selling_point_tags' | 'scene_tags' | 'mood_tags' |
  'product_tags' | 'material_type_tags' | 'usage_tags' | 'version_tags' |
  'risk_tags' | 'channel_tags' | 'language_tags' | 'subject_tags' | 'composition_tags' | 'view_tags'
>

type UsageScopeKey = 'is_public' | 'ai_customer_usable' | 'ai_marketing_usable' | 'ai_reference_usable'
type UsageScopeFilter = '' | 'true' | 'false'
const USAGE_SCOPE_FILTERS: Array<{ key: UsageScopeKey; label: string }> = [
  { key: 'is_public', label: '对外公开' },
  { key: 'ai_customer_usable', label: '客服 AI' },
  { key: 'ai_marketing_usable', label: '营销 AI' },
  { key: 'ai_reference_usable', label: 'AI 参考' },
]

export default function AssetSearch() {
  const user = useAuthStore((state) => state.user)
  const [tags, setTags] = useState<SearchTags>({})
  const [sku, setSku] = useState('')
  const [channel, setChannel] = useState('')
  const [maintainer, setMaintainer] = useState('')
  const [qualityStatus, setQualityStatus] = useState('')
  const [duplicateStatus, setDuplicateStatus] = useState('')
  const [reviewStatus, setReviewStatus] = useState('')
  const [authorizationStatus, setAuthorizationStatus] = useState('')
  const [usageScopes, setUsageScopes] = useState<Record<UsageScopeKey, UsageScopeFilter>>({
    is_public: '',
    ai_customer_usable: '',
    ai_marketing_usable: '',
    ai_reference_usable: '',
  })
  const [items, setItems] = useState<ProductAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  const [taxonomy, setTaxonomy] = useState<AssetTaxonomy | null>(null)
  const [tagPresets, setTagPresets] = useState(TAG_PRESETS)

  useEffect(() => {
    api.assets.taxonomy().then(data => {
      setTaxonomy(data)
      setTagPresets(current => {
        const next = { ...current }
        for (const [key, dimension] of Object.entries(data.dimensions)) next[key] = dimension.values
        return next
      })
    }).catch(() => {
      // Keep the bundled presets as a safe UI fallback if the API is unavailable.
    })
  }, [])

  const toggle = (key: keyof SearchTags, value: string) => setTags(current => {
    const values = current[key] || []
    return { ...current, [key]: values.includes(value) ? values.filter(item => item !== value) : [...values, value] }
  })

  const search = async () => {
    setLoading(true)
    setError('')
    setItems([])
    try {
      const result = await api.assets.search({
        ...tags,
        sku: sku.trim() || undefined,
        channel: channel || undefined,
        maintainer: maintainer.trim() || undefined,
        quality_status: qualityStatus || undefined,
        duplicate_status: duplicateStatus || undefined,
        review_status: reviewStatus || undefined,
        authorization_status: authorizationStatus || undefined,
        is_public: usageScopes.is_public === '' ? undefined : usageScopes.is_public === 'true',
        ai_customer_usable: usageScopes.ai_customer_usable === '' ? undefined : usageScopes.ai_customer_usable === 'true',
        ai_marketing_usable: usageScopes.ai_marketing_usable === '' ? undefined : usageScopes.ai_marketing_usable === 'true',
        ai_reference_usable: usageScopes.ai_reference_usable === '' ? undefined : usageScopes.ai_reference_usable === 'true',
      })
      setItems(result.items)
      setSearched(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '素材检索失败')
    } finally {
      setLoading(false)
    }
  }

  // Search uses the complete asset vocabulary.  The backend taxonomy keeps
  // the four controlled pilot dimensions authoritative, while the remaining
  // dimensions are intentionally free-form for existing materials.
  const dimensions = TAG_DIMENSIONS.filter(item => item.key in tagPresets)
  const qualityStatuses = taxonomy?.quality_statuses || ['usable', 'pending_tagging', 'suspected_duplicate', 'invalid', 'archived']
  const duplicateStatuses = taxonomy?.duplicate_statuses || ['unique', 'cross_sku_reuse', 'suspected_duplicate']
  const reviewStatuses = taxonomy?.review_statuses || ['pending', 'approved', 'rejected', 'disabled', 'archived']
  const authorizationStatuses = taxonomy?.authorization_statuses || ['unknown', 'pending', 'internal_test', 'approved', 'authorized', 'rejected', 'denied', 'revoked', 'unapproved']
  return <div className="mx-auto w-full max-w-[1500px] px-4 pb-10 sm:px-6">
    <section className="glass p-5">
      <p className="eyebrow">Visual Asset Search</p><h1 className="mt-1 text-2xl font-black text-apple-text">素材检索</h1>
      <div className="mt-4 grid gap-3 md:grid-cols-3"><input className="glass-input h-10 px-3" value={sku} onChange={e => setSku(e.target.value)} placeholder="SKU（可选）" /><input className="glass-input h-10 px-3" value={maintainer} onChange={e => setMaintainer(e.target.value)} placeholder="维护人（可选）" /><select className="glass-input h-10 px-3" value={channel} onChange={e => setChannel(e.target.value)}><option value="">全部主渠道（历史字段）</option>{(tagPresets.channel_tags || []).map(item => <option key={item}>{item}</option>)}</select></div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm font-black">质量状态<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={qualityStatus} onChange={event => setQualityStatus(event.target.value)}><option value="">全部质量状态</option>{qualityStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
        <label className="text-sm font-black">重复状态<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={duplicateStatus} onChange={event => setDuplicateStatus(event.target.value)}><option value="">全部重复状态</option>{duplicateStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
        <label className="text-sm font-black">审核状态<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={reviewStatus} onChange={event => setReviewStatus(event.target.value)}><option value="">全部审核状态</option>{reviewStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
        <label className="text-sm font-black">使用授权<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={authorizationStatus} onChange={event => setAuthorizationStatus(event.target.value)}><option value="">全部授权状态</option>{authorizationStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        {USAGE_SCOPE_FILTERS.map(scope => <label key={scope.key} className="text-sm font-black">{scope.label}<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={usageScopes[scope.key]} onChange={event => setUsageScopes(current => ({ ...current, [scope.key]: event.target.value as UsageScopeFilter }))}><option value="">全部</option><option value="true">已允许</option><option value="false">未允许</option></select></label>)}
      </div>
      {dimensions.map(dim => <div key={dim.key} className="mt-4"><div className="mb-2 text-sm font-black">{dim.label}</div>{dim.key === 'view_tags' && <div className="mb-2 text-xs text-apple-gray-medium">多角度图的下一级标签，可按正面、侧面、背面或特写筛选。</div>}<div className="flex flex-wrap gap-2">{(tagPresets[dim.key] || []).map(item => <button key={item} onClick={() => toggle(dim.key as keyof SearchTags, item)} className={`rounded-full px-3 py-1 text-xs font-bold ${(tags[dim.key as keyof SearchTags] || []).includes(item) ? 'bg-teal-600 text-white' : dim.color}`}>{getTagDisplayName(item)}</button>)}</div></div>)}
      <button onClick={search} className="mt-5 rounded-full bg-teal-600 px-5 py-2 text-sm font-bold text-white">{loading ? '检索中…' : '开始检索'}</button>
    </section>
    {error && <p role="alert" className="mt-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {!error && searched && !loading && items.length === 0 && <p className="mt-5 text-sm text-apple-gray-medium">没有符合条件的素材，请调整筛选条件。</p>}
    <section className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map(asset => {
      const enabledScopes = [asset.is_public && '公开', asset.ai_customer_usable && '客服 AI', asset.ai_marketing_usable && '营销 AI', asset.ai_reference_usable && 'AI 参考'].filter(Boolean)
      const effectiveTags = getEffectiveAssetTags(asset)
      return <article key={asset.id} className="glass p-4"><div className="font-black">{asset.sku}</div><div className="mt-1 text-sm text-apple-gray-medium">{asset.sub_category || '未分类'} · {getMaterialTypeDisplayName(asset.material_type)} · {asset.channel || 'General'}</div>{asset.maintainer && <div className="mt-1 text-xs text-apple-gray-medium">维护人：{asset.maintainer}</div>}<div className="mt-2 flex flex-wrap gap-1"><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">质量：{asset.quality_status || 'usable'}</span><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">重复：{asset.duplicate_status || 'unique'}</span><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">审核：{asset.review_status || 'pending'}</span><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">授权：{asset.authorization_status || 'unknown'}</span></div><div className="mt-2 text-xs text-apple-gray-medium">已开启范围：{enabledScopes.length ? enabledScopes.join('、') : '无'}</div><div className="mt-3 flex flex-wrap gap-1">{(Object.entries(effectiveTags) as Array<[string, string[]]>).flatMap(([key, values]) => values.map((tag: string) => <span key={`${key}-${tag}`} className="rounded-full bg-teal-50 px-2 py-1 text-xs text-teal-700">{getTagDisplayName(tag)}</span>))}</div>{hasPermission(user, 'media.read') && <Link className="mt-4 inline-block text-sm font-bold text-teal-700" to={`/assets?sku=${encodeURIComponent(asset.sku)}`}>打开 SKU 素材库 →</Link>}</article>
    })}</section>
  </div>
}
