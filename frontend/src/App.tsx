import { Suspense, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom'
import { QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { queryClient } from './query/queryClient'
import { clearSessionCache, resumeQueriesAfterOutage } from './query/cacheEffects'
import {
  markAuthDegraded,
  markAuthRecovered,
  resetQueryRetryBudget,
} from './query/outageRetryBudget'
import { lazyRoute } from './routes/routeModules'
import Seo from './seo/Seo'
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
import { isDefinitiveAuthenticationFailure, createAuthError, type AuthState, calculateRetryDelay } from './services/authState'
import type { AuthUser } from './types'
import { useBugReport } from './hooks/useBugReport'
import { useScrollRestoration } from './hooks/useScrollRestoration'
import ReadingPlanEditRoute from './pages/ReadingPlanEditRoute'
import { PreferencesSync } from './hooks/usePreferences'
import { useAuthDegradedState, ServiceUnavailableWrapper } from './hooks/useAuthDegradedState'
import type { DiagnosticData } from './hooks/useDiagnostics'
import { ToastProvider } from './contexts/ToastProvider'
import { BugReportRestoreProvider } from './contexts/BugReportRestoreContext'
import { NavCollapseProvider } from './contexts/NavCollapseContext'
import { AuthContext, AuthContextValue, AuthContextLegacyValue, useAuth } from './contexts/AuthContext'
import './index.css'

declare global {
  interface Window {
    __COMIC_PILE_ACCESS_TOKEN?: string
  }
}

const AUTH_BOOTSTRAP_TIMEOUT_MS = 15000
const AUTH_BOOTSTRAP_MAX_RETRIES = 5
const AUTH_RETRY_BASE_DELAY_MS = 1000

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
const CreatorComparisonPage = lazyRoute('creatorComparison')
const CreatorsPage = lazyRoute('creators')
const HistoryPage = lazyRoute('history')
const SessionPage = lazyRoute('session')
const CrossoversPage = lazyRoute('crossovers')
const CrossoverDetailPage = lazyRoute('crossoverDetail')
const ContinuityPlannerPage = lazyRoute('continuityPlanner')
const ContinuityPlansIndexPage = lazyRoute('continuityPlansIndex')
const ReadingPlanDetailPage = lazyRoute('readingPlanDetail')
const ReadingListEditorPage = lazyRoute('readingListEditor')
const CblBrowserPage = lazyRoute('cblBrowser')
const HelpPage = lazyRoute('glossary')
const WhatsNewPage = lazyRoute('whatsNew')
const LoginPage = lazyRoute('login')
const RegisterPage = lazyRoute('register')
const ForgotPasswordPage = lazyRoute('forgotPassword')
const ResetPasswordPage = lazyRoute('resetPassword')
const IdentityInboxPage = lazyRoute('identityInbox')
const LandingPage = lazyRoute('landing')
const DemoRollPage = lazyRoute('demoRoll')
const NotFoundPage = lazyRoute('notFound')

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const sessionGeneration = useRef(0)
  const authChannelRef = useRef<BroadcastChannel | null>(null)
  // Synchronous bootstrap retry bookkeeping. The retry scheduler reads the
  // attempt ordinal immediately after deciding to retry, and React is not
  // required to evaluate a state updater synchronously, so the counter must
  // never be derived from `authState`.
  const bootstrapRetryCountRef = useRef(0)
  const bootstrapTimerRef = useRef<number | null>(null)
  // Shared across effect instances so a StrictMode remount joins the probe that
  // is already in flight instead of issuing a duplicate /v1/auth/me request.
  const bootstrapInFlightRef = useRef<Promise<boolean> | null>(null)
  // Automatic retry is enabled while the bootstrap effect owns recovery. A
  // manual "Try again", login, or logout takes ownership so a pending or
  // in-flight automatic attempt cannot race the user's action.
  const bootstrapAutoRetryRef = useRef(false)
  const [authState, setAuthState] = useState<AuthState>({
    status: 'checking',
    isLoading: true,
    user: null,
    error: null,
    retryCount: 0,
    lastRetryAt: null,
  })
  const recoveryPromise = useRef<Promise<void> | null>(null)

  const cancelBootstrapRetry = useCallback(() => {
    if (bootstrapTimerRef.current !== null) {
      window.clearTimeout(bootstrapTimerRef.current)
      bootstrapTimerRef.current = null
    }
  }, [])

  const markDefinitivelyUnauthenticated = useCallback(() => {
    sessionGeneration.current += 1
    cancelBootstrapRetry()
    bootstrapInFlightRef.current = null
    bootstrapRetryCountRef.current = 0
    bootstrapAutoRetryRef.current = false
    recoveryPromise.current = null
    resetQueryRetryBudget()
    clearAccessToken()
    clearSessionCache(client)
    setAuthState(prev => ({
      ...prev,
      status: 'unauthenticated',
      isLoading: false,
      user: null,
      error: null,
      retryCount: 0,
      lastRetryAt: null,
    }))
  }, [cancelBootstrapRetry, client])

  const clearAuthError = useCallback(() => {
    setAuthState(prev => ({
      ...prev,
      error: null,
    }))
  }, [])

  const recoverSession = useCallback(
    (timeout?: number): Promise<void> => {
      if (recoveryPromise.current) return recoveryPromise.current
      const generation = sessionGeneration.current
      const attempt = (async () => {
        try {
          if (isSessionRefreshRejected()) {
            throw Object.assign(new Error('Session refresh unavailable'), {
              isAxiosError: true,
              response: { status: 401 },
            })
          }
          // AuthProvider owns this recovery attempt. Suppress the interceptor's
          // automatic refresh so an exhausted retry cannot rotate the cookie twice.
          const validate = () => api.get<AuthUser>('/v1/auth/me', {
            timeout,
            skipAuthRedirect: true,
            skipAuthRefresh: true,
          })
          let response: AuthUser
          try {
            response = await validate()
          } catch (error) {
            if (generation !== sessionGeneration.current) return
            if (!isDefinitiveAuthenticationFailure(error) || isSessionRefreshRejected()) throw error
            await refreshSession({ skipAuthRedirect: true })
            if (generation !== sessionGeneration.current) return
            response = await validate()
          }
          if (generation !== sessionGeneration.current) return
          // A successful recovery ends the bootstrap outage: a retry scheduled
          // by an older attempt must never fire against a healthy session.
          cancelBootstrapRetry()
          bootstrapRetryCountRef.current = 0
          setAuthState(prev => ({
            ...prev,
            status: 'authenticated',
            isLoading: false,
            user: response,
            error: null,
            retryCount: 0,
            lastRetryAt: null,
          }))
        } catch (error) {
          if (generation !== sessionGeneration.current) return
          if (isDefinitiveAuthenticationFailure(error)) {
            markDefinitivelyUnauthenticated()
          } else {
            const authError = createAuthError(error)
            setAuthState(prev => ({
              ...prev,
              status: authError?.type === 'service_unavailable' ? 'service_unavailable' : 'network_error',
              isLoading: false,
              error: authError,
              retryCount: prev.retryCount + 1,
              lastRetryAt: Date.now(),
            }))
          }
          throw error
        }
      })().finally(() => {
        // A login/logout may have started a different generation's recovery.
        if (recoveryPromise.current === attempt) recoveryPromise.current = null
      })
      recoveryPromise.current = attempt
      return attempt
    }, [cancelBootstrapRetry, markDefinitivelyUnauthenticated])

  const retryAuth = useCallback(async () => {
    // Manual recovery takes over from the automatic budget: cancel the pending
    // timer before touching the recovery promise so the timer and the manual
    // action cannot issue concurrent /v1/auth/me requests for this session.
    cancelBootstrapRetry()
    bootstrapRetryCountRef.current = 0
    bootstrapAutoRetryRef.current = false
    const generation = sessionGeneration.current
    setAuthState(prev => ({
      ...prev,
      isLoading: true,
      error: null,
    }))

    try {
      // If a bootstrap probe is still in flight, wait for it instead of
      // starting a second concurrent request, then recover only if it failed.
      const pendingBootstrap = bootstrapInFlightRef.current
      if (pendingBootstrap) {
        const recovered = await pendingBootstrap
        if (generation !== sessionGeneration.current) return
        if (recovered) return
      }
      await recoverSession(AUTH_BOOTSTRAP_TIMEOUT_MS)
    } catch (error) {
      if (generation === sessionGeneration.current) {
        setAuthState(prev => ({
          ...prev,
          isLoading: false,
          error: createAuthError(error),
        }))
      }
      throw error
    }
  }, [cancelBootstrapRetry, recoverSession])

  const revalidateSession = recoverSession

  useEffect(() => {
    const bootstrapGeneration = sessionGeneration.current
    bootstrapRetryCountRef.current = 0
    bootstrapAutoRetryRef.current = true
    cancelBootstrapRetry()
    const authChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('comic-pile-auth') : null
    authChannelRef.current = authChannel

    const scheduleRetry = (error: unknown) => {
      if (!bootstrapAutoRetryRef.current) return
      if (bootstrapGeneration !== sessionGeneration.current) return
      // Read the synchronous attempt ordinal; never infer it from a React
      // state updater that may not have run yet.
      const currentAttempt = bootstrapRetryCountRef.current
      if (currentAttempt >= AUTH_BOOTSTRAP_MAX_RETRIES) return
      const nextAttempt = currentAttempt + 1
      bootstrapRetryCountRef.current = nextAttempt
      const authError = createAuthError(error)
      setAuthState(prev => ({
        ...prev,
        status: authError?.type === 'service_unavailable' ? 'service_unavailable' : 'network_error',
        isLoading: false,
        error: authError,
        retryCount: nextAttempt,
        lastRetryAt: Date.now(),
      }))
      cancelBootstrapRetry()
      bootstrapTimerRef.current = window.setTimeout(() => {
        bootstrapTimerRef.current = null
        void validateSession()
      }, calculateRetryDelay(nextAttempt, AUTH_RETRY_BASE_DELAY_MS))
    }

    const validateSession = async (): Promise<boolean> => {
      if (bootstrapGeneration !== sessionGeneration.current) return false
      // One coordinated attempt per bootstrap generation: a timer callback and
      // a StrictMode remount must join the in-flight probe, not issue a second.
      if (bootstrapInFlightRef.current) return bootstrapInFlightRef.current
      const isPublicAuthPage = window.location.pathname === '/login' || window.location.pathname === '/register'
      if (!getAccessToken() && !window.__COMIC_PILE_ACCESS_TOKEN && isPublicAuthPage) {
        cancelBootstrapRetry()
        bootstrapRetryCountRef.current = 0
        setAuthState(prev => ({
          ...prev,
          status: 'unauthenticated',
          isLoading: false,
        }))
        return false
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

      const attempt = (async (): Promise<boolean> => {
        try {
          const response = await api.get<AuthUser>('/v1/auth/me', {
            timeout: AUTH_BOOTSTRAP_TIMEOUT_MS,
            skipAuthRedirect: true,
          })
          if (bootstrapGeneration !== sessionGeneration.current) return false
          cancelBootstrapRetry()
          bootstrapRetryCountRef.current = 0
          setAuthState(prev => ({
            ...prev,
            status: 'authenticated',
            isLoading: false,
            user: response,
            error: null,
            retryCount: 0,
            lastRetryAt: null,
          }))
          return true
        } catch (error) {
          if (bootstrapGeneration !== sessionGeneration.current) return false
          
          if (isDefinitiveAuthenticationFailure(error)) {
            // A stale access token is routine on a return visit. Try the
            // refresh cookie before surfacing the login screen.
            try {
              await recoverSession(AUTH_BOOTSTRAP_TIMEOUT_MS)
              if (bootstrapGeneration !== sessionGeneration.current) return false
              cancelBootstrapRetry()
              bootstrapRetryCountRef.current = 0
              return true
            } catch (recoveryError) {
              if (bootstrapGeneration !== sessionGeneration.current) return false
              if (isDefinitiveAuthenticationFailure(recoveryError)) {
                // recoverSession already marked the session unauthenticated.
                return false
              }
              // Transient recovery failure: retry from the transient error so
              // the degraded state reports 503/network instead of a stale 401.
              scheduleRetry(recoveryError)
              return false
            }
          }

          scheduleRetry(error)
          return false
        }
      })()
      bootstrapInFlightRef.current = attempt
      void attempt.then(() => {
        if (bootstrapInFlightRef.current === attempt) bootstrapInFlightRef.current = null
      })
      return attempt
    }

    if (authChannel) {
      authChannel.onmessage = (event: MessageEvent<{ type?: string }>) => {
        if (event.data?.type === 'logout') {
          markDefinitivelyUnauthenticated()
        }
      }
    }
    
    void validateSession()
    
    return () => {
      // Leaving this effect (including StrictMode's simulated remount) stops
      // automatic scheduling; an already in-flight probe is allowed to finish
      // so a remount can join it instead of issuing a duplicate request.
      bootstrapAutoRetryRef.current = false
      cancelBootstrapRetry()
      authChannel?.close()
      if (authChannelRef.current === authChannel) {
        authChannelRef.current = null
      }
    }
  }, [cancelBootstrapRetry, markDefinitivelyUnauthenticated, recoverSession])

  useEffect(() => {
    if (authState.status === 'service_unavailable' || authState.status === 'network_error') {
      // The bootstrap/recovery machinery already probes authentication with its
      // own bounded budget. Independent query retries would multiply that load.
      markAuthDegraded()
      return
    }
    if (authState.status === 'authenticated' && markAuthRecovered()) {
      // Resume the queries that failed while degraded once per distinct key.
      void resumeQueriesAfterOutage(client)
    }
  }, [authState.status, client])

  const login = async (accessToken: string) => {
    const generation = ++sessionGeneration.current
    cancelBootstrapRetry()
    bootstrapInFlightRef.current = null
    bootstrapRetryCountRef.current = 0
    bootstrapAutoRetryRef.current = false
    recoveryPromise.current = null
    resetQueryRetryBudget()
    setAuthState(prev => ({ ...prev, status: 'checking', isLoading: true, user: null }))
    clearSessionCache(client)
    setAccessToken(accessToken)
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', { skipAuthRedirect: true })
      if (generation !== sessionGeneration.current) return
      cancelBootstrapRetry()
      bootstrapRetryCountRef.current = 0
      setAuthState(prev => ({
        ...prev,
        status: 'authenticated',
        isLoading: false,
        user: response,
        error: null,
        retryCount: 0,
        lastRetryAt: null,
      }))
    } catch (error) {
      if (generation !== sessionGeneration.current) return
      const authError = createAuthError(error)
      // Preserve the freshly issued session only when the hydration failure is
      // positively identified as a transient outage (503 / network). A
      // definitive 401 — or an unclassifiable validation failure — keeps the
      // legacy invalid-credentials behavior: clear the token and log out.
      if (isDefinitiveAuthenticationFailure(error) || authError === null) {
        clearAccessToken()
        clearSessionCache(client)
        setAuthState(prev => ({
          ...prev,
          status: 'unauthenticated',
          isLoading: false,
          user: null,
          error: authError,
        }))
      } else {
        // Preserve session for service/network failures (degraded state)
        setAuthState(prev => ({
          ...prev,
          status: authError?.type === 'service_unavailable' ? 'service_unavailable' : 'network_error',
          isLoading: false,
          error: authError,
          retryCount: prev.retryCount + 1,
          lastRetryAt: Date.now(),
        }))
      }
      throw error
    }
  }

  const logout = () => {
    markDefinitivelyUnauthenticated()
    // Posting on the receiving instance excludes this tab from its own logout.
    authChannelRef.current?.postMessage({ type: 'logout' })
  }

  // Legacy context value for backward compatibility
  const legacyValue: AuthContextLegacyValue = {
    isAuthenticated: authState.status === 'authenticated',
    isLoading: authState.isLoading,
    user: authState.user,
  }

  return (
    <AuthContext.Provider
      value={{
        ...legacyValue,
        authState,
        login,
        logout,
        revalidateSession,
        recoverSession,
        retryAuth,
        clearAuthError,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { authState } = useAuth()
  const location = useLocation()
  
  if (authState.isLoading) {
    return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Checking authentication...</div>
  }
  
  if (authState.status === 'unauthenticated') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  
  if (authState.status === 'service_unavailable' || authState.status === 'network_error') {
    // Show the degraded service state instead of redirecting
    return children
  }
  
  return children
}

function PublicRoute({ children }: { children: ReactNode }) {
  const { authState } = useAuth()
  const location = useLocation()
  
  if (authState.isLoading) {
    return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Loading...</div>
  }
  
  if (authState.status === 'authenticated') {
    return <Navigate to={location.state?.from?.pathname || '/'} replace />
  }
  
  return children
}

function NotFoundRoute({ children }: { children: ReactNode }) {
  const { authState } = useAuth()
  
  if (authState.isLoading) {
    return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Loading...</div>
  }
  
  // For both authenticated and unauthenticated users, show the NotFoundPage
  return children
}

function LegacyThreadsRedirect() {
  const { id } = useParams()
  return <Navigate to={`/thread/${id ?? ''}`} replace />
}

function CrossoversListRedirect() {
  const { search } = useLocation()
  const group = new URLSearchParams(search).get('group')
  if (group) {
    return <Navigate to={`/continuity-plans/events${search}`} replace />
  }
  return <Navigate to="/continuity-plans" replace />
}

function RootRoute({ onBugReportSubmit }: { onBugReportSubmit: BugReportSubmit }) {
  const { authState } = useAuth()

  if (authState.isLoading) {
    return <div className="flex min-h-screen items-center justify-center text-center text-stone-500" data-app-shell-ready>Checking authentication...</div>
  }

  // Only a definitively unauthenticated visitor sees the logged-out landing page.
  // Degraded states (service_unavailable/network_error) must keep the authenticated
  // shell so the "your session is still active" recovery overlay stays coherent.
  if (authState.status === 'unauthenticated') {
    return (
      <PublicLayout onBugReportSubmit={onBugReportSubmit}>
        <LandingPage />
      </PublicLayout>
    )
  }

  return (
    <ProtectedRoute>
      <ServiceUnavailableWrapper>
        <AuthenticatedLayout wide onBugReportSubmit={onBugReportSubmit}>
          <RollPage />
        </AuthenticatedLayout>
      </ServiceUnavailableWrapper>
    </ProtectedRoute>
  )
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
  const { authState, ServiceUnavailableWrapper } = useAuthDegradedState()
  useScrollRestoration()
  
  const isAuthenticated = authState.status === 'authenticated'

  return (
    <Suspense fallback={<div className="text-center text-stone-500">Loading page...</div>}>
      <Seo />
      <RouteChunkPrefetcher enabled={isAuthenticated} />
      <Routes>
        <Route path="/login" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><LoginPage /></PublicLayout></PublicRoute>} />
        <Route path="/register" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><RegisterPage /></PublicLayout></PublicRoute>} />
        <Route path="/forgot-password" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><ForgotPasswordPage /></PublicLayout></PublicRoute>} />
        <Route path="/reset-password" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><ResetPasswordPage /></PublicLayout></PublicRoute>} />
        <Route path="/demo" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><DemoRollPage /></PublicLayout></PublicRoute>} />
        <Route path="/rate" element={<Navigate to="/" replace />} />
        <Route path="/analytics" element={<Navigate to="/" replace />} />
        <Route path="/roll" element={<Navigate to="/" replace />} />
        <Route path="/" element={<RootRoute onBugReportSubmit={submit} />} />
        <Route path="/queue" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <QueuePage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/thread/:id" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ThreadDetailView />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/threads/:id" element={<LegacyThreadsRedirect />} />
        <Route path="/creators/compare" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CreatorComparisonPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/creators/:creatorKey" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CreatorDetailPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/history" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <HistoryPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/sessions/:id" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <SessionPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/creators" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CreatorsPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/crossovers" element={
          <ProtectedRoute>
            <CrossoversListRedirect />
          </ProtectedRoute>
        } />
        <Route path="/crossovers/:group" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CrossoverDetailPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/continuity-plans" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ContinuityPlansIndexPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/continuity-plans/new" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ContinuityPlannerPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/continuity-plans/events" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CrossoversPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/continuity-plans/:id/edit" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ReadingPlanEditRoute legacyEditor={<ContinuityPlannerPage />} />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/continuity-plans/:id" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ReadingPlanDetailPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/reading-lists/:id" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ReadingListEditorPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/cbl-sources" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CblBrowserPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/whats-new" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <WhatsNewPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/glossary" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <HelpPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="/help" element={<Navigate to="/glossary" replace />} />
        <Route path="/identity-inbox" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <IdentityInboxPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
        <Route path="*" element={
          <NotFoundRoute>
            <PublicLayout onBugReportSubmit={submit}>
              <NotFoundPage />
            </PublicLayout>
          </NotFoundRoute>
        } />
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
  return <BrowserRouter><QueryClientProvider client={queryClient}><BugReportRestoreProvider><ToastProvider><AuthProvider><NavCollapseProvider><AuthResumeBoundary><AppRoutes /></AuthResumeBoundary></NavCollapseProvider></AuthProvider></ToastProvider></BugReportRestoreProvider></QueryClientProvider></BrowserRouter>
}

export { AppRoutes, useAuth }
export type { AuthContextValue, AuthContextLegacyValue }
export default App
