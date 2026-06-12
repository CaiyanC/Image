import { useEffect, useMemo, useState } from 'react'
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

interface Permission {
  id: string
  permission_key: string
  permission_name: string
  permission_type?: string
  description?: string
}

const PERMISSION_LABELS: Record<string, string> = {
  'history.view': '查看历史记录',
  'profile.view': '查看个人资料',
  'category.read': '查看产品品类',
  'ai.generate': 'AI 生图/生视频',
  'ai.customer_service': '智能客服对话',
  'ai.call': 'AI 基础调用',
  'product.read': '查看产品数据',
  'product.create': '新增产品数据',
  'product.edit': '修改产品数据',
  'product.delete': '删除产品数据',
  'product.review': '审核产品数据',
  'media.upload': '上传素材',
  'media.review': '审核素材',
  'media.download': '下载素材',
  'tag.edit': '编辑标签',
  'ai.authorize': 'AI 调用授权',
  'competitor.view': '查看竞品图',
  'new_product.view': '查看新品图',
  'export.approved': '导出审批',
}

const TYPE_LABELS: Record<string, string> = {
  api: 'AI 与接口能力',
  page: '页面访问',
  button: '操作按钮',
}

function labelForPermission(permission: Permission) {
  return PERMISSION_LABELS[permission.permission_key] || permission.permission_name || permission.permission_key
}

export default function AdminGroups() {
  const [groups, setGroups] = useState<Group[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [savingPermissions, setSavingPermissions] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ group_name: '', description: '' })
  const [editingGroup, setEditingGroup] = useState<Group | null>(null)
  const [editForm, setEditForm] = useState({ group_name: '', description: '' })
  const [expandedGroup, setExpandedGroup] = useState<Group | null>(null)
  const [members, setMembers] = useState<GroupMember[]>([])
  const [allUsers, setAllUsers] = useState<AllUser[]>([])
  const [showAddMember, setShowAddMember] = useState(false)
  const [addMemberForm, setAddMemberForm] = useState({ user_id: '', group_role: 'member' })

  const filteredGroups = useMemo(() => {
    if (!searchQuery.trim()) return groups
    const q = searchQuery.trim().toLowerCase()
    return groups.filter(
      (g) =>
        g.group_name.toLowerCase().includes(q) ||
        (g.description && g.description.toLowerCase().includes(q))
    )
  }, [groups, searchQuery])

  const groupedPermissions = useMemo(() => {
    return permissions.reduce<Record<string, Permission[]>>((result, permission) => {
      const type = permission.permission_type || 'other'
      result[type] = result[type] || []
      result[type].push(permission)
      return result
    }, {})
  }, [permissions])

  useEffect(() => {
    loadInitialData()
  }, [])

  async function loadInitialData() {
    try {
      const [groupData, permissionData] = await Promise.all([
        api.groups.list(),
        api.groups.permissions(),
      ])
      setGroups(groupData)
      setPermissions(permissionData)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载团队权限失败')
    } finally {
      setLoading(false)
    }
  }

  async function refreshMembers(groupId: string) {
    const data = await api.groups.members(groupId)
    setMembers(data)
  }

  async function refreshPermissions(groupId: string) {
    const data = await api.groups.groupPermissions(groupId)
    setSelectedPermissions(data.map((item: Permission) => item.permission_key))
  }

  async function handleCreate() {
    if (!createForm.group_name.trim()) return
    try {
      await api.groups.create(createForm)
      setShowCreate(false)
      setCreateForm({ group_name: '', description: '' })
      setMessage('团队创建成功')
      loadInitialData()
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
      loadInitialData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新团队失败')
    }
  }

  async function handleDelete(groupId: string) {
    if (!confirm('确定删除该团队吗？')) return
    try {
      await api.groups.delete(groupId)
      setMessage('团队已删除')
      setExpandedGroup(null)
      loadInitialData()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除团队失败')
    }
  }

  async function toggleExpand(group: Group) {
    if (expandedGroup?.id === group.id) {
      setExpandedGroup(null)
      setMembers([])
      setSelectedPermissions([])
      return
    }
    setExpandedGroup(group)
    setShowAddMember(false)
    try {
      await Promise.all([refreshMembers(group.id), refreshPermissions(group.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载团队详情失败')
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
      await api.groups.addUser(expandedGroup.id, addMemberForm)
      setAddMemberForm({ user_id: '', group_role: 'member' })
      setShowAddMember(false)
      await refreshMembers(expandedGroup.id)
      setMessage('成员已添加')
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加成员失败')
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!expandedGroup) return
    try {
      await api.groups.removeUser(expandedGroup.id, userId)
      await refreshMembers(expandedGroup.id)
      setMessage('成员已移除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除成员失败')
    }
  }

  async function handleChangeRole(userId: string, newRole: string) {
    if (!expandedGroup) return
    try {
      await api.groups.updateRole(expandedGroup.id, userId, { group_role: newRole })
      await refreshMembers(expandedGroup.id)
      setMessage('成员角色已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新成员角色失败')
    }
  }

  function togglePermission(permissionKey: string) {
    setSelectedPermissions((current) => {
      if (current.includes(permissionKey)) {
        return current.filter((item) => item !== permissionKey)
      }
      return [...current, permissionKey]
    })
  }

  async function handleSavePermissions() {
    if (!expandedGroup) return
    setSavingPermissions(true)
    try {
      await api.groups.updatePermissions(expandedGroup.id, selectedPermissions)
      await refreshPermissions(expandedGroup.id)
      setMessage(`${expandedGroup.group_name} 的权限已更新`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存权限失败')
    } finally {
      setSavingPermissions(false)
    }
  }

  return (
    <div className="p-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">团队与权限</h1>
          <p className="text-sm text-apple-gray-medium mt-1">超级管理员可以按部门统一分配生图、智能客服、产品数据等权限。</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors"
        >
          新建团队
        </button>
      </div>

      <div className="mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索团队名称或描述..."
          className="w-full px-4 py-2.5 bg-white/60 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all"
        />
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
          <div className="grid md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">团队名称 *</label>
              <input
                type="text"
                value={createForm.group_name}
                onChange={(event) => setCreateForm({ ...createForm, group_name: event.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                placeholder="例如：市场部"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">描述</label>
              <input
                value={createForm.description}
                onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                placeholder="团队职责说明"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={!createForm.group_name.trim()} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50">
              创建
            </button>
            <button onClick={() => setShowCreate(false)} className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors">
              取消
            </button>
          </div>
        </div>
      )}

      {editingGroup && (
        <div className="glass rounded-xl p-6 mb-6 animate-fade-in">
          <h2 className="text-lg font-semibold text-apple-text mb-4">编辑团队</h2>
          <div className="grid md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">团队名称 *</label>
              <input
                type="text"
                value={editForm.group_name}
                onChange={(event) => setEditForm({ ...editForm, group_name: event.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-apple-gray-dark block mb-1">描述</label>
              <input
                value={editForm.description}
                onChange={(event) => setEditForm({ ...editForm, description: event.target.value })}
                className="w-full px-3 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleUpdate} disabled={!editForm.group_name.trim()} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50">
              保存
            </button>
            <button onClick={() => setEditingGroup(null)} className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors">
              取消
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20 animate-pulse-soft text-apple-gray-medium">加载中...</div>
      ) : filteredGroups.length === 0 ? (
        <div className="glass p-12 text-center rounded-xl">
          <p className="text-apple-gray-medium">{searchQuery ? '没有匹配的团队' : '暂无团队'}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredGroups.map((group) => (
            <div key={group.id} className="glass rounded-xl overflow-hidden">
              <div className="p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-sm shrink-0">
                      {group.group_name.charAt(0)}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-apple-text truncate">{group.group_name}</h3>
                        {group.is_preset && <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded-full font-medium">预置</span>}
                      </div>
                      <p className="text-xs text-apple-gray-medium mt-0.5 truncate">{group.description || '暂无描述'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button onClick={() => toggleExpand(group)} className="text-xs px-3 py-1.5 bg-black/[0.04] hover:bg-black/[0.08] rounded-lg text-apple-gray-dark transition-colors">
                      {expandedGroup?.id === group.id ? '收起' : '管理权限'}
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
                      <button onClick={() => handleDelete(group.id)} className="text-xs px-3 py-1.5 bg-red-50 hover:bg-red-100 rounded-lg text-red-500 transition-colors">
                        删除
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {expandedGroup?.id === group.id && (
                <div className="border-t border-black/5 p-4 bg-black/[0.01] animate-fade-in">
                  <div className="grid lg:grid-cols-[360px_1fr] gap-4">
                    <section className="bg-white/45 rounded-xl p-4">
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
                        <div className="mb-4 p-3 bg-white/70 rounded-lg space-y-3">
                          <select
                            value={addMemberForm.user_id}
                            onChange={(event) => setAddMemberForm({ ...addMemberForm, user_id: event.target.value })}
                            className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                          >
                            <option value="">选择用户</option>
                            {allUsers.map((user) => (
                              <option key={user.id} value={user.id}>{user.username}</option>
                            ))}
                          </select>
                          <div className="flex gap-2">
                            <select
                              value={addMemberForm.group_role}
                              onChange={(event) => setAddMemberForm({ ...addMemberForm, group_role: event.target.value })}
                              className="flex-1 px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                            >
                              <option value="member">普通成员</option>
                              <option value="admin">组管理员</option>
                            </select>
                            <button onClick={handleAddMember} disabled={!addMemberForm.user_id} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50">
                              添加
                            </button>
                            <button onClick={() => setShowAddMember(false)} className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors">
                              取消
                            </button>
                          </div>
                        </div>
                      )}

                      {members.length === 0 ? (
                        <p className="text-xs text-apple-gray-medium py-4 text-center">暂无成员</p>
                      ) : (
                        <div className="space-y-2">
                          {members.map((member) => (
                            <div key={member.user_id} className="flex items-center justify-between gap-2 py-2 px-3 bg-white/60 rounded-lg">
                              <div className="min-w-0">
                                <p className="text-sm text-apple-text font-medium truncate">{member.username}</p>
                                <p className="text-xs text-apple-gray-medium truncate">{member.email}</p>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <select value={member.group_role} onChange={(event) => handleChangeRole(member.user_id, event.target.value)} className="text-xs px-2 py-1 bg-white border border-gray-200 rounded-md focus:outline-none">
                                  <option value="member">普通成员</option>
                                  <option value="admin">组管理员</option>
                                </select>
                                <button onClick={() => handleRemoveMember(member.user_id)} className="text-xs text-red-400 hover:text-red-600 transition-colors px-2">
                                  移除
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </section>

                    <section className="bg-white/45 rounded-xl p-4">
                      <div className="flex items-center justify-between gap-3 mb-4">
                        <div>
                          <h4 className="text-sm font-semibold text-apple-text">部门权限</h4>
                          <p className="text-xs text-apple-gray-medium mt-0.5">勾选后，该团队下所有成员都会获得对应能力。</p>
                        </div>
                        <button onClick={handleSavePermissions} disabled={savingPermissions} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50">
                          {savingPermissions ? '保存中...' : '保存权限'}
                        </button>
                      </div>

                      <div className="space-y-4">
                        {Object.entries(groupedPermissions).map(([type, items]) => (
                          <div key={type}>
                            <h5 className="text-xs font-semibold text-apple-gray-dark mb-2">{TYPE_LABELS[type] || '其他权限'}</h5>
                            <div className="grid md:grid-cols-2 gap-2">
                              {items.map((permission) => (
                                <label key={permission.permission_key} className="flex items-start gap-3 p-3 bg-white/65 border border-black/5 rounded-lg cursor-pointer hover:bg-white transition-colors">
                                  <input
                                    type="checkbox"
                                    checked={selectedPermissions.includes(permission.permission_key)}
                                    onChange={() => togglePermission(permission.permission_key)}
                                    className="mt-1"
                                  />
                                  <span>
                                    <span className="block text-sm font-medium text-apple-text">{labelForPermission(permission)}</span>
                                    <span className="block text-[11px] text-apple-gray-medium mt-0.5">{permission.permission_key}</span>
                                  </span>
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
