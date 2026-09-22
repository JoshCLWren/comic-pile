import { Suspense, useState, useEffect, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
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
import { isDefinitiveAuthenticationFailure, createAuthError, type AuthState, type AuthStatus, type AuthError, calculateRetryDelay } from './services/authState'
import type { AuthUser } from './types'
import { useBugReport } from './hooks/useBugReport'
import { usePingHeartbeat } from './hooks/usePingHeartbeat'
import { useScrollRestoration } from './hooks/useScrollRestoration'
import { PreferencesSync } from './hooks/usePreferences'
import { useAuthDegradedState } from './hooks/useAuthDegradedState'
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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authState, setAuthState] = useState<AuthState>({
    status: 'checking',
    isLoading: true,
    user: null,
    error: null,
    retryCount: 0,
    lastRetryAt: null,
  })
  const recoveryPromise = useRef<Promise<void> | null>(null)

  const markDefinitivelyUnauthenticated = useCallback(() => {
    clearAccessToken()
    setAuthState(prev => ({
      ...prev,
      status: 'unauthenticated',
      isLoading: false,
      user: null,
      error: null,
      retryCount: 0,
      lastRetryAt: null,
    }))
  }, [])

const clearAuthError = useCallback(() => {
     setAuthState(prev => ({
       ...prev,
       error: null,
     }))
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
           const authError = createAuthError(error)
           if (isDefinitiveAuthenticationFailure(error)) {
             markDefinitivelyUnauthenticated()
           } else {
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
        recoveryPromise.current = null
      })
     }
     return recoveryPromise.current
   }, [markDefinitivelyUnauthenticated]);

   const retryAuth = useCallback(async () => {
     setAuthState(prev => ({
       ...prev,
       isLoading: true,
       error: null,
     }))

     try {
       await recoverSession(AUTH_BOOTSTRAP_TIMEOUT_MS)
     } catch (error) {
       const authError = createAuthError(error)
       setAuthState(prev => ({
         ...prev,
         isLoading: false,
         error: authError,
       }))
       throw error
     }
   }, [recoverSession])

  const revalidateSession = useCallback(async (timeout?: number) => {
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', {
        timeout,
        skipAuthRedirect: true,
      })
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
      const authError = createAuthError(error)
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
      } else {
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
  }, [markDefinitivelyUnauthenticated, recoverSession])

  useEffect(() => {
    let isMounted = true
    let retryTimer: number | undefined
    const authChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('comic-pile-auth') : null
    
    const validateSession = async () => {
      const isPublicAuthPage = window.location.pathname === '/login' || window.location.pathname === '/register'
      if (!getAccessToken() && !window.__COMIC_PILE_ACCESS_TOKEN && isPublicAuthPage) {
        setAuthState(prev => ({
          ...prev,
          status: 'unauthenticated',
          isLoading: false,
        }))
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
          setAuthState(prev => ({
            ...prev,
            status: 'authenticated',
            isLoading: false,
            user: response,
            error: null,
            retryCount: 0,
            lastRetryAt: null,
          }))
        }
      } catch (error) {
        if (!isMounted) return
        
        const authError = createAuthError(error)
        
        if (isDefinitiveAuthenticationFailure(error)) {
          // A stale or expired access token is routine on a return visit. Try to
          // renew the session silently with the refresh cookie before surfacing
          // the login screen for a single-user app.
          try {
            await recoverSession(AUTH_BOOTSTRAP_TIMEOUT_MS)
            return
          } catch (recoveryError) {
            if (isDefinitiveAuthenticationFailure(recoveryError)) {
              markDefinitivelyUnauthenticated()
              return
            }
          }
        }

        // Handle service unavailable and network errors with retry logic
        const retryDelay = calculateRetryDelay(authState.retryCount + 1, AUTH_RETRY_BASE_DELAY_MS)
        
        if (isMounted) {
          setAuthState(prev => ({
            ...prev,
            status: authError?.type === 'service_unavailable' ? 'service_unavailable' : 'network_error',
            isLoading: false,
            error: authError,
            retryCount: prev.retryCount + 1,
            lastRetryAt: Date.now(),
          }))
        }

        if (!isMounted) return
        
        retryTimer = window.setTimeout(() => {
          void validateSession()
        }, retryDelay)
      }
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
      isMounted = false
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer)
      }
      authChannel?.close()
    }
  }, [markDefinitivelyUnauthenticated, recoverSession, authState.retryCount])

  const login = async (accessToken: string) => {
    setAccessToken(accessToken)
    try {
      const response = await api.get<AuthUser>('/v1/auth/me', { skipAuthRedirect: true })
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
      const authError = createAuthError(error)
      clearAccessToken()
      setAuthState(prev => ({
        ...prev,
        status: 'unauthenticated',
        isLoading: false,
        user: null,
        error: authError,
      }))
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
      <RouteChunkPrefetcher enabled={isAuthenticated} />
      <Routes>
        <Route path="/login" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><LoginPage /></PublicLayout></PublicRoute>} />
        <Route path="/register" element={<PublicRoute><PublicLayout onBugReportSubmit={submit}><RegisterPage /></PublicLayout></PublicRoute>} />
        <Route path="/rate" element={<Navigate to="/" replace />} />
        <Route path="/analytics" element={<Navigate to="/" replace />} />
        <Route path="/" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout wide onBugReportSubmit={submit}>
                <RollPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
          </ProtectedRoute>
        } />
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
        <Route path="/crossovers" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <CrossoversPage />
              </AuthenticatedLayout>
            </ServiceUnavailableWrapper>
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
        <Route path="/continuity-plans/:id" element={
          <ProtectedRoute>
            <ServiceUnavailableWrapper>
              <AuthenticatedLayout onBugReportSubmit={submit}>
                <ContinuityPlannerPage />
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