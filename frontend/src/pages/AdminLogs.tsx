import { useEffect, useState } from 'react'
import { api } from '../services/api'

interface OperationLogItem {
  id: string
  operator_name: string
  action_type: string
  action_name: string
  target_type: string
  target_name: string
  status: string
  ip_address?: string | null
  created_at: string
  request_data?: unknown
  response_data?: unknown
}

export default function AdminLogs() {
  const [logs, setLogs] = useState<OperationLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [actionType, setActionType] = useState('')
  const [targetType, setTargetType] = useState('')
  const [selected, setSelected] = useState<OperationLogItem | null>(null)

  useEffect(() => {
    loadLogs()
  }, [actionType, targetType])

  async function loadLogs() {
    setLoading(true)
    try {
      const result = await api.admin.operationLogs({
        limit: 100,
        search: search.trim() || undefined,
        action_type: actionType || undefined,
        target_type: targetType || undefined,
      })
      setLogs(result.items)
      setTotal(result.total)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">操作日志</h1>
          <p className="text-sm text-apple-gray-medium mt-1">共 {total} 条记录</p>
        </div>
        <button onClick={loadLogs} className="btn-primary text-sm" disabled={loading}>
          {loading ? '加载中...' : '刷新'}
        </button>
      </div>

      <div className="glass rounded-xl p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_160px_180px_auto] gap-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') loadLogs()
            }}
            placeholder="搜索操作者、动作、对象"
            className="glass-input px-3 py-2 text-sm"
          />
          <select value={actionType} onChange={(e) => setActionType(e.target.value)} className="glass-input px-3 py-2 text-sm">
            <option value="">全部动作</option>
            <option value="create">创建</option>
            <option value="update">更新</option>
            <option value="delete">删除</option>
            <option value="import">导入</option>
            <option value="reset_password">重置密码</option>
            <option value="enable">启用</option>
            <option value="disable">禁用</option>
          </select>
          <select value={targetType} onChange={(e) => setTargetType(e.target.value)} className="glass-input px-3 py-2 text-sm">
            <option value="">全部对象</option>
            <option value="user">用户</option>
            <option value="group">团队</option>
            <option value="product">产品</option>
            <option value="product_qa">产品 QA</option>
            <option value="product_draft">产品草稿</option>
            <option value="product_media">产品素材</option>
            <option value="system_config">系统配置</option>
          </select>
          <button onClick={loadLogs} className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm">
            查询
          </button>
        </div>
      </div>

      <div className="glass rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-black/5">
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">时间</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">操作者</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">动作</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">对象</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">状态</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-apple-gray-dark">详情</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-black/5">
            {logs.map((log) => (
              <tr key={log.id} className="hover:bg-black/[0.01]">
                <td className="px-4 py-3 text-xs text-apple-gray-medium">{new Date(log.created_at).toLocaleString('zh-CN')}</td>
                <td className="px-4 py-3 text-sm text-apple-text">{log.operator_name}</td>
                <td className="px-4 py-3">
                  <div className="text-sm font-medium text-apple-text">{log.action_name}</div>
                  <div className="text-xs text-apple-gray-medium">{log.action_type}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="text-sm text-apple-text">{log.target_name}</div>
                  <div className="text-xs text-apple-gray-medium">{log.target_type}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded-full ${log.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {log.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => setSelected(log)} className="text-xs text-apple-blue hover:underline">
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!logs.length && (
          <div className="py-12 text-center text-sm text-apple-gray-medium">
            暂无日志
          </div>
        )}
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[80vh] overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h3 className="font-semibold text-apple-text">日志详情</h3>
              <button onClick={() => setSelected(null)} className="text-2xl leading-none text-apple-gray-medium">×</button>
            </div>
            <div className="p-5 overflow-y-auto max-h-[calc(80vh-4rem)]">
              <div className="grid grid-cols-2 gap-3 text-sm mb-4">
                <div><span className="text-apple-gray-medium">动作：</span>{selected.action_name}</div>
                <div><span className="text-apple-gray-medium">对象：</span>{selected.target_name}</div>
                <div><span className="text-apple-gray-medium">操作者：</span>{selected.operator_name}</div>
                <div><span className="text-apple-gray-medium">IP：</span>{selected.ip_address || '-'}</div>
              </div>
              <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto">
{JSON.stringify({ request_data: selected.request_data, response_data: selected.response_data }, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
