import { useAuthStore } from '../../store/authStore'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'

export default function Header() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setAdminOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  const isSuperAdmin = useAuthStore((s) => s.isManagement)
  const hasProductAccess = isSuperAdmin || user?.permissions?.includes('product.read') || user?.groups?.some(
    (g) => g.group_name === '产品团队' || g.group_name === '设计团队'
  )
  const hasWorkspaceAccess = isSuperAdmin || user?.permissions?.includes('ai.call')

  const navItems = [
    ...(hasWorkspaceAccess ? [{ path: '/customer-service', label: '智能客服' }] : []),
    ...(hasWorkspaceAccess ? [{ path: '/', label: '创作' }] : []),
    { path: '/history', label: '历史' },
    ...(hasProductAccess ? [{ path: '/products', label: '产品' }] : []),
  ]

  const superAdminItems = [
    { path: '/admin/users', label: '用户' },
    { path: '/admin/groups', label: '团队' },
    { path: '/admin/settings', label: '设置' },
    { path: '/admin/logs', label: '日志' },
  ]

  const isAdminActive = location.pathname.startsWith('/admin')

  return (
    <header className="fixed top-0 left-0 right-0 z-50 h-14">
      <div className="glass-dark mx-4 mt-3 px-6 h-12 flex items-center justify-between rounded-glass">
        <div className="flex items-center gap-8">
          <Link to="/" className="text-lg font-semibold text-apple-text tracking-tight">
            AI 创作平台
          </Link>
          <nav className="flex items-center gap-1">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`px-3 py-1.5 rounded-[10px] text-sm font-medium transition-all duration-200 ${
                  location.pathname === item.path
                    ? 'bg-black/5 text-apple-text'
                    : 'text-apple-gray-dark hover:text-apple-text hover:bg-black/3'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1" ref={menuRef}>
          {isSuperAdmin && (
            <div className="relative">
              <button
                onClick={() => setAdminOpen(!adminOpen)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-[10px] text-sm font-medium transition-all duration-200 ${
                  isAdminActive
                    ? 'bg-black/5 text-apple-text'
                    : 'text-apple-gray-dark hover:text-apple-text hover:bg-black/3'
                }`}
              >
                管理
                <svg className={`w-3 h-3 transition-transform duration-200 ${adminOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {adminOpen && (
                <div className="absolute right-0 top-full mt-2 w-36 glass rounded-xl py-1 animate-fade-in z-50">
                  {superAdminItems.map((item) => (
                    <Link
                      key={item.path}
                      to={item.path}
                      onClick={() => setAdminOpen(false)}
                      className={`block px-4 py-2.5 text-sm transition-colors duration-150 ${
                        location.pathname === item.path
                          ? 'text-apple-blue font-medium bg-blue-50/50'
                          : 'text-apple-gray-dark hover:text-apple-text hover:bg-black/[0.02]'
                      }`}
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="relative">
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-[10px] hover:bg-black/3 transition-all duration-200"
            >
              <div className="w-7 h-7 rounded-full bg-apple-blue flex items-center justify-center text-white text-xs font-medium">
                {user?.username?.charAt(0).toUpperCase()}
              </div>
              <span className="text-sm font-medium text-apple-text">{user?.username}</span>
              <svg className="w-3.5 h-3.5 text-apple-gray-medium" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d={menuOpen ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} />
              </svg>
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-full mt-2 w-48 glass rounded-xl py-1 animate-fade-in">
                <div className="px-4 py-2.5 border-b border-black/5">
                  <p className="text-sm font-medium text-apple-text">{user?.username}</p>
                  <p className="text-xs text-apple-gray-medium mt-0.5">{user?.email}</p>
                </div>
                <Link
                  to="/profile"
                  onClick={() => setMenuOpen(false)}
                  className="block px-4 py-2.5 text-sm text-apple-gray-dark hover:text-apple-text hover:bg-black/[0.02] transition-colors duration-150"
                >
                  个人资料
                </Link>
                <button
                  onClick={handleLogout}
                  className="w-full text-left px-4 py-2.5 text-sm text-red-500 hover:bg-red-50/50 transition-colors duration-150"
                >
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
