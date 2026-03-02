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
  Collection,
  CollectionCreate,
  CollectionListResponse,
  CollectionUpdate,
  Dependency,
  DependencyCreatePayload,
  ReactivateThreadPayload,
  RollResponse,
  SessionCurrent,
  SessionDetails,
  SessionSnapshotsResponse,
  SessionSummary,
  Thread,
  ThreadCreatePayload,
  ThreadDependenciesResponse,
  ThreadQueryParams,
  ThreadUpdatePayload,
} from '../types'

type ApiRequestConfig<D = unknown> = AxiosRequestConfig<D> & {
  _retry?: boolean
  skipAuthRedirect?: boolean
}

interface ApiClient extends Omit<AxiosInstance, 'request' | 'get' | 'delete' | 'head' | 'post' | 'put' | 'patch'> {
  request<T = any, D = unknown>(config: ApiRequestConfig<D>): Promise<T>
  get<T = any>(url: string, config?: ApiRequestConfig): Promise<T>
  delete<T = any>(url: string, config?: ApiRequestConfig): Promise<T>
  head<T = any>(url: string, config?: ApiRequestConfig): Promise<T>
  post<T = any, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  put<T = any, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
  patch<T = any, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>): Promise<T>
}

const rawApi = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

const api = rawApi as unknown as ApiClient

let refreshTokenPromise: Promise<AuthTokens> | null = null
let isRedirectingToLogin = false
let redirectTimeoutId: ReturnType<typeof setTimeout> | null = null
let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function clearAccessToken(): void {
  accessToken = null
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

  if (redirectTimeoutId) {
    clearTimeout(redirectTimeoutId)
  }

  clearAccessToken()

  redirectTimeoutId = setTimeout(() => {
    isRedirectingToLogin = false
    redirectTimeoutId = null
  }, 5000)

  window.location.href = '/login'
}

rawApi.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    if (token) {
      ;(config.headers as Record<string, string>).Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: unknown) => Promise.reject(error),
)

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

    if (error.response.status === 401 && !originalRequest._retry) {
      const requestUrl = originalRequest.url ?? ''
      const isAuthEndpoint =
        requestUrl.includes('/auth/login') ||
        requestUrl.includes('/auth/register') ||
        requestUrl.includes('/auth/refresh')
      if (isAuthEndpoint || originalRequest.skipAuthRedirect) {
        if (requestUrl.includes('/auth/refresh')) {
          redirectToLogin()
        }
        return Promise.reject(error)
      }

      originalRequest._retry = true

      try {
        if (!refreshTokenPromise) {
          // Refresh token is held in an HttpOnly cookie; request body is optional.
          refreshTokenPromise = api.post<AuthTokens>('/auth/refresh')
        }

        const response = await refreshTokenPromise
        refreshTokenPromise = null

        const { access_token } = response
        setAccessToken(access_token)

        originalRequest.headers = originalRequest.headers ?? {}
        ;(originalRequest.headers as Record<string, string>).Authorization = `Bearer ${access_token}`
        return api.request(originalRequest)
      } catch (refreshError) {
        refreshTokenPromise = null
        redirectToLogin()
        return Promise.reject(refreshError)
      }
    }

    console.error('API Error:', error)
    return Promise.reject(error)
  },
)

export default api

export const threadsApi = {
  list: (params?: ThreadQueryParams) => api.get<Thread[]>('/threads/', { params }),
  get: (id: number) => api.get<Thread>(`/threads/${id}`),
  create: (data: ThreadCreatePayload) => api.post<Thread, ThreadCreatePayload>('/threads/', data),
  update: (id: number, data: ThreadUpdatePayload) =>
    api.put<Thread, ThreadUpdatePayload>(`/threads/${id}`, data),
  delete: (id: number) => api.delete<void>(`/threads/${id}`),
  reactivate: (data: ReactivateThreadPayload) =>
    api.post<Thread, ReactivateThreadPayload>('/threads/reactivate', data),
  listStale: (days = 30) => api.get<Thread[]>('/threads/stale', { params: { days } }),
  setPending: (id: number) => api.post<RollResponse>(`/threads/${id}/set-pending`),
}

export const rollApi = {
  roll: () => api.post<RollResponse>('/roll/'),
  override: (data: { thread_id: number }) => api.post<RollResponse, { thread_id: number }>('/roll/override', data),
  dismissPending: () => api.post<void>('/roll/dismiss-pending'),
  reroll: () => api.post<RollResponse>('/roll/'),
  setDie: (die: number) => api.post<void>('/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post<void>('/roll/clear-manual-die'),
}

export const rateApi = {
  rate: (data: { thread_id: number; rating: number }) => api.post<void, { thread_id: number; rating: number }>('/rate/', data),
}

export const sessionApi = {
  list: (params?: Record<string, unknown>) => api.get<SessionSummary[]>('/sessions/', { params }),
  get: (id: number) => api.get<SessionSummary>(`/sessions/${id}`),
  getCurrent: () => api.get<SessionCurrent>('/sessions/current/'),
  getDetails: (id: number | string) => api.get<SessionDetails>(`/sessions/${id}/details`),
  getSnapshots: (id: number | string) => api.get<SessionSnapshotsResponse>(`/sessions/${id}/snapshots`),
  restoreSessionStart: (id: number | string) => api.post<void>(`/sessions/${id}/restore-session-start`),
}

export const queueApi = {
  moveToPosition: (id: number, position: number) =>
    api.put<void, { new_position: number }>(`/queue/threads/${id}/position/`, { new_position: position }),
  moveToFront: (id: number) => api.put<void>(`/queue/threads/${id}/front/`),
  moveToBack: (id: number) => api.put<void>(`/queue/threads/${id}/back/`),
}

export const undoApi = {
  undo: (sessionId: number | string, snapshotId: number | string) =>
    api.post<void>(`/undo/${sessionId}/undo/${snapshotId}`),
  listSnapshots: (sessionId: number | string) => api.get<SessionSnapshotsResponse>(`/undo/${sessionId}/snapshots`),
}

export const dependenciesApi = {
  listBlockedThreadIds: () => api.get<number[]>('/v1/dependencies/blocked'),
  listThreadDependencies: (threadId: number) =>
    api.get<ThreadDependenciesResponse>(`/v1/threads/${threadId}/dependencies`),
  getBlockingInfo: (threadId: number) =>
    api.post<BlockingInfoResponse>(`/v1/threads/${threadId}:getBlockingInfo`),
  createDependency: ({ sourceType = 'thread', sourceId, targetType = 'thread', targetId }: DependencyCreatePayload) =>
    api.post<Dependency, { source_type: 'thread' | 'issue'; source_id: number; target_type: 'thread' | 'issue'; target_id: number }>('/v1/dependencies/', {
      source_type: sourceType,
      source_id: sourceId,
      target_type: targetType,
      target_id: targetId,
    }),
  deleteDependency: (dependencyId: number) => api.delete<void>(`/v1/dependencies/${dependencyId}`),
}

export const tasksApi = {
  getMetrics: () => api.get<AnalyticsMetrics>('/analytics/metrics'),
}

export const snoozeApi = {
  snooze: () => api.post<void>('/snooze/'),
  unsnooze: (threadId: number) => api.post<void>(`/snooze/${threadId}/unsnooze`),
}

export const collectionsApi = {
  list: () => api.get<CollectionListResponse>('/v1/collections/'),
  get: (id: number) => api.get<Collection>(`/v1/collections/${id}`),
  create: (data: CollectionCreate) => api.post<Collection, CollectionCreate>('/v1/collections/', data),
  update: (id: number, data: CollectionUpdate) => api.put<Collection, CollectionUpdate>(`/v1/collections/${id}`, data),
  delete: (id: number) => api.delete<void>(`/v1/collections/${id}`),
  moveThreadToCollection: (threadId: number, collectionId: number | null) =>
    api.post<void>(`/threads/${threadId}:moveToCollection`, null, { params: { collection_id: collectionId } }),
}

export const migrationApi = {
  migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) =>
    api.post<Thread, { last_issue_read: number; total_issues: number }>(`/threads/${threadId}:migrateToIssues`, data),
}
