import { Link, useLocation } from 'react-router-dom'
import { hasPermission, useAuthStore } from '../../store/authStore'
import { sections, sectionForPath } from './navigation'

export default function BusinessSidebar() {
  const { user } = useAuthStore()
  const { pathname } = useLocation()
  const has = (key: string) => hasPermission(user, key)
  const entries = sections.flatMap(section => {
    const entry = section.items.find(item => item.permissions.some(has))
    return entry ? [{ path: entry.path, label: section.label, active: sectionForPath(pathname) === section.key }] : []
  })
  return <nav aria-label="业务功能" className="border-b border-slate-200 bg-white px-3 py-3 md:fixed md:bottom-0 md:left-0 md:top-20 md:w-44 md:overflow-y-auto md:border-b-0 md:border-r">
    <p className="mb-3 hidden px-3 text-xs font-semibold text-slate-400 md:block">工作空间</p>
    <div className="flex gap-1 overflow-x-auto md:flex-col">
      {entries.map(item => <Link key={item.path} to={item.path} aria-current={item.active ? 'page' : undefined}
        className={`shrink-0 rounded-lg px-3 py-2.5 text-sm font-medium ${item.active ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-50'}`}>{item.label}</Link>)}
    </div>
  </nav>
}
