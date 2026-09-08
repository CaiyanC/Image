export interface NavigationItem { path: string; label: string; permissions: string[] }
export interface NavigationSection { key: string; label: string; items: NavigationItem[] }

// Navigation only: route guards and backend permissions remain authoritative.
export const sections: NavigationSection[] = [
  { key: 'products', label: '产品中心', items: [
    { path: '/products', label: '产品资料', permissions: ['product.read'] },
    { path: '/products/full-view', label: '表格视图', permissions: ['product.full.view'] },
    { path: '/products/audit', label: '待核对', permissions: ['product.audit.view'] },
    { path: '/products/drafts', label: '草稿箱', permissions: ['product.read', 'product.create', 'product.edit'] },
    { path: '/products/qa/new', label: '录入问答', permissions: ['product.qa.manage', 'product.edit'] },
    { path: '/products/create', label: '新增产品', permissions: ['product.create'] },
  ] },
  { key: 'customer', label: '智能客服', items: [
    { path: '/customer-service', label: '智能客服', permissions: ['ai.customer_service'] },
  ] },
  { key: 'assets', label: '素材中心', items: [
    { path: '/assets', label: '浏览与管理', permissions: ['media.read'] },
    { path: '/assets/search', label: '搜索素材', permissions: ['media.search'] },
  ] },
  { key: 'creation', label: '创作中心', items: [
    { path: '/', label: '开始创作', permissions: ['ai.generate'] },
    { path: '/history', label: '创作记录', permissions: ['history.view'] },
  ] },
  { key: 'tools', label: '工具中心', items: [
    { path: '/tools', label: '全部工具', permissions: ['tools.view'] },
    { path: '/tools/ecommerce-data-fill', label: '财务填表', permissions: ['finance.ecommerce_data_fill'] },
  ] },
]

export function visibleSections(has: (permission: string) => boolean): NavigationSection[] {
  return sections.map(section => ({ ...section, items: section.items.filter(item => item.permissions.some(has)) }))
    .filter(section => section.items.length > 0)
}

export function sectionForPath(path: string): string | undefined {
  if (path === '/products' || path.startsWith('/products/')) return 'products'
  if (path === '/assets' || path.startsWith('/assets/')) return 'assets'
  if (path === '/customer-service' || path.startsWith('/customer-service/')) return 'customer'
  if (path === '/tools' || path.startsWith('/tools/')) return 'tools'
  if (path === '/' || path === '/history') return 'creation'
}

// The registry controls enabled primary tools. Only add independent sub-feature
// entries when the account does not have the primary tool's permission.
export function supplementalEntries(has: (permission: string) => boolean): NavigationItem[] {
  return sections.filter(section => ['products', 'assets', 'creation'].includes(section.key))
    .flatMap(section => {
      if (section.items[0].permissions.some(has)) return []
      const entry = section.items.slice(1).find(item => item.permissions.some(has))
      return entry ? [{ ...entry, label: section.label }] : []
    })
}

export function backEntry(path: string, has: (permission: string) => boolean): { path: string; label: string } | null {
  if (path === '/tools') return null
  if (path.startsWith('/products/') && has('product.read')) return { path: '/products', label: '产品资料' }
  return { path: '/tools', label: '工具中心' }
}
