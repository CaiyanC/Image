import { create } from 'zustand'
import type { User } from '../types'

function isManagement(user: User | null): boolean {
  if (!user || !user.groups) return false
  return user.groups.some((g) => g.group_name === '管理层')
}

function readStoredAuth(): Pick<AuthState, 'token' | 'user' | 'isManagement'> {
  if (typeof window === 'undefined') {
    return { token: null, user: null, isManagement: false }
  }
  const token = localStorage.getItem('token')
  const userStr = localStorage.getItem('user')
  if (!token || !userStr) {
    return { token: null, user: null, isManagement: false }
  }
  try {
    const user = JSON.parse(userStr) as User
    return { token, user, isManagement: isManagement(user) }
  } catch {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    return { token: null, user: null, isManagement: false }
  }
}

interface AuthState {
  token: string | null
  user: User | null
  isManagement: boolean
  setAuth: (token: string, user: User) => void
  updateUser: (user: User) => void
  logout: () => void
  loadFromStorage: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  ...readStoredAuth(),
  setAuth: (token, user) => {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
    set({ token, user, isManagement: isManagement(user) })
  },
  updateUser: (user) => {
    localStorage.setItem('user', JSON.stringify(user))
    set({ user, isManagement: isManagement(user) })
  },
  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    set({ token: null, user: null, isManagement: false })
  },
  loadFromStorage: () => {
    set(readStoredAuth())
  },
}))
