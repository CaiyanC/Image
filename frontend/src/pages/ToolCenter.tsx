import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type PlatformTool } from '../services/api'

export default function ToolCenter() {
  const [tools, setTools] = useState<PlatformTool[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    api.tools.list().then(setTools).catch((err: Error) => setError(err.message))
  }, [])

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8 md:px-6">
      <div className="mb-8">
        <p className="text-sm font-bold text-teal-700">统一工具平台</p>
        <h1 className="mt-2 text-3xl font-black text-apple-text">我的可用工具</h1>
        <p className="mt-2 text-sm text-apple-gray-medium">系统会按你所在部门的权限展示工具。</p>
      </div>
      {error && <div className="mb-5 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</div>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tools.map((tool) => (
          <Link key={tool.tool_key} to={tool.route_path} className="glass group rounded-3xl p-6 transition hover:-translate-y-1 hover:shadow-lg">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-accent text-lg font-black text-white">
              {tool.icon_key === 'spreadsheet' ? '表' : '工'}
            </div>
            <h2 className="mt-5 text-lg font-black text-apple-text">{tool.name}</h2>
            <p className="mt-2 min-h-10 text-sm leading-5 text-apple-gray-medium">{tool.description || '部门授权后可使用的业务工具。'}</p>
            <span className="mt-5 inline-block text-sm font-bold text-teal-700 group-hover:text-teal-600">打开工具 →</span>
          </Link>
        ))}
      </div>
      {!error && tools.length === 0 && <p className="rounded-3xl bg-white/55 p-8 text-center text-sm text-apple-gray-medium">当前账号暂未分配可用工具，请联系管理员。</p>}
    </main>
  )
}
