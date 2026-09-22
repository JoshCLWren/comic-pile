import { Suspense, createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './query/queryClient'
import { lazyRoute } from './routes/routeModules'
import { useRoutePrefetch } from './hooks/useRoutePrefetch'
import Navigation from './components/Navigation'
import type { ReportType } from './components/BugReportModal'
import ResumeRecovery from './components/ResumeRecovery'
import api, {
  clearAccessToken,
  getAccessToken,
  isSessionRefreshRejected,
  readStoredAccessToken,
  refreshSession,
  setAccessToken,
} from './services/api'
import { isDefinitiveAuthenticationFailure } from './services/authFailure'
import { isServiceUnavailableError } from './services/authFailure'
import type { AuthUser } from './types'
import { useBugReport } from './hooks/useBugReport'
import { usePingHeartbeat } from './hooks/usePingHeartbeat'
import { useScrollRestoration } from './hooks/useScrollRestoration'
import { PreferencesSync } from './hooks/usePreferences'
import type { DiagnosticData } from './hooks/useDiagnostics'
import { ToastProvider } from './contexts/ToastProvider'
import { BugReportRestoreProvider } from './contexts/BugReportRestoreContext'
import { NavCollapseProvider } from './contexts/NavCollapseContext'
import './index.css'

declare global {
  interface Window {
    __COMIC_PILE_ACCESS_TOKEN?: string
  }
}

const AUTH_BOOTSTRAP_TIMEOUT_MS = 15000
const AUTH_BOOTSTRAP_RETRY_DELAY_MS = 1000

type BugReportSubmit = (
  reportType: ReportType,
  title: string,
  description: string,
  diagnosticData: DiagnosticData | null,
) => Promise<void>

const RollPage = lazyRoute('roll')
const QueuePage = lazyRoute('queue')
const ThreadDetailView = lazyRoute('threadDetail')
const CreatorDetailPage = lazyRoute('creatorDetail')
const HistoryPage = lazyRoute('history')
const SessionPage = lazyRoute('session')
const CrossoversPage = lazyRoute('crossovers')
const CrossoverDetailPage = lazyRoute('crossoverDetail')
const ContinuityPlannerPage = lazyRoute('continuityPlanner')
const ContinuityPlansIndexPage = lazyRoute('continuityPlansIndex')
const HelpPage = lazyRoute('glossary')
const WhatsNewPage = lazyRoute('whatsNew')
const LoginPage = lazyRoute('login')
const RegisterPage = lazyRoute('register')
const IdentityInboxPage = lazyRoute('identityInbox')

export interface AuthContextValue {
  isAuthenticated: boolean
  isLoading: boolean
  isServiceUnavailable: boolean
  user: AuthUser | null
  login: (accessToken: string) => Promise<void>
  logout: () => void
  revalidateSession: (timeout?: number) => Promise<void>
  recoverSession: (timeout?: number) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isServiceUnavailable, setIsServiceUnavailable] = useState(false)
  const [user, setUser] = useState<AuthUser | null>(null)
  const recoveryPromise = useRef<Promise<void> | null>(null)
  const navigate = useNavigate()
  const location = useLocation()

  const markDefinitivelyUnauthenticated = useCallback(() => {
    clearAccessToken()
    setIsAuthenticated(false)
    setUser(null)
    setIsServiceUnavailable(false)
  }, [])

  const recoverSession = useCallback((timeout?: number): Promise<void> => {
    if (!recoveryPromise.current) {
      recoveryPromise.current = (async () => {
        try {
          if (isSessionRefreshRejected()) {
            markDefinitivelyUnauthenticated()
            throw Object.assign(new Error('Session refresh unavailable'), {
              isAxiosError: true,
              response: { status: 401 },
            })
          }
          await refreshSession({ skipAuthRedirect: true })
          const response = await api.get<AuthUser>('/v1/auth/me', {
            timeout,
            skipAuthRedirect: true,
          })
          setUser(response)
          setIsAuthenticated(true)
        } catch (error) {
          if (isDefinitiveAuthenticationFailure(error)) {
            markDefinitivelyUnauthenticated()
          } else if (isServiceUnavailableError(error)) {
            setIsServiceUnavailable(true)
          }
          throw error
        }
      })().finally(() => {
        recoveryPromise.current = null
      })
    }

    return recoveryPromise.current
  }, [markDefinitivelyUnauthenticated])

  const revalidateSession = useCallback(async (timeout?: number) => {
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', {
        timeout,
        skipAuthRedirect: true,
      })
      setUser(response)
      setIsAuthenticated(true)
    } catch (error) {
      if (isDefinitiveAuthenticationFailure(error)) {
        // The persistent session can usually be renewed silently with the
        // refresh cookie. Only treat the user as logged out when that also fails.
        try {
          await recoverSession(timeout)
          return
        } catch (recoveryError) {
          if (isDefinitiveAuthenticationFailure(recoveryError)) {
            markDefinitivelyUnauthenticated()
          }
        }
      }
      throw error
    }
  }, [markDefinitivelyUnauthenticated, recoverSession])

  useEffect(() => {
    let isMounted = true
    let retryTimer: number | undefined
    const authChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('comic-pile-auth') : null

    // Periodic retry loop when service is temporarily unavailable
    const unavailableInterval = setInterval(async () => {
      if (!isMounted || !isServiceUnavailable) {
        clearInterval(unavailableInterval)
        return
      }
      try {
        await validateSession()
        if (isMounted && isServiceUnavailable) {
          setIsServiceUnavailable(false)
          if (location.state?.from) {
            navigate(location.state.from.pathname, { replace: true })
          } else {
            navigate('/', { replace: true })
          }
        }
      } catch () {
        // Ignore errors during retry, keep polling
      }
    }, 5000)

    const validateSession = async () => {
      const isPublicAuthPage = window.location.pathname === '/login' || window.location.pathname === '/register'
      if (!getAccessToken() && !window.__COMIC_PILE_ACCESS_TOKEN && isPublicAuthPage) {
        setIsLoading(false)
        return
      }
      if (window.__COMIC_PILE_ACCESS_TOKEN) {
        setAccessToken(window.__COMIC_PILE_ACCESS_TOKEN)
        delete window.__COMIC_PILE_ACCESS_TOKEN
      } else if (!getAccessToken()) {
        const storedToken = readStoredAccessToken()
        if (storedToken) {
          setAccessToken(storedToken)
        }
      }
      try {
        const response = await api.get<AuthUser>('/v1/auth/me', {
          timeout: AUTH_BOOTSTRAP_TIMEOUT_MS,
          skipAuthRedirect: true,
        })
        if (isMounted) {
          setUser(response)
          setIsAuthenticated(true)
        }
        if (isMounted) {
          setIsLoading(false)
        }
      } catch (error) {
        if (!isMounted) {
          return
        }
        if (isDefinitiveAuthenticationFailure(error)) {
          // A stale or expired access token is routine on a return visit. Try to
          // renew the session silently with the refresh cookie before surfacing
          // the login screen for a single-user app.
          try {
            await recoverSession(AUTH_BOOTSTRAP_TIMEOUT_MS)
            if (isMounted) {
              setIsLoading(false)
            }
            return
          } catch (recoveryError) {
            if (isDefinitiveAuthenticationFailure(recoveryError)) {
              markDefinitivelyUnauthenticated()
              setIsLoading(false)
              return
            }
          }
        } else if (isServiceUnavailableError(error)) {
          // The database backend is temporarily unavailable. Keep the user's
          // authenticated session visible and show a degraded state rather than
          // forcing a login loop.
          setIsServiceUnavailable(true)
          if (isMounted) {
            setIsLoading(false)
          }
          return
        }

        if (!isMounted) {
          return
        }
        retryTimer = window.setTimeout(() => {
          void validateSession()
        }, AUTH_BOOTSTRAP_RETRY_DELAY_MS)
      }
    }

    void validateSession()

    if (authChannel) {
      authChannel.onmessage = (event: MessageEvent<{ type?: string }>) => {
        if (event.data?.type === 'logout') {
          markDefinitivelyUnauthenticated()
          setIsLoading(false)
        }
      }
    }

    return () => {
      isMounted = false
      clearInterval(unavailableInterval)
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer)
      }
      authChannel?.close()
    }
  }, [isServiceUnavailable, location.state?.from, navigate, markDefinitivelyUnauthenticated, recoverSession])

  const login = async (accessToken: string) => {
    setAccessToken(accessToken)
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', { skipAuthRedirect: true })
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
    markDefinitivelyUnauthenticated()
    if (typeof BroadcastChannel !== 'undefined') {
      const authChannel = new BroadcastChannel('comic-pile-auth')
      authChannel.postMessage({ type: 'logout' })
      authChannel.close()
    }
  }

  return <AuthContext.Provider value={{ isAuthenticated, isLoading, isServiceUnavailable, user, login, logout, revalidateSession, recoverSession }}>{children}</AuthContext.Provider>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, isServiceUnavailable } = useAuth()
  const location = useLocation()
  if (isLoading) return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Checking authentication...</div>
  if (isServiceUnavailable) return <div className="min-h-screen flex flex-col items-center justify-center text-center text-stone-500">ComicPile is temporarily unavailable. Please try again in a moment.</div>
  if (!isAuthenticated) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}

function PublicRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Loading...</div>
  if (isAuthenticated) return <Navigate to={location.state?.from?.pathname || '/'} replace />
  return children
}

function AuthenticatedLayout({ children, onBugReportSubmit, wide = false }: { children: ReactNode; onBugReportSubmit: BugReportSubmit; wide?: boolean }) {
  const maxWidthClass = wide ? 'max-w-lg md:max-w-2xl lg:max-w-5xl xl:max-w-[1536px]' : 'max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl';
  return (
    <div
      className="min-h-screen md:grid md:grid-cols-[auto_minmax(0,1fr)]"
      data-app-shell-ready
      data-authenticated-shell
    >
      <Navigation onBugReportSubmit={onBugReportSubmit} />
      <main className={`container mx-auto min-w-0 px-3 md:px-4 py-4 md:py-6 ${maxWidthClass} pb-28 md:pb-6`}>
        <PreferencesSync isAuthenticated={true} />
        {children}
      </main>
    </div>
  )
}

function PublicLayout({ children, onBugReportSubmit }: { children: ReactNode; onBugReportSubmit: BugReportSubmit }) {
  return <div className="min-h-screen" data-app-shell-ready><main className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-28">{children}</main><Navigation onBugReportSubmit={onBugReportSubmit} /></div>
}

function RouteChunkPrefetcher({ enabled }: { enabled: boolean }) {
  useRoutePrefetch(enabled)
  return null
}

function AppRoutes() {
  const { submit } = useBugReport()
  const { isAuthenticated } = useAuth()
  useScrollRestoration()
  return (
    <Suspense fallback={<div className="text-center text-stone-500">Loading page...</div>}>
      <RouteChunkPrefetcher enabled={isAuthenticated} />
      <Routes>
        <Route path="/login" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><LoginPage /></PublicLayout></PublicRoute>} />
        <Route path="/register" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><RegisterPage /></PublicLayout></PublicRoute>} />
        <Route path="/rate" element={<Navigate to="/" replace />} />
        <Route path="/analytics" element={<Navigate to="/" replace />} />
        <Route path="/" element={<ProtectedRoute><AuthenticatedLayout wide onBugReportSubmit={submit}><RollPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/queue" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><QueuePage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/thread/:id" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ThreadDetailView /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/creators/:creatorKey" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><CreatorDetailPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/history" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><HistoryPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/sessions/:id" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><SessionPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/crossovers" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><CrossoversPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/crossovers/:group" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><CrossoverDetailPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlansIndexPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans/new" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlannerPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans/:id" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlannerPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/whats-new" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><WhatsNewPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/glossary" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><HelpPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/help" element={<Navigate to="/glossary" replace />} />
        <Route path="/identity-inbox" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><IdentityInboxPage /></AuthenticatedLayout></ProtectedRoute>} />
      </Routes>
    </Suspense>
  )
}

function AuthResumeBoundary({ children }: { children: ReactNode }) {
  const { revalidateSession, recoverSession } = useAuth()
  return (
    <ResumeRecovery revalidateSession={revalidateSession} recoverSession={recoverSession}>
      {children}
    </ResumeRecovery>
  )
}

function App() {
  usePingHeartbeat()
  return <BrowserRouter><QueryClientProvider client={queryClient}><BugReportRestoreProvider><ToastProvider><AuthProvider><NavCollapseProvider><AuthResumeBoundary><AppRoutes /></AuthResumeBoundary></NavCollapseProvider></AuthProvider></ToastProvider></BugReportRestoreProvider></QueryClientProvider></BrowserRouter>
}

export { AppRoutes }
export default App