import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../services/api'
import type { KnowledgeBaseHealth, KnowledgeSearchPreview } from '../services/api'

export default function KnowledgeBase() {
  const [health, setHealth] = useState<KnowledgeBaseHealth | null>(null)
  const [preview, setPreview] = useState<KnowledgeSearchPreview | null>(null)
  const [query, setQuery] = useState('camping coffee')
  const [sku, setSku] = useState('')
  const [loading, setLoading] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadHealth()
  }, [])

  async function loadHealth() {
    setError('')
    try {
      setHealth(await api.knowledgeBase.health())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load knowledge health')
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
      setError(err instanceof Error ? err.message : 'Search preview failed')
    } finally {
      setLoading(false)
    }
  }

  async function reindex(mode: 'pending' | 'full') {
    setReindexing(true)
    setError('')
    try {
      const result = await api.knowledgeBase.reindexProducts({ mode, limit: mode === 'full' ? undefined : 100, embed: true })
      setHealth(result.health)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reindex failed')
    } finally {
      setReindexing(false)
    }
  }

  const productCoverage = percent(health?.coverage.product_index_coverage)
  const embeddingCoverage = percent(health?.coverage.embedding_coverage)

  return (
    <div className="mx-auto max-w-7xl p-4">
      <div className="mb-5 overflow-hidden rounded-[2rem] border border-white/70 bg-white/60 p-6 shadow-[0_24px_80px_rgba(15,23,42,0.10)] backdrop-blur-xl">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.24em] text-teal-700/70">Enterprise RAG Ops</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">Knowledge Base Control Center</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-apple-gray-dark">
              Monitor product coverage, vector readiness, failed chunks and retrieval evidence before customer-service answers reach users.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary px-4 py-2 text-sm" onClick={loadHealth} disabled={reindexing}>Refresh</button>
            <button className="btn-secondary px-4 py-2 text-sm" onClick={() => reindex('pending')} disabled={reindexing}>
              Sync Pending
            </button>
            <button className="btn-primary px-4 py-2 text-sm" onClick={() => reindex('full')} disabled={reindexing}>
              {reindexing ? 'Running...' : 'Full Reindex'}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-4">
        <Metric title="Health Grade" value={health?.grade || '-'} tone={health?.grade === 'healthy' ? 'good' : health?.grade === 'critical' ? 'bad' : 'warn'} />
        <Metric title="Product Coverage" value={productCoverage} sub={`${health?.totals.indexed_product_skus ?? 0}/${health?.totals.products ?? 0} products`} />
        <Metric title="Embedding Coverage" value={embeddingCoverage} sub={`${health?.vector.embedded_chunks ?? 0}/${health?.totals.chunks ?? 0} chunks`} />
        <Metric title="Vector Engine" value={health?.vector.available ? 'pgvector on' : 'fallback'} tone={health?.vector.available ? 'good' : 'warn'} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="glass rounded-3xl p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-black text-apple-text">Retrieval Preview</h2>
              <p className="text-sm text-apple-gray-medium">Test what the customer-service agent can retrieve before it answers.</p>
            </div>
            <span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">
              {preview?.mode || 'not tested'}
            </span>
          </div>

          <div className="grid gap-3 md:grid-cols-[1fr_180px_auto]">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="glass-input px-3 py-2 text-sm"
              placeholder="Semantic query"
            />
            <input
              value={sku}
              onChange={(event) => setSku(event.target.value)}
              className="glass-input px-3 py-2 text-sm"
              placeholder="Optional SKU"
            />
            <button className="btn-primary px-4 py-2 text-sm" onClick={runPreview} disabled={loading || !query.trim()}>
              {loading ? 'Testing...' : 'Test'}
            </button>
          </div>

          <div className="mt-4 space-y-3">
            {(preview?.results || []).length === 0 ? (
              <div className="rounded-2xl border border-black/5 bg-white/60 px-4 py-8 text-center text-sm text-apple-gray-medium">
                No retrieval preview yet.
              </div>
            ) : preview?.results.map((item, index) => (
              <div key={`${item.sku || 'global'}-${index}`} className="rounded-2xl border border-black/5 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-black text-blue-700">{item.source_type || 'knowledge'}</span>
                    {item.sku && <span className="font-mono text-xs font-bold text-apple-text">{item.sku}</span>}
                  </div>
                  <span className="text-xs text-apple-gray-medium">score {formatScore(item.score)}</span>
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
          <Panel title="Readiness Recommendations">
            {(health?.recommendations || []).length === 0 ? (
              <p className="text-sm text-emerald-700">No blocking recommendation. Knowledge base is ready.</p>
            ) : (
              <div className="space-y-2">
                {health?.recommendations.map((item, index) => (
                  <div key={index} className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">{item}</div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Embedding Status">
            <KeyValue data={health?.embedding_status_counts || {}} />
          </Panel>

          <Panel title="Source Types">
            <KeyValue data={health?.source_type_counts || {}} />
          </Panel>

          <ChunkSamples title="Failed Chunks" items={health?.samples.failed_chunks || []} />
          <ChunkSamples title="Pending Chunks" items={health?.samples.pending_chunks || []} />
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
  if (!entries.length) return <p className="text-sm text-apple-gray-medium">No data</p>
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
        <p className="text-sm text-apple-gray-medium">No samples</p>
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

function percent(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '-'
  return `${Math.round(value * 100)}%`
}

function formatScore(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return value.toFixed(3)
}
