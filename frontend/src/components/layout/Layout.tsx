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
    <div className="min-h-screen bg-gradient-subtle text-apple-text">
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 subtle-grid" />
        <div className="ambient-orb absolute -top-32 -right-28 h-[28rem] w-[28rem] bg-cyan-300/30" />
        <div className="ambient-orb absolute left-[-10rem] top-1/3 h-[24rem] w-[24rem] bg-amber-300/28" />
        <div className="ambient-orb absolute bottom-[-12rem] right-1/4 h-[26rem] w-[26rem] bg-emerald-300/22" />
      </div>
      <Header />
      <main className="relative z-10 pt-28 md:pt-20">
        {children}
      </main>
    </div>
  )
}
