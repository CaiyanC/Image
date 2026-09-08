import Header from './Header'
import BusinessSidebar from './BusinessSidebar'
import SectionNavigation from './SectionNavigation'
import './business.css'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  return (
    <div className="business-shell min-h-screen bg-slate-50 text-slate-900">
      <Header />
      <div className="pt-20"><BusinessSidebar /></div>
      <main className="relative z-10 min-w-0 md:ml-44">
        <SectionNavigation />
        {children}
      </main>
    </div>
  )
}
