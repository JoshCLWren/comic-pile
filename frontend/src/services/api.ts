import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import type {
  AnalyticsMetrics,
  AuthTokens,
  BugReportResponse,
  RollResponse,
  Thread,
} from '../types'
import type { HttpClient, ApiRequestConfig } from './httpClient'
import { setDefaultHttpClient } from './httpClient'

export interface ApiClient extends Omit<AxiosInstance, 'request' | 'get' | 'delete' | 'head' | 'post' | 'put' | 'patch'> {
  request<T = unknown, D = unknown>(config: ApiRequestConfig<D>): Promise<T>
  get<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  delete<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  head<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  post<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  put<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  patch<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
}

/**
 * Transport `createApiClient` configures.
 *
 * The production factory returns a real axios instance; tests can return a
 * double that records requests and captures the registered interceptors.
 */
export type ApiClientTransport = HttpClient & Pick<AxiosInstance, 'interceptors'>

const CSRF_COOKIE_NAME = 'csrf_token'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const CSRF_PROTECTED_METHODS = new Set(['post', 'put', 'patch', 'delete'])
const AUTH_ENDPOINT_PATHS = new Set([
  '/v1/auth/login',
  '/v1/auth/register',
  '/v1/auth/refresh',
  '/v1/auth/forgot-password',
  '/v1/auth/reset-password',
])

export const AUTH_TOKEN_STORAGE_KEY = 'auth_token'

let isRedirectingToLogin = false
let accessToken: string | null = null
let csrfTokenPromise: Promise<string | null> | null = null
let failedQueue: Array<{
  client: ApiClient
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  config: ApiRequestConfig
}> = []
let isRefreshing = false
let sessionRefreshRejected = false
let refreshPromise: Promise<string> | null = null

export function readStoredAccessToken(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }

  return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
}

function writeStoredAccessToken(token: string | null): void {
  if (typeof localStorage === 'undefined') {
    return
  }

  if (token) {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token
  writeStoredAccessToken(token)
  // A new explicit token write (login or test setup) allows another cookie probe.
  sessionRefreshRejected = false
}

export function getAccessToken(): string | null {
  if (accessToken) {
    return accessToken
  }

  const stored = readStoredAccessToken()
  if (stored) {
    accessToken = stored
  }
  return stored
}

export function clearAccessToken(): void {
  accessToken = null
  writeStoredAccessToken(null)
}

function discardAccessToken(): void {
  accessToken = null
  writeStoredAccessToken(null)
}

function markSessionRefreshRejected(): void {
  sessionRefreshRejected = true
  discardAccessToken()
}

export function isSessionRefreshRejected(): boolean {
  return sessionRefreshRejected
}

function buildRejectedRefreshError(): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error('Session refresh unavailable'), {
    isAxiosError: true as const,
    response: { status: 401 },
  })
}

export function refreshSession(options?: { skipAuthRedirect?: boolean }): Promise<string> {
  return refreshSessionOn(api, options)
}

async function refreshSessionOn(
  client: ApiClient,
  options?: { skipAuthRedirect?: boolean },
): Promise<string> {
  if (sessionRefreshRejected) {
    throw buildRejectedRefreshError()
  }
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      const response = options?.skipAuthRedirect
        ? await client.post<AuthTokens>('/v1/auth/refresh', undefined, { skipAuthRedirect: true })
        : await client.post<AuthTokens>('/v1/auth/refresh')
      setAccessToken(response.access_token)
      return response.access_token
    } catch (error) {
      // SAFETY: catch clause is unknown; axios interceptor always receives AxiosError.
      if (isAuthenticationFailure(error as AxiosError)) {
        markSessionRefreshRejected()
      }
      throw error
    } finally {
      refreshPromise = null
    }
  })()

  return refreshPromise
}

function getCookieValue(name: string): string | null {
  if (typeof document === 'undefined' || !document.cookie) {
    return null
  }

  const prefix = `${encodeURIComponent(name)}=`
  for (const cookie of document.cookie.split('; ')) {
    if (cookie.startsWith(prefix)) {
      return decodeURIComponent(cookie.slice(prefix.length))
    }
  }

  return null
}

function getRequestPathname(requestUrl: string): string {
  return new URL(requestUrl, 'http://comic-pile.local').pathname
}

function shouldAttachCsrfToken(config: InternalAxiosRequestConfig): boolean {
  const method = (config.method ?? 'get').toLowerCase()
  if (!CSRF_PROTECTED_METHODS.has(method)) {
    return false
  }

  return !AUTH_ENDPOINT_PATHS.has(getRequestPathname(config.url ?? ''))
}

async function ensureCsrfToken(client: ApiClient): Promise<string | null> {
  const existingToken = getCookieValue(CSRF_COOKIE_NAME)
  if (existingToken) {
    return existingToken
  }

  if (!csrfTokenPromise) {
    // SAFETY: only the skipAuthRedirect flag is needed from ApiRequestConfig; other fields have sensible defaults.
    csrfTokenPromise = client
      .get<{ csrf_token: string }>('/v1/auth/csrf', { skipAuthRedirect: true } as ApiRequestConfig)
      .then((response) => response.csrf_token ?? getCookieValue(CSRF_COOKIE_NAME))
      .finally(() => {
        csrfTokenPromise = null
      })
  }

  return csrfTokenPromise
}

function isOnAuthPage(): boolean {
  const pathname = window.location.pathname
  return (
    pathname === '/login' ||
    pathname === '/register' ||
    pathname === '/forgot-password' ||
    pathname === '/reset-password'
  )
}

function redirectToLogin(): void {
  if (isOnAuthPage() || isRedirectingToLogin) {
    return
  }

  isRedirectingToLogin = true

  clearAccessToken()

  setTimeout(() => {
    isRedirectingToLogin = false
  }, 5000)

  window.location.href = '/login'
}

function isAuthenticationFailure(error: AxiosError): boolean {
  if (error.response?.status === 401) {
    return true
  }

  if (error.response?.status !== 403) {
    return false
  }

  // SAFETY: axios 403 responses always carry a JSON body; narrowing to check for auth-failure detail.
  const responseData = error.response.data as { detail?: unknown } | undefined
  return responseData?.detail === 'Not authenticated'
}

function createRequestInterceptor(client: ApiClient) {
  return async (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    config.headers = config.headers ?? {}

    if (token) {
      // SAFETY: InternalAxiosRequestHeaders is indexable by string key; setting Authorization is safe.
      (config.headers as Record<string, string>).Authorization = `Bearer ${token}`
    }

    if (shouldAttachCsrfToken(config)) {
      const csrfToken = await ensureCsrfToken(client)
      if (csrfToken) {
        // SAFETY: InternalAxiosRequestHeaders is indexable by string key; CSRF header assignment is safe.
        (config.headers as Record<string, string>)[CSRF_HEADER_NAME] = csrfToken
      }
    }

    return config
  }
}

function processQueue(error: unknown | null, token: string | null = null): void {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.config.headers = prom.config.headers ?? {}
      // SAFETY: headers is initialized above and is indexable by string; Authorization assignment is safe.
      const authHeaders = prom.config.headers as Record<string, string>
      authHeaders.Authorization = `Bearer ${token}`
      prom.resolve(prom.client.request(prom.config))
    }
  })
  failedQueue = []
}

function createResponseErrorInterceptor(client: ApiClient) {
  return async (error: AxiosError) => {
    // SAFETY: error.config may be absent for network errors; default to empty object and widen to ApiRequestConfig.
    const originalRequest = (error.config ?? {}) as ApiRequestConfig

    if (!error.response) {
      console.error('Network Error:', error.message)
      return Promise.reject(new Error('Network error. Please check your connection and try again.'))
    }

    if (error.response.status === 400) {
      console.error('API Validation Error Details:', {
        status: error.response.status,
        data: error.response.data,
      })
    }

    if (isAuthenticationFailure(error) && !originalRequest._retry) {
      const requestPathname = getRequestPathname(originalRequest.url ?? '')
      if (AUTH_ENDPOINT_PATHS.has(requestPathname)) {
        if (requestPathname === '/v1/auth/refresh' && isAuthenticationFailure(error)) {
          markSessionRefreshRejected()
          if (!originalRequest.skipAuthRedirect) {
            redirectToLogin()
          }
        }
        return Promise.reject(error)
      }

      if (sessionRefreshRejected) {
        if (!originalRequest.skipAuthRedirect) {
          redirectToLogin()
        }
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ client, resolve, reject, config: originalRequest })
        }).then((token) => token).catch((err) => {
          // SAFETY: rejected value from refresh queue is either an AxiosError or a plain error from processQueue.
          if ((err as AxiosError)?.response?.status === 401) {
            return Promise.reject(error)
          }
          return Promise.reject(err)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const access_token = await refreshSessionOn(client, {
          skipAuthRedirect: originalRequest.skipAuthRedirect,
        })

        processQueue(null, access_token)
        isRefreshing = false

        originalRequest.headers = originalRequest.headers ?? {}
        // SAFETY: headers is initialized above and is indexable by string; Authorization assignment is safe.
        const authHeaders = originalRequest.headers as Record<string, string>
        authHeaders.Authorization = `Bearer ${access_token}`
        return client.request(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        isRefreshing = false
        // SAFETY: catch clause is unknown; refreshSession rethrows AxiosError on auth failure.
        if (
          !originalRequest.skipAuthRedirect &&
          isAuthenticationFailure(refreshError as AxiosError)
        ) {
          redirectToLogin()
        }
        return Promise.reject(refreshError)
      }
    }

    const status = error.response?.status
    if (status !== 503) {
      console.error('API Error:', error)
    }
    return Promise.reject(error)
  }
}

/**
 * Build an API client that carries the production interceptor pipeline.
 *
 * Every request the client makes, including CSRF bootstrap, token refresh, and
 * retry replays, goes back through that same client, so a test can substitute
 * the transport and still exercise the real auth and CSRF behaviour.
 *
 * @param factory - Produces the underlying axios instance to configure.
 * @returns The configured client exposing payload-returning request methods.
 */
export function createApiClient(factory: () => ApiClientTransport): ApiClient {
  // SAFETY: the factory produces the request methods and the interceptor
  // registry; the interceptors registered below unwrap responses to payloads,
  // which is the ApiClient contract those methods already promise.
  const client = factory() as ApiClient
  client.interceptors.request.use(
    createRequestInterceptor(client),
    (error: unknown) => Promise.reject(error),
  )
  client.interceptors.response.use(
    (response) => response.data,
    createResponseErrorInterceptor(client),
  )
  return client
}

function createRawApiInstance(): ApiClientTransport {
  // SAFETY: axios.create returns an AxiosInstance; createApiClient registers the
  // response interceptor that unwraps `.data`, which is the payload contract.
  return axios.create({
    baseURL: '/api',
    timeout: 10000,
  }) as ApiClientTransport
}

// Axios returns AxiosResponse by default, but the response interceptor unwraps to
// response.data, so the client hands callers strongly typed payload methods.
const api = createApiClient(createRawApiInstance)

// Service modules are evaluated before this module body runs, so they bind
// their default singletons through `defaultHttpClient()` and resolve the real
// transport here.
setDefaultHttpClient(api)

export default api

// Temporary reading-runtime re-exports keep this slice independently shippable.
// TODO(#2785): remove these re-exports once every call site imports the focused domain clients.
export { threadsApi } from './api-threads'
export { rollApi } from './api-roll'
export { rateApi } from './api-rate'

export { sessionApi } from './api-sessions'
export type { SessionListParams } from './api-sessions'
export { queueApi } from './api-queue'
export { undoApi } from './api-undo'

export { dependenciesApi } from './api-dependencies'

export { comicVineApi } from './api-comicvine'

export function createTasksApi(client: HttpClient) {
  return {
    getMetrics: () => client.get<AnalyticsMetrics>('/v1/analytics/metrics'),
  }
}

export const tasksApi = createTasksApi(api)

export { creatorsApi } from './api-creators'

// Temporary reading-runtime re-exports keep this slice independently shippable.
// TODO(#2785): remove these re-exports once every call site imports the focused domain clients.
export { snoozeApi } from './api-snooze'
export { skipApi } from './api-skip'

export function createMigrationApi(client: HttpClient) {
  return {
    migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) =>
      client.post<Thread, { last_issue_read: number; total_issues: number }>(`/v1/threads/${threadId}:migrateToIssues`, data),
  }
}

export const migrationApi = createMigrationApi(api)

export function createBugReportsApi(client: HttpClient) {
  return {
    create: (data: { title: string; description: string; diagnostics?: unknown }) =>
      client.post<BugReportResponse>('/v1/bug-reports/', data),
  }
}

export const bugReportsApi = createBugReportsApi(api)

export { identityInboxApi } from './api-identity'

export interface UserPreferencesResponse {
  theme: 'classic' | 'ink-gold' | 'command-center'
  user_id: number
}

export interface UserPreferencesPatchRequest {
  theme?: 'classic' | 'ink-gold' | 'command-center' | null
}

export const preferencesApi = {
  get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
    api.get<UserPreferencesResponse>('/v1/users/me/preferences', options),
  patch: (data: UserPreferencesPatchRequest) =>
    api.patch<UserPreferencesResponse, UserPreferencesPatchRequest>('/v1/users/me/preferences', data),
}
