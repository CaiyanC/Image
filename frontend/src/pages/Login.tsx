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
    <div className="min-h-screen bg-gradient-subtle flex items-center justify-center overflow-x-hidden p-4">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 subtle-grid" />
        <div className="ambient-orb absolute -top-40 -right-24 h-[28rem] w-[28rem] bg-cyan-300/35" />
        <div className="ambient-orb absolute -bottom-40 -left-24 h-[28rem] w-[28rem] bg-amber-300/32" />
        <div className="ambient-orb absolute bottom-12 right-1/4 h-[22rem] w-[22rem] bg-emerald-300/22" />
      </div>

      <div className="relative z-10 mx-auto grid w-[calc(100vw-2rem)] max-w-[340px] items-stretch gap-6 animate-slide-up sm:max-w-md lg:w-full lg:max-w-5xl lg:grid-cols-[1fr_440px]">
        <section className="auth-card glass hidden min-h-[520px] flex-col justify-between p-8 lg:flex">
          <div className="relative z-10">
            <div className="eyebrow mb-4">Enterprise AI Workspace</div>
            <h1 className="max-w-lg text-5xl font-black leading-tight tracking-[-0.04em] text-apple-text">
              让产品、内容和客服在同一个工作台协同。
            </h1>
            <p className="mt-5 max-w-md text-base leading-7 text-apple-gray-dark">
              面向团队的 AI 创作平台，统一生成、产品库、历史记录和智能客服能力。
            </p>
          </div>
          <div className="relative z-10 grid grid-cols-3 gap-3">
            {['权限隔离', '产品数据库', '智能客服'].map((item) => (
              <div key={item} className="rounded-2xl border border-white/60 bg-white/45 px-4 py-3 text-sm font-bold text-apple-text shadow-sm">
                {item}
              </div>
            ))}
          </div>
        </section>

        <div className="flex min-w-0 flex-col justify-center">
          <div className="mb-7 text-center lg:text-left">
            <div className="eyebrow mb-3">CaiYan Studio</div>
            <h1 className="text-4xl font-black tracking-[-0.04em] text-apple-text">欢迎回来</h1>
            <p className="mt-2 text-apple-gray-medium">登录后进入企业 AI 工作台</p>
          </div>

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
                  onChange={(event) => setUsername(event.target.value)}
                  className="glass-input w-full px-4 py-3 text-sm text-apple-text placeholder:text-apple-gray-medium"
                  placeholder="请输入用户名"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-bold text-apple-text mb-1.5">密码</label>
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
                  <Link to="/register" className="font-bold text-teal-700 hover:underline">
                    注册
                  </Link>
                </div>
              ) : (
                <div className="rounded-2xl border border-white/60 bg-white/45 px-4 py-3 text-center text-xs font-medium text-apple-gray-medium">
                  企业账号请联系管理员创建
                </div>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
