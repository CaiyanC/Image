import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Layout from './components/layout/Layout'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Workspace = lazy(() => import('./pages/Workspace'))
const History = lazy(() => import('./pages/History'))
const AdminUsers = lazy(() => import('./pages/AdminUsers'))
const AdminSettings = lazy(() => import('./pages/AdminSettings'))
const AdminGroups = lazy(() => import('./pages/AdminGroups'))
const AdminLogs = lazy(() => import('./pages/AdminLogs'))
const ProductManagement = lazy(() => import('./pages/ProductManagement'))
const CustomerService = lazy(() => import('./pages/CustomerService'))
const ProductCreate = lazy(() => import('./pages/ProductCreate'))
const DraftBox = lazy(() => import('./pages/DraftBox'))
const Profile = lazy(() => import('./pages/Profile'))

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function SuperAdminRoute({ children }: { children: React.ReactNode }) {
  const { token, isManagement } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!isManagement) return <Navigate to="/history" replace />
  return <>{children}</>
}

function hasTeamAccess(user: ReturnType<typeof useAuthStore.getState>['user'], isManagement: boolean) {
  if (isManagement) return true
  if (user?.permissions?.includes('product.read')) return true
  return !!user?.groups?.some(
    (g) => g.group_name === '产品团队' || g.group_name === '设计团队'
  )
}

function hasWorkspaceAccess(user: ReturnType<typeof useAuthStore.getState>['user'], isManagement: boolean) {
  if (isManagement) return true
  return !!user?.permissions?.includes('ai.call')
}

function TeamRoute({ children }: { children: React.ReactNode }) {
  const { token, isManagement, user } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!hasTeamAccess(user, isManagement)) return <Navigate to="/history" replace />
  return <>{children}</>
}

function WorkspaceRoute({ children }: { children: React.ReactNode }) {
  const { token, isManagement, user } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  if (!hasWorkspaceAccess(user, isManagement)) return <Navigate to="/history" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <WorkspaceRoute>
              <Layout>
                <Workspace />
              </Layout>
            </WorkspaceRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <Layout>
                <History />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <Layout>
                <Profile />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/products"
          element={
            <TeamRoute>
              <Layout>
                <ProductManagement />
              </Layout>
            </TeamRoute>
          }
        />
        <Route
          path="/customer-service"
          element={
            <WorkspaceRoute>
              <Layout>
                <CustomerService />
              </Layout>
            </WorkspaceRoute>
          }
        />
        <Route
          path="/products/create"
          element={
            <TeamRoute>
              <Layout>
                <ProductCreate />
              </Layout>
            </TeamRoute>
          }
        />
        <Route
          path="/products/create/:draftId"
          element={
            <TeamRoute>
              <Layout>
                <ProductCreate />
              </Layout>
            </TeamRoute>
          }
        />
        <Route
          path="/products/edit/:sku"
          element={
            <TeamRoute>
              <Layout>
                <ProductCreate />
              </Layout>
            </TeamRoute>
          }
        />
        <Route
          path="/products/drafts"
          element={
            <TeamRoute>
              <Layout>
                <DraftBox />
              </Layout>
            </TeamRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminUsers />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/settings"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminSettings />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/groups"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminGroups />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/logs"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminLogs />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

function RouteFallback() {
  return (
    <div className="min-h-screen bg-[#f6f3ee] text-[#2f241d] flex items-center justify-center">
      <div className="px-6 py-4 rounded-2xl border border-[#d9c9b8] bg-white/80 text-sm tracking-[0.02em]">
        页面加载中...
      </div>
    </div>
  )
}
