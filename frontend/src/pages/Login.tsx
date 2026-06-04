import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import { useAuthStore } from '../store/authStore'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const data = await api.auth.login(username, password)
      setAuth(data.access_token, data.user)
      const canUseWorkspace = data.user.permissions?.includes('ai.call') || data.user.groups?.some(
        (g: { group_name: string }) =>
          g.group_name === '管理层' || g.group_name === '产品团队' || g.group_name === '设计团队'
      )
      navigate(canUseWorkspace ? '/' : '/history')
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
          <p className="text-apple-gray-medium mt-2">登录以开始创作</p>
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
              onChange={(e) => setUsername(e.target.value)}
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
              onChange={(e) => setPassword(e.target.value)}
              className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
              placeholder="请输入密码"
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
          >
            {loading ? '登录中...' : '登录'}
          </button>

          <p className="text-center text-sm text-apple-gray-medium">
            还没有账号？{' '}
            <Link to="/register" className="text-apple-blue hover:underline font-medium">
              注册
            </Link>
          </p>
        </form>
      </div>
    </div>
  )
}
