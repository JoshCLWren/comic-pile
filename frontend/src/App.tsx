import { Suspense, createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './query/queryClient'
import { lazyRoute } from './routes/routeModules'
import { useRoutePrefetch } from './hooks/useRoutePrefetch'
import Navigation from './components/Navigation'
import BugReportButton from './components/BugReportButton'
import type { ReportType } from './components/BugReportModal'
import ResumeRecovery from './components/ResumeRecovery'
import api, { clearAccessToken, setAccessToken, getAccessToken, readStoredAccessToken } from './services/api'
import {
  applyTheme,
  ensureThemeApplied,
  getThemeSelectionToken,
  isSupportedTheme,
  readStoredThemePreference,
} from './services/theme'
import { isDefinitiveAuthenticationFailure } from './services/authFailure'
import { reconcileStoredThemeWithServer } from './services/themePreferenceSync'
import type { AuthTokens, AuthUser } from './types'
import { useBugReport } from './hooks/useBugReport'
import { usePingHeartbeat } from './hooks/usePingHeartbeat'
import { useScrollRestoration } from './hooks/useScrollRestoration'
import type { DiagnosticData } from './hooks/useDiagnostics'
import { ToastProvider } from './contexts/ToastProvider'
import { CacheProvider } from './contexts/CacheContext'
import { BugReportRestoreProvider } from './contexts/BugReportRestoreContext'
import './index.css'

declare global {
  interface Window {
    __COMIC_PILE_ACCESS_TOKEN?: string
  }
}

type BugReportSubmit = (
  reportType: ReportType,
  title: string,
  description: string,
  diagnosticData: DiagnosticData | null,
) => Promise<void>

const AUTH_BOOTSTRAP_TIMEOUT_MS = 15000
const AUTH_BOOTSTRAP_RETRY_DELAY_MS = 1000

async function fetchAndApplyPersistedTheme(timeout?: number): Promise<void> {
  // Capture the local-selection generation before awaiting so a theme picked
  // while this request is in flight always wins over the older server value.
  const selectionTokenAtStart = getThemeSelectionToken()
  try {
    const prefResponse = await api.get<{ theme?: string }>('/v1/users/me/preferences', {
      timeout,
      skipAuthRedirect: true,
    })
    if (getThemeSelectionToken() !== selectionTokenAtStart) {
      return
    }
    const theme = prefResponse?.theme
    if (isSupportedTheme(theme)) {
      const storedTheme = readStoredThemePreference()
      if (storedTheme === null || theme === storedTheme) {
        applyTheme(theme)
      } else {
        // The locally stored choice is newer than the server value (a prior
        // persistence attempt likely failed during an outage, issue #1872).
        // Keep it rendered and quietly converge the server to it.
        ensureThemeApplied()
        reconcileStoredThemeWithServer(storedTheme)
      }
    } else {
      // Unknown/stale ids must not strand the tokens; keep any rendered theme
      // and only seed a default when nothing has been resolved yet.
      ensureThemeApplied()
    }
  } catch {
    // A transient preferences outage (for example 503 during a database
    // blip, issue #1611) must never reset the rendered theme to classic.
    // Keep whatever is applied; seed the stored choice/default only when the
    // document has no valid theme yet.
    ensureThemeApplied()
  }
}

const RollPage = lazyRoute('roll')
const QueuePage = lazyRoute('queue')
const ThreadDetailView = lazyRoute('threadDetail')
const HistoryPage = lazyRoute('history')
const SessionPage = lazyRoute('session')
const CrossoversPage = lazyRoute('crossovers')
const CrossoverDetailPage = lazyRoute('crossoverDetail')
const ContinuityPlannerPage = lazyRoute('continuityPlanner')
const ContinuityPlansIndexPage = lazyRoute('continuityPlansIndex')
const HelpPage = lazyRoute('help')
const WhatsNewPage = lazyRoute('whatsNew')
const LoginPage = lazyRoute('login')
const RegisterPage = lazyRoute('register')
const IdentityInboxPage = lazyRoute('identityInbox')

export interface AuthContextValue {
  isAuthenticated: boolean
  isLoading: boolean
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
  const [user, setUser] = useState<AuthUser | null>(null)
  const recoveryPromise = useRef<Promise<void> | null>(null)

  const markDefinitivelyUnauthenticated = useCallback(() => {
    clearAccessToken()
    setIsAuthenticated(false)
    setUser(null)
  }, [])

  const recoverSession = useCallback((timeout?: number): Promise<void> => {
    if (!recoveryPromise.current) {
      recoveryPromise.current = (async () => {
        try {
          const tokens = await api.post<AuthTokens>('/v1/auth/refresh', undefined, {
            skipAuthRedirect: true,
          })
          setAccessToken(tokens.access_token)
          const response = await api.get<AuthUser>('/v1/auth/me', {
            timeout,
            skipAuthRedirect: true,
          })
          setUser(response)
          setIsAuthenticated(true)
        } catch (error) {
          if (isDefinitiveAuthenticationFailure(error)) {
            markDefinitivelyUnauthenticated()
          }
          throw error
        }
        await fetchAndApplyPersistedTheme(timeout)
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
        // Resolve the persisted theme after the user is loaded
        await fetchAndApplyPersistedTheme(AUTH_BOOTSTRAP_TIMEOUT_MS)
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
        }

        if (!isMounted) {
          return
        }
        retryTimer = window.setTimeout(() => {
          void validateSession()
        }, AUTH_BOOTSTRAP_RETRY_DELAY_MS)
      }
    }
    if (authChannel) {
      authChannel.onmessage = (event: MessageEvent<{ type?: string }>) => {
        if (event.data?.type === 'logout') {
          markDefinitivelyUnauthenticated()
          setIsLoading(false)
        }
      }
    }
    void validateSession()
    return () => {
      isMounted = false
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer)
      }
      authChannel?.close()
    }
  }, [markDefinitivelyUnauthenticated, recoverSession])

  const login = async (accessToken: string) => {
    setAccessToken(accessToken)
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', { skipAuthRedirect: true })
      setUser(response)
      setIsAuthenticated(true)
      void fetchAndApplyPersistedTheme()
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

  return <AuthContext.Provider value={{ isAuthenticated, isLoading, user, login, logout, revalidateSession, recoverSession }}>{children}</AuthContext.Provider>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Checking authentication...</div>
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
  return <div className="flex min-h-screen" data-app-shell-ready><main className={`flex-1 container mx-auto px-3 md:px-4 py-4 md:py-6 ${maxWidthClass} pb-28 md:ml-56 md:pb-6`}>{children}</main><Navigation onBugReportSubmit={onBugReportSubmit} /></div>
}

function PublicLayout({ children, onBugReportSubmit }: { children: ReactNode; onBugReportSubmit: BugReportSubmit }) {
  return <div className="min-h-screen" data-app-shell-ready><main className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-lg md:max-w-2xl lg:max-w-4xl xl:max-w-5xl pb-28">{children}</main><Navigation onBugReportSubmit={onBugReportSubmit} /></div>
}

function BugReportConnected({ onSubmit }: { onSubmit: BugReportSubmit }) {
  return <div className="hidden md:block"><BugReportButton onSubmit={onSubmit} /></div>
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
        <Route path="/history" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><HistoryPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/sessions/:id" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><SessionPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/crossovers" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><CrossoversPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/crossovers/:group" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><CrossoverDetailPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlansIndexPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans/new" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlannerPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/continuity-plans/:id" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><ContinuityPlannerPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/whats-new" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><WhatsNewPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/help" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><HelpPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/identity-inbox" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><IdentityInboxPage /></AuthenticatedLayout></ProtectedRoute>} />
        <Route path="/glossary" element={<ProtectedRoute><AuthenticatedLayout onBugReportSubmit={submit}><HelpPage /></AuthenticatedLayout></ProtectedRoute>} />
      </Routes>
      {isAuthenticated && <BugReportConnected onSubmit={submit} />}
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
  return <BrowserRouter><QueryClientProvider client={queryClient}><BugReportRestoreProvider><ToastProvider><CacheProvider><AuthProvider><AuthResumeBoundary><AppRoutes /></AuthResumeBoundary></AuthProvider></CacheProvider></ToastProvider></BugReportRestoreProvider></QueryClientProvider></BrowserRouter>
}

export { AppRoutes }
export default App
