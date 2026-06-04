import { useEffect } from 'react'
import { useAuthStore } from '../../store/authStore'
import Header from './Header'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { loadFromStorage } = useAuthStore()

  useEffect(() => {
    loadFromStorage()
  }, [])

  return (
    <div className="min-h-screen bg-gradient-subtle">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -right-40 w-96 h-96 rounded-full bg-blue-400/10 blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 rounded-full bg-purple-400/10 blur-3xl" />
      </div>
      <Header />
      <main className="pt-14 relative z-10">
        {children}
      </main>
    </div>
  )
}
