import { useEffect, useMemo, useState } from 'react'
import { api, type PlatformTool } from '../services/api'

type Group = { id: string; group_name: string; description?: string }
type Permission = { permission_key: string }

export default function AdminDepartmentWorkbench() {
  const [groups, setGroups] = useState<Group[]>([])
  const [tools, setTools] = useState<PlatformTool[]>([])
  const [selected, setSelected] = useState<Group | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => { Promise.all([api.groups.list(), api.tools.listManaged()]).then(([nextGroups, nextTools]) => { setGroups(nextGroups); setTools(nextTools); setSelected(nextGroups[0] || null) }).catch((err: Error) => setError(err.message)) }, [])
  useEffect(() => { if (!selected) return; api.groups.groupPermissions(selected.id).then((items: Permission[]) => setPermissions(items.map((item) => item.permission_key))).catch((err: Error) => setError(err.message)) }, [selected])
  const visibleTools = useMemo(() => tools.filter((tool) => tool.is_enabled && permissions.includes(tool.permission_key)), [tools, permissions])

  return <main className="mx-auto max-w-6xl px-4 pb-12 pt-8 md:px-6">
    <p className="text-sm font-bold text-teal-700">IT / 管理员工作台</p><h1 className="mt-2 text-3xl font-black text-apple-text">部门工具工作台</h1><p className="mt-2 text-sm text-apple-gray-medium">选择部门，即可预览该部门员工实际能看到的功能；这里不读取员工文件或运行记录。</p>
    {error && <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>}
    <div className="mt-7 grid gap-5 lg:grid-cols-[250px_1fr]"><aside className="glass rounded-3xl p-3"><p className="px-3 py-2 text-xs font-bold text-apple-gray-medium">部门</p>{groups.map((group) => <button key={group.id} onClick={() => setSelected(group)} className={`block w-full rounded-2xl px-4 py-3 text-left text-sm font-bold ${selected?.id === group.id ? 'bg-teal-700 text-white' : 'text-apple-gray-dark hover:bg-white/60'}`}>{group.group_name}</button>)}</aside><section className="glass rounded-3xl p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-black text-apple-text">{selected?.group_name || '请选择部门'}</h2><p className="mt-1 text-sm text-apple-gray-medium">已授予 {permissions.length} 项权限，可见 {visibleTools.length} 个已启用工具。</p></div><a href="/admin/groups" className="rounded-full bg-teal-50 px-4 py-2 text-sm font-bold text-teal-700">修改部门权限</a></div><div className="mt-5 grid gap-3 sm:grid-cols-2">{visibleTools.map((tool) => <a key={tool.tool_key} href={tool.route_path} className="rounded-2xl border border-teal-100 bg-white/55 p-4"><p className="font-black text-apple-text">{tool.name}</p><p className="mt-1 text-xs text-apple-gray-medium">{tool.permission_key}</p><p className="mt-3 text-xs font-bold text-teal-700">以该部门视角查看 →</p></a>)}</div>{selected && !visibleTools.length && <p className="mt-5 rounded-2xl bg-amber-50 px-4 py-4 text-sm text-amber-800">这个部门当前没有已启用的工具。可到“部门权限”或“工具管理”调整。</p>}</section></div>
  </main>
}
