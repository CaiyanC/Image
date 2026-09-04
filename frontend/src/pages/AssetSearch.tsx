import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../services/api'
import type { AssetTags, AssetTaxonomy, ProductAsset } from '../types'
import { TAG_DIMENSIONS, TAG_PRESETS } from './assetLibraryConfig'

type SearchTags = Pick<AssetTags,
  'expression_tags' | 'selling_point_tags' | 'scene_tags' | 'mood_tags' |
  'product_tags' | 'material_type_tags' | 'usage_tags' | 'version_tags' |
  'risk_tags' | 'channel_tags' | 'language_tags'
>

export default function AssetSearch() {
  const [tags, setTags] = useState<SearchTags>({})
  const [sku, setSku] = useState('')
  const [channel, setChannel] = useState('')
  const [qualityStatus, setQualityStatus] = useState('')
  const [duplicateStatus, setDuplicateStatus] = useState('')
  const [items, setItems] = useState<ProductAsset[]>([])
  const [loading, setLoading] = useState(false)
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
    try {
      const result = await api.assets.search({
        ...tags,
        sku: sku.trim() || undefined,
        channel: channel || undefined,
        quality_status: qualityStatus || undefined,
        duplicate_status: duplicateStatus || undefined,
      })
      setItems(result.items)
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
  return <div className="mx-auto w-full max-w-[1500px] px-4 pb-10 sm:px-6">
    <section className="glass p-5">
      <p className="eyebrow">Visual Asset Search</p><h1 className="mt-1 text-2xl font-black text-apple-text">素材检索</h1>
      <div className="mt-4 grid gap-3 md:grid-cols-2"><input className="glass-input h-10 px-3" value={sku} onChange={e => setSku(e.target.value)} placeholder="SKU（可选）" /><select className="glass-input h-10 px-3" value={channel} onChange={e => setChannel(e.target.value)}><option value="">全部渠道</option>{(tagPresets.channel_tags || []).map(item => <option key={item}>{item}</option>)}</select></div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-sm font-black">质量状态<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={qualityStatus} onChange={event => setQualityStatus(event.target.value)}><option value="">全部质量状态</option>{qualityStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
        <label className="text-sm font-black">重复状态<select className="glass-input mt-1 h-10 w-full px-3 font-normal" value={duplicateStatus} onChange={event => setDuplicateStatus(event.target.value)}><option value="">全部重复状态</option>{duplicateStatuses.map(item => <option key={item}>{item}</option>)}</select></label>
      </div>
      {dimensions.map(dim => <div key={dim.key} className="mt-4"><div className="mb-2 text-sm font-black">{dim.label}</div><div className="flex flex-wrap gap-2">{(tagPresets[dim.key] || []).map(item => <button key={item} onClick={() => toggle(dim.key as keyof SearchTags, item)} className={`rounded-full px-3 py-1 text-xs font-bold ${(tags[dim.key as keyof SearchTags] || []).includes(item) ? 'bg-teal-600 text-white' : dim.color}`}>{item}</button>)}</div></div>)}
      <button onClick={search} className="mt-5 rounded-full bg-teal-600 px-5 py-2 text-sm font-bold text-white">{loading ? '检索中…' : '开始检索'}</button>
    </section>
    <section className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map(asset => <article key={asset.id} className="glass p-4"><div className="font-black">{asset.sku}</div><div className="mt-1 text-sm text-apple-gray-medium">{asset.sub_category || '未分类'} · {asset.channel || 'General'}</div><div className="mt-2 flex flex-wrap gap-1"><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">质量：{asset.quality_status || 'usable'}</span><span className="rounded-full bg-stone-100 px-2 py-1 text-xs text-stone-700">重复：{asset.duplicate_status || 'unique'}</span></div><div className="mt-3 flex flex-wrap gap-1">{Object.values(asset.tags || {}).flat().map(tag => <span key={tag} className="rounded-full bg-teal-50 px-2 py-1 text-xs text-teal-700">{tag}</span>)}</div><Link className="mt-4 inline-block text-sm font-bold text-teal-700" to={`/assets?sku=${encodeURIComponent(asset.sku)}`}>打开 SKU 素材库 →</Link></article>)}</section>
  </div>
}
