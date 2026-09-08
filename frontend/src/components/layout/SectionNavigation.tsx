import { Link, useLocation } from 'react-router-dom'
import { hasPermission, useAuthStore } from '../../store/authStore'
import { backEntry, sectionForPath, visibleSections } from './navigation'

export default function SectionNavigation() {
  const user = useAuthStore(state => state.user)
  const { pathname } = useLocation()
  const has = (key: string) => hasPermission(user, key)
  const section = visibleSections(has).find(item => item.key === sectionForPath(pathname))
  const back = backEntry(pathname, has)
  if (!back) return null
  const maintenance = section?.key === 'products'
    ? section.items.filter(item => ['/products/audit', '/products/drafts', '/products/qa/new'].includes(item.path)) : []
  const items = !section || section.key === 'tools' || section.items.length < 2 ? [] : section.items.filter(item =>
    item.path !== '/products/create' && !maintenance.includes(item))
  return <nav aria-label={`${section?.label || '页面'}内导航`} className="mx-auto flex max-w-7xl flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-4 md:px-6">
    <Link to={back.path} className="mr-auto rounded-md px-2 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 hover:text-teal-800">← {back.label}</Link>
    {items.map(item => <Link key={item.path} to={item.path} aria-current={pathname === item.path ? 'page' : undefined}
      className={`rounded-md px-3 py-2 text-sm font-medium ${pathname === item.path ? 'bg-teal-50 text-teal-800' : 'text-slate-600 hover:bg-slate-100'}`}>{item.label}</Link>)}
    {maintenance.length > 0 && <details key={pathname} className="relative">
      <summary className="cursor-pointer rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700">资料维护</summary>
      <div className="absolute right-0 z-30 mt-2 w-44 rounded-lg border border-slate-200 bg-white p-1 shadow-lg">
        {maintenance.map(item => <Link key={item.path} to={item.path} aria-current={pathname === item.path ? 'page' : undefined}
          className={`block rounded-md px-3 py-2 text-sm hover:bg-slate-50 ${pathname === item.path ? 'text-teal-800 font-semibold' : 'text-slate-600'}`}>{item.label}</Link>)}
      </div>
    </details>}
    {section?.key === 'products' && pathname !== '/products' && !pathname.startsWith('/products/create') && section.items.some(item => item.path === '/products/create') &&
      <Link to="/products/create" className="rounded-md bg-teal-700 px-3 py-2 text-sm font-semibold text-white">+ 新增产品</Link>}
  </nav>
}
