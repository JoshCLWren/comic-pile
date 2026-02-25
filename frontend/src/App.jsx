import { lazy, Suspense, createContext, useContext, useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Navigation from './components/Navigation'
import Sidebar from './components/Sidebar'
import api from './services/api'
import './index.css'

const RollPage = lazy(() => import('./pages/RollPage'))
const QueuePage = lazy(() => import('./pages/QueuePage'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const SessionPage = lazy(() => import('./pages/SessionPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))

const AuthContext = createContext(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}

export function AuthProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [user, setUser] = useState(null)

  useEffect(() => {
    let isMounted = true

    const validateToken = async () => {
      const token = localStorage.getItem('auth_token')

      if (!token) {
        if (isMounted) {
          setIsAuthenticated(false)
          setIsLoading(false)
        }
        return
      }

      try {
        const response = await api.get('/auth/me')
        if (isMounted) {
          setUser(response)
          setIsAuthenticated(true)
        }
      } catch {
        if (isMounted) {
          localStorage.removeItem('auth_token')
          localStorage.removeItem('refresh_token')
          setIsAuthenticated(false)
          setUser(null)
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    validateToken()

    const handleStorageChange = (event) => {
      if (event.key === 'auth_token' || event.key === null) {
        const newToken = localStorage.getItem('auth_token')
        if (!newToken) {
          setIsAuthenticated(false)
          setUser(null)
        }
      }
    }

    window.addEventListener('storage', handleStorageChange)
    return () => {
      isMounted = false
      window.removeEventListener('storage', handleStorageChange)
    }
  }, [])

  const login = async (accessToken, refreshToken = null) => {
    localStorage.setItem('auth_token', accessToken)
    if (refreshToken) {
      localStorage.setItem('refresh_token', refreshToken)
    }
    try {
      const response = await api.get('/auth/me')
      setUser(response)
      setIsAuthenticated(true)
    } catch (error) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('refresh_token')
      setIsAuthenticated(false)
      setUser(null)
      throw error
    }
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('refresh_token')
    setIsAuthenticated(false)
    setUser(null)
  }

  const value = { isAuthenticated, isLoading, user, login, logout }

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

function AuthenticatedLayout({ children }) {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24 lg:ml-64">
        {children}
      </main>
      <Navigation />
    </div>
  )
}

function PublicLayout({ children }) {
  return (
    <div className="min-h-screen">
      <main className="container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24">
        {children}
      </main>
      <Navigation />
    </div>
  )
}

function AppRoutes() {
  return (
    <Suspense fallback={<div className="text-center text-slate-500">Loading page...</div>}>
      <Routes>
        <Route
          path="/login"
          element={
            <PublicRoute>
              <PublicLayout>
                <LoginPage />
              </PublicLayout>
            </PublicRoute>
          }
        />
        <Route
          path="/register"
          element={
            <PublicRoute>
              <PublicLayout>
                <RegisterPage />
              </PublicLayout>
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
              <AuthenticatedLayout>
                <RollPage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/queue"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <QueuePage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <HistoryPage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/sessions/:id"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <SessionPage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/analytics"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <AnalyticsPage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </Suspense>
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
