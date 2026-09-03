import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api } from '../services/api'
import type { User } from '../types'
import { useAuthStore } from '../store/authStore'

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

interface Permission {
  id: string
  permission_key: string
  permission_name: string
  permission_type?: string
  description?: string
}

type Selection =
  | { kind: 'user'; id: string }
  | { kind: 'group'; id: string }
  | null

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
  'product.qa.manage': '管理产品 QA',
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

function permissionLabelByKey(permissionKey: string) {
  return PERMISSION_LABELS[permissionKey] || permissionKey
}

export default function AdminAccessControl() {
  const currentUser = useAuthStore((state) => state.user)
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [members, setMembers] = useState<GroupMember[]>([])
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([])
  const [groupDetailsLoading, setGroupDetailsLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [showCreateUser, setShowCreateUser] = useState(false)
  const [showCreateGroup, setShowCreateGroup] = useState(false)
  const [newUser, setNewUser] = useState({
    username: '',
    email: '',
    password: '',
    account_type: 'normal',
    group_id: '',
    group_role: 'member',
  })
  const [newGroup, setNewGroup] = useState({ group_name: '', description: '' })
  const [editingGroup, setEditingGroup] = useState(false)
  const [groupForm, setGroupForm] = useState({ group_name: '', description: '' })
  const [editUserForm, setEditUserForm] = useState({
    username: '',
    display_name: '',
    email: '',
    is_active: true,
  })
  const [assignForm, setAssignForm] = useState({ group_id: '', group_role: 'member' })
  const [addMemberForm, setAddMemberForm] = useState({ user_id: '', group_role: 'member' })
  const [resetPassword, setResetPassword] = useState('')
  const [resetOpen, setResetOpen] = useState(false)

  const selectedUser = selection?.kind === 'user' ? users.find((user) => user.id === selection.id) || null : null
  const selectedGroup = selection?.kind === 'group' ? groups.find((group) => group.id === selection.id) || null : null

  const filteredUsers = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return users
    return users.filter((user) => {
      const groupText = (user.groups || []).map((group) => group.group_name).join(' ')
      return [user.username, user.display_name, user.email, groupText].filter(Boolean).join(' ').toLowerCase().includes(query)
    })
  }, [searchQuery, users])

  const filteredGroups = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return groups
    return groups.filter((group) => [group.group_name, group.description].filter(Boolean).join(' ').toLowerCase().includes(query))
  }, [groups, searchQuery])

  const groupedPermissions = useMemo(() => permissions.reduce<Record<string, Permission[]>>((result, permission) => {
    const type = permission.permission_type || 'other'
    result[type] = result[type] || []
    result[type].push(permission)
    return result
  }, {}), [permissions])

  const selectedUserGroups = selectedUser?.groups || []
  const availableUserGroups = groups.filter((group) => !selectedUserGroups.some((item) => item.group_id === group.id))
  const availableMembers = users.filter((user) => !members.some((member) => member.user_id === user.id))
  const unassignedUsers = users.filter((user) => !user.groups?.length).length

  useEffect(() => {
    void loadInitialData()
  }, [])

  useEffect(() => {
    if (!selectedUser) return
    setEditUserForm({
      username: selectedUser.username || '',
      display_name: selectedUser.display_name || '',
      email: selectedUser.email || '',
      is_active: selectedUser.is_active,
    })
    setAssignForm({ group_id: availableUserGroups[0]?.id || '', group_role: 'member' })
    setResetOpen(false)
    setResetPassword('')
  }, [selectedUser, availableUserGroups])

  useEffect(() => {
    if (!selectedGroup) return
    setGroupForm({ group_name: selectedGroup.group_name, description: selectedGroup.description || '' })
  }, [selectedGroup])

  useEffect(() => {
    if (!selectedGroup) {
      setMembers([])
      setSelectedPermissions([])
      setGroupDetailsLoading(false)
      return
    }
    let active = true
    setMembers([])
    setSelectedPermissions([])
    setGroupDetailsLoading(true)
    Promise.all([api.groups.members(selectedGroup.id), api.groups.groupPermissions(selectedGroup.id)])
      .then(([nextMembers, nextPermissions]) => {
        if (!active) return
        setMembers(nextMembers as GroupMember[])
        setSelectedPermissions((nextPermissions as Permission[]).map((item) => item.permission_key))
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        if (active) setGroupDetailsLoading(false)
      })
    return () => { active = false }
  }, [selectedGroup])

  async function loadInitialData() {
    setLoading(true)
    try {
      const [nextUsers, nextGroups, nextPermissions] = await Promise.all([
        api.users.list(0, 200) as Promise<User[]>,
        api.groups.list() as Promise<Group[]>,
        api.groups.permissions() as Promise<Permission[]>,
      ])
      setUsers(nextUsers)
      setGroups(nextGroups)
      setPermissions(nextPermissions)
      setSelection((current) => current && (current.kind === 'user' ? nextUsers.some((user) => user.id === current.id) : nextGroups.some((group) => group.id === current.id))
        ? current
        : nextGroups[0] ? { kind: 'group', id: nextGroups[0].id } : nextUsers[0] ? { kind: 'user', id: nextUsers[0].id } : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载组织权限失败')
    } finally {
      setLoading(false)
    }
  }

  async function reloadUsers() {
    const nextUsers = await api.users.list(0, 200) as User[]
    setUsers(nextUsers)
    return nextUsers
  }

  async function reloadGroups() {
    const nextGroups = await api.groups.list() as Group[]
    setGroups(nextGroups)
    return nextGroups
  }

  async function refreshGroupDetails(groupId: string) {
    const [nextMembers, nextPermissions] = await Promise.all([
      api.groups.members(groupId),
      api.groups.groupPermissions(groupId),
    ])
    setMembers(nextMembers as GroupMember[])
    setSelectedPermissions((nextPermissions as Permission[]).map((item) => item.permission_key))
  }

  function clearNotices() {
    setError('')
    setMessage('')
  }

  async function handleCreateUser(event: React.FormEvent) {
    event.preventDefault()
    if (!newUser.username.trim() || !newUser.password) {
      setError('请填写用户名和密码')
      return
    }
    if (newUser.password.length < 8) {
      setError('密码至少 8 位')
      return
    }
    clearNotices()
    try {
      const managementGroup = groups.find((group) => group.group_name === '总经办')
      const groupId = newUser.account_type === 'admin' ? managementGroup?.id : newUser.group_id
      if (newUser.account_type === 'admin' && !groupId) {
        throw new Error('系统中没有找到总经办部门，无法创建管理员')
      }
      const payload: { username: string; email?: string; password: string; group_id?: string; group_role?: string } = {
        username: newUser.username.trim(),
        password: newUser.password,
      }
      if (newUser.email.trim()) payload.email = newUser.email.trim()
      if (groupId) {
        payload.group_id = groupId
        payload.group_role = newUser.account_type === 'admin' ? 'admin' : newUser.group_role
      }
      const created = await api.users.create(payload) as User
      setShowCreateUser(false)
      setNewUser({ username: '', email: '', password: '', account_type: 'normal', group_id: '', group_role: 'member' })
      await reloadUsers()
      setSelection({ kind: 'user', id: created.id })
      setMessage('用户创建成功，可在右侧继续调整部门和账号状态')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建用户失败')
    }
  }

  async function handleCreateGroup(event: React.FormEvent) {
    event.preventDefault()
    if (!newGroup.group_name.trim()) return
    clearNotices()
    try {
      const created = await api.groups.create({ group_name: newGroup.group_name.trim(), description: newGroup.description.trim() }) as Group
      setShowCreateGroup(false)
      setNewGroup({ group_name: '', description: '' })
      await reloadGroups()
      setSelection({ kind: 'group', id: created.id })
      setMessage('部门创建成功，可在右侧直接配置权限和添加成员')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建部门失败')
    }
  }

  async function handleUpdateGroup(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedGroup || !groupForm.group_name.trim()) return
    clearNotices()
    try {
      await api.groups.update(selectedGroup.id, { group_name: groupForm.group_name.trim(), description: groupForm.description.trim() })
      await reloadGroups()
      setEditingGroup(false)
      setMessage('部门信息已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新部门失败')
    }
  }

  async function handleDeleteGroup() {
    if (!selectedGroup || !confirm(`确定删除部门“${selectedGroup.group_name}”吗？`)) return
    clearNotices()
    try {
      await api.groups.delete(selectedGroup.id)
      const nextGroups = await reloadGroups()
      setSelection(nextGroups[0] ? { kind: 'group', id: nextGroups[0].id } : users[0] ? { kind: 'user', id: users[0].id } : null)
      setMessage('部门已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除部门失败')
    }
  }

  async function handleSaveUser(event?: FormEvent) {
    event?.preventDefault()
    if (!selectedUser || !editUserForm.username.trim()) return
    clearNotices()
    try {
      await api.users.update(selectedUser.id, {
        username: editUserForm.username.trim(),
        display_name: editUserForm.display_name.trim() || null,
        email: editUserForm.email.trim() || null,
        is_active: editUserForm.is_active,
      })
      await reloadUsers()
      setMessage('用户信息已更新，权限变更会立即生效')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新用户失败')
    }
  }

  async function handleDeleteUser() {
    if (!selectedUser || currentUser?.id === selectedUser.id || !confirm(`确认删除用户“${selectedUser.username}”吗？`)) return
    clearNotices()
    try {
      await api.users.delete(selectedUser.id)
      const nextUsers = await reloadUsers()
      setSelection(nextUsers[0] ? { kind: 'user', id: nextUsers[0].id } : groups[0] ? { kind: 'group', id: groups[0].id } : null)
      setMessage('用户已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除用户失败')
    }
  }

  async function handleResetPassword(event?: FormEvent) {
    event?.preventDefault()
    if (!selectedUser || resetPassword.length < 8) {
      setError('新密码至少 8 位')
      return
    }
    clearNotices()
    try {
      await api.users.resetPassword(selectedUser.id, resetPassword)
      setResetOpen(false)
      setResetPassword('')
      setMessage(`已重置 ${selectedUser.username} 的密码`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '重置密码失败')
    }
  }

  async function handleAssignUser(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedUser || !assignForm.group_id) return
    clearNotices()
    try {
      await api.groups.addUser(assignForm.group_id, { user_id: selectedUser.id, group_role: assignForm.group_role })
      await reloadUsers()
      setMessage('部门归属已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '分配部门失败')
    }
  }

  async function handleRemoveUserGroup(groupId: string) {
    if (!selectedUser) return
    clearNotices()
    try {
      await api.groups.removeUser(groupId, selectedUser.id)
      await reloadUsers()
      setMessage('已移出该部门')
    } catch (err) {
      setError(err instanceof Error ? err.message : '移出部门失败')
    }
  }

  async function handleChangeUserGroupRole(groupId: string, groupRole: string) {
    if (!selectedUser) return
    clearNotices()
    try {
      await api.groups.updateRole(groupId, selectedUser.id, { group_role: groupRole })
      await reloadUsers()
      setMessage('用户在该部门中的角色已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新部门角色失败')
    }
  }

  async function handleAddMember(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedGroup || !addMemberForm.user_id) return
    clearNotices()
    try {
      await api.groups.addUser(selectedGroup.id, addMemberForm)
      setAddMemberForm({ user_id: '', group_role: 'member' })
      await Promise.all([reloadUsers(), refreshGroupDetails(selectedGroup.id)])
      setMessage('成员已添加')
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加成员失败')
    }
  }

  async function handleRemoveMember(userId: string) {
    if (!selectedGroup) return
    clearNotices()
    try {
      await api.groups.removeUser(selectedGroup.id, userId)
      await Promise.all([reloadUsers(), refreshGroupDetails(selectedGroup.id)])
      setMessage('成员已移除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '移除成员失败')
    }
  }

  async function handleChangeRole(userId: string, groupRole: string) {
    if (!selectedGroup) return
    clearNotices()
    try {
      await api.groups.updateRole(selectedGroup.id, userId, { group_role: groupRole })
      await Promise.all([reloadUsers(), refreshGroupDetails(selectedGroup.id)])
      setMessage('成员角色已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新成员角色失败')
    }
  }

  function togglePermission(permissionKey: string) {
    setSelectedPermissions((current) => current.includes(permissionKey)
      ? current.filter((item) => item !== permissionKey)
      : [...current, permissionKey])
  }

  async function handleSavePermissions() {
    if (!selectedGroup || groupDetailsLoading) return
    setSaving(true)
    clearNotices()
    try {
      await api.groups.updatePermissions(selectedGroup.id, selectedPermissions)
      await Promise.all([refreshGroupDetails(selectedGroup.id), reloadUsers()])
      setMessage(`${selectedGroup.group_name} 的权限已更新，成员登录后立即按新权限生效`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存部门权限失败')
    } finally {
      setSaving(false)
    }
  }

  function openCreateUser() {
    clearNotices()
    setShowCreateGroup(false)
    setShowCreateUser((current) => !current)
  }

  function openCreateGroup() {
    clearNotices()
    setShowCreateUser(false)
    setShowCreateGroup((current) => !current)
  }

  if (loading) {
    return <div className="mx-auto flex max-w-7xl items-center justify-center px-4 py-24 text-apple-gray-medium animate-pulse-soft">正在加载组织与权限...</div>
  }

  return (
    <main className="mx-auto max-w-7xl px-4 pb-12 pt-6 md:px-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.16em] text-teal-700">Administration / Access</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight text-apple-text">组织与权限</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-apple-gray-medium">用户归属、部门成员、部门权限和账号操作集中在这里设置。先选左侧的用户或部门，右侧直接完成配置。</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={openCreateUser} className="btn-primary px-4 py-2 text-sm">+ 新增用户</button>
          <button onClick={openCreateGroup} className="rounded-xl border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-bold text-teal-800 transition hover:bg-teal-100">+ 新建部门</button>
        </div>
      </header>

      <div className="mb-5 grid gap-3 sm:grid-cols-4">
        {[
          ['成员', users.length, '当前账号'],
          ['部门', groups.length, '组织范围'],
          ['未分配部门', unassignedUsers, '需要补充归属'],
          ['权限项', permissions.length, '可分配能力'],
        ].map(([label, value, hint]) => (
          <div key={label} className="glass rounded-2xl px-4 py-3">
            <div className="flex items-end justify-between gap-2"><span className="text-xs font-bold text-apple-gray-medium">{label}</span><span className="text-2xl font-black text-apple-text">{value}</span></div>
            <p className="mt-1 text-[11px] text-apple-gray-medium">{hint}</p>
          </div>
        ))}
      </div>

      {(error || message) && (
        <div className={`mb-5 rounded-2xl border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-600' : 'border-green-200 bg-green-50 text-green-700'}`}>
          {error || message}
          <button onClick={clearNotices} className="float-right font-bold">&times;</button>
        </div>
      )}

      {showCreateUser && (
        <form onSubmit={handleCreateUser} className="glass mb-5 rounded-2xl p-5">
          <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="text-lg font-black text-apple-text">新增用户</h2><p className="mt-1 text-xs text-apple-gray-medium">创建后仍可在同一页调整部门归属与账号状态。</p></div><button type="button" onClick={() => setShowCreateUser(false)} className="text-sm text-apple-gray-medium">关闭</button></div>
          <div className="grid gap-3 md:grid-cols-3">
            <input value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} placeholder="用户名 *" className="glass-input px-3 py-2 text-sm" />
            <input value={newUser.email} onChange={(event) => setNewUser({ ...newUser, email: event.target.value })} placeholder="邮箱（选填）" type="email" className="glass-input px-3 py-2 text-sm" />
            <input value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.target.value })} placeholder="初始密码（至少 8 位） *" type="password" className="glass-input px-3 py-2 text-sm" />
            <select value={newUser.account_type} onChange={(event) => setNewUser({ ...newUser, account_type: event.target.value, group_id: event.target.value === 'admin' ? '' : newUser.group_id, group_role: event.target.value === 'admin' ? 'admin' : newUser.group_role })} className="glass-input px-3 py-2 text-sm"><option value="normal">普通用户</option><option value="admin">管理员（加入总经办）</option></select>
            <select value={newUser.group_id} disabled={newUser.account_type === 'admin'} onChange={(event) => setNewUser({ ...newUser, group_id: event.target.value })} className="glass-input px-3 py-2 text-sm"><option value="">{newUser.account_type === 'admin' ? '自动加入总经办' : '暂不分配部门'}</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.group_name}</option>)}</select>
            <select value={newUser.group_role} disabled={newUser.account_type === 'admin' || !newUser.group_id} onChange={(event) => setNewUser({ ...newUser, group_role: event.target.value })} className="glass-input px-3 py-2 text-sm"><option value="member">普通成员</option><option value="admin">组管理员</option></select>
          </div>
          <button type="submit" className="btn-primary mt-4 px-4 py-2 text-sm">创建用户</button>
        </form>
      )}

      {showCreateGroup && (
        <form onSubmit={handleCreateGroup} className="glass mb-5 rounded-2xl p-5">
          <div className="mb-4 flex items-start justify-between gap-3"><div><h2 className="text-lg font-black text-apple-text">新建部门</h2><p className="mt-1 text-xs text-apple-gray-medium">创建后可在右侧立即分配权限和成员。</p></div><button type="button" onClick={() => setShowCreateGroup(false)} className="text-sm text-apple-gray-medium">关闭</button></div>
          <div className="grid gap-3 md:grid-cols-2"><input value={newGroup.group_name} onChange={(event) => setNewGroup({ ...newGroup, group_name: event.target.value })} placeholder="部门名称 *" className="glass-input px-3 py-2 text-sm" /><input value={newGroup.description} onChange={(event) => setNewGroup({ ...newGroup, description: event.target.value })} placeholder="部门职责说明（选填）" className="glass-input px-3 py-2 text-sm" /></div>
          <button type="submit" className="btn-primary mt-4 px-4 py-2 text-sm">创建部门</button>
        </form>
      )}

      <div className="grid gap-5 xl:grid-cols-[310px_minmax(0,1fr)]">
        <aside className="glass rounded-3xl p-3">
          <div className="mb-3 px-2"><input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索成员或部门..." className="glass-input w-full px-3 py-2 text-sm" /></div>
          <div className="mb-2 flex items-center justify-between px-3"><span className="text-xs font-black uppercase tracking-[0.12em] text-apple-gray-medium">成员</span><span className="text-xs font-bold text-apple-gray-medium">{filteredUsers.length}</span></div>
          <div className="max-h-[34vh] space-y-1 overflow-y-auto pr-1">
            {filteredUsers.map((user) => <button key={user.id} onClick={() => setSelection({ kind: 'user', id: user.id })} className={`w-full rounded-2xl px-3 py-2.5 text-left transition ${selection?.kind === 'user' && selection.id === user.id ? 'bg-teal-700 text-white shadow-lg shadow-teal-900/10' : 'text-apple-gray-dark hover:bg-white/70'}`}><div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-bold">{user.display_name || user.username}</span><span className={`h-2 w-2 shrink-0 rounded-full ${user.is_active ? 'bg-emerald-400' : 'bg-red-400'}`} /></div><p className={`mt-0.5 truncate text-xs ${selection?.kind === 'user' && selection.id === user.id ? 'text-white/70' : 'text-apple-gray-medium'}`}>{user.groups?.length ? user.groups.map((group) => group.group_name).join(' · ') : '未分配部门'}</p></button>)}
            {!filteredUsers.length && <p className="px-3 py-4 text-xs text-apple-gray-medium">没有匹配的成员</p>}
          </div>
          <div className="my-4 border-t border-black/5" />
          <div className="mb-2 flex items-center justify-between px-3"><span className="text-xs font-black uppercase tracking-[0.12em] text-apple-gray-medium">部门</span><span className="text-xs font-bold text-apple-gray-medium">{filteredGroups.length}</span></div>
          <div className="max-h-[34vh] space-y-1 overflow-y-auto pr-1">
            {filteredGroups.map((group) => <button key={group.id} onClick={() => setSelection({ kind: 'group', id: group.id })} className={`w-full rounded-2xl px-3 py-3 text-left transition ${selection?.kind === 'group' && selection.id === group.id ? 'bg-teal-700 text-white shadow-lg shadow-teal-900/10' : 'text-apple-gray-dark hover:bg-white/70'}`}><div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-bold">{group.group_name}</span>{group.is_preset && <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${selection?.kind === 'group' && selection.id === group.id ? 'bg-white/20 text-white' : 'bg-amber-50 text-amber-700'}`}>预置</span>}</div><p className={`mt-0.5 truncate text-xs ${selection?.kind === 'group' && selection.id === group.id ? 'text-white/70' : 'text-apple-gray-medium'}`}>{group.description || '未填写部门说明'}</p></button>)}
            {!filteredGroups.length && <p className="px-3 py-4 text-xs text-apple-gray-medium">没有匹配的部门</p>}
          </div>
        </aside>

        <section className="min-w-0">
          {selectedUser && (
            <div className="space-y-5">
              <div className="glass rounded-3xl p-6">
                <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex items-center gap-3"><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-teal-700 text-lg font-black text-white">{(selectedUser.display_name || selectedUser.username).charAt(0).toUpperCase()}</div><div><p className="text-xs font-bold uppercase tracking-[0.12em] text-teal-700">成员账号</p><h2 className="mt-1 text-2xl font-black text-apple-text">{selectedUser.display_name || selectedUser.username}</h2><p className="mt-1 text-sm text-apple-gray-medium">{selectedUser.email || '未填写邮箱'} · {selectedUser.is_active ? '当前启用' : '当前禁用'}</p></div></div><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void handleSaveUser()} className="btn-primary px-4 py-2 text-sm">保存用户</button><button type="button" onClick={() => setResetOpen((current) => !current)} className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-bold text-amber-700">重置密码</button>{currentUser?.id !== selectedUser.id && <button type="button" onClick={() => void handleDeleteUser()} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-bold text-red-600">删除</button>}</div></div>
                {resetOpen && <div className="mt-5 flex flex-wrap gap-2 rounded-2xl bg-amber-50 p-3"><input value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} type="password" placeholder="新密码（至少 8 位）" className="glass-input min-w-60 flex-1 px-3 py-2 text-sm" /><button type="button" onClick={() => void handleResetPassword()} className="rounded-xl bg-amber-600 px-4 py-2 text-sm font-bold text-white">确认重置</button></div>}
                <div className="mt-6 grid gap-4 md:grid-cols-2"><label className="block"><span className="mb-1 block text-xs font-bold text-apple-gray-dark">登录用户名</span><input value={editUserForm.username} onChange={(event) => setEditUserForm({ ...editUserForm, username: event.target.value })} className="glass-input w-full px-3 py-2 text-sm" /></label><label className="block"><span className="mb-1 block text-xs font-bold text-apple-gray-dark">显示名称</span><input value={editUserForm.display_name} onChange={(event) => setEditUserForm({ ...editUserForm, display_name: event.target.value })} className="glass-input w-full px-3 py-2 text-sm" /></label><label className="block"><span className="mb-1 block text-xs font-bold text-apple-gray-dark">邮箱</span><input value={editUserForm.email} onChange={(event) => setEditUserForm({ ...editUserForm, email: event.target.value })} type="email" className="glass-input w-full px-3 py-2 text-sm" /></label><label className="flex items-center gap-3 pt-6 text-sm font-bold text-apple-gray-dark"><input type="checkbox" checked={editUserForm.is_active} onChange={(event) => setEditUserForm({ ...editUserForm, is_active: event.target.checked })} />账号启用</label></div>
              </div>

              <div className="grid gap-5 lg:grid-cols-2">
                <section className="glass rounded-3xl p-6"><div className="flex items-start justify-between gap-3"><div><h3 className="text-lg font-black text-apple-text">所属部门</h3><p className="mt-1 text-xs leading-5 text-apple-gray-medium">在这里添加、移出或调整角色；部门权限会自动继承。</p></div><span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">{selectedUserGroups.length} 个部门</span></div><form onSubmit={handleAssignUser} className="mt-5 flex flex-wrap gap-2"><select value={assignForm.group_id} onChange={(event) => setAssignForm({ ...assignForm, group_id: event.target.value })} disabled={!availableUserGroups.length} className="glass-input min-w-0 flex-1 px-3 py-2 text-sm"><option value="">{availableUserGroups.length ? '添加到部门...' : '已加入全部部门'}</option>{availableUserGroups.map((group) => <option key={group.id} value={group.id}>{group.group_name}</option>)}</select><select value={assignForm.group_role} onChange={(event) => setAssignForm({ ...assignForm, group_role: event.target.value })} className="glass-input px-3 py-2 text-sm"><option value="member">成员</option><option value="admin">组管理员</option></select><button type="submit" disabled={!assignForm.group_id} className="rounded-xl bg-teal-700 px-3 py-2 text-sm font-bold text-white disabled:opacity-40">添加</button></form><div className="mt-4 space-y-2">{selectedUserGroups.map((group) => <div key={group.group_id} className="flex items-center justify-between gap-3 rounded-2xl border border-black/5 bg-white/60 px-3 py-3"><div className="min-w-0"><p className="truncate text-sm font-bold text-apple-text">{group.group_name}</p><select value={group.group_role} onChange={(event) => void handleChangeUserGroupRole(group.group_id, event.target.value)} className="glass-input mt-1 px-2 py-1 text-xs"><option value="member">普通成员</option><option value="admin">组管理员</option></select></div><div className="flex items-center gap-2"><button type="button" onClick={() => setSelection({ kind: 'group', id: group.group_id })} className="text-xs font-bold text-teal-700 hover:underline">设置权限</button><button type="button" onClick={() => void handleRemoveUserGroup(group.group_id)} className="text-xs font-bold text-red-500 hover:underline">移出</button></div></div>)}{!selectedUserGroups.length && <p className="rounded-2xl bg-amber-50 px-3 py-4 text-xs leading-5 text-amber-800">该用户还没有部门归属，因此不会继承部门权限。</p>}</div></section>
                <section className="glass rounded-3xl p-6"><div className="flex items-start justify-between gap-3"><div><h3 className="text-lg font-black text-apple-text">当前有效权限</h3><p className="mt-1 text-xs leading-5 text-apple-gray-medium">只读汇总，具体权限在对应部门中统一设置。</p></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">{selectedUser.permissions?.length || 0} 项</span></div><div className="mt-5 flex max-h-64 flex-wrap content-start gap-2 overflow-y-auto">{selectedUser.permissions?.map((permission) => <span key={permission} className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-700">{permissionLabelByKey(permission)}</span>)}{!selectedUser.permissions?.length && <p className="text-sm text-apple-gray-medium">当前没有有效权限。</p>}</div></section>
              </div>
            </div>
          )}

          {selectedGroup && (
            <div className="space-y-5">
              <div className="glass rounded-3xl p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><p className="text-xs font-bold uppercase tracking-[0.12em] text-teal-700">部门权限模板</p>{selectedGroup.is_preset && <span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700">预置部门</span>}</div><h2 className="mt-2 text-2xl font-black text-apple-text">{selectedGroup.group_name}</h2><p className="mt-1 text-sm text-apple-gray-medium">{selectedGroup.description || '未填写部门说明'}</p></div><div className="flex flex-wrap gap-2"><button onClick={() => setEditingGroup((current) => !current)} className="rounded-xl border border-black/10 bg-white/65 px-4 py-2 text-sm font-bold text-apple-gray-dark">{editingGroup ? '关闭编辑' : '编辑部门'}</button>{!selectedGroup.is_preset && <button onClick={handleDeleteGroup} className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm font-bold text-red-600">删除部门</button>}</div></div>{editingGroup && <form onSubmit={handleUpdateGroup} className="mt-5 grid gap-3 rounded-2xl bg-white/55 p-4 md:grid-cols-2"><input value={groupForm.group_name} onChange={(event) => setGroupForm({ ...groupForm, group_name: event.target.value })} className="glass-input px-3 py-2 text-sm" /><input value={groupForm.description} onChange={(event) => setGroupForm({ ...groupForm, description: event.target.value })} placeholder="部门说明" className="glass-input px-3 py-2 text-sm" /><button type="submit" className="btn-primary w-fit px-4 py-2 text-sm">保存部门信息</button></form>}</div>

              <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.15fr)]">
                        <section className="glass rounded-3xl p-6"><div className="flex items-start justify-between gap-3"><div><h3 className="text-lg font-black text-apple-text">部门成员</h3><p className="mt-1 text-xs leading-5 text-apple-gray-medium">成员和权限在同一个部门面板里处理。</p></div><span className="rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">{groupDetailsLoading ? '加载中' : `${members.length} 人`}</span></div><form onSubmit={handleAddMember} className="mt-5 space-y-2"><select value={addMemberForm.user_id} onChange={(event) => setAddMemberForm({ ...addMemberForm, user_id: event.target.value })} disabled={groupDetailsLoading || !availableMembers.length} className="glass-input w-full px-3 py-2 text-sm"><option value="">{groupDetailsLoading ? '正在加载成员...' : availableMembers.length ? '添加现有用户...' : '没有可添加的用户'}</option>{availableMembers.map((user) => <option key={user.id} value={user.id}>{user.display_name || user.username}</option>)}</select><div className="flex gap-2"><select value={addMemberForm.group_role} onChange={(event) => setAddMemberForm({ ...addMemberForm, group_role: event.target.value })} disabled={groupDetailsLoading} className="glass-input flex-1 px-3 py-2 text-sm"><option value="member">普通成员</option><option value="admin">组管理员</option></select><button type="submit" disabled={groupDetailsLoading || !addMemberForm.user_id} className="rounded-xl bg-teal-700 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">添加成员</button></div></form><div className="mt-5 space-y-2">{groupDetailsLoading && <p className="rounded-2xl bg-white/60 px-3 py-4 text-xs text-apple-gray-medium">正在加载部门成员...</p>}{!groupDetailsLoading && members.map((member) => { const user = users.find((item) => item.id === member.user_id); return <div key={member.user_id} className="rounded-2xl border border-black/5 bg-white/60 p-3"><div className="flex items-center justify-between gap-2"><button type="button" onClick={() => setSelection({ kind: 'user', id: member.user_id })} className="min-w-0 text-left"><p className="truncate text-sm font-bold text-apple-text">{member.username}</p><p className="mt-0.5 truncate text-xs text-apple-gray-medium">{member.email || '未填写邮箱'}</p></button><span className={`shrink-0 text-[11px] font-bold ${user?.is_active ? 'text-emerald-600' : 'text-red-500'}`}>{user?.is_active ? '启用' : '禁用'}</span></div><div className="mt-3 flex items-center justify-between gap-2"><select value={member.group_role} onChange={(event) => void handleChangeRole(member.user_id, event.target.value)} className="glass-input px-2 py-1 text-xs"><option value="member">普通成员</option><option value="admin">组管理员</option></select><button type="button" onClick={() => void handleRemoveMember(member.user_id)} className="text-xs font-bold text-red-500 hover:underline">移出部门</button></div></div>})}{!groupDetailsLoading && !members.length && <p className="rounded-2xl bg-amber-50 px-3 py-4 text-xs leading-5 text-amber-800">暂无成员。可以先在上方添加用户，或从左侧选用户后添加部门。</p>}</div></section>

                        <section className="glass rounded-3xl p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-black text-apple-text">部门权限</h3><p className="mt-1 text-xs leading-5 text-apple-gray-medium">勾选后，该部门下所有成员都会继承这些能力。</p></div><button onClick={handleSavePermissions} disabled={saving || groupDetailsLoading} className="btn-primary px-4 py-2 text-sm disabled:opacity-50">{groupDetailsLoading ? '加载中...' : saving ? '保存中...' : '保存权限'}</button></div><div className="mt-5 space-y-5">{groupDetailsLoading ? <p className="rounded-2xl bg-white/60 px-3 py-4 text-xs text-apple-gray-medium">正在加载部门权限...</p> : Object.entries(groupedPermissions).map(([type, items]) => <div key={type}><h4 className="mb-2 text-xs font-black text-apple-gray-dark">{TYPE_LABELS[type] || '其他权限'}</h4><div className="grid gap-2 md:grid-cols-2">{items.map((permission) => <label key={permission.permission_key} className="flex cursor-pointer items-start gap-3 rounded-2xl border border-black/5 bg-white/60 p-3 transition hover:bg-white"><input type="checkbox" checked={selectedPermissions.includes(permission.permission_key)} onChange={() => togglePermission(permission.permission_key)} className="mt-1" /><span><span className="block text-sm font-bold text-apple-text">{labelForPermission(permission)}</span>{permission.description && <span className="mt-0.5 block text-[11px] leading-4 text-apple-gray-medium">{permission.description}</span>}</span></label>)}</div></div>)}</div></section>
              </div>
            </div>
          )}

          {!selectedUser && !selectedGroup && <div className="glass flex min-h-[520px] items-center justify-center rounded-3xl p-8 text-center"><div><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-50 text-2xl text-teal-700">↗</div><h2 className="mt-4 text-xl font-black text-apple-text">选择一个用户或部门</h2><p className="mt-2 text-sm text-apple-gray-medium">左侧组织目录会把账号设置和部门权限放在同一条工作流里。</p></div></div>}
        </section>
      </div>
    </main>
  )
}
