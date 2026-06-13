import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../services/api'

export default function Register() {
  const allowPublicRegistration = import.meta.env.VITE_ENABLE_PUBLIC_REGISTRATION === 'true'
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!allowPublicRegistration) {
      setError('公开注册已关闭，请联系管理员创建账号')
      return
    }

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    if (password.length < 8) {
      setError('密码长度至少8位')
      return
    }

    setLoading(true)

    try {
      await api.auth.register({ username, email, password })
      navigate('/login', { state: { registered: true } })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-subtle flex items-center justify-center overflow-x-hidden p-4">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 subtle-grid" />
        <div className="ambient-orb absolute -top-40 -right-24 h-[28rem] w-[28rem] bg-cyan-300/35" />
        <div className="ambient-orb absolute -bottom-40 -left-24 h-[28rem] w-[28rem] bg-amber-300/32" />
        <div className="ambient-orb absolute bottom-12 right-1/4 h-[22rem] w-[22rem] bg-emerald-300/22" />
      </div>

      <div className="relative z-10 mx-auto w-[calc(100vw-2rem)] max-w-[340px] animate-slide-up sm:max-w-md">
        <div className="mb-7 text-center">
          <div className="eyebrow mb-3">Account Access</div>
          <h1 className="text-4xl font-black tracking-[-0.04em] text-apple-text">创建账号</h1>
          <p className="mt-2 text-apple-gray-medium">
            {allowPublicRegistration ? '注册以开始使用 AI 创作平台' : '公开注册已关闭，请联系管理员创建账号'}
          </p>
        </div>

        {!allowPublicRegistration ? (
          <div className="auth-card glass space-y-5 p-6 text-center sm:p-8">
            <div className="relative z-10 rounded-2xl border border-teal-100 bg-teal-50/80 px-4 py-4 text-sm leading-6 text-teal-800">
              当前系统已关闭公开注册。请联系管理员在“用户管理”中创建企业账号并分配团队权限。
            </div>
            <Link to="/login" className="btn-primary relative z-10 inline-flex w-full justify-center">
              返回登录
            </Link>
          </div>
        ) : (
        <form onSubmit={handleSubmit} className="auth-card glass space-y-5 p-6 sm:p-8">
          <div className="relative z-10 space-y-5">
            {error && (
              <div className="rounded-2xl border border-red-200 bg-red-50/90 px-4 py-3 text-sm text-red-600">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-bold text-apple-text mb-1.5">用户名</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
                placeholder="请输入用户名"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-bold text-apple-text mb-1.5">邮箱 <span className="text-apple-gray-medium font-normal">(选填)</span></label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
                placeholder="请输入邮箱（选填）"
              />
            </div>

            <div>
              <label className="block text-sm font-bold text-apple-text mb-1.5">密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
                placeholder="至少8位密码"
                required
                minLength={8}
              />
            </div>

            <div>
              <label className="block text-sm font-bold text-apple-text mb-1.5">确认密码</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
                placeholder="再次输入密码"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full"
            >
              {loading ? '注册中...' : '注册'}
            </button>

            <p className="text-center text-sm text-apple-gray-medium">
              已有账号？{' '}
              <Link to="/login" className="font-bold text-teal-700 hover:underline">
                登录
              </Link>
            </p>
          </div>
        </form>
        )}
      </div>
    </div>
  )
}
