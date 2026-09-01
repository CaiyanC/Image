import { Suspense, lazy, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Layout from './components/layout/Layout'
import PermissionToast from './components/PermissionToast'

const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Workspace = lazy(() => import('./pages/Workspace'))
const History = lazy(() => import('./pages/History'))
const AdminUsers = lazy(() => import('./pages/AdminUsers'))
const AdminSettings = lazy(() => import('./pages/AdminSettings'))
const AdminGroups = lazy(() => import('./pages/AdminGroups'))
const AdminLogs = lazy(() => import('./pages/AdminLogs'))
const ProductManagement = lazy(() => import('./pages/ProductManagement'))
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

function hasPermission(
  user: ReturnType<typeof useAuthStore.getState>['user'],
  isManagement: boolean,
  permissionKey: string,
) {
  if (isManagement) return true
  return !!user?.permissions?.includes(permissionKey)
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
  const { authenticated, isManagement, user } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  if (!hasPermission(user, isManagement, permissionKey)) return <Navigate to={fallback} replace />
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
  const { authenticated, isManagement, user } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  if (!isManagement && !permissionKeys.some((key) => hasPermission(user, isManagement, key))) {
    return <Navigate to={fallback} replace />
  }
  return <>{children}</>
}

export default function App() {
  const { bootstrap, initialized } = useAuthStore()

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

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
            <ProtectedRoute>
              <Layout>
                <ToolCenter />
              </Layout>
            </ProtectedRoute>
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
            <PermissionRoute permissionKey="product.read">
              <Layout>
                <AssetLibrary />
              </Layout>
            </PermissionRoute>
          }
        />
        <Route
          path="/assets/search"
          element={
            <PermissionRoute permissionKey="product.read">
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
            <SuperAdminRoute>
              <Layout>
                <KnowledgeBase />
              </Layout>
            </SuperAdminRoute>
          }
        />
        <Route
          path="/file-knowledge"
          element={
            <SuperAdminRoute>
              <Layout>
                <FileKnowledgeBase />
              </Layout>
            </SuperAdminRoute>
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
            <PermissionRoute permissionKey="product.create" fallback="/products">
              <Layout>
                <ProductCreate />
              </Layout>
            </PermissionRoute>
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
            <PermissionRoute permissionKey="product.read">
              <Layout>
                <DraftBox />
              </Layout>
            </PermissionRoute>
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
        </div>
      </div>
    </div>
  )
}
