import { useEffect, useState } from 'react'
import { api, type PersonalCredentialSummary } from '../services/api'
import { useAuthStore } from '../store/authStore'
import type { User } from '../types'

export default function Profile() {
  const { user, updateUser, logout } = useAuthStore()
  const userId = user?.id
  const [profileForm, setProfileForm] = useState({
    username: user?.username || '',
    display_name: user?.display_name || '',
    email: user?.email || '',
  })
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)
  const [personalCredentials, setPersonalCredentials] = useState<PersonalCredentialSummary[]>([])
  const [credentialKeys, setCredentialKeys] = useState<Record<string, string>>({})
  const [loadingCredentials, setLoadingCredentials] = useState(false)
  const [savingCredential, setSavingCredential] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (user) {
      setProfileForm({
        username: user.username || '',
        display_name: user.display_name || '',
        email: user.email || '',
      })
    }
  }, [user])

  useEffect(() => {
    if (!userId) return
    let active = true
    setLoadingCredentials(true)
    api.modelGovernance.myCredentials()
      .then((items) => {
        if (active) setPersonalCredentials(items)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : '模型凭据读取失败')
      })
      .finally(() => {
        if (active) setLoadingCredentials(false)
      })
    return () => {
      active = false
    }
  }, [userId])

  async function handleSaveProfile() {
    if (!profileForm.username.trim()) {
      setError('用户名不能为空')
      return
    }
    setError('')
    setMessage('')
    setSavingProfile(true)
    try {
      const updated = await api.auth.updateMe({
        username: profileForm.username.trim(),
        display_name: profileForm.display_name.trim(),
        email: profileForm.email.trim(),
      }) as User
      updateUser(updated)
      setMessage('个人信息已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSavingProfile(false)
    }
  }

  async function handleChangePassword() {
    if (!passwordForm.current_password || !passwordForm.new_password) {
      setError('请填写当前密码和新密码')
      return
    }
    if (passwordForm.new_password.length < 8) {
      setError('新密码至少 8 位')
      return
    }
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setError('两次输入的新密码不一致')
      return
    }
    setError('')
    setMessage('')
    setSavingPassword(true)
    try {
      await api.auth.changePassword({
        current_password: passwordForm.current_password,
        new_password: passwordForm.new_password,
      })
      setPasswordForm({ current_password: '', new_password: '', confirm_password: '' })
      setMessage('密码已更新，请用新密码重新登录')
      setTimeout(() => {
        logout()
        window.location.href = '/login'
      }, 1200)
    } catch (err) {
      setError(err instanceof Error ? err.message : '密码修改失败')
    } finally {
      setSavingPassword(false)
    }
  }

  async function handleSavePersonalCredential(item: PersonalCredentialSummary) {
    const apiKey = (credentialKeys[item.provider_name] || '').trim()
    if (!apiKey) {
      setError('请输入 API Key；已保存的 Key 不会回显')
      return
    }
    setError('')
    setMessage('')
    setSavingCredential(item.provider_name)
    try {
      const updated = await api.modelGovernance.updateMyCredential(item.provider_name, {
        api_key: apiKey,
        is_enabled: true,
      })
      setPersonalCredentials((current) => current.map((entry) => entry.provider_name === updated.provider_name ? updated : entry))
      setCredentialKeys((current) => ({ ...current, [item.provider_name]: '' }))
      setMessage(`${item.provider_name} 的个人 Key 已加密保存`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '个人 Key 保存失败')
    } finally {
      setSavingCredential(null)
    }
  }

  async function handleTogglePersonalCredential(item: PersonalCredentialSummary) {
    setError('')
    setMessage('')
    setSavingCredential(item.provider_name)
    try {
      const updated = await api.modelGovernance.updateMyCredential(item.provider_name, {
        is_enabled: !item.is_enabled,
      })
      setPersonalCredentials((current) => current.map((entry) => entry.provider_name === updated.provider_name ? updated : entry))
      setMessage(`${item.provider_name} 的个人 Key 已${updated.is_enabled ? '启用' : '停用'}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '个人 Key 状态更新失败')
    } finally {
      setSavingCredential(null)
    }
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-apple-text tracking-tight">个人资料</h1>
        <p className="text-sm text-apple-gray-medium mt-1">管理你的登录信息和账号显示信息</p>
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="glass rounded-xl p-5">
          <h2 className="text-base font-semibold text-apple-text mb-4">基本信息</h2>
          <div className="space-y-4">
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">用户名</span>
              <input
                value={profileForm.username}
                onChange={(e) => setProfileForm({ ...profileForm, username: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">显示名称</span>
              <input
                value={profileForm.display_name}
                onChange={(e) => setProfileForm({ ...profileForm, display_name: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
                placeholder="可选"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">邮箱</span>
              <input
                value={profileForm.email}
                onChange={(e) => setProfileForm({ ...profileForm, email: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
                type="email"
                placeholder="可选"
              />
            </label>
          </div>
          <button
            onClick={handleSaveProfile}
            disabled={savingProfile}
            className="btn-primary mt-5 py-2 text-sm disabled:opacity-60"
          >
            {savingProfile ? '保存中...' : '保存信息'}
          </button>
        </section>

        <section className="glass rounded-xl p-5">
          <h2 className="text-base font-semibold text-apple-text mb-4">修改密码</h2>
          <div className="space-y-4">
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">当前密码</span>
              <input
                value={passwordForm.current_password}
                onChange={(e) => setPasswordForm({ ...passwordForm, current_password: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
                type="password"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">新密码</span>
              <input
                value={passwordForm.new_password}
                onChange={(e) => setPasswordForm({ ...passwordForm, new_password: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
                type="password"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-apple-gray-dark">确认新密码</span>
              <input
                value={passwordForm.confirm_password}
                onChange={(e) => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })}
                className="glass-input w-full px-3 py-2 text-sm mt-1"
                type="password"
              />
            </label>
          </div>
          <button
            onClick={handleChangePassword}
            disabled={savingPassword}
            className="btn-primary mt-5 py-2 text-sm disabled:opacity-60"
          >
            {savingPassword ? '更新中...' : '更新密码'}
          </button>
        </section>
      </div>

      <section className="glass rounded-xl p-5 mt-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-apple-text">我的模型配置</h2>
            <p className="text-sm text-apple-gray-medium mt-1">
              你可以自助填写自己的 API Key。Key 会在服务端加密保存，只显示脱敏结果；模型目录、授权和 API 地址由管理员统一配置。
            </p>
          </div>
          <span className="rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-700">个人凭据</span>
        </div>

        {loadingCredentials && <p className="mt-4 text-sm text-apple-gray-medium">正在读取可用模型…</p>}
        {!loadingCredentials && personalCredentials.length === 0 && (
          <p className="mt-4 rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
            当前没有已启用的模型提供商，请联系管理员先配置模型目录和服务地址。
          </p>
        )}
        <div className="mt-4 space-y-3">
          {personalCredentials.map((item) => (
            <div key={item.provider_name} className="rounded-xl border border-black/5 bg-white/55 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium text-apple-text">{item.provider_name}</h3>
                  <p className="mt-1 text-xs text-apple-gray-medium">
                    {item.models.length > 0
                      ? `可用于：${item.models.map((model) => model.display_name).join('、')}`
                      : '暂无可用模型'}
                  </p>
                  <p className="mt-1 text-xs text-apple-gray-medium">API 地址由管理员配置{item.api_base_url ? `：${item.api_base_url}` : ''}</p>
                </div>
                <div className="text-right text-xs">
                  <div className={item.is_configured && item.is_enabled ? 'text-emerald-600' : 'text-apple-gray-medium'}>
                    {item.is_configured ? `个人 Key ${item.api_key_masked}` : '尚未填写个人 Key'}
                  </div>
                  <div className="mt-1 text-apple-gray-medium">
                    当前使用：{credentialScopeLabel(item.effective_credential_scope_type)}
                  </div>
                </div>
              </div>

              {item.can_configure && (
                <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={credentialKeys[item.provider_name] || ''}
                    onChange={(event) => setCredentialKeys((current) => ({ ...current, [item.provider_name]: event.target.value }))}
                    placeholder={item.has_personal_credential ? '输入新 Key 以替换' : '输入你的 API Key'}
                    className="glass-input min-w-0 flex-1 px-3 py-2 text-sm"
                  />
                  <button
                    onClick={() => void handleSavePersonalCredential(item)}
                    disabled={savingCredential === item.provider_name}
                    className="btn-primary whitespace-nowrap py-2 text-sm disabled:opacity-60"
                  >
                    {savingCredential === item.provider_name ? '保存中…' : item.has_personal_credential ? '替换个人 Key' : '保存个人 Key'}
                  </button>
                  {item.has_personal_credential && (
                    <button
                      onClick={() => void handleTogglePersonalCredential(item)}
                      disabled={savingCredential === item.provider_name}
                      className="rounded-lg border border-black/10 px-3 py-2 text-sm text-apple-gray-dark hover:bg-white/70 disabled:opacity-60"
                    >
                      {item.is_enabled ? '停用' : '启用'}
                    </button>
                  )}
                </div>
              )}
              {!item.can_configure && <p className="mt-3 text-xs text-amber-700">管理员尚未为此提供商配置可用地址，暂不能新增个人 Key。</p>}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function credentialScopeLabel(scope: PersonalCredentialSummary['effective_credential_scope_type']) {
  if (scope === 'user') return '个人 Key'
  if (scope === 'group') return '部门 Key'
  if (scope === 'company') return '公司 Key'
  return '未配置'
}
