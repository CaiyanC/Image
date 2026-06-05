import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AgentAction, AgentStep, ProductSearchResult, api } from '../services/api'
import { useAuthStore } from '../store/authStore'

interface ChatMessage {
  id?: string
  message_id?: string | null
  role: 'user' | 'assistant'
  content: string
  created_at?: string | null
  streaming?: boolean
  status?: string
  intent?: string | null
  answer_type?: string | null
  confidence?: string | null
  uncertainty?: string | null
  needs_clarification?: boolean
  anomalies?: Array<Record<string, unknown>>
  suggested_followups?: string[]
  followups?: string[]
  warnings?: string[]
  evidence?: Array<Record<string, unknown>>
  debug?: Record<string, unknown>
  feedback?: Record<string, unknown> | null
  sources?: Array<Record<string, unknown>>
  actions?: AgentAction[]
  results?: ProductSearchResult[]
  steps?: AgentStep[]
}

interface CustomerServiceDraft {
  version: number
  conversationId: string | null
  question: string
  messages: ChatMessage[]
  savedAt: string
}

const CUSTOMER_SERVICE_DRAFT_VERSION = 1

export default function CustomerService() {
  const { isManagement, user } = useAuthStore()
  const [question, setQuestion] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversations, setConversations] = useState<Array<Record<string, unknown>>>([])
  const [knowledgeStatus, setKnowledgeStatus] = useState<Record<string, unknown> | null>(null)
  const [reviewSummary, setReviewSummary] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [debugMode, setDebugMode] = useState(false)
  const [feedbackLoadingId, setFeedbackLoadingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const chatContainerRef = useRef<HTMLDivElement | null>(null)
  const draftHydratedRef = useRef(false)
  const skipNextDraftPersistRef = useRef(false)
  const draftCacheKey = useMemo(() => customerServiceDraftKey(user?.id || user?.username), [user?.id, user?.username])

  useEffect(() => {
    loadSideData()
  }, [])

  useEffect(() => {
    skipNextDraftPersistRef.current = true
    draftHydratedRef.current = false
    const draft = loadCustomerServiceDraft(draftCacheKey)
    setConversationId(draft?.conversationId || null)
    setQuestion(draft?.question || '')
    setMessages(draft?.messages || [])
    draftHydratedRef.current = true
  }, [draftCacheKey])

  useEffect(() => {
    if (!draftHydratedRef.current) return
    if (skipNextDraftPersistRef.current) {
      skipNextDraftPersistRef.current = false
      return
    }
    saveCustomerServiceDraft(draftCacheKey, {
      version: CUSTOMER_SERVICE_DRAFT_VERSION,
      conversationId,
      question,
      messages: compactDraftMessages(messages),
      savedAt: new Date().toISOString(),
    })
  }, [conversationId, draftCacheKey, messages, question])

  useEffect(() => {
    // Use scrollTop for instant scroll during streaming; smooth on completion
    const container = chatContainerRef.current
    if (container) {
      container.scrollTop = container.scrollHeight
    } else {
      bottomRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' })
    }
  }, [messages, loading])

  const latestSources = useMemo(() => {
    const msg = [...messages].reverse().find((item) => item.role === 'assistant' && !item.streaming && item.sources?.length)
    return (msg?.sources || []).filter((source) => !['agent_steps', 'agent_meta'].includes(String(source.type || '')))
  }, [messages])

  async function loadSideData() {
    try {
      const [conversationResult, status, review] = await Promise.all([
        api.customerService.conversations(),
        api.knowledgeBase.status(),
        api.customerService.reviewSamples(50),
      ])
      setConversations(conversationResult.items)
      setKnowledgeStatus(status)
      setReviewSummary(review.summary || null)
    } catch {
      // Side data should not block the chat surface.
    }
  }

  async function ask() {
    if (!question.trim()) return
    setLoading(true)
    setError('')
    const userText = question.trim()
    const assistantId = `assistant-${Date.now()}`
    let streamError = ''
    setQuestion('')
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: userText },
      { id: assistantId, role: 'assistant', content: '', streaming: true },
    ])

    try {
      await api.customerService.askStream(
        {
          question: userText,
          conversation_id: conversationId,
        },
        (event) => {
          if (event.type === 'status') {
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, status: event.label || event.message || '处理中...' }
                : message
            )))
            return
          }

          if (event.type === 'meta') {
            setConversationId(event.conversation_id)
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? {
                  ...message,
                  message_id: event.message_id,
                  intent: event.intent,
                  answer_type: event.answer_type,
                  confidence: event.confidence,
                  uncertainty: event.uncertainty,
                  needs_clarification: event.needs_clarification,
                  anomalies: event.anomalies || [],
                  suggested_followups: dedupe(event.suggested_followups || event.followups || []),
                  followups: dedupe(event.followups || event.suggested_followups || []),
                  warnings: dedupe(event.warnings || []),
                  evidence: event.evidence || [],
                  debug: event.debug || {},
                  feedback: event.feedback || null,
                  sources: event.sources,
                  actions: event.actions || [],
                  results: event.results || [],
                  steps: event.steps || [],
                }
                : message
            )))
            return
          }

          if (event.type === 'clarification') {
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? {
                  ...message,
                  needs_clarification: true,
                  suggested_followups: dedupe([...(message.suggested_followups || []), ...(event.suggested_followups || [])]),
                }
                : message
            )))
            return
          }

          if (event.type === 'warning') {
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, warnings: dedupe([...(message.warnings || []), event.message || '']) }
                : message
            )))
            return
          }

          if (event.type === 'recommendation') {
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, suggested_followups: dedupe([...(message.suggested_followups || []), event.message || '']) }
                : message
            )))
            return
          }

          if (event.type === 'answer_delta') {
            setMessages((prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, content: `${message.content}${event.text}`, status: '' }
                : message
            )))
            return
          }

          if (event.type === 'error') {
            streamError = event.message || '智能客服请求失败'
          }
        },
      )
      if (streamError) throw new Error(streamError)
      setMessages((prev) => prev.map((message) => (
        message.id === assistantId ? { ...message, streaming: false, status: '' } : message
      )))
      loadSideData()
    } catch (err) {
      const message = err instanceof Error ? err.message : '智能客服请求失败'
      setError(message)
      setMessages((prev) => prev.map((item) => (
        item.id === assistantId ? { ...item, content: message, streaming: false, status: '' } : item
      )))
    } finally {
      setLoading(false)
    }
  }

  async function openConversation(id: string) {
    setError('')
    try {
      const data = await api.customerService.conversation(id) as {
        id: string
        messages?: ChatMessage[]
      }
      setConversationId(data.id)
      setMessages(orderMessages(data.messages || []))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话失败')
    }
  }

  async function deleteConversation(id: string) {
    setError('')
    try {
      await api.customerService.deleteConversation(id)
      setConversations((prev) => prev.filter((item) => String(item.id) !== id))
      if (conversationId === id) {
        newConversation()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除会话失败')
    }
  }

  function newConversation() {
    setConversationId(null)
    setMessages([])
    setQuestion('')
    setError('')
    clearCustomerServiceDraft(draftCacheKey)
  }

  async function updateAction(actionId: string, mode: 'confirm' | 'cancel') {
    setActionLoadingId(actionId)
    setError('')
    try {
      const updated = mode === 'confirm'
        ? await api.customerService.confirmAction(actionId)
        : await api.customerService.cancelAction(actionId)
      setMessages((prev) => prev.map((message) => ({
        ...message,
        actions: message.actions?.map((action) => action.id === actionId ? updated : action),
      })))
    } catch (err) {
      setError(err instanceof Error ? err.message : '动作处理失败')
    } finally {
      setActionLoadingId(null)
    }
  }

  async function sendFeedback(message: ChatMessage, rating: 'helpful' | 'incorrect' | 'missing_data') {
    const messageId = message.message_id || message.id
    if (!messageId) return
    setFeedbackLoadingId(messageId)
    setError('')
    try {
      const result = await api.customerService.feedback(messageId, { rating })
      setMessages((prev) => prev.map((item) => (
        (item.message_id || item.id) === messageId ? { ...item, feedback: result.feedback } : item
      )))
    } catch (err) {
      setError(err instanceof Error ? err.message : '反馈提交失败')
    } finally {
      setFeedbackLoadingId(null)
    }
  }

  return (
    <div className="p-4 max-w-7xl mx-auto h-[calc(100vh-88px)]">
      <div className="grid grid-cols-12 gap-4 h-full">
        <aside className="col-span-12 lg:col-span-3 glass rounded-2xl overflow-hidden flex flex-col">
          <div className="p-4 border-b border-black/5 flex items-center justify-between">
            <div>
              <h1 className="text-lg font-bold text-apple-text">智能客服</h1>
            </div>
            <button onClick={newConversation} className="text-sm text-blue-500 hover:text-blue-700 shrink-0 whitespace-nowrap ml-2">新会话</button>
          </div>
          <div className="p-3 overflow-y-auto space-y-2">
            {conversations.length === 0 ? (
              <div className="text-sm text-apple-gray-medium px-2 py-8 text-center">暂无会话</div>
            ) : conversations.map((item) => (
              <div
                key={String(item.id)}
                className={`group flex items-start gap-2 rounded-xl transition-colors ${
                  conversationId === item.id ? 'bg-blue-50 text-blue-600' : 'hover:bg-black/[0.03] text-apple-text'
                }`}
              >
                <button
                  onClick={() => openConversation(String(item.id))}
                  className="min-w-0 flex-1 text-left px-3 py-2"
                >
                  <div className="text-sm font-medium truncate">{String(item.title || '客服会话')}</div>
                  <div className="text-xs text-apple-gray-medium mt-1 font-mono">{String(item.sku || '未选择 SKU')}</div>
                </button>
                <button
                  onClick={() => deleteConversation(String(item.id))}
                  className="mt-2 mr-2 shrink-0 rounded-lg px-2 py-1 text-xs text-red-500 opacity-0 transition-opacity hover:bg-red-50 group-hover:opacity-100"
                  title="删除会话"
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        </aside>

        <main className="col-span-12 lg:col-span-6 glass rounded-2xl overflow-hidden flex flex-col">
          <div className="p-4 border-b border-black/5">
            {isManagement && (
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setDebugMode((value) => !value)}
                  className={`px-3 py-2 rounded-xl text-xs border transition-colors ${
                    debugMode ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-white/70 border-black/10 text-apple-gray-dark'
                  }`}
                >
                  {debugMode ? '调试开启' : '调试模式'}
                </button>
              </div>
            )}
          </div>

          <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 ? (
              <div className="h-full flex items-center justify-center text-center text-apple-gray-medium text-sm">
                输入问题后开始。修改和删除只会生成确认卡，不会自动写库。
              </div>
            ) : messages.map((message, index) => (
              <div key={message.id || index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[88%] space-y-3 ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                  <div className={`rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                    message.role === 'user'
                      ? 'bg-blue-500 text-white'
                      : 'bg-black/[0.04] text-apple-text'
                  }`}>
                    {message.content || message.status || ''}
                  </div>

                  {message.role === 'assistant' && !message.streaming && message.needs_clarification && (
                    <div className="flex flex-wrap gap-2 text-[11px]">
                      <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 border border-amber-100">
                        需要澄清
                      </span>
                    </div>
                  )}

                  {message.role === 'assistant' && !message.streaming && message.uncertainty && message.uncertainty !== 'confirmed' && (
                    <UncertaintyNotice uncertainty={message.uncertainty} />
                  )}

                  {message.role === 'assistant' && !message.streaming && Boolean(message.evidence?.length) && (
                    <EvidenceList evidence={message.evidence || []} />
                  )}

                  {message.role === 'assistant' && !message.streaming && Boolean(message.suggested_followups?.length) && (
                    <HintList title="下一步建议" tone="info" items={dedupe(message.suggested_followups || []).slice(0, 3)} />
                  )}

                  {message.role === 'assistant' && !message.streaming && Boolean(message.results?.length) && (
                    <ResultList results={message.results || []} evidence={message.evidence || []} />
                  )}
                  {message.role === 'assistant' && !message.streaming && Boolean(message.actions?.length) && (
                    <ActionList
                      actions={message.actions || []}
                      loadingId={actionLoadingId}
                      onConfirm={(id) => updateAction(id, 'confirm')}
                      onCancel={(id) => updateAction(id, 'cancel')}
                    />
                  )}
                  {message.role === 'assistant' && !message.streaming && message.content && (
                    <FeedbackBar
                      feedback={message.feedback}
                      loading={feedbackLoadingId === (message.message_id || message.id)}
                      onFeedback={(rating) => sendFeedback(message, rating)}
                    />
                  )}
                  {message.role === 'assistant' && !message.streaming && debugMode && isManagement && (
                    <DebugPanel message={message} />
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <div className="p-4 border-t border-black/5">
            {error && <div className="text-sm text-red-500 mb-2">{error}</div>}
            <div className="flex items-end gap-3">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (!loading && question.trim()) ask()
                  }
                }}
                placeholder="输入客服问题，Enter 发送，Shift+Enter 换行"
                className="glass-input flex-1 px-3 py-2 text-sm min-h-[76px] resize-none"
              />
              <button onClick={ask} disabled={loading || !question.trim()} className="btn-primary px-5 py-2 text-sm disabled:opacity-50">
                {loading ? '处理中...' : '发送'}
              </button>
            </div>
          </div>
        </main>

        <aside className="col-span-12 lg:col-span-3 space-y-4">
          {debugMode && (
            <section className="glass rounded-2xl p-4">
              <h2 className="text-sm font-semibold text-apple-text mb-3">知识库状态</h2>
              <div className="space-y-2 text-sm">
                <Info label="pgvector" value={knowledgeStatus?.available ? '已启用' : '未启用'} />
                <Info label="知识分片" value={String(knowledgeStatus?.chunks ?? 0)} />
                <Info label="已向量化" value={String(knowledgeStatus?.embedded_chunks ?? 0)} />
              </div>
            </section>

          )}
          <section className="glass rounded-2xl p-4">
            <h2 className="text-sm font-semibold text-apple-text mb-3">本次依据</h2>
            {latestSources.length === 0 ? (
              <p className="text-sm text-apple-gray-medium">暂无来源</p>
            ) : (
              <div className="space-y-2">
                {latestSources.map((source, index) => (
                  <div key={index} className="px-3 py-2 rounded-xl bg-black/[0.03]">
                    {(() => {
                      const sourceSku = typeof source.sku === 'string' ? source.sku : ''
                      const sourceSkus = Array.isArray(source.result_skus) ? source.result_skus.map((sku) => String(sku)) : []
                      const sourceLayer = layerFromSource(source)
                      return (
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-apple-text">{String(source.label || source.type || '来源')}</div>
                        <div className="text-xs text-apple-gray-medium mt-1 font-mono">
                          {String(sourceSku || source.query || source.count || '')}
                        </div>
                        {sourceSkus.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {sourceSkus.slice(0, 6).map((sku) => (
                              <SourceLink key={sku} sku={sku} compact layer={sourceLayer} />
                            ))}
                          </div>
                        )}
                      </div>
                      {sourceSku && (
                        <SourceLink sku={sourceSku} layer={sourceLayer} />
                      )}
                    </div>
                      )
                    })()}
                  </div>
                ))}
              </div>
            )}
          </section>

          {debugMode && (
            <section className="glass rounded-2xl p-4">
              <h2 className="text-sm font-semibold text-apple-text mb-3">客服回放概览</h2>
              <div className="space-y-2 text-sm">
                <Info label="样本数" value={String(reviewSummary?.total_samples ?? 0)} />
                <Info label="澄清样本" value={String(reviewSummary?.clarification_samples ?? 0)} />
                <Info label="异常样本" value={String(reviewSummary?.anomaly_samples ?? 0)} />
              </div>
            </section>
          )}
        </aside>
    </div>
    </div>
  )
}

function HintList({ title, items, tone }: { title: string; items: string[]; tone: 'warning' | 'info' }) {
  const toneClass = tone === 'warning'
    ? 'border-amber-100 bg-amber-50/80 text-amber-800'
    : 'border-sky-100 bg-sky-50/80 text-sky-800'

  return (
    <div className={`rounded-xl border px-3 py-2 ${toneClass}`}>
      <div className="text-xs font-semibold">{title}</div>
      <div className="mt-1 space-y-1 text-xs">
        {items.map((item, index) => (
          <div key={`${title}-${index}`}>{item}</div>
        ))}
      </div>
    </div>
  )
}

function UncertaintyNotice({ uncertainty }: { uncertainty: string }) {
  const labels: Record<string, string> = {
    not_recorded: '资料未标注，暂不能确认',
    insufficient_data: '资料不足，结论可靠性较低',
    ambiguous_product: '需要先确认产品范围',
  }
  return (
    <div className="rounded-xl border border-amber-100 bg-amber-50/80 px-3 py-2 text-xs text-amber-800">
      {labels[uncertainty] || '当前回答存在不确定性'}
    </div>
  )
}

function EvidenceList({ evidence }: { evidence: Array<Record<string, unknown>> }) {
  const visible = evidence.slice(0, 5)
  return (
    <div className="rounded-xl border border-blue-100 bg-blue-50/60 px-3 py-2">
      <div className="text-xs font-semibold text-blue-700">核心依据</div>
      <div className="mt-1 space-y-1 text-xs text-blue-900">
        {visible.map((item, index) => (
          <div key={`${String(item.sku || '')}-${String(item.field_label || '')}-${index}`}>
            <span className="font-mono">{String(item.sku || '')}</span>
            {item.product_name ? ` ${String(item.product_name)}` : ''}：
            {String(item.field_label || '资料')}：{stringifyValue(item.value)}
          </div>
        ))}
      </div>
    </div>
  )
}

function orderMessages(items: ChatMessage[]): ChatMessage[] {
  return [...items].sort((left, right) => {
    const leftTime = timestampOf(left.created_at)
    const rightTime = timestampOf(right.created_at)
    if (leftTime !== rightTime) return leftTime - rightTime
    if (left.role !== right.role) return left.role === 'user' ? -1 : 1
    return 0
  })
}

function timestampOf(value?: string | null): number {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function customerServiceDraftKey(userKey?: string | null): string {
  return `customer-service:draft:${userKey || 'anonymous'}`
}

function loadCustomerServiceDraft(key: string): CustomerServiceDraft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const draft = JSON.parse(raw) as CustomerServiceDraft
    if (draft.version !== CUSTOMER_SERVICE_DRAFT_VERSION || !Array.isArray(draft.messages)) {
      localStorage.removeItem(key)
      return null
    }
    return draft
  } catch {
    localStorage.removeItem(key)
    return null
  }
}

function saveCustomerServiceDraft(key: string, draft: CustomerServiceDraft) {
  const hasContent = Boolean(draft.conversationId || draft.question.trim() || draft.messages.length)
  if (!hasContent) {
    localStorage.removeItem(key)
    return
  }

  try {
    localStorage.setItem(key, JSON.stringify(draft))
  } catch {
    try {
      localStorage.setItem(key, JSON.stringify({
        ...draft,
        messages: compactDraftMessages(draft.messages, 20),
      }))
    } catch {
      // Browser storage may be full or disabled; losing the draft should not break chat.
    }
  }
}

function clearCustomerServiceDraft(key: string) {
  localStorage.removeItem(key)
}

function compactDraftMessages(messages: ChatMessage[], maxMessages = 80): ChatMessage[] {
  return messages.slice(-maxMessages).map((message) => ({
    ...message,
    streaming: false,
    status: message.streaming ? '' : message.status,
  }))
}

function FeedbackBar({
  feedback,
  loading,
  onFeedback,
}: {
  feedback?: Record<string, unknown> | null
  loading: boolean
  onFeedback: (rating: 'helpful' | 'incorrect' | 'missing_data') => void
}) {
  const rating = String(feedback?.rating || '')
  const items: Array<{ rating: 'helpful' | 'incorrect' | 'missing_data'; label: string }> = [
    { rating: 'helpful', label: '有用' },
    { rating: 'incorrect', label: '不准确' },
    { rating: 'missing_data', label: '资料缺失' },
  ]
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <button
          key={item.rating}
          type="button"
          disabled={loading}
          onClick={() => onFeedback(item.rating)}
          className={`rounded-lg border px-2 py-1 text-[11px] transition-colors disabled:opacity-50 ${
            rating === item.rating
              ? 'border-blue-200 bg-blue-50 text-blue-700'
              : 'border-black/10 bg-white/70 text-apple-gray-dark hover:bg-black/[0.03]'
          }`}
        >
          {loading && rating === item.rating ? '提交中...' : item.label}
        </button>
      ))}
    </div>
  )
}

function DebugPanel({ message }: { message: ChatMessage }) {
  return (
    <div className="rounded-xl border border-emerald-100 bg-emerald-50/70 overflow-hidden">
      <div className="px-3 py-2 text-xs font-semibold text-emerald-700 border-b border-emerald-100">管理员调试</div>
      <div className="space-y-2 p-3 text-xs text-apple-text">
        <div className="flex flex-wrap gap-2">
          {message.intent && <Badge label={`意图：${message.intent}`} />}
          {message.answer_type && <Badge label={`类型：${message.answer_type}`} />}
          {message.confidence && <Badge label={`置信度：${message.confidence}`} />}
          {message.uncertainty && <Badge label={`不确定性：${message.uncertainty}`} />}
        </div>
        {Boolean(message.warnings?.length) && <HintList title="异常提示" tone="warning" items={message.warnings || []} />}
        {Boolean(message.steps?.length) && (
          <div>
            <div className="font-semibold text-emerald-700 mb-1">Agent 执行过程</div>
            <div className="space-y-1">
              {(message.steps || []).map((step, index) => (
                <div key={`${step.type}-${index}`} className="rounded-lg bg-white/60 px-2 py-1">
                  {step.label || step.type}{step.detail ? `：${step.detail}` : ''}
                </div>
              ))}
            </div>
          </div>
        )}
        {message.debug && Object.keys(message.debug).length > 0 && (
          <pre className="max-h-56 overflow-auto rounded-lg bg-white/70 p-2 text-[11px] text-apple-gray-dark whitespace-pre-wrap">
            {JSON.stringify(message.debug, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

function Badge({ label }: { label: string }) {
  return <span className="rounded-full bg-white/80 px-2 py-1 text-emerald-700 border border-emerald-100">{label}</span>
}

function ResultList({ results, evidence }: { results: ProductSearchResult[]; evidence: Array<Record<string, unknown>> }) {
  const navigate = useNavigate()
  const relatedFields = new Set(evidence.map((item) => String(item.field_label || '')).filter(Boolean))

  function openProduct(item: ProductSearchResult) {
    const sku = item.sku
    if (!sku) return
    const params = new URLSearchParams({ sku })
    const layer = layerFromField(item.field_label || item.matched_by || '')
    if (layer) params.set('layer', layer)
    navigate(`/products?${params.toString()}`)
  }

  return (
    <div className="rounded-xl border border-black/10 bg-white/70 overflow-hidden">
      <div className="px-3 py-2 text-xs font-semibold text-apple-gray-dark border-b border-black/5">查询结果</div>
      <div className="max-h-80 overflow-y-auto divide-y divide-black/5">
        {results.map((item, index) => (
          <button
            key={`${item.sku}-${item.field_label || item.matched_by || index}`}
            type="button"
            onClick={() => openProduct(item)}
            className="block w-full px-3 py-2 text-sm text-left hover:bg-blue-50/70 transition-colors"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono font-semibold text-blue-600">{item.sku}</span>
              <span className="text-xs text-apple-gray-medium">{item.matched_by || item.field_label || '产品资料'}</span>
            </div>
            <div className="mt-1 text-apple-text">{item.product_name_cn || item.product_name_en || '-'}</div>
            <div className="mt-1 text-xs text-apple-gray-medium">{resultSummary(item, relatedFields)}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function SourceLink({ sku, compact = false, layer }: { sku: string; compact?: boolean; layer?: string }) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => {
        const params = new URLSearchParams({ sku })
        if (layer) params.set('layer', layer)
        navigate(`/products?${params.toString()}`)
      }}
      className={`shrink-0 rounded-lg border border-blue-100 bg-blue-50 text-blue-700 hover:bg-blue-100 ${
        compact ? 'px-2 py-0.5 text-[10px]' : 'px-2 py-1 text-[11px]'
      }`}
    >
      {compact ? sku : '打开产品'}
    </button>
  )
}

function layerFromSource(source: Record<string, unknown>): string {
  const explicit = typeof source.layer === 'string' ? source.layer : ''
  if (explicit) return explicit
  switch (String(source.type || '')) {
    case 'product':
      return 'L1'
    case 'product_specs':
      return 'L2'
    case 'product_business':
      return 'L3'
    case 'product_content':
      return 'L4'
    case 'product_qa':
    case 'product_qa_negative':
    case 'knowledge_base':
      return 'L5'
    default:
      return ''
  }
}

function layerFromField(label: string): string {
  if (!label) return ''
  if (['容量', '重量', '毛重', '材质', '颜色', '表面工艺', '热源', '功率'].some((item) => label.includes(item))) return 'L2'
  if (['卖点', '目标人群', '定位', '价格定位', '情绪价值', '使用场景', '竞品'].some((item) => label.includes(item))) return 'L3'
  if (['标题', '描述', '关键词', 'listing', 'Listing', 'A+'].some((item) => label.includes(item))) return 'L4'
  if (['QA', '差评'].some((item) => label.includes(item))) return 'L5'
  if (['图片', '素材', '媒体'].some((item) => label.includes(item))) return 'L6'
  if (['品质', '负责人', '英文名', '英文名称', '类目', '品牌', '系列', '生命周期'].some((item) => label.includes(item))) return 'L1'
  return ''
}

function ActionList({
  actions,
  loadingId,
  onConfirm,
  onCancel,
}: {
  actions: AgentAction[]
  loadingId: string | null
  onConfirm: (id: string) => void
  onCancel: (id: string) => void
}) {
  return (
    <div className="space-y-2">
      {actions.map((action) => (
        <div key={action.id} className={`rounded-xl border p-3 text-sm ${action.action_type === 'delete_product' ? 'border-red-200 bg-red-50' : 'border-blue-100 bg-blue-50'}`}>
          <div className="flex items-center justify-between gap-3">
            <div className="font-semibold text-apple-text">{actionTitle(action)}</div>
            <StatusBadge status={action.status} />
          </div>
          <div className="mt-2 grid grid-cols-1 gap-1 text-xs text-apple-gray-dark">
            <Line label="产品" value={action.sku} mono />
            <Line label="位置" value={action.field_label || action.target_type} />
            {action.action_type !== 'delete_product' && (
              <>
                <Line label="原值" value={stringifyValue(action.original_value)} />
                <Line label="新值" value={stringifyValue(action.proposed_value)} />
              </>
            )}
            {action.action_type === 'delete_product' && (
              <Line label="删除范围" value={deletePreview(action.original_value)} />
            )}
            {action.status === 'stale' && (
              <Line label="当前值" value={stringifyValue(action.current_value || action.result)} />
            )}
          </div>
          {action.status === 'pending' && (
            <div className="mt-3 flex justify-end gap-2">
              <button
                onClick={() => onCancel(action.id)}
                disabled={loadingId === action.id}
                className="px-3 py-1.5 rounded-lg text-xs bg-white border border-black/10 hover:bg-black/[0.03] disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={() => onConfirm(action.id)}
                disabled={loadingId === action.id}
                className={`px-3 py-1.5 rounded-lg text-xs text-white disabled:opacity-50 ${action.action_type === 'delete_product' ? 'bg-red-500 hover:bg-red-600' : 'bg-blue-500 hover:bg-blue-600'}`}
              >
                {loadingId === action.id ? '执行中...' : '确认'}
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-apple-gray-medium">{label}</span>
      <span className="text-apple-text font-medium">{value}</span>
    </div>
  )
}

function Line({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[64px_1fr] gap-2">
      <span className="text-apple-gray-medium">{label}</span>
      <span className={mono ? 'font-mono text-apple-text break-all' : 'text-apple-text break-words'}>{value || '-'}</span>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: '待确认',
    confirmed: '已执行',
    cancelled: '已取消',
    stale: '需重确认',
    failed: '失败',
  }
  return (
    <span className="shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[11px] text-apple-gray-dark">
      {labels[status] || status}
    </span>
  )
}

function actionTitle(action: AgentAction) {
  if (action.action_type === 'delete_product') return '强确认：删除整个产品'
  if (action.action_type === 'delete_info') return '待确认：删除/清空信息'
  return '待确认：修改字段'
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function resultSummary(item: ProductSearchResult, relatedFields: Set<string>): string {
  if (item.field_values && Object.keys(item.field_values).length > 0) {
    return Object.entries(item.field_values)
      .map(([label, value]) => `${label}：${stringifyValue(value) || '暂无'}`)
      .join(' / ')
  }
  const shouldShow = (label: string) => relatedFields.size === 0 || relatedFields.has(label)
  const parts = [
    shouldShow('条形码') && item.barcode ? `条形码：${item.barcode}` : '',
    shouldShow('品牌') && item.brand ? `品牌：${item.brand}` : '',
    shouldShow('类目') && item.category ? `类目：${item.category}` : '',
    shouldShow('负责人') && item.person_in_charge ? `负责人：${item.person_in_charge}` : '',
    shouldShow('品质') && item.quality_note ? `品质：${item.quality_note}` : '',
    shouldShow('生命周期') && item.lifecycle_status ? `生命周期：${item.lifecycle_status}` : '',
    shouldShow('容量') && item.capacity ? `容量：${item.capacity}` : '',
    shouldShow('材质') && item.body_material ? `材质：${item.body_material}` : '',
    shouldShow('备注') && item.status_note ? `备注：${item.status_note}` : '',
  ].filter(Boolean)
  return parts.join(' / ') || stringifyValue(item.value) || item.features || ''
}

function deletePreview(value: unknown): string {
  if (!value || typeof value !== 'object') return stringifyValue(value)
  const preview = value as { will_delete?: Record<string, unknown> }
  const scope = preview.will_delete || {}
  return Object.entries(scope)
    .filter(([, v]) => Boolean(v))
    .map(([k, v]) => `${k}: ${v}`)
    .join('；')
}

function dedupe(items: string[]) {
  return Array.from(new Set(items.filter(Boolean)))
}
