import { lazy, Suspense, createContext, useContext, useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Navigation from './components/Navigation'
import Sidebar from './components/Sidebar'
import './index.css'

const RollPage = lazy(() => import('./pages/RollPage'))
const QueuePage = lazy(() => import('./pages/QueuePage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const SessionPage = lazy(() => import('./pages/SessionPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))

const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('auth_token')
    setIsAuthenticated(!!token)
    setIsLoading(false)

    const handleStorageChange = (event) => {
      if (event.key === 'auth_token' || event.key === null) {
        const newToken = localStorage.getItem('auth_token')
        setIsAuthenticated(!!newToken)
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

  const login = (accessToken, refreshToken = null) => {
    localStorage.setItem('auth_token', accessToken)
    if (refreshToken) {
      localStorage.setItem('refresh_token', refreshToken)
    }
    setIsAuthenticated(true)
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('refresh_token')
    setIsAuthenticated(false)
  }

  const value = { isAuthenticated, isLoading, login, logout }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function ProtectedRoute({ children }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="text-center text-slate-500">Checking authentication...</div>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return children
}

function PublicRoute({ children }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="text-center text-slate-500">Loading...</div>
  }

  if (isAuthenticated) {
    const from = location.state?.from?.pathname || '/'
    return <Navigate to={from} replace />
  }

  return children
}

function AppLayout({ children }) {
  const { isAuthenticated } = useAuth()
  
  return (
    <div className="flex min-h-screen">
      {isAuthenticated && <Sidebar />}
      <main className={`flex-1 container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24 ${isAuthenticated ? 'lg:ml-64' : ''}`}>
        {children}
      </main>
      <Navigation />
    </div>
  )
}

function AppRoutes() {
  return (
    <AppLayout>
      <Suspense fallback={<div className="text-center text-slate-500">Loading page...</div>}>
        <Routes>
          <Route
            path="/login"
            element={
              <PublicRoute>
                <LoginPage />
              </PublicRoute>
            }
          />
          <Route
            path="/register"
            element={
              <PublicRoute>
                <RegisterPage />
              </PublicRoute>
            }
          />
          <Route
            path="/rate"
            element={<Navigate to="/" replace />}
          />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <RollPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/queue"
            element={
              <ProtectedRoute>
                <QueuePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/history"
            element={
              <ProtectedRoute>
                <HistoryPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/sessions/:id"
            element={
              <ProtectedRoute>
                <SessionPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/analytics"
            element={
              <ProtectedRoute>
                <AnalyticsPage />
              </ProtectedRoute>
            }
          />
        </Routes>
      </Suspense>
    </AppLayout>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export { AppRoutes }
export default App
