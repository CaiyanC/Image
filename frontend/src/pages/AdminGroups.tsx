import { useState, useEffect } from 'react'
import { api } from '../services/api'

interface Group {
  id: string
  group_name: string
  description?: string
  is_preset: boolean
  created_at: string
}

interface GroupMember {
  user_id: string
  username: string
  email: string
  group_role: string
}

interface AllUser {
  id: string
  username: string
  email: string
}

export default function AdminGroups() {
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ group_name: '', description: '' })
  const [editingGroup, setEditingGroup] = useState<Group | null>(null)
  const [editForm, setEditForm] = useState({ group_name: '', description: '' })
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const [members, setMembers] = useState<GroupMember[]>([])
  const [allUsers, setAllUsers] = useState<AllUser[]>([])
  const [showAddMember, setShowAddMember] = useState(false)
  const [addMemberForm, setAddMemberForm] = useState({ user_id: '', group_role: 'member' })

  useEffect(() => {
    loadGroups()
  }, [])

  async function loadGroups() {
    try {
      const data = await api.groups.list()
      setGroups(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '团队加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function refreshMembers(groupId: string) {
    const data = await api.groups.members(groupId)
    setMembers(data)
  }

  async function handleCreate() {
    if (!createForm.group_name.trim()) return
    try {
      await api.groups.create(createForm)
      setShowCreate(false)
      setCreateForm({ group_name: '', description: '' })
      setMessage('团队创建成功')
      loadGroups()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建团队失败')
    }
  }

  async function handleUpdate() {
    if (!editingGroup || !editForm.group_name.trim()) return
    try {
      await api.groups.update(editingGroup.id, editForm)
      setEditingGroup(null)
      setMessage('团队已更新')
      loadGroups()
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新团队失败')
    }
  }

  async function handleDelete(groupId: string) {
    if (!confirm('确定删除该团队？')) return
    try {
      await api.groups.delete(groupId)
      setMessage('团队已删除')
      loadGroups()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除团队失败')
    }
  }

  async function toggleExpand(groupId: string) {
    if (expandedGroup === groupId) {
      setExpandedGroup(null)
      setMembers([])
      return
    }
    setExpandedGroup(groupId)
    try {
      await refreshMembers(groupId)
    } catch (err) {
      setError(err instanceof Error ? err.message : '成员加载失败')
    }
  }

  async function loadAllUsers() {
    try {
      const data = await api.users.list() as AllUser[]
      setAllUsers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户加载失败')
    }
  }

  async function handleAddMember() {
    if (!addMemberForm.user_id || !expandedGroup) return
    try {
      await api.groups.addUser(expandedGroup, addMemberForm)
      setAddMemberForm({ user_id: '', group_role: 'member' })
      setShowAddMember(false)
      await refreshMembers(expandedGroup)
      setMessage('成员已添加')
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加成员失败')
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!expandedGroup) return
    try {
      await api.groups.removeUser(expandedGroup, userId)
      await refreshMembers(expandedGroup)
      setMessage('成员已移除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除成员失败')
    }
  }

  async function handleChangeRole(userId: string, newRole: string) {
    if (!expandedGroup) return
    try {
      await api.groups.updateRole(expandedGroup, userId, { group_role: newRole })
      await refreshMembers(expandedGroup)
      setMessage('成员角色已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新成员角色失败')
    }
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text tracking-tight">团队管理</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors"
        >
          新建团队
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

      {showCreate && (
        <div className="glass rounded-xl p-6 mb-6 animate-fade-in">
          <h2 className="text-lg font-semibold text-apple-text mb-4">新建团队</h2>
          <div className="space-y-4 mb-4">
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">团队名称 *</label>
              <input
                type="text"
                value={createForm.group_name}
                onChange={(e) => setCreateForm({ ...createForm, group_name: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                placeholder="例如：产品团队"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">描述</label>
              <textarea
                value={createForm.description}
                onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                rows={2}
                placeholder="团队职责说明..."
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={!createForm.group_name.trim()}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50"
            >
              创建
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {editingGroup && (
        <div className="glass rounded-xl p-6 mb-6 animate-fade-in">
          <h2 className="text-lg font-semibold text-apple-text mb-4">编辑团队</h2>
          <div className="space-y-4 mb-4">
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">团队名称 *</label>
              <input
                type="text"
                value={editForm.group_name}
                onChange={(e) => setEditForm({ ...editForm, group_name: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">描述</label>
              <textarea
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                rows={2}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleUpdate}
              disabled={!editForm.group_name.trim()}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50"
            >
              保存
            </button>
            <button
              onClick={() => setEditingGroup(null)}
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20 animate-pulse-soft text-apple-gray-medium">加载中...</div>
      ) : groups.length === 0 ? (
        <div className="glass p-12 text-center rounded-xl">
          <p className="text-apple-gray-medium">暂无团队</p>
          <p className="text-sm text-apple-gray-medium/60 mt-1">点击右上角"新建团队"开始创建</p>
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((group) => (
            <div key={group.id} className="glass rounded-xl overflow-hidden">
              <div className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-sm">
                      {group.group_name.charAt(0)}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-apple-text">{group.group_name}</h3>
                        {group.is_preset && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded-full font-medium">预置</span>
                        )}
                      </div>
                      <p className="text-xs text-apple-gray-medium mt-0.5">{group.description || '暂无描述'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleExpand(group.id)}
                      className="text-xs px-3 py-1.5 bg-black/[0.04] hover:bg-black/[0.08] rounded-lg text-apple-gray-dark transition-colors"
                    >
                      {expandedGroup === group.id ? '收起成员' : '管理成员'}
                    </button>
                    <button
                      onClick={() => {
                        setEditingGroup(group)
                        setEditForm({ group_name: group.group_name, description: group.description || '' })
                      }}
                      className="text-xs px-3 py-1.5 bg-black/[0.04] hover:bg-black/[0.08] rounded-lg text-apple-gray-dark transition-colors"
                    >
                      编辑
                    </button>
                    {!group.is_preset && (
                      <button
                        onClick={() => handleDelete(group.id)}
                        className="text-xs px-3 py-1.5 bg-red-50 hover:bg-red-100 rounded-lg text-red-500 transition-colors"
                      >
                        删除
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {expandedGroup === group.id && (
                <div className="border-t border-black/5 p-4 bg-black/[0.01] animate-fade-in">
                  <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-semibold text-apple-text">团队成员</h4>
                    <button
                      onClick={() => {
                        setShowAddMember(true)
                        loadAllUsers()
                      }}
                      className="text-xs px-3 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
                    >
                      添加成员
                    </button>
                  </div>

                  {showAddMember && (
                    <div className="mb-4 p-3 bg-white/50 rounded-lg">
                      <div className="flex items-end gap-3">
                        <div className="flex-1">
                          <label className="text-xs font-medium text-apple-gray-dark block mb-1">选择用户</label>
                          <select
                            value={addMemberForm.user_id}
                            onChange={(e) => setAddMemberForm({ ...addMemberForm, user_id: e.target.value })}
                            className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                          >
                            <option value="">-- 选择用户 --</option>
                            {allUsers.map((u) => (
                              <option key={u.id} value={u.id}>{u.username}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="text-xs font-medium text-apple-gray-dark block mb-1">角色</label>
                          <select
                            value={addMemberForm.group_role}
                            onChange={(e) => setAddMemberForm({ ...addMemberForm, group_role: e.target.value })}
                            className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                          >
                            <option value="member">普通成员</option>
                            <option value="admin">组管理员</option>
                          </select>
                        </div>
                        <button
                          onClick={handleAddMember}
                          disabled={!addMemberForm.user_id}
                          className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50"
                        >
                          添加
                        </button>
                        <button
                          onClick={() => setShowAddMember(false)}
                          className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors"
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  )}

                  {members.length === 0 ? (
                    <p className="text-xs text-apple-gray-medium py-4 text-center">暂无成员</p>
                  ) : (
                    <div className="space-y-1">
                      {members.map((m) => (
                        <div key={m.user_id} className="flex items-center justify-between py-2 px-3 bg-white/40 rounded-lg">
                          <div>
                            <span className="text-sm text-apple-text font-medium">{m.username}</span>
                            <span className="text-xs text-apple-gray-medium ml-2">{m.email}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <select
                              value={m.group_role}
                              onChange={(e) => handleChangeRole(m.user_id, e.target.value)}
                              className="text-xs px-2 py-1 bg-white border border-gray-200 rounded-md focus:outline-none"
                            >
                              <option value="member">普通成员</option>
                              <option value="admin">组管理员</option>
                            </select>
                            <button
                              onClick={() => handleRemoveMember(m.user_id)}
                              className="text-xs text-red-400 hover:text-red-600 transition-colors px-2"
                            >
                              移除
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
