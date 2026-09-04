import { create } from 'zustand'
import { api } from '../services/api'
import type { User } from '../types'

function isManagement(user: User | null): boolean {
  return !!user?.permissions?.includes('system.admin')
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
}

let bootstrapPromise: Promise<void> | null = null

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  authenticated: false,
  initialized: false,
  isManagement: false,
  setAuth: (user) => {
    set({ user, authenticated: true, initialized: true, isManagement: isManagement(user) })
  },
  updateUser: (user) => {
    set({ user, authenticated: true, isManagement: isManagement(user) })
  },
  logout: async () => {
    try {
      await api.auth.logout()
    } finally {
      set({ user: null, authenticated: false, initialized: true, isManagement: false })
    }
  },
  bootstrap: async () => {
    if (get().initialized) return
    if (!bootstrapPromise) {
      bootstrapPromise = api.auth.me()
        .then((user) => {
          set({ user, authenticated: true, initialized: true, isManagement: isManagement(user) })
        })
        .catch(() => {
          set({ user: null, authenticated: false, initialized: true, isManagement: false })
        })
        .finally(() => {
          bootstrapPromise = null
        })
    }
    await bootstrapPromise
  },
}))
