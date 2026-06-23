import { useEffect, useMemo, useState } from 'react'
import { api } from '../services/api'
import type { User } from '../types'

interface OperationLogItem {
  id: string
  operator_id: string
  operator_name: string
  operator_display_name?: string | null
  action_type: string
  action_name: string
  target_type: string
  target_id?: string | null
  target_name: string
  status: string
  error_message?: string | null
  ip_address?: string | null
  user_agent?: string | null
  snapshot_id?: string | null
  can_restore?: boolean
  restored_at?: string | null
  created_at: string
  request_data?: unknown
  response_data?: unknown
}

const PAGE_SIZE = 50

export default function AdminLogs() {
  const [logs, setLogs] = useState<OperationLogItem[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [actionType, setActionType] = useState('')
  const [targetType, setTargetType] = useState('')
  const [status, setStatus] = useState('')
  const [operatorId, setOperatorId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<OperationLogItem | null>(null)

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total])

  useEffect(() => {
    loadUsers()
  }, [])

  useEffect(() => {
    loadLogs()
  }, [page, actionType, targetType, status, operatorId])

  async function loadUsers() {
    try {
      const data = (await api.users.list(0, 200)) as User[]
      setUsers(data)
    } catch {
      setUsers([])
    }
  }

  async function loadLogs(nextPage = page) {
    setLoading(true)
    try {
      const result = await api.admin.operationLogs({
        skip: (nextPage - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search.trim() || undefined,
        action_type: actionType || undefined,
        target_type: targetType || undefined,
        status: status || undefined,
        operator_id: operatorId || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      setLogs(result.items)
      setTotal(result.total)
    } finally {
      setLoading(false)
    }
  }

  async function restoreSnapshot(log: OperationLogItem) {
    if (!log.snapshot_id) return
    if (!confirm(`确认恢复产品「${log.target_name}」到这次操作之前的状态吗？恢复行为也会写入操作记录。`)) {
      return
    }
    await api.admin.restoreProductSnapshot(log.snapshot_id)
    setSelected(null)
    loadLogs()
  }

  function handleSearch() {
    setPage(1)
    loadLogs(1)
  }

  function resetFilters() {
    setSearch('')
    setActionType('')
    setTargetType('')
    setStatus('')
    setOperatorId('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  function changePage(nextPage: number) {
    setPage(Math.min(Math.max(nextPage, 1), totalPages))
  }

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">操作记录</h1>
          <p className="text-sm text-apple-gray-medium mt-1">
            共 {total} 条记录，按时间倒序排列
          </p>
        </div>
        <button onClick={() => loadLogs()} className="btn-primary text-sm" disabled={loading}>
          {loading ? '加载中...' : '刷新'}
        </button>
      </div>

      <div className="glass rounded-xl p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSearch()
            }}
            placeholder="搜账号、SKU、对象、动作"
            className="glass-input px-3 py-2 text-sm md:col-span-2"
          />
          <select value={operatorId} onChange={(e) => { setOperatorId(e.target.value); setPage(1) }} className="glass-input px-3 py-2 text-sm">
            <option value="">全部账号</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.display_name || user.username}
              </option>
            ))}
          </select>
          <select value={actionType} onChange={(e) => { setActionType(e.target.value); setPage(1) }} className="glass-input px-3 py-2 text-sm">
            <option value="">全部动作</option>
            <option value="create">创建</option>
            <option value="update">更新</option>
            <option value="replace">覆盖更新</option>
            <option value="delete">删除</option>
            <option value="import">导入</option>
            <option value="ask">提问</option>
            <option value="reset_password">重置密码</option>
            <option value="enable">启用</option>
            <option value="disable">禁用</option>
          </select>
          <select value={targetType} onChange={(e) => { setTargetType(e.target.value); setPage(1) }} className="glass-input px-3 py-2 text-sm">
            <option value="">全部对象</option>
            <option value="user">用户</option>
            <option value="group">团队</option>
            <option value="user_group">团队成员</option>
            <option value="group_permissions">团队权限</option>
            <option value="product">产品</option>
            <option value="product_qa">产品 QA</option>
            <option value="product_media">产品素材</option>
            <option value="customer_service">智能客服</option>
            <option value="system_config">系统配置</option>
          </select>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} className="glass-input px-3 py-2 text-sm">
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="glass-input px-3 py-2 text-sm"
            title="开始日期"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="glass-input px-3 py-2 text-sm"
            title="结束日期"
          />
        </div>
        <div className="flex gap-2 mt-3">
          <button onClick={handleSearch} className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm">
            查询
          </button>
          <button onClick={resetFilters} className="px-4 py-2 rounded-lg bg-gray-100 text-gray-700 text-sm">
            重置
          </button>
        </div>
      </div>

      <div className="glass rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-black/5">
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">时间</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-apple-gray-dark">账号</th>
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
                <td className="px-4 py-3 text-sm text-apple-text">{log.operator_display_name || log.operator_name}</td>
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
                    {log.status === 'success' ? '成功' : '失败'}
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
            暂无操作记录
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mt-4 text-sm text-apple-gray-medium">
        <span>第 {page} / {totalPages} 页</span>
        <div className="flex gap-2">
          <button
            onClick={() => changePage(page - 1)}
            disabled={page <= 1 || loading}
            className="px-3 py-1.5 rounded-lg bg-gray-100 disabled:opacity-50"
          >
            上一页
          </button>
          <button
            onClick={() => changePage(page + 1)}
            disabled={page >= totalPages || loading}
            className="px-3 py-1.5 rounded-lg bg-gray-100 disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[80vh] overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h3 className="font-semibold text-apple-text">操作详情</h3>
              <button onClick={() => setSelected(null)} className="text-2xl leading-none text-apple-gray-medium">×</button>
            </div>
            <div className="p-5 overflow-y-auto max-h-[calc(80vh-4rem)]">
              <div className="grid grid-cols-2 gap-3 text-sm mb-4">
                <div><span className="text-apple-gray-medium">动作：</span>{selected.action_name}</div>
                <div><span className="text-apple-gray-medium">对象：</span>{selected.target_name}</div>
                <div><span className="text-apple-gray-medium">账号：</span>{selected.operator_display_name || selected.operator_name}</div>
                <div><span className="text-apple-gray-medium">时间：</span>{new Date(selected.created_at).toLocaleString('zh-CN')}</div>
                <div><span className="text-apple-gray-medium">IP：</span>{selected.ip_address || '-'}</div>
                <div><span className="text-apple-gray-medium">状态：</span>{selected.status}</div>
                <div><span className="text-apple-gray-medium">恢复：</span>{selected.can_restore ? '可恢复' : selected.restored_at ? '已恢复' : '不可恢复'}</div>
              </div>
              {selected.can_restore && (
                <button
                  onClick={() => restoreSnapshot(selected)}
                  className="mb-4 px-4 py-2 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700"
                >
                  恢复到本次操作之前
                </button>
              )}
              <pre className="bg-gray-50 rounded-lg p-3 text-xs overflow-auto">
{JSON.stringify({
  target_id: selected.target_id,
  snapshot_id: selected.snapshot_id,
  restored_at: selected.restored_at,
  user_agent: selected.user_agent,
  error_message: selected.error_message,
  request_data: selected.request_data,
  response_data: selected.response_data,
}, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
