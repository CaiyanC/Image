import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AgentAction, AgentStep, ApiRequestError, CustomerServicePipeline, ProductSearchResult, api } from '../services/api'
import { useAuthStore } from '../store/authStore'

interface ChatMessage {
  id?: string
  message_id?: string | null
  role: 'user' | 'assistant'
  content: string
  created_at?: string | null
  response_started_at?: number
  response_completed_at?: number
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
  answer_metadata?: Record<string, unknown>
  agent_quality?: Record<string, unknown>
  debug?: Record<string, unknown>
  feedback?: Record<string, unknown> | null
  sources?: Array<Record<string, unknown>>
  sku?: string | null
  result_skus?: string[]
  candidate_skus?: string[]
  actions?: AgentAction[]
  results?: ProductSearchResult[]
  steps?: AgentStep[]
}

interface CustomerServiceDraft {
  version: number
  activeConversationKey: ConversationKey
  conversationStates: Record<ConversationKey, CustomerConversationState>
  savedAt: string
}

type ConversationKey = string

interface CustomerConversationState {
  conversationId: string | null
  question: string
  messages: ChatMessage[]
  loading: boolean
  abortController: AbortController | null
  error: string
  title?: string
}

interface ConversationListItem {
  key: ConversationKey
  id: string | null
  title: string
  lastMessage: string
  loading: boolean
  deleting: boolean
}

const CUSTOMER_SERVICE_DRAFT_VERSION = 2

interface InFlightCustomerServiceRequest {
  abortController: AbortController
  snapshot: CustomerConversationState
}

// A route change unmounts CustomerService, but it must not cancel a request
// that the customer already sent.  Keep the active request outside the page
// component so its stream can continue and the next mount can reattach to the
// same conversation state.
const inFlightCustomerServiceRequests = new Map<string, InFlightCustomerServiceRequest>()

function inFlightCustomerServiceRequestKey(cacheKey: string, conversationKey: ConversationKey): string {
  return `${cacheKey}\u0000${conversationKey}`
}

function getInFlightCustomerServiceRequest(
  cacheKey: string,
  conversationKey: ConversationKey,
): InFlightCustomerServiceRequest | null {
  return inFlightCustomerServiceRequests.get(inFlightCustomerServiceRequestKey(cacheKey, conversationKey)) || null
}

function hasInFlightCustomerServiceRequests(cacheKey: string): boolean {
  const prefix = `${cacheKey}\u0000`
  return Array.from(inFlightCustomerServiceRequests.keys()).some((key) => key.startsWith(prefix))
}

function mergeInFlightCustomerServiceStates(
  cacheKey: string,
  states: Record<ConversationKey, CustomerConversationState>,
): Record<ConversationKey, CustomerConversationState> {
  const merged = { ...states }
  const prefix = `${cacheKey}\u0000`
  for (const [requestKey, request] of inFlightCustomerServiceRequests.entries()) {
    if (requestKey.startsWith(prefix)) {
      merged[requestKey.slice(prefix.length)] = request.snapshot
    }
  }
  return merged
}

function persistInFlightCustomerServiceState(
  cacheKey: string,
  conversationKey: ConversationKey,
  state: CustomerConversationState,
  activeConversationKey: ConversationKey,
) {
  const existing = loadCustomerServiceDraft(cacheKey)
  const conversationStates = existing?.conversationStates
    ? { ...existing.conversationStates }
    : {}
  conversationStates[conversationKey] = { ...state, abortController: null }
  saveCustomerServiceDraft(cacheKey, {
    version: CUSTOMER_SERVICE_DRAFT_VERSION,
    activeConversationKey: activeConversationKey || existing?.activeConversationKey || conversationKey,
    conversationStates,
    savedAt: new Date().toISOString(),
  })
}

function registerInFlightCustomerServiceRequest(
  cacheKey: string,
  conversationKey: ConversationKey,
  abortController: AbortController,
  snapshot: CustomerConversationState,
  activeConversationKey: ConversationKey,
) {
  inFlightCustomerServiceRequests.set(inFlightCustomerServiceRequestKey(cacheKey, conversationKey), {
    abortController,
    snapshot,
  })
  persistInFlightCustomerServiceState(cacheKey, conversationKey, snapshot, activeConversationKey)
}

function removeInFlightCustomerServiceRequest(cacheKey: string, conversationKey: ConversationKey) {
  inFlightCustomerServiceRequests.delete(inFlightCustomerServiceRequestKey(cacheKey, conversationKey))
}

function abortInFlightCustomerServiceRequest(cacheKey: string, conversationKey: ConversationKey) {
  getInFlightCustomerServiceRequest(cacheKey, conversationKey)?.abortController.abort()
}

interface CustomerServiceProps {
  pipeline?: CustomerServicePipeline
  title?: string
  subtitle?: string
}

export default function CustomerService({
  // The normal page keeps the established semantic-RAG baseline.  The Agent
  // page uses a dedicated server-owned endpoint, so production never needs to
  // trust a caller-supplied pipeline override.
  pipeline = 'semantic_rag_v2',
  title = '智能客服',
  subtitle = '基于产品资料和知识库回答',
}: CustomerServiceProps = {}) {
  const { isManagement, user } = useAuthStore()
  const canManageQa = isManagement || Boolean(
    user?.permissions?.includes('product.qa.manage') || user?.permissions?.includes('product.edit'),
  )
  const initialConversationKey = useMemo(() => createLocalConversationKey(), [])
  const [activeConversationKey, setActiveConversationKey] = useState<ConversationKey>(initialConversationKey)
  const [conversationStates, setConversationStates] = useState<Record<ConversationKey, CustomerConversationState>>(() => ({
    [initialConversationKey]: createConversationState(),
  }))
  const [conversations, setConversations] = useState<Array<Record<string, unknown>>>([])
  const [knowledgeStatus, setKnowledgeStatus] = useState<Record<string, unknown> | null>(null)
  const [reviewSummary, setReviewSummary] = useState<Record<string, unknown> | null>(null)
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null)
  const [debugMode, setDebugMode] = useState(false)
  const [feedbackLoadingId, setFeedbackLoadingId] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const chatContainerRef = useRef<HTMLDivElement | null>(null)
  const deletedConversationKeysRef = useRef<Set<ConversationKey>>(new Set())
  const deletedConversationIdsRef = useRef<Set<string>>(new Set())
  // The ref is an immediate mutual-exclusion guard. React state alone is
  // asynchronous, so it cannot stop two rapid clicks from issuing two DELETEs.
  const deletingConversationKeysRef = useRef<Set<ConversationKey>>(new Set())
  const [deletingConversationKeys, setDeletingConversationKeys] = useState<Set<ConversationKey>>(() => new Set())
  const activeConversationKeyRef = useRef(activeConversationKey)
  const conversationListRequestRef = useRef(0)
  const draftHydratedRef = useRef(false)
  const skipNextDraftPersistRef = useRef(false)
  const draftCacheKey = useMemo(
    () => customerServiceDraftKey(user?.id || user?.username, pipeline),
    [pipeline, user?.id, user?.username],
  )
  const activeConversation = conversationStates[activeConversationKey] || createConversationState()
  const question = activeConversation.question
  const messages = activeConversation.messages
  const loading = activeConversation.loading
  const error = activeConversation.error

  useEffect(() => {
    activeConversationKeyRef.current = activeConversationKey
  }, [activeConversationKey])

  useEffect(() => {
    if (!Object.values(conversationStates).some((state) => state.loading)) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [conversationStates])

  useEffect(() => {
    skipNextDraftPersistRef.current = true
    draftHydratedRef.current = false
    const draft = loadCustomerServiceDraft(draftCacheKey)
    const savedStates = mergeInFlightCustomerServiceStates(draftCacheKey, draft?.conversationStates || {})
    const states = Object.keys(savedStates).length
      ? restoreConversationStates(savedStates, draftCacheKey)
      : { [initialConversationKey]: createConversationState() }
    const draftKey = draft?.activeConversationKey && states[draft.activeConversationKey]
      ? draft.activeConversationKey
      : Object.keys(states)[0]
    setActiveConversationKey(draftKey)
    setConversationStates(states)
    draftHydratedRef.current = true
  }, [draftCacheKey, initialConversationKey])

  useEffect(() => {
    if (!draftHydratedRef.current) return
    if (skipNextDraftPersistRef.current) {
      skipNextDraftPersistRef.current = false
      return
    }
    saveCustomerServiceDraft(draftCacheKey, {
      version: CUSTOMER_SERVICE_DRAFT_VERSION,
      activeConversationKey,
      conversationStates: serializeConversationStates(conversationStates),
      savedAt: new Date().toISOString(),
    })
  }, [activeConversationKey, conversationStates, draftCacheKey])

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

  const conversationListItems = useMemo(() => {
    const visibleConversations = conversations.filter((item) => !deletedConversationIdsRef.current.has(String(item.id)))
    const serverIds = new Set(visibleConversations.map((item) => String(item.id)))
    const serverItems = visibleConversations.map((item): ConversationListItem => {
      const id = String(item.id)
      const key = findConversationKeyById(conversationStates, id) || conversationKeyForId(id)
      const state = conversationStates[key]
      return {
        key,
        id,
        title: String(item.title || state?.title || titleFromMessages(state?.messages || []) || '客服会话'),
        lastMessage: String(item.last_message || item.sku || lastMessagePreview(state?.messages || []) || '暂无消息'),
        loading: Boolean(state?.loading),
        deleting: deletingConversationKeys.has(key),
      }
    })
    const localItems = Object.entries(conversationStates)
      .filter(([, state]) => !state.conversationId || !serverIds.has(state.conversationId))
      .map(([key, state]): ConversationListItem => ({
        key,
        id: state.conversationId,
        title: state.title || titleFromMessages(state.messages) || (state.question.trim() ? state.question.trim().slice(0, 20) : '客服会话'),
        lastMessage: lastMessagePreview(state.messages) || state.question || '暂无消息',
        loading: state.loading,
        deleting: deletingConversationKeys.has(key),
      }))
    return [...localItems, ...serverItems]
  }, [conversationStates, conversations, deletingConversationKeys])

  function updateConversationState(
    key: ConversationKey,
    updater: (state: CustomerConversationState) => CustomerConversationState,
  ) {
    if (!deletedConversationKeysRef.current.has(key)) {
      const inFlight = getInFlightCustomerServiceRequest(draftCacheKey, key)
      if (inFlight) {
        inFlight.snapshot = updater(inFlight.snapshot)
        // This write is intentionally independent of React.  It keeps the
        // latest streamed text/status available after this page unmounts.
        persistInFlightCustomerServiceState(
          draftCacheKey,
          key,
          inFlight.snapshot,
          activeConversationKeyRef.current,
        )
      }
    }
    setConversationStates((prev) => {
      if (deletedConversationKeysRef.current.has(key)) return prev
      const current = prev[key] || createConversationState()
      return { ...prev, [key]: updater(current) }
    })
  }

  function updateConversationMessages(key: ConversationKey, updater: (messages: ChatMessage[]) => ChatMessage[]) {
    updateConversationState(key, (state) => ({ ...state, messages: updater(state.messages) }))
  }

  function updateActiveConversation(updater: (state: CustomerConversationState) => CustomerConversationState) {
    updateConversationState(activeConversationKey, updater)
  }

  const loadConversationList = useCallback(async () => {
    const requestVersion = ++conversationListRequestRef.current
    try {
      const conversationResult = await api.customerService.conversations(0, 30, pipeline)
      if (requestVersion !== conversationListRequestRef.current) return
      // A response that began before a deletion may complete afterward.  Do
      // not let that stale list response resurrect an already deleted row.
      setConversations(conversationResult.items.filter((item) => !deletedConversationIdsRef.current.has(String(item.id))))
      if (conversationResult.total === 0 && !hasInFlightCustomerServiceRequests(draftCacheKey)) {
        // Server-side history may be cleared outside this tab.  A persisted
        // draft with a former conversation_id is no longer a real session and
        // must not be rendered or reused for the next ask request.
        localStorage.removeItem(draftCacheKey)
        const activeKey = activeConversationKeyRef.current
        setConversationStates((prev) => {
          const next: Record<ConversationKey, CustomerConversationState> = {}
          for (const [key, state] of Object.entries(prev)) {
            if (!state.conversationId || state.loading) {
              next[key] = state
            } else if (key === activeKey) {
              next[key] = createConversationState()
            }
          }
          return Object.keys(next).length ? next : { [activeKey]: createConversationState() }
        })
      }
    } catch {
      // Conversation history must not block the chat surface.
    }
  }, [draftCacheKey, pipeline])

  const loadSideData = useCallback(async () => {
    // History is an independently useful, lightweight request.  Do not wait
    // for knowledge/review panels before showing it, otherwise old records
    // appear as a surprising late batch after the user sends a new message.
    void loadConversationList()
    try {
      const [status, review] = await Promise.all([
        api.knowledgeBase.status(),
        api.customerService.reviewSamples(50),
      ])
      setKnowledgeStatus(status)
      setReviewSummary(review.summary || null)
    } catch {
      // Side data should not block the chat surface.
    }
  }, [loadConversationList])

  useEffect(() => {
    void loadSideData()
  }, [loadSideData])

  async function ask() {
    const requestKey = activeConversationKey
    const requestState = conversationStates[requestKey] || createConversationState()
    if (requestState.loading || !requestState.question.trim()) return
    const userText = requestState.question.trim()
    const requestConversationId = requestState.conversationId
    const assistantId = `assistant-${Date.now()}`
    const abortController = new AbortController()
    let streamError = ''
    const responseStartedAt = Date.now()
    const startedState = createConversationState({
      ...requestState,
      question: '',
      loading: true,
      abortController,
      error: '',
      title: requestState.title || userText.slice(0, 20),
      messages: [
        ...requestState.messages,
        { role: 'user', content: userText },
        { id: assistantId, role: 'assistant', content: '', streaming: true, response_started_at: responseStartedAt },
      ],
    })
    registerInFlightCustomerServiceRequest(
      draftCacheKey,
      requestKey,
      abortController,
      startedState,
      activeConversationKeyRef.current,
    )
    updateConversationState(requestKey, () => startedState)

    try {
      await api.customerService.askStream(
        {
          question: userText,
          conversation_id: requestConversationId,
        },
        (event) => {
          if (event.type === 'status') {
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, status: event.label || event.message || '处理中...' }
                : message
            )))
            return
          }

          if (event.type === 'meta') {
            updateConversationState(requestKey, (state) => ({
              ...state,
              conversationId: event.conversation_id,
              messages: state.messages.map((message) => (
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
                    answer_metadata: event.answer_metadata || {},
                    agent_quality: event.agent_quality || {},
                    debug: event.debug || {},
                    feedback: event.feedback || null,
                    sources: event.sources,
                    sku: event.sku,
                    result_skus: event.result_skus || [],
                    candidate_skus: event.candidate_skus || [],
                    actions: event.actions || [],
                    results: event.results || [],
                    steps: event.steps || [],
                  }
                  : message
              )),
            }))
            return
          }

          if (event.type === 'clarification') {
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
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
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, warnings: dedupe([...(message.warnings || []), event.message || '']) }
                : message
            )))
            return
          }

          if (event.type === 'recommendation') {
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, suggested_followups: dedupe([...(message.suggested_followups || []), event.message || '']) }
                : message
            )))
            return
          }

          if (event.type === 'content') {
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
              message.id === assistantId
                ? { ...message, content: `${message.content}${event.content}`, status: '' }
                : message
            )))
            return
          }

          if (event.type === 'answer_delta') {
            updateConversationMessages(requestKey, (prev) => prev.map((message) => (
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
        abortController.signal,
        pipeline,
      )
      if (streamError) throw new Error(streamError)
      updateConversationMessages(requestKey, (prev) => prev.map((message) => (
        message.id === assistantId ? { ...message, streaming: false, status: '', response_completed_at: Date.now() } : message
      )))
      loadSideData()
    } catch (err) {
      if (abortController.signal.aborted || isAbortError(err)) {
        updateConversationMessages(requestKey, (prev) => prev.map((item) => (
          item.id === assistantId ? { ...item, streaming: false, status: '', response_completed_at: Date.now() } : item
        )))
        return
      }
      if (err instanceof ApiRequestError && err.status === 404 && requestConversationId) {
        // The server has already removed this history (for example after a
        // cleanup in another tab).  Reset the local draft instead of keeping
        // a dead conversation_id that can never be sent again.
        deletedConversationIdsRef.current.add(requestConversationId)
        localStorage.removeItem(draftCacheKey)
        setConversations((prev) => prev.filter((conversation) => String(conversation.id) !== requestConversationId))
        updateConversationState(requestKey, () => createConversationState({
          question: userText,
          error: '历史会话已被清理，已新建会话；请重新发送。',
        }))
        return
      }
      const message = err instanceof Error ? err.message : '智能客服请求失败'
      updateConversationState(requestKey, (state) => ({
        ...state,
        error: message,
        messages: state.messages.map((item) => (
          item.id === assistantId ? { ...item, content: message, streaming: false, status: '', response_completed_at: Date.now() } : item
        )),
      }))
    } finally {
      updateConversationState(requestKey, (state) => ({
        ...state,
        loading: false,
        abortController: state.abortController === abortController ? null : state.abortController,
      }))
      removeInFlightCustomerServiceRequest(draftCacheKey, requestKey)
    }
  }

  function cancelCurrentAnswer() {
    conversationStates[activeConversationKey]?.abortController?.abort()
    abortInFlightCustomerServiceRequest(draftCacheKey, activeConversationKey)
  }

  async function openConversation(id: string, preferredKey?: ConversationKey) {
    const key = preferredKey || findConversationKeyById(conversationStates, id) || conversationKeyForId(id)
    setActiveConversationKey(key)
    updateConversationState(key, (state) => ({ ...state, conversationId: state.conversationId || id, error: '' }))
    const current = conversationStates[key]
    if (current?.loading || current?.messages.length) return
    try {
      const data = await api.customerService.conversation(id, pipeline) as {
        id: string
        messages?: ChatMessage[]
      }
      updateConversationState(key, (state) => ({
        ...state,
        conversationId: data.id,
        messages: orderMessages(data.messages || []),
        error: '',
      }))
    } catch (err) {
      updateConversationState(key, (state) => ({
        ...state,
        error: err instanceof Error ? err.message : '加载会话失败',
      }))
    }
  }

  async function deleteConversation(item: ConversationListItem) {
    if (deletedConversationKeysRef.current.has(item.key) || deletingConversationKeysRef.current.has(item.key)) return
    conversationStates[item.key]?.abortController?.abort()
    abortInFlightCustomerServiceRequest(draftCacheKey, item.key)
    // Tombstone the local key before awaiting the HTTP request.  A cancelled
    // stream can still deliver a final event briefly; without this guard that
    // event writes the deleted chat back into React state and localStorage.
    deletedConversationKeysRef.current.add(item.key)
    if (item.id) deletedConversationIdsRef.current.add(item.id)
    deletingConversationKeysRef.current.add(item.key)
    setDeletingConversationKeys((prev) => new Set(prev).add(item.key))
    const remainingItems = conversationListItems.filter((conversation) => conversation.key !== item.key)
    const deletedIndex = conversationListItems.findIndex((conversation) => conversation.key === item.key)
    const nextItem = remainingItems.find((conversation) => !deletingConversationKeysRef.current.has(conversation.key))
      || remainingItems[Math.min(Math.max(deletedIndex, 0), Math.max(remainingItems.length - 1, 0))]
    try {
      if (item.id) {
        await api.customerService.deleteConversation(item.id, pipeline)
        setConversations((prev) => prev.filter((conversation) => String(conversation.id) !== item.id))
      }
      setConversationStates((prev) => {
        const next = { ...prev }
        delete next[item.key]
        return next
      })
      if (activeConversationKeyRef.current === item.key) {
        if (nextItem?.id) {
          void openConversation(nextItem.id, nextItem.key)
        } else if (nextItem) {
          setActiveConversationKey(nextItem.key)
        } else {
          const key = createLocalConversationKey()
          setConversationStates((prev) => ({ ...prev, [key]: createConversationState() }))
          setActiveConversationKey(key)
        }
      }
    } catch (err) {
      // The server did not delete the conversation, so restore normal state
      // updates and keep the existing chat available with a visible error.
      deletedConversationKeysRef.current.delete(item.key)
      if (item.id) deletedConversationIdsRef.current.delete(item.id)
      updateConversationState(item.key, (state) => ({
        ...state,
        error: err instanceof Error ? err.message : '删除会话失败',
      }))
    } finally {
      deletingConversationKeysRef.current.delete(item.key)
      setDeletingConversationKeys((prev) => {
        if (!prev.has(item.key)) return prev
        const next = new Set(prev)
        next.delete(item.key)
        return next
      })
    }
  }

  function newConversation() {
    const key = createLocalConversationKey()
    setConversationStates((prev) => ({ ...prev, [key]: createConversationState() }))
    setActiveConversationKey(key)
  }

  async function updateAction(actionId: string, mode: 'confirm' | 'cancel') {
    const requestKey = activeConversationKey
    setActionLoadingId(actionId)
    updateConversationState(requestKey, (state) => ({ ...state, error: '' }))
    try {
      const updated = mode === 'confirm'
        ? await api.customerService.confirmAction(actionId)
        : await api.customerService.cancelAction(actionId)
      updateConversationMessages(requestKey, (prev) => prev.map((message) => ({
        ...message,
        actions: message.actions?.map((action) => action.id === actionId ? updated : action),
      })))
    } catch (err) {
      updateConversationState(requestKey, (state) => ({
        ...state,
        error: err instanceof Error ? err.message : '动作处理失败',
      }))
    } finally {
      setActionLoadingId(null)
    }
  }

  async function sendFeedback(message: ChatMessage, rating: 'helpful' | 'incorrect' | 'missing_data') {
    const requestKey = activeConversationKey
    const messageId = message.message_id || message.id
    if (!messageId) return
    setFeedbackLoadingId(messageId)
    updateConversationState(requestKey, (state) => ({ ...state, error: '' }))
    try {
      const result = await api.customerService.feedback(messageId, { rating })
      updateConversationMessages(requestKey, (prev) => prev.map((item) => (
        (item.message_id || item.id) === messageId ? { ...item, feedback: result.feedback } : item
      )))
    } catch (err) {
      updateConversationState(requestKey, (state) => ({
        ...state,
        error: err instanceof Error ? err.message : '反馈提交失败',
      }))
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
              <h1 className="text-lg font-bold text-apple-text">{title}</h1>
              <p className="mt-1 text-[11px] text-apple-gray-medium">{subtitle}</p>
            </div>
            <button onClick={newConversation} className="text-sm text-blue-500 hover:text-blue-700 shrink-0 whitespace-nowrap ml-2">新会话</button>
          </div>
          <div className="p-3 overflow-y-auto space-y-2">
            {conversationListItems.length === 0 ? (
              <div className="text-sm text-apple-gray-medium px-2 py-8 text-center">暂无会话</div>
            ) : conversationListItems.map((item) => (
              <div
                key={item.key}
                className={`group flex items-start gap-2 rounded-xl transition-colors ${
                  activeConversationKey === item.key ? 'bg-blue-50 text-blue-600' : 'hover:bg-black/[0.03] text-apple-text'
                }`}
              >
                <button
                  onClick={() => item.id ? openConversation(item.id, item.key) : setActiveConversationKey(item.key)}
                  className="min-w-0 flex-1 text-left px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 text-sm font-medium truncate">{item.title}</span>
                    {item.loading && (
                      <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-700 border border-emerald-100">
                        生成中
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-apple-gray-medium mt-1 truncate">
                    {item.lastMessage}
                  </div>
                </button>
                <button
                  onClick={() => deleteConversation(item)}
                  disabled={item.deleting}
                  className="mt-2 mr-2 shrink-0 rounded-lg px-2 py-1 text-xs text-red-500 opacity-0 transition-opacity hover:bg-red-50 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-60"
                  title={item.deleting ? '正在删除会话' : '删除会话'}
                >
                  {item.deleting ? '删除中…' : '删除'}
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

                  {message.role === 'assistant' && message.response_started_at && (
                    <div className="px-1 text-[11px] text-apple-gray-medium">
                      {message.streaming ? '回复中' : '回复耗时'} {formatResponseDuration(message.response_started_at, message.response_completed_at || now)}
                    </div>
                  )}

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
                    <div className="flex flex-wrap items-center gap-2">
                      <FeedbackBar
                        feedback={message.feedback}
                        loading={feedbackLoadingId === (message.message_id || message.id)}
                        onFeedback={(rating) => sendFeedback(message, rating)}
                      />
                      {canManageQa && (
                        <AddQaButton
                          message={message}
                          question={previousUserQuestionForMessage(messages, index)}
                        />
                      )}
                    </div>
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
                onChange={(e) => {
                  const value = e.target.value
                  updateActiveConversation((state) => ({ ...state, question: value }))
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (!loading && question.trim()) ask()
                  }
                }}
                placeholder="输入客服问题，Enter 发送，Shift+Enter 换行"
                className="glass-input flex-1 px-3 py-2 text-sm min-h-[76px] resize-none"
              />
              <button
                type="button"
                onClick={loading ? cancelCurrentAnswer : ask}
                disabled={!loading && !question.trim()}
                className={loading ? 'px-5 py-2 text-sm rounded-xl bg-red-500 text-white hover:bg-red-600' : 'btn-primary px-5 py-2 text-sm disabled:opacity-50'}
              >
                {loading ? '取消' : '发送'}
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

function createConversationState(overrides: Partial<CustomerConversationState> = {}): CustomerConversationState {
  return {
    conversationId: null,
    question: '',
    messages: [],
    loading: false,
    abortController: null,
    error: '',
    ...overrides,
  }
}

function serializeConversationStates(
  states: Record<ConversationKey, CustomerConversationState>,
  maxMessages = 80,
): Record<ConversationKey, CustomerConversationState> {
  return Object.fromEntries(Object.entries(states).map(([key, state]) => [key, {
    ...state,
    abortController: null,
    messages: compactDraftMessages(state.messages, maxMessages, state.loading),
  }]))
}

function restoreConversationStates(
  states: Record<ConversationKey, CustomerConversationState>,
  cacheKey?: string,
): Record<ConversationKey, CustomerConversationState> {
  return Object.fromEntries(Object.entries(states).map(([key, state]) => {
    const inFlight = cacheKey ? getInFlightCustomerServiceRequest(cacheKey, key) : null
    const source = inFlight?.snapshot || state
    const pending = Boolean(inFlight && source.loading)
    return [key, createConversationState({
      ...source,
      loading: pending,
      abortController: inFlight?.abortController || null,
      messages: compactDraftMessages(source.messages || [], 80, pending),
    })]
  }))
}

function formatResponseDuration(startedAt: number, endedAt: number): string {
  const milliseconds = Math.max(0, endedAt - startedAt)
  return `${(milliseconds / 1000).toFixed(milliseconds < 10_000 ? 1 : 0)} 秒`
}

function createLocalConversationKey(): ConversationKey {
  return `local:${Date.now()}:${Math.random().toString(36).slice(2)}`
}

function conversationKeyForId(id: string): ConversationKey {
  return `server:${id}`
}

function findConversationKeyById(
  states: Record<ConversationKey, CustomerConversationState>,
  id: string,
): ConversationKey | null {
  return Object.entries(states).find(([, state]) => state.conversationId === id)?.[0] || null
}

function titleFromMessages(messages: ChatMessage[]): string {
  return messages.find((message) => message.role === 'user')?.content.trim().slice(0, 20) || ''
}

function lastMessagePreview(messages: ChatMessage[]): string {
  const message = [...messages].reverse().find((item) => item.content.trim() || item.status?.trim())
  return (message?.content || message?.status || '').trim().slice(0, 40)
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

function customerServiceDraftKey(
  userKey?: string | null,
  pipeline: CustomerServicePipeline = 'semantic_rag_v2',
): string {
  return `customer-service:draft:${pipeline}:${userKey || 'anonymous'}`
}

function loadCustomerServiceDraft(key: string): CustomerServiceDraft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const draft = JSON.parse(raw) as CustomerServiceDraft
    if (
      draft.version !== CUSTOMER_SERVICE_DRAFT_VERSION
      || !draft.activeConversationKey
      || !draft.conversationStates
      || typeof draft.conversationStates !== 'object'
    ) {
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
  const states = Object.values(draft.conversationStates)
  const hasContent = states.length > 1 || states.some((state) => (
    state.conversationId || state.question.trim() || state.messages.length
  ))
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
        conversationStates: serializeConversationStates(draft.conversationStates, 20),
      }))
    } catch {
      // Browser storage may be full or disabled; losing the draft should not break chat.
    }
  }
}

function compactDraftMessages(messages: ChatMessage[], maxMessages = 80, preservePending = false): ChatMessage[] {
  return messages.slice(-maxMessages).map((message) => ({
    ...message,
    streaming: preservePending ? message.streaming : false,
    status: preservePending ? message.status : (message.streaming ? '' : message.status),
    response_completed_at: preservePending ? message.response_completed_at : (message.streaming ? Date.now() : message.response_completed_at),
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

function AddQaButton({ message, question }: { message: ChatMessage; question: string }) {
  const navigate = useNavigate()
  if (!question.trim()) return null

  const skus = skuCandidatesFromMessage(message)
  const boundSku = skus.length === 1 ? skus[0] : ''

  function openQaForm() {
    const params = new URLSearchParams({ question: question.trim() })
    if (boundSku) params.set('sku', boundSku)
    navigate(`/products/qa/new?${params.toString()}`)
  }

  return (
    <button
      type="button"
      onClick={openQaForm}
      title={boundSku ? `已从结构化回答来源带入 ${boundSku}` : '回答未绑定唯一 SKU，请在下一页确认'}
      className="rounded-lg border border-teal-100 bg-teal-50 px-2 py-1 text-[11px] text-teal-700 transition-colors hover:bg-teal-100"
    >
      {boundSku ? `添加 QA · ${boundSku}` : '添加 QA'}
    </button>
  )
}

function previousUserQuestionForMessage(messages: ChatMessage[], index: number): string {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (messages[cursor].role === 'user') return messages[cursor].content.trim()
  }
  return ''
}

function skuCandidatesFromMessage(message: ChatMessage): string[] {
  const candidates: string[] = []
  const add = (value: unknown) => {
    if (value === null || value === undefined || typeof value === 'object') return
    const normalized = String(value).trim().toUpperCase()
    if (normalized && !candidates.includes(normalized)) candidates.push(normalized)
  }
  const addList = (value: unknown) => {
    if (!Array.isArray(value)) return
    value.forEach(add)
  }

  add(message.sku)
  addList(message.result_skus)
  addList(message.candidate_skus)
  for (const item of message.results || []) add(item.sku)
  for (const item of message.evidence || []) add(item.sku)

  const metadata = message.answer_metadata || {}
  add(metadata.current_sku)
  add(metadata.resolved_sku)
  add(metadata.final_choice_sku)
  for (const source of message.sources || []) {
    add(source.sku)
    addList(source.result_skus)
    addList(source.candidate_skus)
    const recommendationContext = source.recommendation_context
    if (recommendationContext && typeof recommendationContext === 'object') {
      const context = recommendationContext as Record<string, unknown>
      addList(context.recommended_skus)
      addList(context.ordered_result_skus)
    }
    const candidateContext = source.candidate_context
    if (candidateContext && typeof candidateContext === 'object') {
      const context = candidateContext as Record<string, unknown>
      addList(context.candidate_skus)
      addList(context.ordered_result_skus)
    }
    if (Array.isArray(source.results)) {
      source.results.forEach((row) => {
        if (row && typeof row === 'object') add((row as Record<string, unknown>).sku)
      })
    }
  }
  return candidates
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
    stale: '需重新确认',
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

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
