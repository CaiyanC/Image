import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { hasPermission, useAuthStore } from '../store/authStore'
import type { Product, ProductListItem } from '../types'

// Remount on identity/permission changes so cached product data cannot cross accounts.
export default function ProductLookup() {
  const { user } = useAuthStore()
  if (!hasPermission(user, 'product.read')) return null
  const canReadFull = hasPermission(user, 'product.full.view') || hasPermission(user, 'product.edit')
  return <Lookup key={`${user?.id || user?.username}:${canReadFull}`} canReadFull={canReadFull} />
}

function Lookup({ canReadFull }: { canReadFull: boolean }) {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<ProductListItem[]>([])
  const [detail, setDetail] = useState<Product | null>(null)
  const [status, setStatus] = useState('输入 SKU 或产品名称，不会打断当前对话')
  const [busy, setBusy] = useState(false)
  const requestId = useRef(0)
  useEffect(() => () => { requestId.current += 1 }, [])
  async function search() {
    if (!query.trim()) return
    const id = ++requestId.current
    setBusy(true); setDetail(null); setItems([]); setStatus('正在查询…')
    try {
      const result = await api.products.search(query.trim())
      if (id !== requestId.current) return
      setItems(result.items)
      setStatus(result.total ? `找到 ${result.total} 个产品，显示前 ${result.items.length} 个` : '没有匹配产品，请尝试其他名称或 SKU')
    } catch (error) {
      if (id === requestId.current) setStatus(error instanceof Error ? error.message : '查询失败，请重试')
    } finally { if (id === requestId.current) setBusy(false) }
  }
  async function open(sku: string) {
    if (!canReadFull) return
    const id = ++requestId.current
    setBusy(true); setDetail(null); setStatus('正在读取参数…')
    try {
      const result = await api.products.getBySku(encodeURIComponent(sku))
      if (id !== requestId.current) return
      setDetail(result); setStatus('产品参数')
    } catch (error) {
      if (id === requestId.current) setStatus(error instanceof Error ? error.message : '读取失败，请重试')
    } finally { if (id === requestId.current) setBusy(false) }
  }
  const fields: Array<[string, unknown]> = detail ? [
    ['品牌', detail.brand], ['分类', detail.category], ['尺寸', detail.specs?.size_info],
    ['容量', detail.specs?.capacity], ['材质', detail.specs?.body_material], ['颜色', detail.specs?.color],
    ['适用热源', detail.specs?.heat_source], ['功率', detail.specs?.power],
    ['使用说明', detail.specs?.usage_instruction], ['卖点', detail.business?.top_selling_points],
  ] : []
  return <section aria-label="查产品" className="glass p-4">
    <h2 className="mb-3 text-sm font-semibold">查产品</h2>
    <form className="flex gap-2" onSubmit={event => { event.preventDefault(); void search() }}>
      <input aria-label="SKU 或产品名称" value={query} onChange={event => setQuery(event.target.value)} placeholder="SKU / 产品名称" className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-2 text-sm" />
      <button disabled={busy || !query.trim()} className="rounded-lg bg-teal-700 px-3 text-sm text-white disabled:opacity-50">查询</button>
    </form>
    <p role="status" className="my-3 text-xs text-slate-500">{status}</p>
    <div className="max-h-[50vh] space-y-2 overflow-y-auto break-words">
      {detail ? <>
        <button className="text-xs text-teal-700" onClick={() => { setDetail(null); setStatus('请选择产品') }}>← 查询结果</button>
        <h3 className="text-sm font-semibold">{detail.product_name_cn || detail.product_name_en || detail.sku}</h3>
        <p className="text-xs font-mono">{detail.sku}</p>
        <dl className="space-y-2 text-sm">{fields.map(([label, value]) => <div key={String(label)}><dt className="text-xs text-slate-500">{label}</dt><dd className="whitespace-pre-wrap">{value == null || value === '' ? '未填写' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
      </> : items.map(item => <div key={item.sku} className="rounded-lg border border-slate-200 p-3 text-sm">
        <p className="font-semibold">{item.product_name_cn || item.product_name_en || item.sku}</p>
        <p className="mt-1 text-xs text-slate-500">{item.sku} · {item.brand || '品牌未填写'} · {item.category || '分类未填写'}</p>
        {canReadFull && <button disabled={busy} onClick={() => void open(item.sku)} className="mt-2 text-xs text-teal-700 disabled:opacity-50">查看参数</button>}
      </div>)}
    </div>
    {!canReadFull && <p className="mt-3 text-xs text-slate-500">当前可查基础资料；完整参数需要产品详情权限。</p>}
  </section>
}
