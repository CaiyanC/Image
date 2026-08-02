import { useEffect, useState } from 'react'
import { api, type PlatformTool } from '../services/api'

export default function AdminTools() {
  const [tools, setTools] = useState<PlatformTool[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState<string | null>(null)

  const load = () => api.tools.listManaged().then(setTools).catch((err: Error) => setError(err.message))
  useEffect(() => { load() }, [])

  async function update(tool: PlatformTool, data: Partial<PlatformTool>) {
    setSaving(tool.tool_key); setError('')
    try {
      const updated = await api.tools.update(tool.tool_key, data)
      setTools((items) => items.map((item) => item.tool_key === updated.tool_key ? updated : item))
    } catch (err) { setError(err instanceof Error ? err.message : '保存失败')
    } finally { setSaving(null) }
  }

  return <main className="mx-auto max-w-5xl px-4 pb-12 pt-8 md:px-6">
    <div><p className="text-sm font-bold text-teal-700">开发与管理</p><h1 className="mt-2 text-3xl font-black text-apple-text">工具管理</h1><p className="mt-2 text-sm text-apple-gray-medium">代码接入后会由系统登记为工具；此处只管理名称、排序和启用状态，权限仍由部门权限配置决定。</p></div>
    {error && <p className="mt-5 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>}
    <div className="mt-7 space-y-3">
      {tools.map((tool) => <article key={tool.tool_key} className="glass rounded-3xl p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0 flex-1"><p className="text-xs font-bold text-teal-700">{tool.tool_key} · {tool.permission_key}</p><input value={tool.name} onChange={(event) => setTools((items) => items.map((item) => item.tool_key === tool.tool_key ? { ...item, name: event.target.value } : item))} className="mt-2 w-full bg-transparent text-lg font-black text-apple-text outline-none" /><p className="mt-1 text-sm text-apple-gray-medium">{tool.route_path}</p></div><div className="flex items-center gap-3"><button disabled={saving === tool.tool_key} onClick={() => update(tool, { name: tool.name })} className="rounded-full px-3 py-1.5 text-xs font-bold text-teal-700 hover:bg-teal-50">保存名称</button><label className="flex items-center gap-2 text-sm font-bold text-apple-gray-dark"><input type="checkbox" checked={tool.is_enabled} disabled={saving === tool.tool_key} onChange={(event) => update(tool, { is_enabled: event.target.checked })} />{tool.is_enabled ? '已启用' : '已停用'}</label></div></div></article>)}
    </div>
  </main>
}
