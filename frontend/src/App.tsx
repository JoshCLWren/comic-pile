import { lazy, Suspense, createContext, useContext, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Navigation from './components/Navigation'
import api, { clearAccessToken, setAccessToken } from './services/api'
import type { AuthUser } from './types'
import { ToastProvider } from './contexts/ToastContext'
import { CacheProvider } from './contexts/CacheContext'
import './index.css'

declare global {
  interface Window {
    __COMIC_PILE_ACCESS_TOKEN?: string
  }
}

const RollPage = lazy(() => import('./pages/RollPage'))
const QueuePage = lazy(() => import('./pages/QueuePage'))
const ThreadDetailView = lazy(() => import('./pages/ThreadDetailView'))
const HistoryPage = lazy(() => import('./pages/HistoryPage'))
const SessionPage = lazy(() => import('./pages/SessionPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const HelpPage = lazy(() => import('./pages/HelpPage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))
const RegisterPage = lazy(() => import('./pages/RegisterPage'))

export interface AuthContextValue {
  isAuthenticated: boolean
  isLoading: boolean
  user: AuthUser | null
  login: (accessToken: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [user, setUser] = useState<AuthUser | null>(null)

  useEffect(() => {
    let isMounted = true
    const authChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('comic-pile-auth') : null

    const validateSession = async () => {
      if (window.__COMIC_PILE_ACCESS_TOKEN) {
        setAccessToken(window.__COMIC_PILE_ACCESS_TOKEN)
        delete window.__COMIC_PILE_ACCESS_TOKEN
      }
      try {
        const response = await api.get<AuthUser>('/auth/me')
        if (isMounted) {
          setUser(response)
          setIsAuthenticated(true)
        }
      } catch {
        if (isMounted) {
          clearAccessToken()
          setIsAuthenticated(false)
          setUser(null)
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    if (authChannel) {
      authChannel.onmessage = (event: MessageEvent<{ type?: string }>) => {
        if (event.data?.type === 'logout') {
          clearAccessToken()
          setIsAuthenticated(false)
          setUser(null)
        }
      }
    }

    validateSession()
    return () => {
      isMounted = false
      authChannel?.close()
    }
  }, [])

  const login = async (accessToken: string) => {
    setAccessToken(accessToken)
    try {
      const response = await api.get<AuthUser>('/auth/me')
      setUser(response)
      setIsAuthenticated(true)
    } catch (error) {
      clearAccessToken()
      setIsAuthenticated(false)
      setUser(null)
      throw error
    }
  }

  const logout = () => {
    clearAccessToken()
    setIsAuthenticated(false)
    setUser(null)
    if (typeof BroadcastChannel !== 'undefined') {
      const authChannel = new BroadcastChannel('comic-pile-auth')
      authChannel.postMessage({ type: 'logout' })
      authChannel.close()
    }
  }

  const value = { isAuthenticated, isLoading, user, login, logout }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="text-center text-stone-500">Checking authentication...</div>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return children
}

function PublicRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="text-center text-stone-500">Loading...</div>
  }

  if (isAuthenticated) {
    const from = location.state?.from?.pathname || '/'
    return <Navigate to={from} replace />
  }

  return children
}

function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <main className="flex-1 container mx-auto px-4 py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-24">
        {children}
      </main>
      <Navigation />
    </div>
  )
}

function PublicLayout({ children }: { children: ReactNode }) {
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
    <Suspense fallback={<div className="text-center text-stone-500">Loading page...</div>}>
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
          path="/thread/:id"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <ThreadDetailView />
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
        <Route
          path="/help"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <HelpPage />
              </AuthenticatedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/glossary"
          element={
            <ProtectedRoute>
              <AuthenticatedLayout>
                <HelpPage />
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
      <ToastProvider>
        <CacheProvider>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </CacheProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}

export { AppRoutes }
export default App
