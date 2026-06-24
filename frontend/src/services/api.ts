const API_BASE_ENV = import.meta.env.VITE_API_BASE_URL || '/api'
const BASE_URL = resolveApiBaseUrl(API_BASE_ENV)
const TRACE_CUSTOMER_AGENT = import.meta.env.VITE_TRACE_CUSTOMER_AGENT === 'true'

import type { AssetGrouped, AssetTags, AssetUploadResponse, Product, ProductAsset, ProductListResponse, ProductDraft } from '../types'
import { NO_PERMISSION_MESSAGE, showNoPermissionToast } from './permissionFeedback'

const ERROR_MESSAGES: Record<string, string> = {
  'Incorrect username or password': '账号或密码错误',
  'Account is disabled': '账号已被禁用，请联系管理员',
  'Unauthorized': '登录已过期，请重新登录',
  'Could not validate credentials': '登录已过期，请重新登录',
  'Super admin privileges required': '没有管理员权限',
  'Public registration is disabled': '公开注册已关闭，请联系管理员创建账号',
  'Permission required: product.edit': '没有产品编辑权限',
  'Permission required: product.read': '没有产品查看权限',
  'Permission required: product.create': '没有产品创建权限',
  'Permission required: product.delete': '没有产品删除权限',
  'Permission required: ai.generate': '没有 AI 生图权限',
  'Permission required: ai.customer_service': '没有智能客服权限',
  'Permission required: history.view': '没有历史记录查看权限',
  'Permission required: profile.view': '没有个人资料查看权限',
  'Permission required: category.read': '没有品类查看权限',
  'Product not found': '产品不存在',
  'User not found': '用户不存在或已被删除，请刷新用户列表',
  'Group not found': '团队不存在或已被删除，请刷新页面',
  'Not Found': '接口不存在，请确认后端服务已重启',
  'Request failed': '请求失败',
}

function normalizeErrorMessage(detail: unknown, status?: number) {
  const raw = typeof detail === 'string' ? detail : JSON.stringify(detail || '')
  if (ERROR_MESSAGES[raw]) return ERROR_MESSAGES[raw]
  if (status === 404) return '接口或数据不存在，请刷新页面后重试'
  if (status === 403) return NO_PERMISSION_MESSAGE
  if (status === 401) return '账号或密码错误'
  return raw || '请求失败'
}

function shouldTraceCustomerAgent(url: string) {
  return TRACE_CUSTOMER_AGENT && (url.startsWith('/customer-service/ask') || url.includes('/customer-service/actions/'))
}

function traceCustomerAgent(label: string, payload: unknown) {
  try {
    console.log(`[CUSTOMER_AGENT_BROWSER_${label}]`, sanitizeTracePayload(payload))
  } catch {
    console.log(`[CUSTOMER_AGENT_BROWSER_${label}]`, payload)
  }
}

function sanitizeTracePayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeTracePayload)
  if (value && typeof value === 'object') {
    const result: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      const lower = key.toLowerCase()
      if (lower.includes('token') || lower.includes('password') || lower.includes('authorization')) {
        result[key] = '***'
      } else {
        result[key] = sanitizeTracePayload(item)
      }
    }
    return result
  }
  return value
}

function parseTraceBody(body: BodyInit | null | undefined) {
  if (typeof body !== 'string') return body ? '[non-json body]' : undefined
  try {
    return JSON.parse(body)
  } catch {
    return body
  }
}

function resolveApiBaseUrl(value: string) {
  if (value !== 'auto') return value
  if (typeof window === 'undefined') return '/api'
  const protocol = window.location.protocol || 'http:'
  const hostname = window.location.hostname || 'localhost'
  return `${protocol}//${hostname}:8000/api`
}

function toBackendUrl(path: string) {
  if (path.startsWith('http')) return path
  if (BASE_URL.startsWith('http')) {
    return `${BASE_URL.replace(/\/api\/?$/, '')}${path}`
  }
  return path
}

export interface CategoryItem {
  id: string
  category_name: string
  description?: string | null
}

export interface AgentAction {
  id: string
  action_type: string
  sku: string
  target_type: string
  target_id?: string | null
  field_path?: string | null
  field_label?: string | null
  original_value?: unknown
  proposed_value?: unknown
  status: string
  result?: unknown
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  current_value?: unknown
}

export interface ProductSearchResult {
  sku: string
  barcode?: string | null
  product_name_cn?: string | null
  product_name_en?: string | null
  brand?: string | null
  series?: string | null
  category?: string | null
  sub_category?: string | null
  product_level?: string | null
  lifecycle_status?: string | null
  person_in_charge?: string | null
  quality_note?: string | null
  status_note?: string | null
  capacity?: string | null
  body_material?: string | null
  color?: string | null
  surface_finish?: string | null
  heat_source?: string | null
  power?: string | null
  matched_by?: string | null
  features?: string | null
  field_label?: string | null
  field_values?: Record<string, unknown>
  value?: unknown
}

export interface AgentStep {
  type: string
  label: string
  detail?: string
  ok?: boolean
}

export interface CustomerServiceAskResult {
  conversation_id: string
  message_id?: string | null
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
  sku: string | null
  answer: string
  sources: Array<Record<string, unknown>>
  actions: AgentAction[]
  results: ProductSearchResult[]
  steps: AgentStep[]
}

export interface KnowledgeBaseHealth {
  grade: 'healthy' | 'warning' | 'critical' | string
  vector: {
    available: boolean
    extension: boolean
    embedding_column: boolean
    chunks: number
    embedded_chunks: number
    error?: string
  }
  totals: {
    products: number
    documents: number
    chunks: number
    indexed_product_skus: number
    embedded_product_skus: number
    pending_products: number
  }
  coverage: {
    product_index_coverage: number
    embedding_coverage: number
  }
  embedding_status_counts: Record<string, number>
  source_type_counts: Record<string, number>
  samples: {
    failed_chunks: Array<Record<string, unknown>>
    pending_chunks: Array<Record<string, unknown>>
  }
  recommendations: string[]
}

export interface KnowledgeSearchPreview {
  query: string
  sku?: string | null
  mode: string
  count: number
  vector: KnowledgeBaseHealth['vector']
  results: Array<{
    source_type?: string | null
    sku?: string | null
    content: string
    metadata?: Record<string, unknown>
    score?: number
  }>
}

export interface KnowledgeJob {
  id: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string
  stage: string
  payload: Record<string, unknown>
  result?: Record<string, unknown> | null
  error?: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface KnowledgeFileUploadResult {
  document_id: string
  task_id?: string | null
  task_status?: string | null
  file_name: string
  file_type: string
  parse_status: string
  parse_error?: string | null
  chunk_count: number
  related_skus: string[]
  duplicate: boolean
  reused_document_id?: string | null
  message?: string | null
}

export interface KnowledgeFileUploadResponse {
  items: KnowledgeFileUploadResult[]
}

export interface KnowledgeFileRecord {
  document_id: string
  file_name: string
  file_type?: string | null
  parse_status: string
  parse_error?: string | null
  chunk_count: number
  embedding_synced_count: number
  embedding_pending_count: number
  embedding_failed_count: number
  related_skus: string[]
  related_products: Array<{
    sku: string
    product_name_cn?: string | null
    product_name_en?: string | null
    exists: boolean
  }>
  task_id?: string | null
  task_status?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface KnowledgeFileListResponse {
  items: KnowledgeFileRecord[]
  total: number
}

export interface KnowledgeRecoverStuckResponse {
  recovered_count: number
  candidates_count: number
  documents: Array<{
    id: string
    file_name?: string | null
    parse_status: string
    updated_at?: string | null
    parse_error?: string | null
  }>
}

export interface KnowledgeParseTask {
  task_id: string
  document_id: string
  status: string
  error_message?: string | null
  created_at?: string | null
  finished_at?: string | null
}

export type CustomerServiceStreamEvent =
  | { type: 'status'; message?: string; label?: string }
  | ({ type: 'meta' } & Omit<CustomerServiceAskResult, 'answer'>)
  | { type: 'clarification'; message?: string; suggested_followups?: string[] }
  | { type: 'warning'; message?: string }
  | { type: 'recommendation'; message?: string }
  | { type: 'content'; content: string }
  | { type: 'answer_delta'; text: string }
  | { type: 'done'; ok: boolean }
  | { type: 'error'; message: string }

function fileToBase64(file: File): Promise<{ data: string; mimeType: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      const base64 = result.split(',')[1]
      resolve({ data: base64, mimeType: file.type || 'image/png' })
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function request<T>(url: string, options: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {}

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  if (!(options.body instanceof FormData) && options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    if (options.body && typeof options.body !== 'string') {
      options.body = JSON.stringify(options.body)
    }
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const traceAgent = shouldTraceCustomerAgent(url)

  if (traceAgent) {
    traceCustomerAgent('REQUEST', {
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      body: parseTraceBody(options.body),
      timeoutMs,
    })
  }

  try {
    const response = await fetch(`${BASE_URL}${url}`, {
      ...options,
      headers: { ...headers, ...(options.headers as Record<string, string>) },
      signal: controller.signal,
    })

    if (response.status === 401 && url !== '/auth/login') {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
      throw new Error('Unauthorized')
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }))
      if (traceAgent) {
        traceCustomerAgent('ERROR_RESPONSE', {
          url,
          status: response.status,
          error,
        })
      }
      if (response.status === 403) showNoPermissionToast()
      throw new Error(normalizeErrorMessage(error.detail || error, response.status))
    }

    const data = await response.json()
    if (traceAgent) {
      traceCustomerAgent('RESPONSE', {
        url,
        status: response.status,
        data,
      })
      if (url.startsWith('/customer-service/ask')) {
        traceCustomerAgent('ANSWER', {
          answer: (data as Record<string, unknown>).answer,
          actions: (data as Record<string, unknown>).actions,
          results: (data as Record<string, unknown>).results,
          sources: (data as Record<string, unknown>).sources,
          steps: (data as Record<string, unknown>).steps,
        })
      }
      if (url.includes('/customer-service/actions/')) {
        traceCustomerAgent('ACTION_RESULT', data)
      }
    }
    return data
  } finally {
    clearTimeout(timer)
  }
}

async function streamRequest(
  url: string,
  options: RequestInit,
  onEvent: (event: CustomerServiceStreamEvent) => void,
  timeoutMs = 150000,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {}

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  if (!(options.body instanceof FormData) && options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    if (options.body && typeof options.body !== 'string') {
      options.body = JSON.stringify(options.body)
    }
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const abortFromExternalSignal = () => controller.abort()

  if (signal?.aborted) {
    controller.abort()
  } else {
    signal?.addEventListener('abort', abortFromExternalSignal, { once: true })
  }

  try {
    const response = await fetch(`${BASE_URL}${url}`, {
      ...options,
      headers: { ...headers, ...(options.headers as Record<string, string>) },
      signal: controller.signal,
    })

    if (response.status === 401 && url !== '/auth/login') {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
      throw new Error('Unauthorized')
    }

    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }))
      if (response.status === 403) showNoPermissionToast()
      throw new Error(normalizeErrorMessage(error.detail || error, response.status))
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const rawEvent of events) {
        const parsed = parseStreamEvent(rawEvent)
        if (parsed) onEvent(parsed)
      }
    }

    buffer += decoder.decode()
    const parsed = parseStreamEvent(buffer)
    if (parsed) onEvent(parsed)
  } finally {
    signal?.removeEventListener('abort', abortFromExternalSignal)
    clearTimeout(timer)
  }
}

function uploadKnowledgeFilesRequest(files: File[], relatedSkus: string[] | string = []) {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  formData.append(
    'related_skus',
    Array.isArray(relatedSkus)
      ? relatedSkus.map((item) => String(item).trim()).filter(Boolean).join(',')
      : String(relatedSkus || '').trim(),
  )
  return request<KnowledgeFileUploadResponse>('/knowledge-base/files/upload', {
    method: 'POST',
    body: formData,
  })
}

function parseStreamEvent(rawEvent: string): CustomerServiceStreamEvent | null {
  const lines = rawEvent.split('\n')
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const dataLines = lines.filter((line) => line.startsWith('data:'))
  if (!eventLine || dataLines.length === 0) return null
  const eventType = eventLine.replace(/^event:\s*/, '').trim()
  const dataText = dataLines.map((line) => line.replace(/^data:\s*/, '')).join('\n')
  try {
    return { type: eventType, ...JSON.parse(dataText) } as CustomerServiceStreamEvent
  } catch {
    return null
  }
}

export const api = {
  auth: {
    register: (data: { username: string; email: string; password: string }) =>
      request('/auth/register', { method: 'POST', body: JSON.stringify(data) }),

    login: (username: string, password: string) =>
      request<{ access_token: string; token_type: string; user: any }>(
        '/auth/login',
        { method: 'POST', body: JSON.stringify({ username, password }) }
      ),

    me: () => request('/auth/me'),
    updateMe: (data: { username?: string; email?: string; display_name?: string }) =>
      request('/auth/me', { method: 'PUT', body: JSON.stringify(data) }),
    changePassword: (data: { current_password: string; new_password: string }) =>
      request('/auth/me/password', { method: 'PUT', body: JSON.stringify(data) }),
  },

  generation: {
    models: () => request<any[]>('/generation/models'),

    txt2img: (data: {
      prompt: string
      model_name?: string
      negative_prompt?: string
      params?: Record<string, unknown>
    }) =>
      request('/generation/txt2img', { method: 'POST', body: JSON.stringify(data) }, 330000),

    img2img: (data: {
      prompt: string
      model_name?: string
      negative_prompt?: string
      size?: string
      images: File[]
      n?: number
      quality?: string
      output_format?: string
      output_compression?: number
      moderation?: string
      background?: string
    }) => {
      const formData = new FormData()
      formData.append('prompt', data.prompt)
      formData.append('model_name', data.model_name || 'gpt-image-2-ssvip')
      formData.append('negative_prompt', data.negative_prompt || '')
      formData.append('size', data.size || '1024x1024')
      if (data.n !== undefined) formData.append('n', String(data.n))
      if (data.quality) formData.append('quality', data.quality)
      if (data.output_format) formData.append('output_format', data.output_format)
      if (data.output_compression !== undefined) formData.append('output_compression', String(data.output_compression))
      if (data.moderation) formData.append('moderation', data.moderation)
      if (data.background) formData.append('background', data.background)
      for (const img of data.images) {
        formData.append('images', img)
      }
      return request('/generation/img2img', { method: 'POST', body: formData }, 1200000)
    },

    img2imgGemini: async (data: {
      prompt: string
      model_name?: string
      negative_prompt?: string
      params?: Record<string, unknown>
      images: File[]
    }) => {
      const imagePayloads = await Promise.all(
        data.images.map(f => fileToBase64(f))
      )
      const payload = {
        prompt: data.prompt,
        model_name: data.model_name || 'gemini-3.1-flash-image-preview',
        negative_prompt: data.negative_prompt || undefined,
        params: data.params,
        images: imagePayloads,
      }
      return request('/generation/img2img-gemini', { method: 'POST', body: JSON.stringify(payload) }, 1200000)
    },

    txt2vid: (data: {
      prompt: string
      model_name?: string
      negative_prompt?: string
      params?: Record<string, unknown>
    }) =>
      request('/generation/txt2vid', { method: 'POST', body: JSON.stringify(data) }, 330000),
  },

  history: {
    list: (skip = 0, limit = 20, search?: string, dateFrom?: string, dateTo?: string) => {
      let url = `/history?skip=${skip}&limit=${limit}`
      if (search) url += `&search=${encodeURIComponent(search)}`
      if (dateFrom) url += `&date_from=${dateFrom}`
      if (dateTo) url += `&date_to=${dateTo}`
      return request(url)
    },

    adminList: (skip = 0, limit = 20, search?: string, dateFrom?: string, dateTo?: string) => {
      let url = `/history/admin?skip=${skip}&limit=${limit}`
      if (search) url += `&search=${encodeURIComponent(search)}`
      if (dateFrom) url += `&date_from=${dateFrom}`
      if (dateTo) url += `&date_to=${dateTo}`
      return request(url)
    },

    stats: () => request('/history/stats'),

    get: (id: string) => request(`/history/${id}`),
    delete: (id: string) => request(`/history/${id}`, { method: 'DELETE' }),
  },

  users: {
    list: (skip = 0, limit = 100) => request(`/users?skip=${skip}&limit=${limit}`),
    get: (id: string) => request(`/users/${id}`),
    create: (data: {
      username: string
      email?: string
      password: string
      display_name?: string
      group_id?: string
      group_role?: string
    }) =>
      request('/users', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: string, data: Record<string, unknown>) =>
      request(`/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    resetPassword: (id: string, newPassword: string) =>
      request(`/users/${id}/password/reset`, {
        method: 'PUT',
        body: JSON.stringify({ new_password: newPassword }),
      }),
    delete: (id: string) => request(`/users/${id}`, { method: 'DELETE' }),
  },

  admin: {
    getModels: () => request<any[]>('/admin/models-config'),
    updateModels: (models: any[]) =>
      request('/admin/models-config', { method: 'PUT', body: JSON.stringify({ models }) }),
    operationLogs: (params: {
      skip?: number
      limit?: number
      search?: string
      action_type?: string
      target_type?: string
      status?: string
      operator_id?: string
      date_from?: string
      date_to?: string
    } = {}) => {
      const query = new URLSearchParams()
      query.set('skip', String(params.skip ?? 0))
      query.set('limit', String(params.limit ?? 50))
      if (params.search) query.set('search', params.search)
      if (params.action_type) query.set('action_type', params.action_type)
      if (params.target_type) query.set('target_type', params.target_type)
      if (params.status) query.set('status', params.status)
      if (params.operator_id) query.set('operator_id', params.operator_id)
      if (params.date_from) query.set('date_from', params.date_from)
      if (params.date_to) query.set('date_to', params.date_to)
      return request<{ items: any[]; total: number }>(`/admin/operation-logs?${query.toString()}`)
    },
    restoreProductSnapshot: (snapshotId: string) =>
      request<{ snapshot_id: string; sku: string; restored_to: string }>(
        `/products/operation-snapshots/${snapshotId}/restore`,
        { method: 'POST' },
      ),
  },

  groups: {
    list: () => request<any[]>('/admin/groups'),
    create: (data: { group_name: string; description?: string }) =>
      request('/admin/groups', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: string, data: { group_name?: string; description?: string }) =>
      request(`/admin/groups/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: string) => request(`/admin/groups/${id}`, { method: 'DELETE' }),
    members: (groupId: string) => request<any[]>(`/admin/groups/${groupId}/users`),
    permissions: () => request<any[]>('/admin/groups/permissions'),
    groupPermissions: (groupId: string) => request<any[]>(`/admin/groups/${groupId}/permissions`),
    updatePermissions: (groupId: string, permissionKeys: string[]) =>
      request(`/admin/groups/${groupId}/permissions`, {
        method: 'PUT',
        body: JSON.stringify({ permission_keys: permissionKeys }),
      }),
    addUser: (groupId: string, data: { user_id: string; group_role: string }) =>
      request(`/admin/groups/${groupId}/users`, { method: 'POST', body: JSON.stringify(data) }),
    removeUser: (groupId: string, userId: string) =>
      request(`/admin/groups/${groupId}/users/${userId}`, { method: 'DELETE' }),
    updateRole: (groupId: string, userId: string, data: { group_role: string }) =>
      request(`/admin/groups/${groupId}/users/${userId}`, { method: 'PUT', body: JSON.stringify(data) }),
  },

  products: {
    list: (skip = 0, limit = 20, search?: string) => {
      let url = `/products?skip=${skip}&limit=${limit}`
      if (search) url += `&q=${encodeURIComponent(search)}`
      return request<ProductListResponse>(url)
    },

    search: (query: string) => request<ProductListResponse>(`/products/search?q=${encodeURIComponent(query)}`),

    advancedSearch: (data: Record<string, unknown>) =>
      request<ProductListResponse & { items: Array<Record<string, unknown>> }>(
        '/products/advanced-search',
        { method: 'POST', body: JSON.stringify(data) }
      ),

    filterOptions: () => request<Record<string, string[]>>('/products/filter-options'),

    get: (sku: string) => request<Product>(`/products/${sku}`),

    getBySku: (sku: string) => request<Product>(`/products/by-sku/${sku}`),

    create: (data: Record<string, unknown>) =>
      request('/products', { method: 'POST', body: JSON.stringify(data) }),

    update: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}`, { method: 'PUT', body: JSON.stringify(data) }),

    updateFull: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/full`, { method: 'PUT', body: JSON.stringify(data) }),

    delete: (sku: string) => request(`/products/${sku}`, { method: 'DELETE' }),

    updateSpecs: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/specs`, { method: 'PUT', body: JSON.stringify(data) }),

    updateBusiness: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/business`, { method: 'PUT', body: JSON.stringify(data) }),

    updateContent: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/content`, { method: 'PUT', body: JSON.stringify(data) }),

    // QA
    listQa: (sku: string) => request(`/products/${sku}/qa`),
    addQa: (sku: string, data: { question: string; answer: string; tags?: unknown; priority?: number }) =>
      request(`/products/${sku}/qa`, { method: 'POST', body: JSON.stringify(data) }),
    updateQa: (sku: string, qaId: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/qa/${qaId}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteQa: (sku: string, qaId: string) =>
      request(`/products/${sku}/qa/${qaId}`, { method: 'DELETE' }),
    importQaBatch: (data: {
      mode?: 'replace' | 'append'
      items: Array<{
        sku: string
        file_name?: string
        mode?: 'replace' | 'append'
        qa_items: Array<{ no?: number; question: string; answer: string; tags?: unknown; priority?: number }>
        review_items?: Array<{ no?: number; keyword: string; response: string }>
      }>
    }) => request<{
      total_files: number
      total_qa_created: number
      total_negative_updated: number
      results: Array<{ sku: string; status: string; qa_created: number; qa_skipped_duplicate?: number; negative_updated: boolean; message?: string }>
    }>('/products/qa/batch-import', { method: 'POST', body: JSON.stringify(data) }),

    // QA Negative
    getQaNegative: (sku: string) => request(`/products/${sku}/qa-negative`),
    upsertQaNegative: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/qa-negative`, { method: 'PUT', body: JSON.stringify(data) }),

    // Media (new one-row-per-image model)
    addMedia: (sku: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/media`, { method: 'POST', body: JSON.stringify(data) }),
    updateMedia: (sku: string, mediaId: string, data: Record<string, unknown>) =>
      request(`/products/${sku}/media/${mediaId}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteMedia: (sku: string, mediaId: string) =>
      request(`/products/${sku}/media/${mediaId}`, { method: 'DELETE' }),

    // Prompts
    addPrompt: (sku: string, data: {
      prompt_name?: string
      prompt_type?: string
      prompt_text: string
      version?: string
    }) => request(`/products/${sku}/prompts`, { method: 'POST', body: JSON.stringify(data) }),
    deletePrompt: (sku: string, promptId: string) =>
      request(`/products/${sku}/prompts/${promptId}`, { method: 'DELETE' }),

    // M2M associations
    getChannels: (sku: string) => request(`/products/${sku}/channels`),
    addChannel: (sku: string, channelId: string) =>
      request(`/products/${sku}/channels/${channelId}`, { method: 'POST' }),
    removeChannel: (sku: string, channelId: string) =>
      request(`/products/${sku}/channels/${channelId}`, { method: 'DELETE' }),

    // Drafts
    checkSkus: (skus: string[]) =>
      request<{ existing: Record<string, Record<string, unknown>>; missing: string[] }>(
        '/products/drafts/check-skus',
        { method: 'POST', body: JSON.stringify({ skus }) }
      ),
  },

  assets: {
    list: (sku: string, params: {
      category?: string
      sub_category?: string
      asset_type?: 'image' | 'video'
      grouped?: false
    } = {}) => {
      const query = new URLSearchParams()
      if (params.category) query.set('category', params.category)
      if (params.sub_category) query.set('sub_category', params.sub_category)
      if (params.asset_type) query.set('asset_type', params.asset_type)
      const suffix = query.toString() ? `?${query.toString()}` : ''
      return request<ProductAsset[]>(`/products/${encodeURIComponent(sku)}/assets${suffix}`)
    },
    grouped: (sku: string, params: {
      category?: string
      sub_category?: string
      asset_type?: 'image' | 'video'
    } = {}) => {
      const query = new URLSearchParams()
      query.set('grouped', 'true')
      if (params.category) query.set('category', params.category)
      if (params.sub_category) query.set('sub_category', params.sub_category)
      if (params.asset_type) query.set('asset_type', params.asset_type)
      return request<AssetGrouped[]>(`/products/${encodeURIComponent(sku)}/assets?${query.toString()}`)
    },
    get: (sku: string, assetId: string) =>
      request<ProductAsset>(`/products/${encodeURIComponent(sku)}/assets/${assetId}`),
    create: (sku: string, data: Partial<ProductAsset>) =>
      request<ProductAsset>(`/products/${encodeURIComponent(sku)}/assets`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (sku: string, assetId: string, data: Partial<ProductAsset>) =>
      request<ProductAsset>(`/products/${encodeURIComponent(sku)}/assets/${assetId}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    updateTags: (sku: string, assetId: string, tags: AssetTags) =>
      request<ProductAsset>(`/products/${encodeURIComponent(sku)}/assets/${assetId}/tags`, {
        method: 'PATCH',
        body: JSON.stringify(tags),
      }),
    delete: (sku: string, assetId: string) =>
      request<{ ok: boolean }>(`/products/${encodeURIComponent(sku)}/assets/${assetId}`, {
        method: 'DELETE',
      }),
    upload: (sku: string, data: {
      files: File[]
      category_code: string
      category_name: string
      sub_category?: string | null
      material_type?: string | null
      angle_scene?: string | null
      channel?: string | null
      language_tag?: string | null
      version_tag?: string | null
      status_tag?: string | null
      notes?: string | null
    }) => {
      const formData = new FormData()
      for (const file of data.files) formData.append('files', file)
      formData.append('category_code', data.category_code)
      formData.append('category_name', data.category_name)
      if (data.sub_category) formData.append('sub_category', data.sub_category)
      if (data.material_type) formData.append('material_type', data.material_type)
      if (data.angle_scene) formData.append('angle_scene', data.angle_scene)
      if (data.channel) formData.append('channel', data.channel)
      if (data.language_tag) formData.append('language_tag', data.language_tag)
      if (data.version_tag) formData.append('version_tag', data.version_tag)
      if (data.status_tag) formData.append('status_tag', data.status_tag)
      if (data.notes) formData.append('notes', data.notes)
      return request<AssetUploadResponse>(`/products/${encodeURIComponent(sku)}/assets/upload`, {
        method: 'POST',
        body: formData,
      }, 300000)
    },
  },

  customerService: {
    ask: (data: { question: string; conversation_id?: string | null }) =>
      request<CustomerServiceAskResult>('/customer-service/ask', { method: 'POST', body: JSON.stringify(data) }, 150000),
    askStream: (
      data: { question: string; conversation_id?: string | null },
      onEvent: (event: CustomerServiceStreamEvent) => void,
      signal?: AbortSignal,
    ) => streamRequest('/customer-service/ask-stream', { method: 'POST', body: JSON.stringify(data) }, onEvent, 150000, signal),
    feedback: (messageId: string, data: { rating: 'helpful' | 'incorrect' | 'missing_data'; reason?: string; comment?: string }) =>
      request<{ message_id: string; feedback: Record<string, unknown> }>(
        `/customer-service/messages/${messageId}/feedback`,
        { method: 'POST', body: JSON.stringify(data) }
      ),
    confirmAction: (id: string) =>
      request<AgentAction>(`/customer-service/actions/${id}/confirm`, { method: 'POST' }, 150000),
    cancelAction: (id: string) =>
      request<AgentAction>(`/customer-service/actions/${id}/cancel`, { method: 'POST' }),
    conversations: (skip = 0, limit = 30) =>
      request<{ items: Array<Record<string, unknown>>; total: number }>(
        `/customer-service/conversations?skip=${skip}&limit=${limit}`
      ),
    conversation: (id: string) => request<Record<string, unknown>>(`/customer-service/conversations/${id}`),
    reviewSamples: (limit = 100) =>
      request<{ items: Array<Record<string, unknown>>; summary: Record<string, unknown> }>(
        `/customer-service/review-samples?limit=${limit}`
      ),
    deleteConversation: (id: string) =>
      request<{ deleted: boolean; id: string }>(`/customer-service/conversations/${id}`, { method: 'DELETE' }),
  },

  knowledgeBase: {
    files: (limit = 50) =>
      request<KnowledgeFileListResponse>(`/knowledge-base/files?limit=${limit}`),
    deleteFile: (documentId: string) =>
      request<{ ok: boolean; document_id: string }>(`/knowledge-base/files/${documentId}`, { method: 'DELETE' }),
    uploadFiles: (files: File[], relatedSkus: string[] | string = []) =>
      uploadKnowledgeFilesRequest(files, relatedSkus),
    uploadFile: (file: File, relatedSkus: string[] | string = []) =>
      uploadKnowledgeFilesRequest([file], relatedSkus),
    recoverStuckFiles: (data: { timeout_minutes?: number; dry_run?: boolean } = {}) =>
      request<KnowledgeRecoverStuckResponse>(
        '/knowledge-base/files/recover-stuck',
        { method: 'POST', body: JSON.stringify(data) },
      ),
    task: (id: string) => request<KnowledgeParseTask>(`/knowledge-base/tasks/${id}`),
    status: () => request<{
      available: boolean
      extension: boolean
      embedding_column: boolean
      chunks: number
      embedded_chunks: number
      error?: string
    }>('/knowledge-base/status'),
    health: () => request<KnowledgeBaseHealth>('/knowledge-base/health'),
    searchPreview: (data: { query: string; sku?: string; limit?: number }) =>
      request<KnowledgeSearchPreview>(
        '/knowledge-base/search-preview',
        { method: 'POST', body: JSON.stringify(data) },
        60000,
      ),
    reindexProducts: (data: { mode?: 'pending' | 'full'; limit?: number; embed?: boolean }) =>
      request<{ mode: string; indexed: Record<string, unknown>; embedding?: Record<string, unknown> | null; health: KnowledgeBaseHealth }>(
        '/knowledge-base/reindex-products',
        { method: 'POST', body: JSON.stringify(data) },
        300000,
      ),
    createReindexJob: (data: { mode?: 'pending' | 'full'; limit?: number; embed?: boolean }) =>
      request<KnowledgeJob>(
        '/knowledge-base/jobs/reindex-products',
        { method: 'POST', body: JSON.stringify(data) },
      ),
    retryEmbeddings: (data: { limit?: number }) =>
      request<KnowledgeJob>(
        '/knowledge-base/jobs/retry-embeddings',
        { method: 'POST', body: JSON.stringify(data) },
      ),
    jobs: (limit = 20) =>
      request<{ items: KnowledgeJob[]; total: number }>(`/knowledge-base/jobs?limit=${limit}`),
    job: (id: string) => request<KnowledgeJob>(`/knowledge-base/jobs/${id}`),
  },

  files: {
    sign: async (path: string) => {
      const response = await request<{ url: string; expires_in: number }>(
        '/files/sign',
        { method: 'POST', body: JSON.stringify({ path }) },
      )
      return { ...response, url: toBackendUrl(response.url) }
    },
    knowledgeDownloadUrl: (documentId: string) => toBackendUrl(`/api/knowledge-base/files/${documentId}/download`),
  },

  categories: {
    list: () => request<CategoryItem[]>('/categories', { method: 'GET' }),
    create: (category_name: string) =>
      request('/categories', { method: 'POST', body: JSON.stringify({ category_name }) }),
    delete: (id: string) => request(`/categories/${id}`, { method: 'DELETE' }),
  },

  drafts: {
    list: (skip?: number, limit?: number) =>
      request<{ items: ProductDraft[]; total: number }>(
        `/products/drafts?skip=${skip || 0}&limit=${limit || 20}`
      ),
    get: (id: string) => request<ProductDraft>(`/products/drafts/${id}`),
    create: (data: Record<string, unknown>) =>
      request<ProductDraft>('/products/drafts', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: string, data: Record<string, unknown>) =>
      request<ProductDraft>(`/products/drafts/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: string) => request(`/products/drafts/${id}`, { method: 'DELETE' }),
    publish: (id: string) => request(`/products/drafts/${id}/publish`, { method: 'POST' }),

    createBatch: (items: Record<string, unknown>[]) =>
      request<{ created: number; updated: number; skipped: number }>(
        '/products/drafts/batch',
        { method: 'POST', body: JSON.stringify({ items }) }
      ),
  },

  uploadImage: (files: File[]): Promise<{ urls: string[] }> => {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    return fetch(`${BASE_URL}/products/images/upload`, {
      method: 'POST',
      body: formData,
      headers,
    }).then((r) => {
      if (!r.ok) throw new Error('Upload failed')
      return r.json()
    })
  },

  uploadVideo: (files: File[]): Promise<{ urls: string[] }> => {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    return fetch(`${BASE_URL}/products/videos/upload`, {
      method: 'POST',
      body: formData,
      headers,
    }).then((r) => {
      if (!r.ok) throw new Error('Upload failed')
      return r.json()
    })
  },
}
