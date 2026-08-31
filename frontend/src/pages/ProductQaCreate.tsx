import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../services/api'
import type { ProductQaCreateResponse } from '../services/api'

export default function ProductQaCreate() {
  const [searchParams] = useSearchParams()
  const [sku, setSku] = useState(() => searchParams.get('sku') || '')
  const [question, setQuestion] = useState(() => searchParams.get('question') || '')
  const [answer, setAnswer] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ProductQaCreateResponse | null>(null)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedSku = sku.trim().toUpperCase()
    const normalizedQuestion = question.trim()
    const normalizedAnswer = answer.trim()
    if (!normalizedSku || !normalizedQuestion || !normalizedAnswer) {
      setError('请填写 SKU、问题和答案')
      return
    }

    setSaving(true)
    setError('')
    setResult(null)
    try {
      const response = await api.products.addQa(normalizedSku, {
        question: normalizedQuestion,
        answer: normalizedAnswer,
      })
      setResult(response)
      if (response.ready_for_rag) {
        setAnswer('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'QA 保存失败')
    } finally {
      setSaving(false)
    }
  }

  const audit = result?.integrity_audit || {}
  const vectorSync = result?.vector_sync && typeof result.vector_sync === 'object'
    ? result.vector_sync
    : {}
  const embedding = result?.embedding && typeof result.embedding === 'object'
    ? result.embedding
    : {}

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-teal-700">L5 · 产品知识 QA</div>
          <h1 className="mt-1 text-2xl font-black text-apple-text">添加产品 QA</h1>
          <p className="mt-1 text-sm text-apple-gray-medium">
            问题来自客服现场，答案保存后会先做同 SKU 语义审核，再同步到 RAG。
          </p>
        </div>
        <Link
          to="/customer-service"
          className="rounded-xl border border-black/10 bg-white/70 px-4 py-2 text-sm font-semibold text-apple-gray-dark hover:bg-white"
        >
          返回智能客服
        </Link>
      </div>

      <form onSubmit={handleSubmit} className="glass rounded-2xl p-5 space-y-5">
        <div>
          <label htmlFor="qa-sku" className="mb-1.5 block text-sm font-semibold text-apple-text">
            产品 SKU <span className="text-red-500">*</span>
          </label>
          <input
            id="qa-sku"
            value={sku}
            onChange={(event) => setSku(event.target.value)}
            placeholder="例如：CS-G25"
            className="glass-input w-full px-3 py-2.5 text-sm uppercase"
            autoComplete="off"
          />
          <p className="mt-1.5 text-xs text-apple-gray-medium">
            客服回答只绑定到一个明确 SKU 时会自动带入；推荐多个商品时请在这里确认目标 SKU。
          </p>
        </div>

        <div>
          <label htmlFor="qa-question" className="mb-1.5 block text-sm font-semibold text-apple-text">
            Q · 客户问题 <span className="text-red-500">*</span>
          </label>
          <textarea
            id="qa-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={2000}
            rows={4}
            placeholder="填写客户实际会问的问题"
            className="glass-input w-full resize-y px-3 py-2.5 text-sm"
          />
        </div>

        <div>
          <label htmlFor="qa-answer" className="mb-1.5 block text-sm font-semibold text-apple-text">
            A · 标准答案 <span className="text-red-500">*</span>
          </label>
          <textarea
            id="qa-answer"
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            maxLength={5000}
            rows={7}
            placeholder="填写可直接给客户的标准答案，只写你确认过的同 SKU 事实"
            className="glass-input w-full resize-y px-3 py-2.5 text-sm"
          />
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        {result && (
          <div className={`rounded-xl border px-3 py-3 text-sm ${
            result.ready_for_rag
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : 'border-amber-200 bg-amber-50 text-amber-800'
          }`}>
            <div className="font-bold">
              {result.ready_for_rag ? '已可被 RAG 检索' : '已保存，但暂未进入客服知识'}
            </div>
            <div className="mt-1 text-xs leading-5">
              {result.ready_for_rag
                ? `同 SKU 语义审核通过，产品知识分片已同步（${String(embedding.embedded ?? 0)} 个本次向量化）。`
                : `审核：${String(audit.status || result.status)}${audit.reason ? `；${String(audit.reason)}` : ''}`}
              {!result.ready_for_rag && vectorSync && typeof vectorSync.error === 'string' && (
                <span>；向量同步失败：{vectorSync.error}</span>
              )}
            </div>
            {!result.ready_for_rag && (
              <div className="mt-2 text-xs">
                只有审核为 approved 且产品知识分片没有 pending/failed 时，客服才会使用这条 QA；可修正答案后重新提交。
              </div>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-black/5 pt-4">
          <Link to="/customer-service" className="px-4 py-2 text-sm font-semibold text-apple-gray-dark hover:text-apple-text">
            取消
          </Link>
          <button
            type="submit"
            disabled={saving}
            className="btn-primary px-5 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? '审核并同步中…' : '保存并同步到 RAG'}
          </button>
        </div>
      </form>
    </div>
  )
}
