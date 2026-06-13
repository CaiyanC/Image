import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../store/authStore'
import type { User } from '../types'

export default function Profile() {
  const { user, updateUser, logout } = useAuthStore()
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
    </div>
  )
}
