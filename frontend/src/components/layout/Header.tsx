import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { getLandingPath, hasPermission, useAuthStore } from '../../store/authStore'

export default function Header() {
  const { user, logout } = useAuthStore()
  const isSuperAdmin = useAuthStore((state) => state.isManagement)
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
        setAdminOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function has(permissionKey: string) {
    return hasPermission(user, permissionKey)
  }

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  const homePath = getLandingPath(user)

  const superAdminItems = [
    ...(isSuperAdmin ? [
    { path: '/admin/department-workbench', label: '部门工作台' },
    { path: '/admin/tools', label: '工具管理' },
    { path: '/admin/access-control', label: '组织与权限' },
    { path: '/admin/model-governance', label: '模型治理' },
    { path: '/admin/settings', label: '设置' },
    { path: '/admin/logs', label: '日志' },
    ] : []),
  ]

  const isAdminActive = superAdminItems.some(item => location.pathname === item.path)

  return (
    <header className="fixed left-0 right-0 top-0 z-50 h-20">
      <div className="mx-3 mt-3 flex h-14 items-center justify-between rounded-lg border border-slate-200 bg-white px-4 sm:mx-5 sm:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-4 lg:gap-8">
          <Link to={homePath} className="group flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-gradient-accent text-sm font-black text-white shadow-[0_12px_24px_rgba(15,118,110,0.22)]">
              AI
            </span>
            <span className="min-w-0">
              <span className="block truncate text-base font-black tracking-tight text-apple-text sm:text-lg">
                AI 创作平台
              </span>
              <span className="hidden text-[10px] font-bold uppercase tracking-[0.2em] text-teal-700/60 sm:block">
                Enterprise Studio
              </span>
            </span>
          </Link>
        </div>

        <div className="flex shrink-0 items-center gap-1.5" ref={menuRef}>
          {superAdminItems.length > 0 && (
            <div className="relative">
              <button
                onClick={() => setAdminOpen(!adminOpen)}
                className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-bold transition-all duration-200 ${
                  isAdminActive ? 'nav-active' : 'nav-idle'
                }`}
              >
                系统管理
                <svg className={`h-3 w-3 transition-transform duration-200 ${adminOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {adminOpen && (
                <div className="glass absolute right-0 top-full z-50 mt-3 w-40 rounded-2xl p-1.5 animate-fade-in">
                  {superAdminItems.map((item) => (
                    <Link
                      key={item.path}
                      to={item.path}
                      onClick={() => setAdminOpen(false)}
                      className={`block rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors duration-150 ${
                        location.pathname === item.path
                          ? 'bg-teal-50/80 text-teal-700'
                          : 'text-apple-gray-dark hover:bg-white/60 hover:text-apple-text'
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
              className="flex items-center gap-2 rounded-full px-2 py-1.5 transition-all duration-200 hover:bg-white/55 sm:px-3"
            >
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-accent text-xs font-black text-white shadow-[0_10px_22px_rgba(15,118,110,0.2)]">
                {user?.username?.charAt(0).toUpperCase()}
              </div>
              <span className="hidden max-w-28 truncate text-sm font-bold text-apple-text sm:inline">{user?.username}</span>
              <svg className="h-3.5 w-3.5 text-apple-gray-medium" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d={menuOpen ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'} />
              </svg>
            </button>

            {menuOpen && (
              <div className="glass absolute right-0 top-full mt-3 w-56 rounded-2xl p-1.5 animate-fade-in">
                <div className="border-b border-black/5 px-4 py-3">
                  <p className="text-sm font-bold text-apple-text">{user?.username}</p>
                  <p className="mt-0.5 text-xs text-apple-gray-medium">{user?.email}</p>
                </div>
                {has('profile.view') && (
                  <Link
                    to="/profile"
                    onClick={() => setMenuOpen(false)}
                    className="mt-1 block rounded-xl px-4 py-2.5 text-sm font-semibold text-apple-gray-dark transition-colors duration-150 hover:bg-white/60 hover:text-apple-text"
                  >
                    个人资料
                  </Link>
                )}
                <button
                  onClick={handleLogout}
                  className="w-full rounded-xl px-4 py-2.5 text-left text-sm font-semibold text-red-500 transition-colors duration-150 hover:bg-red-50/70"
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
