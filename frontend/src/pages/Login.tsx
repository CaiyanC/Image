import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { useAuthStore } from '../store/authStore'

export default function Login() {
  const allowPublicRegistration = import.meta.env.VITE_ENABLE_PUBLIC_REGISTRATION === 'true'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      const data = await api.auth.login(username, password)
      setAuth(data.access_token, data.user)
      const permissions = data.user.permissions || []
      if (permissions.includes('ai.generate')) {
        navigate('/')
      } else if (permissions.includes('ai.customer_service')) {
        navigate('/customer-service')
      } else if (permissions.includes('history.view')) {
        navigate('/history')
      } else if (permissions.includes('product.read')) {
        navigate('/products')
      } else if (permissions.includes('profile.view')) {
        navigate('/profile')
      } else {
        navigate('/no-access')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '账号或密码错误')
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
          <h1 className="text-3xl font-bold text-apple-text tracking-tight">AI 创作平台</h1>
          <p className="text-apple-gray-medium mt-2">登录以开始工作</p>
        </div>

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
              onChange={(event) => setUsername(event.target.value)}
              className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
              placeholder="请输入用户名"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-apple-text mb-1.5">密码</label>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
              placeholder="请输入密码"
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? '登录中...' : '登录'}
          </button>

          {allowPublicRegistration ? (
            <div className="text-center text-sm text-apple-gray-medium">
              还没有账号？{' '}
              <Link to="/register" className="text-apple-blue hover:underline">
                注册
              </Link>
            </div>
          ) : (
            <div className="text-center text-xs text-apple-gray-medium">
              企业账号请联系管理员创建
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
