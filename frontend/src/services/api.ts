// API client for ComicPile frontend
import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import type {
  AnalyticsMetrics,
  AuthTokens,
  BlockingInfoResponse,
  BugReportResponse,
  ConnectedDependenciesResponse,
  Dependency,
  DependencyCreatePayload,
  IssueDependenciesResponse,
  ReactivateThreadPayload,
  RollResponse,
  SessionCurrent,
  SessionDetails,
  SessionListResponse,
  SessionSnapshotsResponse,
  SessionSummary,
  Thread,
  ThreadCreatePayload,
  ThreadDependenciesResponse,
  ThreadListResponse,
  ThreadQueryParams,
  ThreadUpdatePayload,
} from '../types'

type ApiRequestConfig<D = unknown> = AxiosRequestConfig<D> & {
  _retry?: boolean
  _queued?: boolean
  skipAuthRedirect?: boolean
}

interface ApiClient extends Omit<AxiosInstance, 'request' | 'get' | 'delete' | 'head' | 'post' | 'put' | 'patch'> {
  request<T = unknown, D = unknown>(config: ApiRequestConfig<D>): Promise<T>
  get<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  delete<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  head<T = unknown>(url: string, config?: ApiRequestConfig): Promise<T>
  post<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  put<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  patch<T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
}

const rawApi = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

const CSRF_COOKIE_NAME = 'csrf_token'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const CSRF_PROTECTED_METHODS = new Set(['post', 'put', 'patch', 'delete'])
const AUTH_ENDPOINT_PATHS = new Set(['/v1/auth/login', '/v1/auth/register', '/v1/auth/refresh'])

// Axios returns AxiosResponse by default, but the response interceptor below unwraps to response.data.
// Cast once at the boundary so callers get strongly typed payload methods.
const api = rawApi as unknown as ApiClient

let isRedirectingToLogin = false
let accessToken: string | null = null
let csrfTokenPromise: Promise<string | null> | null = null
let failedQueue: Array<{
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  config: ApiRequestConfig
}> = []
let isRefreshing = false

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function clearAccessToken(): void {
  accessToken = null
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

async function ensureCsrfToken(): Promise<string | null> {
  const existingToken = getCookieValue(CSRF_COOKIE_NAME)
  if (existingToken) {
    return existingToken
  }
  if (!csrfTokenPromise) {
    csrfTokenPromise = api
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
  return pathname === '/login' || pathname === '/register'
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
  const responseData = error.response.data as { detail?: unknown } | undefined
  return responseData?.detail === 'Not authenticated'
}

rawApi.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    config.headers = config.headers ?? {}
    if (token) {
      ;(config.headers as Record<string, string>).Authorization = `Bearer ${token}`
    }
    if (shouldAttachCsrfToken(config)) {
      const csrfToken = await ensureCsrfToken()
      if (csrfToken) {
        ;(config.headers as Record<string, string>)[CSRF_HEADER_NAME] = csrfToken
      }
    }
    return config
  },
  (error: unknown) => Promise.reject(error),
)

function processQueue(error: unknown | null, token: string | null = null): void {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.config.headers = prom.config.headers ?? {}
      ;(prom.config.headers as Record<string, string>).Authorization = `Bearer ${token}`
      prom.resolve(api.request(prom.config))
    }
  })
  failedQueue = []
}

rawApi.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
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
        if (requestPathname === '/v1/auth/refresh' && !originalRequest.skipAuthRedirect) {
          redirectToLogin()
        }
        return Promise.reject(error)
      }
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject, config: originalRequest })
        })
          .then((token) => token)
          .catch((err) => {
            if ((err as AxiosError)?.response?.status === 401) {
              return Promise.reject(error)
            }
            return Promise.reject(err)
          })
      }
      originalRequest._retry = true
      isRefreshing = true
      try {
        const response = originalRequest.skipAuthRedirect
          ? await api.post<AuthTokens>('/v1/auth/refresh', undefined, { skipAuthRedirect: true })
          : await api.post<AuthTokens>('/v1/auth/refresh')
        const { access_token } = response
        setAccessToken(access_token)
        processQueue(null, access_token)
        isRefreshing = false
        originalRequest.headers = originalRequest.headers ?? {}
        ;(originalRequest.headers as Record<string, string>).Authorization = `Bearer ${access_token}`
        return api.request(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        isRefreshing = false
        if (!originalRequest.skipAuthRedirect && isAuthenticationFailure(refreshError as AxiosError)) {
          redirectToLogin()
        }
        return Promise.reject(refreshError)
      }
    }
    if (error.response && error.response.status >= 500 && error.response.status < 600) {
      console.warn('API request failed with server error:', error.response.status)
    } else {
      console.error('API Error:', error)
    }
    return Promise.reject(error)
  },
)

export default api

export const threadsApi = {
  list: async (params?: ThreadQueryParams, pageToken?: string | null): Promise<ThreadListResponse> => {
    const queryParams = {
      ...(params ?? {}),
      ...(pageToken ? { page_token: pageToken } : {}),
    }
    const response = await api.get<ThreadListResponse>('/v1/threads/', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },
  get: (id: number) => api.get<Thread>(`/v1/threads/${id}`),
  create: (data: ThreadCreatePayload) => api.post<Thread, ThreadCreatePayload>('/v1/threads/', data),
  update: (id: number, data: ThreadUpdatePayload) =>
    api.put<Thread, ThreadUpdatePayload>(`/v1/threads/${id}`, data),
  delete: (id: number) => api.delete<void>(`/v1/threads/${id}`),
  reactivate: (data: ReactivateThreadPayload) =>
    api.post<Thread, ReactivateThreadPayload>('/v1/threads/reactivate', data),
  listStale: (days = 30) => api.get<Thread[]>('/v1/threads/stale', { params: { days } }),
  setPending: (id: number) => api.post<RollResponse>(`/v1/threads/${id}/set-pending`),
}

export const rollApi = {
  roll: () => api.post<RollResponse>('/v1/roll/'),
}
