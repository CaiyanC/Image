import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type PlatformTool } from '../services/api'
import { hasPermission, useAuthStore } from '../store/authStore'
import { supplementalEntries } from '../components/layout/navigation'

type ToolCardData = Pick<PlatformTool, 'name' | 'description' | 'icon_key' | 'entry_type' | 'external_url' | 'open_mode' | 'route_path'>

export default function ToolCenter() {
  const [tools, setTools] = useState<PlatformTool[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const user = useAuthStore((state) => state.user)
  const permissionSignature = [...(user?.permissions || [])].sort().join('|')
  const visibleTools = tools.filter((tool) => tool.is_enabled && hasPermission(user, tool.permission_key))
  const supplementary = supplementalEntries(key => hasPermission(user, key))
    .filter(item => !visibleTools.some(tool => tool.entry_type === 'internal' && tool.route_path === item.path))

  useEffect(() => {
    let active = true
    setLoading(true)
    setTools([])
    setError('')
    api.tools.list().then((items) => { if (active) setTools(items) })
      .catch((err: Error) => { if (active) { setTools([]); setError(err.message) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [permissionSignature])

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8 md:px-6">
      <div className="mb-8">
        <p className="text-sm font-bold text-teal-700">统一工具平台</p>
        <h1 className="mt-2 text-3xl font-black text-apple-text">工具中心</h1>
        <p className="mt-2 text-sm text-apple-gray-medium">选择工具开始工作。产品、素材、客服、创作和财务集中在这里，只展示你有权限使用的功能。</p>
      </div>
      {error && <div className="mb-5 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</div>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleTools.map((tool) => <ToolCard key={tool.tool_key} tool={tool} />)}
        {supplementary.map(item => <ToolCard key={item.path} tool={{ name: item.label, description: '进入已授权的业务功能，更多操作在页面内完成。', icon_key: 'tool', entry_type: 'internal', external_url: null, open_mode: 'same_tab', route_path: item.path }} />)}
      </div>
      {loading && <p className="p-8 text-center text-sm text-apple-gray-medium">正在加载可用工具…</p>}
      {!loading && !error && visibleTools.length === 0 && supplementary.length === 0 && <p className="rounded-3xl bg-white/55 p-8 text-center text-sm text-apple-gray-medium">当前账号暂无可用业务工具。如需使用，请联系管理员分配权限；已有的管理或个人设置入口在右上角。</p>}
    </main>
  )
}

function ToolCard({ tool }: { tool: ToolCardData }) {
  const className = "glass group block rounded-3xl p-6 transition hover:-translate-y-1 hover:shadow-lg"
  const content = <>
    <div className="flex items-start justify-between gap-3">
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-accent text-lg font-black text-white">
        {tool.icon_key === 'spreadsheet' ? '表' : tool.entry_type === 'external' ? '外' : '工'}
      </div>
      {tool.entry_type === 'external' && <span className="rounded-full bg-violet-50 px-2 py-1 text-xs font-bold text-violet-700">外部应用</span>}
    </div>
    <h2 className="mt-5 text-lg font-black text-apple-text">{tool.name}</h2>
    <p className="mt-2 min-h-10 text-sm leading-5 text-apple-gray-medium">{tool.description || '部门授权后可使用的业务工具。'}</p>
    <span className="mt-5 inline-block text-sm font-bold text-teal-700 group-hover:text-teal-600">{tool.entry_type === 'external' ? '打开外部应用 ↗' : '打开工具 →'}</span>
  </>

  if (tool.entry_type === 'external' && tool.external_url) {
    return <a href={tool.external_url} target={tool.open_mode === 'new_tab' ? '_blank' : undefined} rel={tool.open_mode === 'new_tab' ? 'noopener noreferrer' : undefined} className={className}>{content}</a>
  }
  return <Link to={tool.route_path} className={className}>{content}</Link>
}
