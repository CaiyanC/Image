import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  api,
  type AuthorizationOverview,
  type CredentialSummary,
  type FeatureModel,
  type ManagedModel,
  type ModelUsageLog,
} from '../services/api'
import type { User } from '../types'

const FEATURE_OPTIONS = [
  ['generation.image', 'AI 生图'],
  ['customer_service.chat', '智能客服'],
] as const

const emptyModel: ManagedModel = {
  id: '', display_name: '', provider_name: '', capability: 'image', request_model_name: '', api_format: 'openai', api_endpoint: null, is_enabled: true,
}

type EditingCell = {
  subjectType: 'group' | 'user'
  subjectId: string
  subjectName: string
  featureKey: string
  selectedModelIds: string[]
} | null

type GovernancePanel = 'credential' | 'feature-model' | 'usage-log' | null

export default function AdminModelGovernance() {
  const [credentials, setCredentials] = useState<CredentialSummary[]>([])
  const [models, setModels] = useState<ManagedModel[]>([])
  const [featureModels, setFeatureModels] = useState<FeatureModel[]>([])
  const [groups, setGroups] = useState<Array<{ id: string; group_name: string }>>([])
  const [users, setUsers] = useState<User[]>([])
  const [logs, setLogs] = useState<ModelUsageLog[]>([])
  const [authorizationOverview, setAuthorizationOverview] = useState<AuthorizationOverview | null>(null)
  const [panel, setPanel] = useState<GovernancePanel>(null)
  const [editingCell, setEditingCell] = useState<EditingCell>(null)
  const [savingSelection, setSavingSelection] = useState(false)
  const [logTotal, setLogTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [credentialForm, setCredentialForm] = useState({ provider_name: '', api_base_url: '', api_key: '', scope_type: 'company' as 'company' | 'group' | 'user', scope_id: '', is_enabled: true })
  const [replacementKeys, setReplacementKeys] = useState<Record<string, string>>({})
  const [modelForm, setModelForm] = useState<ManagedModel>(emptyModel)
  const [featureKey, setFeatureKey] = useState('generation.image')
  const [logFilters, setLogFilters] = useState({ user_id: '', feature_key: '', model_id: '', result: '', date_from: '', date_to: '' })

  const modelById = useMemo(() => new Map(models.map((model) => [model.id, model])), [models])

  async function loadAll() {
    setLoading(true)
    setError('')
    try {
      const [nextCredentials, nextModels, nextFeatureModels, nextGroups, nextUsers, nextAuthorizationOverview] = await Promise.all([
        api.modelGovernance.credentials(), api.modelGovernance.models(), api.modelGovernance.featureModels(), api.groups.list(), api.users.list(), api.modelGovernance.authorizationOverview(),
      ])
      setCredentials(nextCredentials)
      setModels(nextModels)
      setFeatureModels(nextFeatureModels)
      setGroups(nextGroups as Array<{ id: string; group_name: string }>)
      setUsers(nextUsers as User[])
      setAuthorizationOverview(nextAuthorizationOverview)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载模型治理配置失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadLogs() {
    try {
      const data = await api.modelGovernance.usageLogs(logFilters)
      setLogs(data.items)
      setLogTotal(data.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载调用日志失败')
    }
  }

  // Initial loading intentionally runs once; subsequent refreshes are explicit to avoid replacing in-progress edits.
  useEffect(() => { void loadAll() }, [])

  async function perform(action: () => Promise<void>, success: string) {
    setSaving(true); setError(''); setMessage('')
    try { await action(); setMessage(success) } catch (err) { setError(err instanceof Error ? err.message : '保存失败') } finally { setSaving(false) }
  }

  async function createCredential() {
    if (!credentialForm.provider_name || !credentialForm.api_base_url || !credentialForm.api_key || (credentialForm.scope_type !== 'company' && !credentialForm.scope_id)) {
      setError('请填写供应商、接口地址、Key，以及部门或用户范围。')
      return
    }
    await perform(async () => {
      await api.modelGovernance.createCredential({ ...credentialForm, scope_id: credentialForm.scope_type === 'company' ? null : credentialForm.scope_id })
      setCredentialForm({ provider_name: '', api_base_url: '', api_key: '', scope_type: 'company', scope_id: '', is_enabled: true })
      setCredentials(await api.modelGovernance.credentials())
    }, '凭据已加密保存；页面只会显示脱敏值。')
  }

  async function replaceCredential(credential: CredentialSummary) {
    const apiKey = replacementKeys[credential.id]?.trim()
    if (!apiKey) { setError('请输入新的 API Key 后再替换。'); return }
    await perform(async () => {
      const updated = await api.modelGovernance.updateCredential(credential.id, { api_key: apiKey })
      setCredentials((items) => items.map((item) => item.id === updated.id ? updated : item))
      setReplacementKeys((items) => ({ ...items, [credential.id]: '' }))
    }, 'API Key 已替换并加密保存。')
  }

  async function saveModel() {
    if (!modelForm.id || !modelForm.display_name || !modelForm.provider_name || !modelForm.request_model_name) { setError('请填写模型 ID、名称、供应商和请求模型名。'); return }
    await perform(async () => {
      const existing = models.some((model) => model.id === modelForm.id)
      const saved = existing ? await api.modelGovernance.updateModel(modelForm.id, omitId(modelForm)) : await api.modelGovernance.createModel(modelForm)
      setModels((items) => existing ? items.map((item) => item.id === saved.id ? saved : item) : [...items, saved])
      setModelForm(emptyModel)
    }, '模型配置已保存。')
  }

  async function setFeatureModel(modelId: string, patch: Partial<Pick<FeatureModel, 'is_default' | 'is_enabled' | 'sort_order'>>) {
    const current = featureModels.find((item) => item.feature_key === featureKey && item.model_id === modelId)
    await perform(async () => {
      const saved = await api.modelGovernance.setFeatureModel(featureKey, modelId, {
        is_default: patch.is_default ?? current?.is_default ?? false,
        is_enabled: patch.is_enabled ?? current?.is_enabled ?? true,
        sort_order: patch.sort_order ?? current?.sort_order ?? 0,
      })
      setFeatureModels((items) => [...items.filter((item) => item.id !== saved.id), saved])
    }, '功能模型关联已保存。')
  }

  async function saveSelection() {
    if (!editingCell) return
    setSavingSelection(true)
    setError('')
    try {
      await api.modelGovernance.authorizationOverviewSelection(editingCell.subjectType, editingCell.subjectId, editingCell.featureKey, editingCell.selectedModelIds)
      setEditingCell(null)
      await loadAll()
      setMessage('授权模型已保存，并已按服务端规则重新计算。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存授权模型失败')
    } finally {
      setSavingSelection(false)
    }
  }

  function openPanel(nextPanel: Exclude<GovernancePanel, null>) {
    setPanel(nextPanel)
    if (nextPanel === 'usage-log') void loadLogs()
  }

  if (loading) return <div className="p-6 text-apple-gray-medium">加载模型治理配置中…</div>

  const featureLinks = featureModels.filter((item) => item.feature_key === featureKey)

  return <div className="mx-auto max-w-7xl space-y-6 p-4">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-2xl font-bold text-apple-text">模型治理</h1><p className="mt-1 text-sm text-apple-gray-medium">管理加密凭据、模型、功能授权和安全调用日志。实际调用仍由后端校验。</p></div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button onClick={() => openPanel('feature-model')} className="btn-primary px-3 py-2">添加功能模型</button>
        <button onClick={() => openPanel('credential')} className="px-3 py-2 text-apple-blue hover:underline">管理 API 凭据</button>
        <button onClick={() => openPanel('usage-log')} className="px-3 py-2 text-apple-blue hover:underline">查看调用日志</button>
        <button onClick={() => void loadAll()} className="px-3 py-2 text-apple-blue hover:underline">重新加载</button>
      </div>
    </header>
    {error && <Notice kind="error" text={error} onClose={() => setError('')} />}
    {message && <Notice kind="success" text={message} onClose={() => setMessage('')} />}

    {authorizationOverview && <AuthorizationOverviewMatrix overview={authorizationOverview} onEdit={setEditingCell} />}
    {authorizationOverview && editingCell && <AuthorizationOverviewDrawer overview={authorizationOverview} editingCell={editingCell} saving={savingSelection} onChange={setEditingCell} onClose={() => setEditingCell(null)} onSave={() => void saveSelection()} />}

    {panel === 'credential' && <GovernanceDialog title="管理 API 凭据" onClose={() => setPanel(null)}>
      <p className="text-sm text-apple-gray-medium">新建或替换 Key；已保存的 Key 永不回显。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3"><TextInput label="供应商" value={credentialForm.provider_name} onChange={(value) => setCredentialForm({ ...credentialForm, provider_name: value })} placeholder="例如 dmXAPI" /><TextInput label="API Base URL" value={credentialForm.api_base_url} onChange={(value) => setCredentialForm({ ...credentialForm, api_base_url: value })} placeholder="https://api.example.com" /><TextInput label="API Key（仅本次输入）" type="password" value={credentialForm.api_key} onChange={(value) => setCredentialForm({ ...credentialForm, api_key: value })} /></div>
      <div className="mt-3 grid gap-3 md:grid-cols-3"><SelectInput label="范围" value={credentialForm.scope_type} onChange={(value) => setCredentialForm({ ...credentialForm, scope_type: value as typeof credentialForm.scope_type, scope_id: value === 'company' ? '' : credentialForm.scope_id })} options={[["company", "公司"], ["group", "部门"], ["user", "个人"]]} />{credentialForm.scope_type !== 'company' && <SelectInput label={credentialForm.scope_type === 'group' ? '部门' : '用户'} value={credentialForm.scope_id} onChange={(value) => setCredentialForm({ ...credentialForm, scope_id: value })} options={subjectsFor(credentialForm.scope_type, groups, users)} />}</div>
      <button disabled={saving} onClick={() => void createCredential()} className="btn-primary mt-4 text-sm disabled:opacity-50">新建加密凭据</button>
      <div className="mt-4 space-y-2">{credentials.map((credential) => <div key={credential.id} className="rounded-xl border border-black/5 bg-white/50 p-3"><div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span className="font-medium">{credential.provider_name}</span><span>{credential.scope_type}{credential.scope_id ? ` · ${credential.scope_id}` : ''}</span><code>{credential.api_key_masked}</code><span className={credential.is_enabled ? 'text-emerald-600' : 'text-gray-500'}>{credential.is_enabled ? '启用' : '停用'}</span></div><div className="mt-2 flex gap-2"><input type="password" value={replacementKeys[credential.id] || ''} onChange={(event) => setReplacementKeys({ ...replacementKeys, [credential.id]: event.target.value })} placeholder="输入新 Key 以替换" className="glass-input px-3 py-1.5 text-sm" /><button disabled={saving} onClick={() => void replaceCredential(credential)} className="text-sm text-apple-blue hover:underline">替换 Key</button></div></div>)}</div>
    </GovernanceDialog>}

    {panel === 'feature-model' && <GovernanceDialog title="添加功能模型" onClose={() => setPanel(null)}>
      <p className="text-sm text-apple-gray-medium">创建或更新模型目录项，再将模型加入指定功能并设置默认值。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3"><TextInput label="模型 ID" value={modelForm.id} onChange={(value) => setModelForm({ ...modelForm, id: value })} /><TextInput label="显示名称" value={modelForm.display_name} onChange={(value) => setModelForm({ ...modelForm, display_name: value })} /><TextInput label="供应商" value={modelForm.provider_name} onChange={(value) => setModelForm({ ...modelForm, provider_name: value })} /><SelectInput label="能力" value={modelForm.capability} onChange={(value) => setModelForm({ ...modelForm, capability: value })} options={[["image", "图片"], ["video", "视频"], ["chat", "聊天"], ["embedding", "向量"]]} /><SelectInput label="请求格式" value={modelForm.api_format} onChange={(value) => setModelForm({ ...modelForm, api_format: value as 'openai' | 'gemini' })} options={[["openai", "OpenAI 兼容"], ["gemini", "Gemini"]]} /><TextInput label="请求模型名" value={modelForm.request_model_name} onChange={(value) => setModelForm({ ...modelForm, request_model_name: value })} /><TextInput label="模型端点（可选）" value={modelForm.api_endpoint || ''} onChange={(value) => setModelForm({ ...modelForm, api_endpoint: value || null })} /><CheckInput label="启用模型" checked={modelForm.is_enabled} onChange={(value) => setModelForm({ ...modelForm, is_enabled: value })} /></div>
      <button disabled={saving} onClick={() => void saveModel()} className="btn-primary mt-4 text-sm disabled:opacity-50">保存模型</button>
      <div className="mt-6 border-t border-black/10 pt-4"><SelectInput label="功能" value={featureKey} onChange={setFeatureKey} options={FEATURE_OPTIONS.map(([value, label]) => [value, label])} /><div className="mt-3 space-y-2">{models.map((model) => { const link = featureLinks.find((item) => item.model_id === model.id); return <div key={model.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-black/5 bg-white/50 p-3 text-sm"><button className="min-w-48 text-left font-medium text-apple-blue hover:underline" onClick={() => setModelForm(model)}>{model.display_name} <span className="font-mono text-xs">{model.id}</span></button><CheckInput label="在此功能启用" checked={link?.is_enabled || false} onChange={(is_enabled) => void setFeatureModel(model.id, { is_enabled })} /><CheckInput label="默认" checked={link?.is_default || false} onChange={(is_default) => void setFeatureModel(model.id, { is_default })} /><label className="ml-auto">排序 <input type="number" min="0" value={link?.sort_order ?? 0} onChange={(event) => void setFeatureModel(model.id, { sort_order: Number(event.target.value) || 0 })} className="glass-input ml-1 w-20 px-2 py-1" /></label></div> })}</div></div>
    </GovernanceDialog>}

    {panel === 'usage-log' && <GovernanceDialog title="调用日志" onClose={() => setPanel(null)}>
      <p className="text-sm text-apple-gray-medium">日志不包含 API Key 或请求内容；可按用户、功能、模型、结果和时间筛选。</p>
      <div className="mt-4 grid gap-3 md:grid-cols-4"><SelectInput label="用户" value={logFilters.user_id} onChange={(value) => setLogFilters({ ...logFilters, user_id: value })} options={users.map((user) => [user.id, user.username])} includeEmpty /><SelectInput label="功能" value={logFilters.feature_key} onChange={(value) => setLogFilters({ ...logFilters, feature_key: value })} options={FEATURE_OPTIONS.map(([value, label]) => [value, label])} includeEmpty /><SelectInput label="模型" value={logFilters.model_id} onChange={(value) => setLogFilters({ ...logFilters, model_id: value })} options={models.map((model) => [model.id, model.display_name])} includeEmpty /><SelectInput label="结果" value={logFilters.result} onChange={(value) => setLogFilters({ ...logFilters, result: value })} options={[["success", "成功"], ["failed", "失败"], ["timeout", "超时"]]} includeEmpty /><TextInput label="开始时间" type="datetime-local" value={logFilters.date_from} onChange={(value) => setLogFilters({ ...logFilters, date_from: value })} /><TextInput label="结束时间" type="datetime-local" value={logFilters.date_to} onChange={(value) => setLogFilters({ ...logFilters, date_to: value })} /></div>
      <button onClick={() => void loadLogs()} className="mt-4 text-sm text-apple-blue hover:underline">应用筛选</button><p className="mt-3 text-xs text-apple-gray-medium">共 {logTotal} 条</p><div className="mt-2 overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th>时间</th><th>用户</th><th>功能</th><th>模型</th><th>结果</th><th>耗时</th></tr></thead><tbody>{logs.map((log) => <tr key={log.id} className="border-b border-black/5"><td className="py-2">{new Date(log.created_at).toLocaleString('zh-CN')}</td><td>{users.find((user) => user.id === log.user_id)?.username || log.user_id || '-'}</td><td>{log.feature_key}</td><td>{modelById.get(log.model_id || '')?.display_name || log.model_id || '-'}</td><td>{log.result}</td><td>{log.latency_ms == null ? '-' : `${log.latency_ms} ms`}</td></tr>)}</tbody></table></div>
    </GovernanceDialog>}

  </div>
}

function AuthorizationOverviewMatrix({ overview, onEdit }: { overview: AuthorizationOverview; onEdit: (cell: EditingCell) => void }) {
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(new Set())
  const toggleGroup = (groupId: string) => setExpandedGroupIds((current) => {
    const next = new Set(current)
    if (next.has(groupId)) next.delete(groupId); else next.add(groupId)
    return next
  })

  return <Section title="授权总览" description="部门行管理部门默认授权；展开部门后可为成员设置独属模型。无可用 Key 的模型仍会展示，便于补齐凭据。">
    {overview.groups.length === 0
      ? <p className="text-sm text-apple-gray-medium">还没有部门或可授权模型可供汇总。</p>
      : <div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead><tr className="border-b"><th className="min-w-52 px-2 py-2">对象</th>{overview.features.map((feature) => <th key={feature.feature_key} className="min-w-72 px-2 py-2">{featureLabel(feature.feature_key)}</th>)}</tr></thead><tbody>{overview.groups.map((group) => <Fragment key={group.subject_id}><AuthorizationRow subject={{ subject_id: group.subject_id, subject_name: group.subject_name, features: group.features }} kind="group" expanded={expandedGroupIds.has(group.subject_id)} onToggle={() => toggleGroup(group.subject_id)} onEdit={onEdit} />{expandedGroupIds.has(group.subject_id) && group.members.map((member) => <AuthorizationRow key={member.subject_id} subject={member} kind="user" indent onEdit={onEdit} />)}</Fragment>)}</tbody></table></div>}
  </Section>
}

function AuthorizationRow({ subject, kind, indent = false, expanded, onToggle, onEdit }: { subject: { subject_id: string; subject_name: string; features: AuthorizationOverview['groups'][number]['features']; has_personal_override?: boolean }; kind: 'group' | 'user'; indent?: boolean; expanded?: boolean; onToggle?: () => void; onEdit: (cell: EditingCell) => void }) {
  return <tr className="border-b border-black/5 align-top"><td className="px-2 py-3"><div className={indent ? 'pl-6' : ''}>{kind === 'group' ? <button type="button" onClick={onToggle} className="font-medium text-apple-text hover:text-apple-blue">{expanded ? '▾' : '▸'} {subject.subject_name}</button> : <div className="font-medium">{subject.subject_name}</div>}<div className="mt-1 text-xs text-apple-gray-medium">{kind === 'group' ? '部门默认授权（点击名称展开成员）' : subject.has_personal_override ? '个人例外规则' : '继承部门'}</div></div></td>{subject.features.map((feature) => <td key={feature.feature_key} className="px-2 py-3"><AuthorizationCell subject={subject} kind={kind} feature={feature} onEdit={onEdit} /></td>)}</tr>
}

function AuthorizationCell({ subject, kind, feature, onEdit }: { subject: { subject_id: string; subject_name: string }; kind: 'group' | 'user'; feature: AuthorizationOverview['groups'][number]['features'][number]; onEdit: (cell: EditingCell) => void }) {
  const open = () => onEdit({ subjectType: kind, subjectId: subject.subject_id, subjectName: subject.subject_name, featureKey: feature.feature_key, selectedModelIds: feature.models.map((model) => model.model_id) })
  return <div className="space-y-2">{feature.models.length > 0 && <div className="flex flex-wrap gap-2">{feature.models.map((model) => <div key={`${model.model_id}-${model.permission_source}`} className="rounded-lg border border-black/10 bg-white/60 px-2 py-1.5"><div className="font-medium">{model.display_name}</div><div className="mt-1 flex flex-wrap gap-1 text-xs"><span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">{kind === 'user' && model.permission_source !== 'user_allow' ? '继承部门' : permissionSourceLabel(model.permission_source)}</span>{model.key_available ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">{credentialScopeLabel(model.credential_scope_type)} Key</span> : <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">无可用 Key</span>}</div></div>)}</div>}<button type="button" onClick={open} className="text-sm text-apple-blue hover:underline">{feature.models.length ? '管理模型' : '添加模型'}</button></div>
}

function AuthorizationOverviewDrawer({ overview, editingCell, saving, onChange, onClose, onSave }: { overview: AuthorizationOverview; editingCell: Exclude<EditingCell, null>; saving: boolean; onChange: (cell: EditingCell) => void; onClose: () => void; onSave: () => void }) {
  const catalog = overview.features.find((feature) => feature.feature_key === editingCell.featureKey)?.models || []
  const currentModels = overview.groups.flatMap((group) => [{ subjectType: 'group' as const, subjectId: group.subject_id, features: group.features }, ...group.members.map((member) => ({ subjectType: 'user' as const, subjectId: member.subject_id, features: member.features }))]).find((row) => row.subjectType === editingCell.subjectType && row.subjectId === editingCell.subjectId)?.features.find((feature) => feature.feature_key === editingCell.featureKey)?.models || []
  const pendingPermissionSource = editingCell.subjectType === 'group' ? '尚未授权，保存后将作为部门允许' : '尚未授权，保存后将作为个人允许'
  const pendingKeyStatus = (providerName: string) => `授权后将按${editingCell.subjectType === 'group' ? '该部门' : '该个人'}解析 ${providerName} Key（保存后刷新确认）`
  const toggleModel = (modelId: string) => onChange({ ...editingCell, selectedModelIds: editingCell.selectedModelIds.includes(modelId) ? editingCell.selectedModelIds.filter((id) => id !== modelId) : [...editingCell.selectedModelIds, modelId] })
  return <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="dialog" aria-modal="true" aria-label="管理授权模型"><div className="h-full w-full max-w-lg overflow-y-auto bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><h2 className="text-xl font-semibold">管理模型</h2><p className="mt-1 text-sm text-apple-gray-medium">{editingCell.subjectName} · {featureLabel(editingCell.featureKey)}</p></div><button type="button" onClick={onClose} disabled={saving} className="text-apple-gray-medium hover:text-apple-text">关闭</button></div><p className="mt-5 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">{editingCell.subjectType === 'group' ? '取消选择功能默认模型会生成部门拒绝规则。' : '取消选择继承的模型会生成个人拒绝规则。'}</p><div className="mt-4 space-y-3">{catalog.map((model) => { const current = currentModels.find((item) => item.model_id === model.model_id); return <label key={model.model_id} className="flex cursor-pointer gap-3 rounded-xl border border-black/10 p-3"><input type="checkbox" checked={editingCell.selectedModelIds.includes(model.model_id)} onChange={() => toggleModel(model.model_id)} disabled={saving} className="mt-1" /><span><span className="block font-medium">{model.display_name}</span><span className="mt-1 flex flex-wrap gap-1 text-xs">{current ? <><span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">{permissionSourceLabel(current.permission_source)}</span>{current.key_available ? <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">{credentialScopeLabel(current.credential_scope_type)} Key</span> : <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">无可用 Key</span>}</> : <><span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">{pendingPermissionSource}</span><span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">{pendingKeyStatus(model.provider_name)}</span></>}</span></span></label> })}</div>{catalog.length === 0 && <p className="mt-4 text-sm text-apple-gray-medium">此功能尚未启用可授权模型。</p>}<div className="mt-6 flex justify-end gap-3"><button type="button" onClick={onClose} disabled={saving} className="px-4 py-2 text-sm text-apple-gray-medium">取消</button><button type="button" onClick={onSave} disabled={saving} className="btn-primary px-4 py-2 text-sm disabled:opacity-50">{saving ? '保存中…' : '保存选择'}</button></div></div></div>
}

function featureLabel(featureKey: string) { return FEATURE_OPTIONS.find(([value]) => value === featureKey)?.[1] || featureKey }
function permissionSourceLabel(source: AuthorizationOverview['groups'][number]['features'][number]['models'][number]['permission_source']) { return source === 'user_allow' ? '个人允许' : source === 'group_allow' ? '部门允许' : '功能默认' }
function credentialScopeLabel(scope: AuthorizationOverview['groups'][number]['features'][number]['models'][number]['credential_scope_type']) { return scope === 'user' ? '个人' : scope === 'group' ? '部门' : '公司' }
function omitId(model: ManagedModel): Omit<ManagedModel, 'id'> { const { id: _, ...rest } = model; return rest }
function subjectsFor(type: 'group' | 'user', groups: Array<{ id: string; group_name: string }>, users: User[]): Array<[string, string]> { return type === 'group' ? groups.map((item): [string, string] => [item.id, item.group_name]) : users.map((item): [string, string] => [item.id, item.username]) }
function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) { return <section className="glass rounded-2xl p-5"><h2 className="text-lg font-semibold text-apple-text">{title}</h2><p className="mb-4 mt-1 text-sm text-apple-gray-medium">{description}</p>{children}</section> }
function GovernanceDialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true" aria-label={title}><section className="glass max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-2xl p-5 shadow-xl"><header className="flex items-center justify-between gap-4"><h2 className="text-lg font-semibold text-apple-text">{title}</h2><button onClick={onClose} className="text-2xl leading-none text-apple-gray-medium hover:text-apple-text" aria-label="关闭">×</button></header><div className="mt-4">{children}</div></section></div> }
function Notice({ kind, text, onClose }: { kind: 'error' | 'success'; text: string; onClose: () => void }) { return <div className={`rounded-xl px-4 py-3 text-sm ${kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}>{text}<button onClick={onClose} className="float-right">×</button></div> }
function TextInput({ label, value, onChange, type = 'text', placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) { return <label className="block text-sm"><span className="mb-1 block text-apple-gray-dark">{label}</span><input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} className="glass-input w-full px-3 py-2" /></label> }
function SelectInput({ label, value, onChange, options, includeEmpty = false }: { label: string; value: string; onChange: (value: string) => void; options: readonly (readonly [string, string])[]; includeEmpty?: boolean }) { return <label className="block text-sm"><span className="mb-1 block text-apple-gray-dark">{label}</span><select value={value} onChange={(event) => onChange(event.target.value)} className="glass-input w-full px-3 py-2">{includeEmpty && <option value="">全部</option>}{!includeEmpty && <option value="">请选择</option>}{options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label> }
function CheckInput({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) { return <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />{label}</label> }
