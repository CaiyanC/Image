export interface NavigationItem { path: string; label: string; permissions: string[] }
export interface NavigationSection { key: string; label: string; items: NavigationItem[] }

// Navigation only: route guards and backend permissions remain authoritative.
export const sections: NavigationSection[] = [
  { key: 'products', label: '知识库', items: [
    { path: '/products', label: '产品资料', permissions: ['product.read'] },
    { path: '/products/full-view', label: '表格视图', permissions: ['product.full.view'] },
    { path: '/knowledge-base', label: '知识库运维', permissions: ['knowledge.manage'] },
    { path: '/file-knowledge', label: '文件知识库', permissions: ['knowledge.files.manage'] },
    { path: '/products/audit', label: '待核对', permissions: ['product.audit.view'] },
    { path: '/products/drafts', label: '草稿箱', permissions: ['product.read', 'product.create', 'product.edit'] },
    { path: '/products/qa/new', label: '录入问答', permissions: ['product.qa.manage', 'product.edit'] },
    { path: '/products/create', label: '新增产品', permissions: ['product.create'] },
  ] },
  { key: 'customer', label: '智能客服', items: [
    { path: '/customer-service', label: '智能客服', permissions: ['ai.customer_service'] },
  ] },
  { key: 'assets', label: '素材库', items: [
    { path: '/assets', label: '浏览与管理', permissions: ['media.read'] },
    { path: '/assets/search', label: '搜索素材', permissions: ['media.search'] },
    { path: '/assets/competitors', label: '竞品素材', permissions: ['competitor.view', 'media.upload'] },
  ] },
]

export function visibleSections(has: (permission: string) => boolean): NavigationSection[] {
  return sections.map(section => ({ ...section, items: section.items.filter(item => item.permissions.some(has)) }))
    .filter(section => section.items.length > 0)
}

export function sectionForPath(path: string): string | undefined {
  if (path === '/knowledge-base' || path === '/file-knowledge') return 'products'
  if (path === '/products' || path.startsWith('/products/')) return 'products'
  if (path === '/assets' || path.startsWith('/assets/')) return 'assets'
  if (path === '/customer-service' || path.startsWith('/customer-service/')) return 'customer'
}

// The registry controls enabled primary tools. Only add independent sub-feature
// entries when the account does not have the primary tool's permission.
export function supplementalEntries(has: (permission: string) => boolean): NavigationItem[] {
  return sections.filter(section => ['products', 'assets'].includes(section.key))
    .flatMap(section => {
      if (section.items[0].permissions.some(has)) return []
      const entry = section.items.slice(1).find(item => item.permissions.some(has))
      return entry ? [{ ...entry, label: section.label }] : []
    })
}

export function backEntry(path: string, has: (permission: string) => boolean): { path: string; label: string } | null {
  const section = visibleSections(has).find(item => item.key === sectionForPath(path))
  const parent = section?.items[0]
  if (!parent || parent.path === path) return null
  return { path: parent.path, label: section!.label }
}

export function businessLandingPath(has: (permission: string) => boolean): string {
  if (has('ai.customer_service')) return '/customer-service'
  return visibleSections(has)[0]?.items[0]?.path || '/no-access'
}
