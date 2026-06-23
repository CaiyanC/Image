import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../services/api'
import type { KnowledgeBaseHealth, KnowledgeJob, KnowledgeSearchPreview } from '../services/api'

export default function KnowledgeBase() {
  const [health, setHealth] = useState<KnowledgeBaseHealth | null>(null)
  const [preview, setPreview] = useState<KnowledgeSearchPreview | null>(null)
  const [query, setQuery] = useState('露营咖啡')
  const [sku, setSku] = useState('')
  const [jobs, setJobs] = useState<KnowledgeJob[]>([])
  const [loading, setLoading] = useState(false)
  const [jobLoading, setJobLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadHealth()
    loadJobs()
  }, [])

  useEffect(() => {
    if (!jobs.some((job) => isActiveJob(job.status))) return
    const timer = window.setInterval(() => {
      loadJobs()
      loadHealth()
    }, 2500)
    return () => window.clearInterval(timer)
  }, [jobs])

  async function loadHealth() {
    setError('')
    try {
      setHealth(await api.knowledgeBase.health())
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载知识库状态失败')
    }
  }

  async function loadJobs() {
    try {
      const result = await api.knowledgeBase.jobs(10)
      setJobs(result.items)
    } catch {
      // Job polling should not block the health dashboard.
    }
  }

  async function runPreview() {
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      setPreview(await api.knowledgeBase.searchPreview({
        query: query.trim(),
        sku: sku.trim() || undefined,
        limit: 8,
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '检索预览失败')
    } finally {
      setLoading(false)
    }
  }

  async function createReindexJob(mode: 'pending' | 'full') {
    setJobLoading(true)
    setError('')
    try {
      await api.knowledgeBase.createReindexJob({ mode, limit: mode === 'full' ? undefined : 100, embed: true })
      await loadJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建重建任务失败')
    } finally {
      setJobLoading(false)
    }
  }

  async function retryEmbeddings() {
    setJobLoading(true)
    setError('')
    try {
      await api.knowledgeBase.retryEmbeddings({ limit: 20 })
      await loadJobs()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建重试任务失败')
    } finally {
      setJobLoading(false)
    }
  }

  const productCoverage = percent(health?.coverage.product_index_coverage)
  const embeddingCoverage = percent(health?.coverage.embedding_coverage)
  const hasActiveJob = jobs.some((job) => isActiveJob(job.status))

  return (
    <div className="mx-auto max-w-7xl p-4">
      <div className="mb-5 overflow-hidden rounded-[2rem] border border-white/70 bg-white/60 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur-xl">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.24em] text-teal-700/70">企业级 RAG 运维</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">知识库控制台</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-apple-gray-dark">
              在客服回答触达用户前，先检查产品覆盖率、向量可用性、失败分片和检索证据。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary px-4 py-2 text-sm" onClick={() => { loadHealth(); loadJobs() }} disabled={jobLoading}>刷新</button>
            <button className="btn-secondary px-4 py-2 text-sm" onClick={() => createReindexJob('pending')} disabled={jobLoading || hasActiveJob}>
              同步待处理
            </button>
            <button className="btn-secondary px-4 py-2 text-sm" onClick={retryEmbeddings} disabled={jobLoading || hasActiveJob}>
              重试失败
            </button>
            <button className="btn-primary px-4 py-2 text-sm" onClick={() => createReindexJob('full')} disabled={jobLoading || hasActiveJob}>
              {jobLoading || hasActiveJob ? '任务执行中...' : '全量重建'}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-4">
        <Metric title="健康等级" value={health?.grade || '-'} tone={health?.grade === 'healthy' ? 'good' : health?.grade === 'critical' ? 'bad' : 'warn'} />
        <Metric title="产品覆盖率" value={productCoverage} sub={`${health?.totals.indexed_product_skus ?? 0}/${health?.totals.products ?? 0} 个产品`} />
        <Metric title="向量覆盖率" value={embeddingCoverage} sub={`${health?.vector.embedded_chunks ?? 0}/${health?.totals.chunks ?? 0} 个分片`} />
        <Metric title="向量引擎" value={health?.vector.available ? 'pgvector 已启用' : '关键词兜底'} tone={health?.vector.available ? 'good' : 'warn'} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="glass rounded-3xl p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-black text-apple-text">检索预览</h2>
              <p className="text-sm text-apple-gray-medium">在客服回答前，先测试它能检索到什么内容。</p>
            </div>
            <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">
              {preview?.mode || '未测试'}
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_180px_auto]">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="glass-input px-3 py-2 text-sm"
              placeholder="语义查询"
            />
            <input
              value={sku}
              onChange={(event) => setSku(event.target.value)}
              className="glass-input px-3 py-2 text-sm"
              placeholder="可选 SKU"
            />
            <button className="btn-primary px-4 py-2 text-sm" onClick={runPreview} disabled={loading || !query.trim()}>
              {loading ? '测试中...' : '测试'}
            </button>
          </div>

          <div className="mt-4 space-y-3">
            {(preview?.results || []).length === 0 ? (
              <div className="rounded-2xl border border-black/5 bg-white/60 px-4 py-8 text-center text-sm text-apple-gray-medium">
                还没有检索预览结果。
              </div>
            ) : preview?.results.map((item, index) => (
              <div key={`${item.sku || 'global'}-${index}`} className="rounded-2xl border border-black/5 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-black text-blue-700">{item.source_type || '知识库'}</span>
                    {item.sku && <span className="font-mono text-xs font-bold text-apple-text">{item.sku}</span>}
                  </div>
                  <span className="text-xs text-apple-gray-medium">评分 {formatScore(item.score)}</span>
                </div>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-apple-text">{item.content}</p>
                {item.metadata && Object.keys(item.metadata).length > 0 && (
                  <pre className="mt-3 max-h-32 overflow-auto rounded-xl bg-black/[0.04] p-3 text-xs text-apple-gray-dark">
                    {JSON.stringify(item.metadata, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <Panel title="就绪建议">
            {(health?.recommendations || []).length === 0 ? (
              <p className="text-sm text-emerald-700">没有阻塞项，知识库已就绪。</p>
            ) : (
              <div className="space-y-2">
                {health?.recommendations.map((item, index) => (
                  <div key={index} className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">{item}</div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="后台任务">
            <JobList jobs={jobs} onRefresh={loadJobs} />
          </Panel>

          <Panel title="Embedding 状态">
            <KeyValue data={health?.embedding_status_counts || {}} />
          </Panel>

          <Panel title="来源类型">
            <KeyValue data={health?.source_type_counts || {}} />
          </Panel>

          <ChunkSamples title="失败分片" items={health?.samples.failed_chunks || []} />
          <ChunkSamples title="待处理分片" items={health?.samples.pending_chunks || []} />
        </section>
      </div>
    </div>
  )
}

function Metric({ title, value, sub, tone = 'neutral' }: { title: string; value: string; sub?: string; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  const toneClass = {
    neutral: 'from-slate-50 to-white text-apple-text',
    good: 'from-emerald-50 to-white text-emerald-700',
    warn: 'from-amber-50 to-white text-amber-700',
    bad: 'from-red-50 to-white text-red-700',
  }[tone]
  return (
    <div className={`rounded-3xl border border-white/70 bg-gradient-to-br ${toneClass} p-5 shadow-[0_18px_50px_rgba(15,23,42,0.08)]`}>
      <div className="text-xs font-bold uppercase tracking-[0.18em] text-apple-gray-medium">{title}</div>
      <div className="mt-3 text-2xl font-black">{value}</div>
      {sub && <div className="mt-1 text-xs text-apple-gray-medium">{sub}</div>}
    </div>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="glass rounded-3xl p-5">
      <h2 className="mb-3 text-sm font-black uppercase tracking-[0.14em] text-apple-text">{title}</h2>
      {children}
    </div>
  )
}

function KeyValue({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data)
  if (!entries.length) return <p className="text-sm text-apple-gray-medium">暂无数据</p>
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between rounded-xl bg-white/60 px-3 py-2 text-sm">
          <span className="text-apple-gray-dark">{key}</span>
          <span className="font-mono font-bold text-apple-text">{value}</span>
        </div>
      ))}
    </div>
  )
}

function ChunkSamples({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  return (
    <Panel title={title}>
      {items.length === 0 ? (
        <p className="text-sm text-apple-gray-medium">暂无样本</p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={String(item.id)} className="rounded-xl bg-white/70 p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-bold text-blue-700">{String(item.sku || 'global')}</span>
                <span className="text-apple-gray-medium">{String(item.source_type || '')}</span>
              </div>
              <p className="mt-2 line-clamp-3 text-apple-gray-dark">{String(item.preview || '')}</p>
              {Boolean(item.error) && <p className="mt-2 text-red-600">{String(item.error)}</p>}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function JobList({ jobs, onRefresh }: { jobs: KnowledgeJob[]; onRefresh: () => void }) {
  if (!jobs.length) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-apple-gray-medium">当前还没有后台任务。</p>
        <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={onRefresh}>刷新任务</button>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {jobs.map((job) => {
        const embeddingResult = job.result?.embedding
        return (
          <div key={job.id} className="rounded-xl bg-white/70 p-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="font-bold text-apple-text">{job.kind}</div>
                <div className="mt-1 text-apple-gray-medium">{job.stage}</div>
              </div>
              <span className={`rounded-full px-2 py-1 font-bold ${jobTone(job.status)}`}>{job.status}</span>
            </div>
            <div className="mt-2 font-mono text-[11px] text-apple-gray-medium">{job.id}</div>
            {job.error && <div className="mt-2 rounded-lg bg-red-50 px-2 py-1 text-red-700">{job.error}</div>}
            {Boolean(embeddingResult) && (
              <div className="mt-2 rounded-lg bg-emerald-50 px-2 py-1 text-emerald-700">
                embedding: {JSON.stringify(embeddingResult)}
              </div>
            )}
          </div>
        )
      })}
      <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={onRefresh}>刷新任务</button>
    </div>
  )
}

function jobTone(status: string) {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-700'
  if (status === 'failed') return 'bg-red-50 text-red-700'
  if (status === 'running') return 'bg-blue-50 text-blue-700'
  return 'bg-amber-50 text-amber-700'
}

function isActiveJob(status: string) {
  return status === 'queued' || status === 'running'
}

function percent(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '-'
  return `${Math.round(value * 100)}%`
}

function formatScore(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return value.toFixed(3)
}
