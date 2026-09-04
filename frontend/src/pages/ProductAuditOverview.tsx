import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type ProductAuditItem, type ProductAuditOverview } from '../services/api'
import { useAuthStore } from '../store/authStore'

const ISSUE_LABELS: Record<string, string> = {
  product_fields_missing: '基础字段缺失',
  qa_needs_review: 'QA待审核',
  asset_needs_review: '素材待处理',
  asset_storage_unavailable: '素材文件异常',
  vector_missing: '没有产品向量',
  vector_not_ready: '向量未就绪',
  product_sync_flag_false: '产品未标记同步',
}

export default function ProductAuditOverview() {
  const navigate = useNavigate()
  const { user, isManagement } = useAuthStore()
  const [data, setData] = useState<ProductAuditOverview | null>(null)
  const [query, setQuery] = useState('')
  const [issuesOnly, setIssuesOnly] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const can = (permission: string) => isManagement || !!user?.permissions?.includes(permission)

  async function load(nextIssuesOnly = issuesOnly) {
    setLoading(true)
    setError('')
    try {
      setData(await api.products.auditOverview({ q: query.trim() || undefined, issuesOnly: nextIssuesOnly }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载产品核对视图失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // Search and issue filtering are explicit actions; the initial load runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openProduct(sku: string) {
    navigate(`/products?sku=${encodeURIComponent(sku)}`)
  }

  return (
    <main className="mx-auto max-w-[1500px] px-4 pb-10 pt-6 sm:px-6 lg:px-8">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <div className="text-xs font-black uppercase tracking-[0.2em] text-teal-700">Product Control Tower</div>
          <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">产品全量核对</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-apple-gray-medium">
            一次查看全部产品的基础字段、QA审核、图片素材和产品向量状态。本页是只读核对视图，新增或修改会进入现有产品编辑流程并触发同步。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => navigate('/products/full-view')} className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-semibold text-teal-800 hover:bg-teal-100">
            全字段长视图
          </button>
          {can('product.create') && (
            <button onClick={() => navigate('/products/create')} className="btn-primary px-4 py-2 text-sm">
              新增产品
            </button>
          )}
          <button onClick={() => void load()} className="rounded-xl border border-black/10 bg-white/70 px-4 py-2 text-sm font-semibold text-apple-text hover:bg-white">
            {loading ? '刷新中…' : '刷新核对'}
          </button>
        </div>
      </div>

      {error && <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {data && (
        <>
          <section className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Metric title="产品总数" value={data.summary.products_total} detail={`已返回 ${data.pagination.returned} 条`} />
            <Metric title="核对通过" value={data.summary.products_ready} detail={`有问题 ${data.summary.products_with_issues} 个`} tone={data.summary.products_with_issues ? 'warning' : 'good'} />
            <Metric title="QA" value={data.summary.qa_total} detail={`已审 ${data.summary.qa_approved} · 待审 ${data.summary.qa_review}`} />
            <Metric title="图片素材" value={data.summary.asset_total} detail={`已审 ${data.summary.asset_approved} · 待处理 ${data.summary.asset_pending}`} tone={data.summary.asset_invalid || data.summary.asset_duplicates ? 'warning' : 'default'} />
            <Metric title="产品向量" value={data.summary.vector_product_chunks} detail={`已同步 ${data.summary.vector_synced} · 失败 ${data.summary.vector_failed}`} tone={data.summary.vector_pending || data.summary.vector_failed ? 'warning' : 'good'} />
          </section>

          <section className="mt-4 grid gap-3 md:grid-cols-3">
            <StatusCard title="QA审核状态" items={[['已审核', data.summary.qa_approved, 'text-emerald-700'], ['待审核', data.summary.qa_review, 'text-amber-700'], ['已拒绝', data.summary.qa_rejected, 'text-slate-600']]} />
            <StatusCard title="素材质量与存储" items={[['无效', data.summary.asset_invalid, 'text-red-700'], ['重复/复用', data.summary.asset_duplicates, 'text-amber-700'], ['文件缺失', data.summary.asset_storage_missing, 'text-red-700']]} />
            <StatusCard title="向量诊断" items={[['待同步', data.summary.vector_pending, 'text-amber-700'], ['失败', data.summary.vector_failed, 'text-red-700'], ['孤立 SKU', data.summary.orphan_vector_sku_count, 'text-red-700']]} />
          </section>

          <section className="mt-6 rounded-3xl border border-black/5 bg-white/70 p-4 shadow-sm backdrop-blur sm:p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-lg font-black text-apple-text">全部产品</h2>
                <p className="mt-1 text-xs text-apple-gray-medium">当前显示 {data.pagination.total} 条；点击 SKU 可进入原有产品详情核对。</p>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => { if (event.key === 'Enter') void load() }}
                  placeholder="搜索 SKU、产品名、品牌、品类"
                  className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none ring-teal-500 focus:ring-2 sm:w-72"
                />
                <button onClick={() => void load()} className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-bold text-white hover:bg-slate-700">查询</button>
                <label className="flex items-center gap-2 whitespace-nowrap text-sm text-apple-gray-dark">
                  <input type="checkbox" checked={issuesOnly} onChange={(event) => { const next = event.target.checked; setIssuesOnly(next); void load(next) }} />
                  只看有问题
                </label>
              </div>
            </div>

            <div className="mt-4 overflow-x-auto rounded-2xl border border-black/5">
              <table className="min-w-[1120px] w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs font-black text-slate-600">
                  <tr>
                    <th className="px-3 py-3">产品</th>
                    <th className="px-3 py-3">基础字段</th>
                    <th className="px-3 py-3">QA</th>
                    <th className="px-3 py-3">图片素材</th>
                    <th className="px-3 py-3">向量</th>
                    <th className="px-3 py-3">诊断</th>
                    <th className="px-3 py-3 text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/5 bg-white/60">
                  {data.items.map((item) => <AuditRow key={item.id} item={item} canEdit={can('product.edit')} onOpen={openProduct} onEdit={(sku) => navigate(`/products/edit/${encodeURIComponent(sku)}`)} onAssets={(sku) => navigate(`/assets?sku=${encodeURIComponent(sku)}`)} onQa={(sku) => navigate(`/products/qa/new?sku=${encodeURIComponent(sku)}`)} />)}
                </tbody>
              </table>
              {!data.items.length && <div className="px-4 py-10 text-center text-sm text-apple-gray-medium">没有符合条件的产品。</div>}
            </div>
          </section>
        </>
      )}

      {loading && !data && <div className="mt-8 rounded-2xl bg-white/60 px-4 py-12 text-center text-sm text-apple-gray-medium">正在加载全量核对数据…</div>}
    </main>
  )
}

function Metric({ title, value, detail, tone = 'default' }: { title: string; value: number; detail: string; tone?: 'default' | 'good' | 'warning' }) {
  const color = tone === 'good' ? 'text-emerald-700' : tone === 'warning' ? 'text-amber-700' : 'text-apple-text'
  return <div className="rounded-2xl border border-black/5 bg-white/70 p-4 shadow-sm"><div className="text-xs font-bold text-apple-gray-medium">{title}</div><div className={`mt-2 text-2xl font-black ${color}`}>{value.toLocaleString()}</div><div className="mt-1 text-xs text-apple-gray-medium">{detail}</div></div>
}

function StatusCard({ title, items }: { title: string; items: Array<[string, number, string]> }) {
  return <div className="rounded-2xl border border-black/5 bg-white/60 p-4"><div className="text-sm font-black text-apple-text">{title}</div><div className="mt-3 grid grid-cols-3 gap-2">{items.map(([label, value, color]) => <div key={label}><div className="text-xs text-apple-gray-medium">{label}</div><div className={`mt-1 text-lg font-black ${color}`}>{value.toLocaleString()}</div></div>)}</div></div>
}

function AuditRow({ item, canEdit, onOpen, onEdit, onAssets, onQa }: { item: ProductAuditItem; canEdit: boolean; onOpen: (sku: string) => void; onEdit: (sku: string) => void; onAssets: (sku: string) => void; onQa: (sku: string) => void }) {
  return <tr className="align-top hover:bg-teal-50/40">
    <td className="px-3 py-3"><button onClick={() => onOpen(item.sku)} className="text-left"><div className="font-mono text-xs font-black text-teal-800">{item.sku}</div><div className="mt-1 max-w-[210px] font-semibold text-apple-text">{item.product_name_cn || item.product_name_en || '未命名'}</div><div className="mt-1 text-xs text-apple-gray-medium">{item.category || '未分类'}{item.sub_category ? ` · ${item.sub_category}` : ''}</div></button></td>
    <td className="px-3 py-3"><StatusPill ok={item.record.complete} text={item.record.complete ? '完整' : `缺 ${item.record.missing_fields.length} 项`} /><div className="mt-2 max-w-[180px] text-xs leading-5 text-apple-gray-medium">{item.record.missing_fields.join('、') || '必填字段齐全'}</div></td>
    <td className="px-3 py-3"><div className="font-bold text-apple-text">{item.qa.total} 条</div><div className="mt-1 text-xs leading-5 text-apple-gray-medium">已审 {item.qa.approved} · 待审 {item.qa.review}</div></td>
    <td className="px-3 py-3"><div className="font-bold text-apple-text">{item.assets.total} 张/个</div><div className="mt-1 text-xs leading-5 text-apple-gray-medium">已审 {item.assets.approved} · 待审 {item.assets.pending}</div><div className="text-xs leading-5 text-apple-gray-medium">无效 {item.assets.invalid} · 重复 {item.assets.duplicates}</div></td>
    <td className="px-3 py-3"><StatusPill ok={item.vector.ready} text={item.vector.ready ? '已就绪' : item.vector.chunks ? '需处理' : '缺失'} /><div className="mt-2 text-xs leading-5 text-apple-gray-medium">{item.vector.chunks} chunks · 同步 {item.vector.synced}</div></td>
    <td className="px-3 py-3"><div className="flex max-w-[180px] flex-wrap gap-1">{item.issues.length ? item.issues.map((issue) => <span key={issue} className="rounded-full bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-800">{ISSUE_LABELS[issue] || issue}</span>) : <span className="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800">未发现阻塞</span>}</div></td>
    <td className="px-3 py-3"><div className="flex min-w-[190px] flex-wrap justify-end gap-1.5"><button onClick={() => onOpen(item.sku)} className="rounded-lg px-2 py-1 text-xs font-semibold text-teal-700 hover:bg-teal-50">查看</button>{canEdit && <button onClick={() => onEdit(item.sku)} className="rounded-lg px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50">编辑</button>}<button onClick={() => onAssets(item.sku)} className="rounded-lg px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100">素材</button>{canEdit && <button onClick={() => onQa(item.sku)} className="rounded-lg px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100">加 QA</button>}</div></td>
  </tr>
}

function StatusPill({ ok, text }: { ok: boolean; text: string }) {
  return <span className={`inline-flex rounded-full px-2 py-1 text-[11px] font-black ${ok ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>{text}</span>
}
