import { create } from 'zustand'
import { api, ApiRequestError } from '../services/api'
import type { User } from '../types'

export function isManagement(user: User | null): boolean {
  return !!user?.groups?.some((group) =>
    ['总经办', 'IT部'].includes(group.group_name) && group.group_role === 'admin',
  )
}

// Platform administrators receive the complete permission list from auth/me.
// A single assigned system.admin permission must not imply every business grant.
export function hasPermission(user: User | null, permissionKey: string): boolean {
  return !!user?.permissions?.includes(permissionKey)
}

export function getLandingPath(user: User | null): string {
  const destinations = [
    ['ai.generate', '/'],
    ['ai.customer_service', '/customer-service'],
    ['tools.view', '/tools'],
    ['finance.ecommerce_data_fill', '/tools/ecommerce-data-fill'],
    ['product.read', '/products'],
    ['product.qa.manage', '/products/qa/new'],
    ['product.edit', '/products/qa/new'],
    ['product.create', '/products/create'],
    ['product.audit.view', '/products/audit'],
    ['product.full.view', '/products/full-view'],
    ['media.read', '/assets'],
    ['media.search', '/assets/search'],
    ['knowledge.manage', '/knowledge-base'],
    ['knowledge.files.manage', '/file-knowledge'],
    ['history.view', '/history'],
    ['system.admin', '/admin/access-control'],
    ['profile.view', '/profile'],
  ]
  return destinations.find(([permission]) =>
    permission === 'system.admin' ? isManagement(user) : hasPermission(user, permission),
  )?.[1] || '/no-access'
}

interface AuthState {
  user: User | null
  authenticated: boolean
  initialized: boolean
  isManagement: boolean
  setAuth: (user: User) => void
  updateUser: (user: User) => void
  logout: () => Promise<void>
  bootstrap: () => Promise<void>
  refreshAuth: (force?: boolean) => Promise<void>
  clearAuth: () => void
}

let bootstrapPromise: Promise<void> | null = null
let refreshPromise: Promise<void> | null = null
let lastRefreshAt = 0
let sessionVersion = 0

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  authenticated: false,
  initialized: false,
  isManagement: false,
  setAuth: (user) => {
    sessionVersion += 1
    lastRefreshAt = Date.now()
    set({ user, authenticated: true, initialized: true, isManagement: isManagement(user) })
  },
  updateUser: (user) => {
    sessionVersion += 1
    set({ user, authenticated: true, isManagement: isManagement(user) })
  },
  logout: async () => {
    get().clearAuth()
    try {
      await api.auth.logout()
    } finally {
      get().clearAuth()
    }
  },
  clearAuth: () => {
    sessionVersion += 1
    set({ user: null, authenticated: false, initialized: true, isManagement: false })
  },
  refreshAuth: async (force = false) => {
    if (!get().authenticated) return
    if (refreshPromise) return refreshPromise
    // Forced checks (403/manual retry) also have a cooldown to prevent loops.
    if (Date.now() - lastRefreshAt < (force ? 5000 : 30000)) return
    lastRefreshAt = Date.now()
    const version = sessionVersion
    refreshPromise = api.auth.me()
      .then((user) => {
        if (version !== sessionVersion || !get().authenticated) return
        set({ user, isManagement: isManagement(user) })
      })
      .catch((error: unknown) => {
        if (version !== sessionVersion) return
        if (error instanceof ApiRequestError && (error.status === 401 || error.status === 403)) {
          get().clearAuth()
        }
        // A temporary network/server failure is not a logout or a retry loop.
      })
      .finally(() => { refreshPromise = null })
    await refreshPromise
  },
  bootstrap: async () => {
    if (get().initialized) return
    if (!bootstrapPromise) {
      const version = sessionVersion
      lastRefreshAt = Date.now()
      bootstrapPromise = api.auth.me()
        .then((user) => {
          if (version !== sessionVersion) return
          set({ user, authenticated: true, initialized: true, isManagement: isManagement(user) })
        })
        .catch(() => {
          if (version !== sessionVersion) return
          set({ user: null, authenticated: false, initialized: true, isManagement: false })
        })
        .finally(() => {
          bootstrapPromise = null
        })
    }
    await bootstrapPromise
  },
}))
