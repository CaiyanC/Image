import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { User } from '../types'
import { useAuthStore } from '../store/authStore'

interface GroupOption {
  id: string
  group_name: string
}

export default function AdminUsers() {
  const currentUser = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<GroupOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm, setEditForm] = useState({ is_active: true })
  const [showAddForm, setShowAddForm] = useState(false)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [newUser, setNewUser] = useState({
    username: '',
    email: '',
    password: '',
    account_type: 'normal',
    group_id: '',
    group_role: 'member',
  })

  useEffect(() => {
    loadUsers()
    loadGroups()
  }, [])

  async function loadUsers() {
    try {
      const data = (await api.users.list()) as User[]
      setUsers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadGroups() {
    try {
      const data = await api.groups.list()
      setGroups(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '团队加载失败')
    }
  }

  function handleEdit(user: User) {
    setEditingUser(user)
    setEditForm({ is_active: user.is_active })
  }

  async function handleSave(userId: string) {
    try {
      const updated = (await api.users.update(userId, editForm)) as User
      setUsers((prev) => prev.map((u) => (u.id === userId ? updated : u)))
      setEditingUser(null)
      setMessage('用户状态已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新失败')
    }
  }

  async function handleDelete(user: User) {
    if (!confirm(`确认删除用户 ${user.username}？`)) return
    try {
      await api.users.delete(user.id)
      setUsers((prev) => prev.filter((u) => u.id !== user.id))
      setMessage('用户已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  async function handleAddUser() {
    if (!newUser.username || !newUser.password) {
      setError('请填写用户名和密码')
      return
    }
    if (newUser.password.length < 6) {
      setError('密码至少 6 位')
      return
    }
    setError('')
    setMessage('')
    try {
      const payload: {
        username: string
        email?: string
        password: string
        group_id?: string
        group_role?: string
      } = { username: newUser.username, password: newUser.password }
      if (newUser.email.trim()) payload.email = newUser.email.trim()

      const managementGroup = groups.find((g) => g.group_name === '管理层')
      const selectedGroupId =
        newUser.account_type === 'admin' ? managementGroup?.id : newUser.group_id
      if (selectedGroupId) {
        payload.group_id = selectedGroupId
        payload.group_role = newUser.account_type === 'admin' ? 'admin' : newUser.group_role
      }

      await api.users.create(payload)
      setShowAddForm(false)
      setNewUser({
        username: '',
        email: '',
        password: '',
        account_type: 'normal',
        group_id: '',
        group_role: 'member',
      })
      setMessage(newUser.account_type === 'admin' ? '管理员创建成功' : '用户创建成功')
      loadUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    }
  }

  async function handleResetPassword() {
    if (!resetTarget) return
    if (resetPassword.length < 6) {
      setError('新密码至少 6 位')
      return
    }
    try {
      await api.users.resetPassword(resetTarget.id, resetPassword)
      setResetTarget(null)
      setResetPassword('')
      setMessage(`已重置 ${resetTarget.username} 的密码`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '重置密码失败')
      loadUsers()
    }
  }

  if (loading) {
    return (
      <div className="p-4 max-w-6xl mx-auto flex items-center justify-center py-20 animate-pulse-soft text-apple-gray-medium">
        加载中...
      </div>
    )
  }

  return (
    <div className="p-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text tracking-tight">用户管理</h1>
        <button onClick={() => setShowAddForm(!showAddForm)} className="btn-primary text-sm">
          {showAddForm ? '取消' : '+ 新增用户'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-sm mb-4 animate-fade-in">
          {error}
          <button onClick={() => setError('')} className="float-right font-bold">&times;</button>
        </div>
      )}
      {message && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-xl text-sm mb-4 animate-fade-in">
          {message}
          <button onClick={() => setMessage('')} className="float-right font-bold">&times;</button>
        </div>
      )}

      {showAddForm && (
        <div className="glass p-4 mb-4 animate-slide-up rounded-xl">
          <h3 className="text-sm font-semibold text-apple-text mb-3">新建用户</h3>
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
            <input
              value={newUser.username}
              onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
              placeholder="用户名"
              className="glass-input px-3 py-2 text-sm"
            />
            <input
              value={newUser.email}
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
              placeholder="邮箱（选填）"
              type="email"
              className="glass-input px-3 py-2 text-sm"
            />
            <input
              value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
              placeholder="密码（至少 6 位）"
              type="password"
              className="glass-input px-3 py-2 text-sm"
            />
            <select
              value={newUser.account_type}
              onChange={(e) => {
                const accountType = e.target.value
                setNewUser({
                  ...newUser,
                  account_type: accountType,
                  group_id: accountType === 'admin' ? '' : newUser.group_id,
                  group_role: accountType === 'admin' ? 'admin' : newUser.group_role,
                })
              }}
              className="glass-input px-3 py-2 text-sm"
            >
              <option value="normal">普通用户</option>
              <option value="admin">管理员</option>
            </select>
            <select
              value={newUser.group_id}
              onChange={(e) => setNewUser({ ...newUser, group_id: e.target.value })}
              className="glass-input px-3 py-2 text-sm"
              disabled={newUser.account_type === 'admin'}
            >
              <option value="">
                {newUser.account_type === 'admin' ? '自动加入管理层' : '暂不分配团队'}
              </option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.group_name}
                </option>
              ))}
            </select>
            <select
              value={newUser.group_role}
              onChange={(e) => setNewUser({ ...newUser, group_role: e.target.value })}
              className="glass-input px-3 py-2 text-sm"
              disabled={newUser.account_type === 'admin' || !newUser.group_id}
            >
              <option value="member">普通成员</option>
              <option value="admin">组管理员</option>
            </select>
          </div>
          <button onClick={handleAddUser} className="btn-primary mt-3 py-2 text-sm">
            确认创建
          </button>
        </div>
      )}

      {resetTarget && (
        <div className="glass p-4 mb-4 rounded-xl animate-slide-up">
          <h3 className="text-sm font-semibold text-apple-text mb-3">
            重置 {resetTarget.username} 的密码
          </h3>
          <div className="flex flex-col md:flex-row gap-3">
            <input
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="输入新临时密码（至少 6 位）"
              type="password"
              className="glass-input px-3 py-2 text-sm md:w-80"
            />
            <button onClick={handleResetPassword} className="btn-primary py-2 text-sm">
              确认重置
            </button>
            <button
              onClick={() => {
                setResetTarget(null)
                setResetPassword('')
              }}
              className="text-sm text-apple-gray-dark hover:text-apple-text"
            >
              取消
            </button>
          </div>
        </div>
      )}

      <div className="glass rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-black/5">
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">用户名</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">邮箱</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">用户类型</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">所属团队</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">状态</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-apple-gray-dark">注册时间</th>
              <th className="text-right px-6 py-3 text-xs font-medium text-apple-gray-dark">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-black/5">
            {users.map((user) => (
              <tr key={user.id} className="hover:bg-black/[0.01] transition-colors">
                <td className="px-6 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-apple-blue/10 flex items-center justify-center text-apple-blue text-xs font-semibold">
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-apple-text">{user.username}</span>
                  </div>
                </td>
                <td className="px-6 py-3.5 text-sm text-apple-gray-dark">{user.email || '-'}</td>
                <td className="px-6 py-3.5">
                  <span className="text-xs px-2 py-1 rounded-full font-medium bg-green-100 text-green-700">
                    {user.user_type || 'human'}
                  </span>
                </td>
                <td className="px-6 py-3.5">
                  <div className="flex flex-wrap gap-1">
                    {user.groups?.length ? (
                      user.groups.map((g) => (
                        <span
                          key={g.group_id}
                          className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium"
                        >
                          {g.group_name} ({g.group_role === 'admin' ? '管理' : '成员'})
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-apple-gray-medium">-</span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-3.5">
                  {editingUser?.id === user.id ? (
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={editForm.is_active}
                        onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                        className="rounded"
                      />
                      <span className="text-xs text-apple-gray-dark">
                        {editForm.is_active ? '启用' : '禁用'}
                      </span>
                    </label>
                  ) : (
                    <span className={`text-xs ${user.is_active ? 'text-green-600' : 'text-red-500'}`}>
                      {user.is_active ? '启用' : '禁用'}
                    </span>
                  )}
                </td>
                <td className="px-6 py-3.5 text-xs text-apple-gray-medium">
                  {new Date(user.created_at).toLocaleDateString('zh-CN')}
                </td>
                <td className="px-6 py-3.5 text-right">
                  {editingUser?.id === user.id ? (
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => handleSave(user.id)} className="text-xs text-apple-blue hover:underline font-medium">
                        保存
                      </button>
                      <button onClick={() => setEditingUser(null)} className="text-xs text-apple-gray-medium hover:underline">
                        取消
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center justify-end gap-3">
                      <button onClick={() => handleEdit(user)} className="text-xs text-apple-blue hover:underline font-medium">
                        编辑
                      </button>
                      <button
                        onClick={() => {
                          setResetTarget(user)
                          setResetPassword('')
                          setError('')
                          setMessage('')
                        }}
                        className="text-xs text-amber-600 hover:underline font-medium"
                      >
                        重置密码
                      </button>
                      {currentUser?.id !== user.id && (
                        <button onClick={() => handleDelete(user)} className="text-xs text-red-500 hover:underline font-medium">
                          删除
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-apple-gray-medium mt-3 px-1">共 {users.length} 个用户</p>
    </div>
  )
}
