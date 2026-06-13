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
    <div className="min-h-screen bg-gradient-subtle flex items-center justify-center p-4">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 rounded-full bg-blue-400/15 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 rounded-full bg-purple-400/15 blur-3xl" />
      </div>

      <div className="w-full max-w-md animate-slide-up">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-apple-text tracking-tight">创建账号</h1>
          <p className="text-apple-gray-medium mt-2">
            {allowPublicRegistration ? '注册以开始使用 AI 创作平台' : '公开注册已关闭，请联系管理员创建账号'}
          </p>
        </div>

        {!allowPublicRegistration ? (
          <div className="glass p-8 space-y-5 text-center">
            <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
              当前系统已关闭公开注册。请联系管理员在“用户管理”中创建企业账号并分配团队权限。
            </div>
            <Link to="/login" className="btn-primary inline-flex w-full justify-center">
              返回登录
            </Link>
          </div>
        ) : (
        <form onSubmit={handleSubmit} className="glass p-8 space-y-5">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-xl text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-apple-text mb-1.5">用户名</label>
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
            <label className="block text-sm font-medium text-apple-text mb-1.5">邮箱 <span className="text-apple-gray-medium font-normal">(选填)</span></label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
              placeholder="请输入邮箱（选填）"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-apple-text mb-1.5">密码</label>
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
            <label className="block text-sm font-medium text-apple-text mb-1.5">确认密码</label>
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
            <Link to="/login" className="text-apple-blue hover:underline font-medium">
              登录
            </Link>
          </p>
        </form>
        )}
      </div>
    </div>
  )
}
