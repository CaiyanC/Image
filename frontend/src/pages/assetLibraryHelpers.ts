import type { AssetTags, ProductAsset } from '../types'
import { ASSET_SUB_CATEGORIES, STATUS_TO_EN } from './assetLibraryConfig'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export function formatDate(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}${month}${day}`
}

export function toEnglishStatus(status?: string | null) {
  if (!status) return 'pending'
  return STATUS_TO_EN[status] || status
}

export function buildNamingFormat(asset: Partial<ProductAsset>) {
  const brand = asset.brand || 'alocs'
  const sku = asset.sku || 'SKU'
  const materialType = asset.material_type || 'unknown'
  const angle = asset.angle_scene ? `_${asset.angle_scene}` : ''
  const channel = asset.channel || '_'
  const language = asset.language_tag || '_'
  const version = asset.version_tag || 'V1'
  const date = asset.date_tag || formatDate()
  const status = toEnglishStatus(asset.status_tag || '待审核')
  const seq = String(asset.seq || 1).padStart(2, '0')
  return `${brand}_${sku}_${materialType}${angle}_${channel}_${language}_${version}_${date}_${status}_${seq}`
}

export function toAssetUrl(path?: string | null) {
  if (!path) return ''
  if (path.startsWith('http') || path.startsWith('data:')) return path
  if (API_BASE_URL.startsWith('http')) {
    return `${API_BASE_URL.replace(/\/api\/?$/, '')}${path}`
  }
  return path
}

export function getAssetDisplayUrl(asset: ProductAsset) {
  return toAssetUrl(asset.thumbnail_url || asset.url)
}

export function cloneTags(tags?: AssetTags | null): AssetTags {
  const result: AssetTags = {}
  for (const [key, value] of Object.entries(tags || {})) {
    if (Array.isArray(value)) {
      ;(result as Record<string, string[]>)[key] = [...value]
    }
  }
  return result
}

export function addTag(tags: AssetTags | undefined, key: string, tag: string) {
  const clean = tag.trim()
  const next = cloneTags(tags)
  if (!clean) return next
  const current = (next as Record<string, string[]>)[key] || []
  if (!current.includes(clean)) {
    ;(next as Record<string, string[]>)[key] = [...current, clean]
  }
  return next
}

export function removeTag(tags: AssetTags | undefined, key: string, tag: string) {
  const next = cloneTags(tags)
  const current = (next as Record<string, string[]>)[key] || []
  const filtered = current.filter(item => item !== tag)
  if (filtered.length) {
    ;(next as Record<string, string[]>)[key] = filtered
  } else {
    delete (next as Record<string, string[]>)[key]
  }
  return next
}

export function getMaterialColor(materialType?: string | null) {
  const colorMap: Record<string, string> = {
    whiteBackground: 'bg-sky-100 text-sky-700 border-sky-200',
    side: 'bg-sky-100 text-sky-700 border-sky-200',
    lakeside: 'bg-sky-100 text-sky-700 border-sky-200',
    multiAngle: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    back: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    aliexpress: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    video: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    front: 'bg-blue-100 text-blue-700 border-blue-200',
    clean: 'bg-blue-100 text-blue-700 border-blue-200',
    alibaba: 'bg-blue-100 text-blue-700 border-blue-200',
    detail: 'bg-violet-100 text-violet-700 border-violet-200',
    parameter: 'bg-violet-100 text-violet-700 border-violet-200',
    pinduoduo: 'bg-violet-100 text-violet-700 border-violet-200',
    mainImage: 'bg-purple-100 text-purple-700 border-purple-200',
    dewu: 'bg-purple-100 text-purple-700 border-purple-200',
    socialScene: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    aPlus: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    aiPrompt: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    afterSales: 'bg-pink-100 text-pink-700 border-pink-200',
    detailPage: 'bg-pink-100 text-pink-700 border-pink-200',
    douyin: 'bg-pink-100 text-pink-700 border-pink-200',
    set: 'bg-rose-100 text-rose-700 border-rose-200',
    jdMain: 'bg-rose-100 text-rose-700 border-rose-200',
    xiaohongshu: 'bg-rose-100 text-rose-700 border-rose-200',
    ignite: 'bg-red-100 text-red-700 border-red-200',
    tmallMain: 'bg-red-100 text-red-700 border-red-200',
    install: 'bg-orange-100 text-orange-700 border-orange-200',
    amazonMain: 'bg-orange-100 text-orange-700 border-orange-200',
    kuaishou: 'bg-orange-100 text-orange-700 border-orange-200',
    accessory: 'bg-amber-100 text-amber-700 border-amber-200',
    carCamping: 'bg-amber-100 text-amber-700 border-amber-200',
    campaignAd: 'bg-amber-100 text-amber-700 border-amber-200',
    safety: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    indoor: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    size: 'bg-lime-100 text-lime-700 border-lime-200',
    familyCamping: 'bg-lime-100 text-lime-700 border-lime-200',
    ebay: 'bg-lime-100 text-lime-700 border-lime-200',
    structure: 'bg-green-100 text-green-700 border-green-200',
    forest: 'bg-green-100 text-green-700 border-green-200',
    packed: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    temu: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    hiking: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    exploded: 'bg-teal-100 text-teal-700 border-teal-200',
    socialMedia: 'bg-teal-100 text-teal-700 border-teal-200',
    functional: 'bg-cyan-100 text-cyan-700 border-cyan-200',
    snow: 'bg-cyan-100 text-cyan-700 border-cyan-200',
    standalone: 'bg-cyan-100 text-cyan-700 border-cyan-200',
    hardcoreCamping: 'bg-stone-100 text-stone-700 border-stone-200',
    banned: 'bg-red-100 text-red-700 border-red-200',
  }
  return colorMap[materialType || ''] || 'bg-gray-100 text-gray-700 border-gray-200'
}

export function sortAssets(assets: ProductAsset[], activeSubCategory: string | null) {
  const subRank = new Map(ASSET_SUB_CATEGORIES.map((item, index) => [item.name, index]))
  const slotOrders: Record<string, string[]> = {
    多角度图: ['front', 'side', 'back', 'detail'],
    Amazon: ['mainImage', 'aPlus'],
    天猫: ['mainImage', 'detailPage'],
    京东: ['mainImage', 'detailPage'],
  }
  const materialOrder = activeSubCategory ? slotOrders[activeSubCategory] || [] : []
  return [...assets].sort((a, b) => {
    if (!activeSubCategory) {
      const subDiff = (subRank.get(a.sub_category || '') ?? 999) - (subRank.get(b.sub_category || '') ?? 999)
      if (subDiff !== 0) return subDiff
    }
    const matDiff = materialOrder.indexOf(a.material_type || '') - materialOrder.indexOf(b.material_type || '')
    if (materialOrder.length && matDiff !== 0) return matDiff
    if (a.seq !== b.seq) return a.seq - b.seq
    return String(a.created_at).localeCompare(String(b.created_at))
  })
}
