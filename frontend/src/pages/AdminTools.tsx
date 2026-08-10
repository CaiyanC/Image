import { type FormEvent, useEffect, useState } from 'react'
import { api, type PlatformTool } from '../services/api'

type ExternalToolForm = {
  tool_key: string
  name: string
  description: string
  external_url: string
  open_mode: PlatformTool['open_mode']
}

const emptyExternalForm: ExternalToolForm = {
  tool_key: '',
  name: '',
  description: '',
  external_url: 'http://localhost:',
  open_mode: 'new_tab',
}

export default function AdminTools() {
  const [tools, setTools] = useState<PlatformTool[]>([])
  const [form, setForm] = useState(emptyExternalForm)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const load = () => api.tools.listManaged().then(setTools).catch((err: Error) => setError(err.message))
  useEffect(() => { load() }, [])

  function patchLocal(toolKey: string, data: Partial<PlatformTool>) {
    setTools((items) => items.map((item) => item.tool_key === toolKey ? { ...item, ...data } : item))
  }

  async function update(tool: PlatformTool, data: Partial<PlatformTool>) {
    setSaving(tool.tool_key); setError(''); setMessage('')
    try {
      const updated = await api.tools.update(tool.tool_key, data)
      patchLocal(tool.tool_key, updated)
      setMessage(`“${updated.name}”已保存。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(null)
    }
  }

  async function createExternal(event: FormEvent) {
    event.preventDefault()
    setCreating(true); setError(''); setMessage('')
    try {
      const created = await api.tools.create({
        ...form,
        entry_type: 'external',
        category: '外部应用',
        icon_key: 'external-link',
        is_enabled: true,
        sort_order: 100,
      })
      setTools((items) => [...items, created].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)))
      setForm(emptyExternalForm)
      setMessage(`外部应用“${created.name}”已接入；现在可以到“部门权限”分配 ${created.permission_key}。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '外部应用接入失败')
    } finally {
      setCreating(false)
    }
  }

  async function remove(tool: PlatformTool) {
    if (!confirm(`确定删除外部应用“${tool.name}”吗？对应部门权限也会删除。`)) return
    setSaving(tool.tool_key); setError(''); setMessage('')
    try {
      await api.tools.delete(tool.tool_key)
      setTools((items) => items.filter((item) => item.tool_key !== tool.tool_key))
      setMessage(`“${tool.name}”已删除。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setSaving(null)
    }
  }

  return <main className="mx-auto max-w-5xl px-4 pb-12 pt-8 md:px-6">
    <div>
      <p className="text-sm font-bold text-teal-700">开发与管理</p>
      <h1 className="mt-2 text-3xl font-black text-apple-text">工具管理</h1>
      <p className="mt-2 text-sm text-apple-gray-medium">内部工具由主项目提供；外部应用可以运行在另一个项目、域名或本机端口，并继续使用部门权限控制入口。</p>
    </div>

    <form onSubmit={createExternal} className="glass mt-7 rounded-3xl p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-black text-apple-text">接入外部应用</h2>
          <p className="mt-1 text-sm text-apple-gray-medium">例如填写 http://localhost:5280。这里只建立受部门权限控制的入口，不会向外部页面传递主系统登录令牌。</p>
        </div>
        <a href="/admin/groups" className="rounded-full bg-teal-50 px-4 py-2 text-sm font-bold text-teal-700">管理部门权限</a>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="text-sm font-bold text-apple-gray-dark">工具标识
          <input required pattern="[a-z][a-z0-9_]+" maxLength={64} value={form.tool_key} onChange={(event) => setForm({ ...form, tool_key: event.target.value })} placeholder="inventory_dashboard" className="mt-2 w-full rounded-2xl border border-black/10 bg-white/70 px-4 py-3 font-normal outline-none focus:border-teal-500" />
          <span className="mt-1 block text-xs font-normal text-apple-gray-medium">只能使用小写字母、数字和下划线，创建后不可修改。</span>
        </label>
        <label className="text-sm font-bold text-apple-gray-dark">显示名称
          <input required maxLength={120} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="库存看板" className="mt-2 w-full rounded-2xl border border-black/10 bg-white/70 px-4 py-3 font-normal outline-none focus:border-teal-500" />
        </label>
        <label className="text-sm font-bold text-apple-gray-dark md:col-span-2">外部地址
          <input required type="url" maxLength={2048} value={form.external_url} onChange={(event) => setForm({ ...form, external_url: event.target.value })} placeholder="http://localhost:5280" className="mt-2 w-full rounded-2xl border border-black/10 bg-white/70 px-4 py-3 font-normal outline-none focus:border-teal-500" />
        </label>
        <label className="text-sm font-bold text-apple-gray-dark">打开方式
          <select value={form.open_mode} onChange={(event) => setForm({ ...form, open_mode: event.target.value as 'same_tab' | 'new_tab' })} className="mt-2 w-full rounded-2xl border border-black/10 bg-white/70 px-4 py-3 font-normal outline-none focus:border-teal-500">
            <option value="new_tab">新窗口打开</option>
            <option value="same_tab">当前窗口打开</option>
          </select>
        </label>
        <label className="text-sm font-bold text-apple-gray-dark">说明
          <input maxLength={2000} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="这个工具用来做什么" className="mt-2 w-full rounded-2xl border border-black/10 bg-white/70 px-4 py-3 font-normal outline-none focus:border-teal-500" />
        </label>
      </div>
      <div className="mt-5 flex justify-end"><button disabled={creating} className="btn-primary px-5 py-2.5 text-sm disabled:opacity-50">{creating ? '接入中…' : '接入外部应用'}</button></div>
    </form>

    {error && <p className="mt-5 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>}
    {message && <p className="mt-5 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</p>}

    <div className="mt-7 space-y-4">
      {tools.map((tool) => <article key={tool.tool_key} className="glass rounded-3xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs font-bold text-teal-700">
              <span>{tool.tool_key}</span><span>·</span><span>{tool.permission_key}</span>
              <span className={`rounded-full px-2 py-0.5 ${tool.entry_type === 'external' ? 'bg-violet-50 text-violet-700' : 'bg-teal-50 text-teal-700'}`}>{tool.entry_type === 'external' ? '外部应用' : '内部工具'}</span>
            </div>
            <input value={tool.name} onChange={(event) => patchLocal(tool.tool_key, { name: event.target.value })} className="mt-2 w-full bg-transparent text-lg font-black text-apple-text outline-none" />
            {tool.entry_type === 'external' ? <div className="mt-3 grid gap-3 md:grid-cols-[1fr_160px]">
              <input type="url" value={tool.external_url || ''} onChange={(event) => patchLocal(tool.tool_key, { external_url: event.target.value })} className="rounded-xl border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-teal-500" />
              <select value={tool.open_mode} onChange={(event) => patchLocal(tool.tool_key, { open_mode: event.target.value as PlatformTool['open_mode'] })} className="rounded-xl border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-teal-500">
                <option value="new_tab">新窗口</option><option value="same_tab">当前窗口</option>
              </select>
            </div> : <p className="mt-1 text-sm text-apple-gray-medium">{tool.route_path}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button disabled={saving === tool.tool_key} onClick={() => update(tool, tool.entry_type === 'external' ? { name: tool.name, external_url: tool.external_url, open_mode: tool.open_mode } : { name: tool.name })} className="rounded-full px-3 py-1.5 text-xs font-bold text-teal-700 hover:bg-teal-50 disabled:opacity-50">保存</button>
            <label className="flex items-center gap-2 text-sm font-bold text-apple-gray-dark"><input type="checkbox" checked={tool.is_enabled} disabled={saving === tool.tool_key} onChange={(event) => update(tool, { is_enabled: event.target.checked })} />{tool.is_enabled ? '已启用' : '已停用'}</label>
            {tool.entry_type === 'external' && <button disabled={saving === tool.tool_key} onClick={() => remove(tool)} className="rounded-full px-3 py-1.5 text-xs font-bold text-red-600 hover:bg-red-50 disabled:opacity-50">删除</button>}
          </div>
        </div>
      </article>)}
    </div>
  </main>
}
