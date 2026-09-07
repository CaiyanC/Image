import { Suspense, lazy, useEffect } from 'react'
import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import { getLandingPath, hasPermission, useAuthStore } from './store/authStore'
import { NO_PERMISSION_EVENT } from './services/permissionFeedback'
import Layout from './components/layout/Layout'
import PermissionToast from './components/PermissionToast'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Workspace = lazy(() => import('./pages/Workspace'))
const History = lazy(() => import('./pages/History'))
const AdminSettings = lazy(() => import('./pages/AdminSettings'))
const AdminAccessControl = lazy(() => import('./pages/AdminAccessControl'))
const AdminLogs = lazy(() => import('./pages/AdminLogs'))
const ProductManagement = lazy(() => import('./pages/ProductManagement'))
const ProductAuditOverview = lazy(() => import('./pages/ProductAuditOverview'))
const ProductFullView = lazy(() => import('./pages/ProductFullView'))
const AssetLibrary = lazy(() => import('./pages/AssetLibrary'))
const AssetSearch = lazy(() => import('./pages/AssetSearch'))
const CustomerService = lazy(() => import('./pages/CustomerService'))
const WorkbuddyCustomerService = lazy(() => import('./pages/WorkbuddyCustomerService'))
const AgentCustomerService = lazy(() => import('./pages/AgentCustomerService'))
const ProductQaCreate = lazy(() => import('./pages/ProductQaCreate'))
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'))
const FileKnowledgeBase = lazy(() => import('./pages/FileKnowledgeBase'))
const ProductCreate = lazy(() => import('./pages/ProductCreate'))
const DraftBox = lazy(() => import('./pages/DraftBox'))
const Profile = lazy(() => import('./pages/Profile'))
const ToolCenter = lazy(() => import('./pages/ToolCenter'))
const EcommerceDataFill = lazy(() => import('./pages/EcommerceDataFill'))
const AdminTools = lazy(() => import('./pages/AdminTools'))
const AdminDepartmentWorkbench = lazy(() => import('./pages/AdminDepartmentWorkbench'))
const AdminModelGovernance = lazy(() => import('./pages/AdminModelGovernance'))

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { authenticated } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

function SuperAdminRoute({ children }: { children: React.ReactNode }) {
  const { authenticated, isManagement } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  if (!isManagement) return <Navigate to="/no-access" replace />
  return <>{children}</>
}

function PermissionRoute({
  permissionKey,
  fallback = '/no-access',
  children,
}: {
  permissionKey: string
  fallback?: string
  children: React.ReactNode
}) {
  const { authenticated, user } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  if (!hasPermission(user, permissionKey)) return <Navigate to={fallback} replace />
  return <>{children}</>
}

function AnyPermissionRoute({
  permissionKeys,
  fallback = '/no-access',
  children,
}: {
  permissionKeys: string[]
  fallback?: string
  children: React.ReactNode
}) {
  const { authenticated, user } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  if (!permissionKeys.some((key) => hasPermission(user, key))) {
    return <Navigate to={fallback} replace />
  }
  return <>{children}</>
}

export default function App() {
  const { bootstrap, initialized, authenticated, refreshAuth, clearAuth, user } = useAuthStore()
  const location = useLocation()

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    if (initialized && authenticated) void refreshAuth()
  }, [initialized, authenticated, location.pathname, refreshAuth])

  useEffect(() => {
    const check = () => {
      if (document.visibilityState === 'visible') void refreshAuth()
    }
    const denied = () => { void refreshAuth(true) }
    window.addEventListener('auth:unauthorized', clearAuth)
    window.addEventListener(NO_PERMISSION_EVENT, denied)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    const timer = window.setInterval(check, 60000)
    return () => {
      window.removeEventListener('auth:unauthorized', clearAuth)
      window.removeEventListener(NO_PERMISSION_EVENT, denied)
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
      window.clearInterval(timer)
    }
  }, [refreshAuth, clearAuth])

  if (!initialized) return <RouteFallback />

  return (
    <>
      <PermissionToast />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <PermissionRoute permissionKey="ai.generate">
              <Layout>
                <Workspace />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/tools"
          element={
            <PermissionRoute permissionKey="tools.view">
              <Layout>
                <ToolCenter />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/tools/ecommerce-data-fill"
          element={
            <PermissionRoute permissionKey="finance.ecommerce_data_fill">
              <Layout>
                <EcommerceDataFill />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/history"
          element={
            <PermissionRoute permissionKey="history.view">
              <Layout>
                <History />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <PermissionRoute permissionKey="profile.view">
              <Layout>
                <Profile />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/no-access"
          element={
            <ProtectedRoute>
              <Layout>
                <NoAccess />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/products"
          element={
            <PermissionRoute permissionKey="product.read">
              <Layout>
                <ProductManagement />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/assets"
          element={
            <PermissionRoute permissionKey="media.read">
              <Layout>
                <AssetLibrary />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/assets/search"
          element={
            <PermissionRoute permissionKey="media.search">
              <Layout>
                <AssetSearch />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/customer-service"
          element={
            <PermissionRoute permissionKey="ai.customer_service">
              <Layout>
                <CustomerService />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/products/audit"
          element={
            <PermissionRoute permissionKey="product.audit.view">
              <Layout>
                <ProductAuditOverview />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/products/full-view"
          element={
            <PermissionRoute permissionKey="product.full.view">
              <Layout>
                <ProductFullView />
              </Layout>
            </PermissionRoute>
          }
        />
        {import.meta.env.MODE === 'dev' && (
          <Route
            path="/customer-service/workbuddy"
            element={
              <PermissionRoute permissionKey="ai.customer_service">
                <Layout>
                  <WorkbuddyCustomerService />
                </Layout>
              </PermissionRoute>
            }
          />
        )}
        <Route
          path="/customer-service/agent"
          element={
            <PermissionRoute permissionKey="ai.customer_service">
              <Layout>
                <AgentCustomerService />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/knowledge-base"
          element={
            <PermissionRoute permissionKey="knowledge.manage">
              <Layout>
                <KnowledgeBase />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/file-knowledge"
          element={
            <PermissionRoute permissionKey="knowledge.files.manage">
              <Layout>
                <FileKnowledgeBase />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/products/create"
          element={
            <PermissionRoute permissionKey="product.create" fallback="/products">
              <Layout>
                <ProductCreate />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/products/create/:draftId"
          element={
            <AnyPermissionRoute permissionKeys={['product.create', 'product.edit']}>
              <Layout>
                <ProductCreate />
              </Layout>
            </AnyPermissionRoute>
          }
        />
        <Route
          path="/products/edit/:sku"
          element={
            <PermissionRoute permissionKey="product.edit" fallback="/products">
              <Layout>
                <ProductCreate />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/products/qa/new"
          element={
            <AnyPermissionRoute permissionKeys={['product.qa.manage', 'product.edit']}>
              <Layout>
                <ProductQaCreate />
              </Layout>
            </AnyPermissionRoute>
          }
        />
        <Route
          path="/products/drafts"
          element={
            <AnyPermissionRoute permissionKeys={['product.read', 'product.create', 'product.edit']}>
              <Layout>
                <DraftBox />
              </Layout>
            </AnyPermissionRoute>
          }
        />
        <Route
          path="/admin/department-workbench"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminDepartmentWorkbench />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/tools"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminTools />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/admin/access-control"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminAccessControl />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route path="/admin/users" element={<Navigate to="/admin/access-control" replace />} />
        <Route
          path="/admin/model-governance"
          element={
            <SuperAdminRoute>
              <Layout>
                <AdminModelGovernance />
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
        <Route path="/admin/groups" element={<Navigate to="/admin/access-control" replace />} />
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
        <Route path="*" element={<Navigate to={authenticated ? getLandingPath(user) : '/login'} replace />} />
        </Routes>
      </Suspense>
    </>
  )
}

function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-subtle text-apple-text">
      <div className="glass px-6 py-4 text-sm font-bold tracking-[0.02em]">
        页面加载中...
      </div>
    </div>
  )
}

function NoAccess() {
  const { user, refreshAuth } = useAuthStore()
  const landingPath = getLandingPath(user)
  return (
    <div className="flex min-h-[calc(100vh-7rem)] items-center justify-center px-4 md:min-h-[calc(100vh-5rem)]">
      <div className="auth-card glass p-8 max-w-md w-full text-center">
        <div className="relative z-10">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-accent text-lg font-black text-white shadow-[0_14px_28px_rgba(15,118,110,0.22)]">
            !
          </div>
          <h1 className="text-xl font-black text-apple-text">没有访问权限</h1>
          <p className="text-sm text-apple-gray-medium mt-2">
            当前账号没有访问该页面的权限，请联系总经办或 IT 部管理员调整所在部门权限。
          </p>
          <div className="mt-5 flex justify-center gap-4 text-sm font-bold text-teal-700">
            <button onClick={() => void refreshAuth(true)}>刷新权限</button>
            {landingPath !== '/no-access' && <Link to={landingPath}>前往可用页面</Link>}
          </div>
        </div>
      </div>
    </div>
  )
}
