import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import type {
  AnalyticsMetrics,
  AuthTokens,
  BatchBlockingInfoResponse,
  BlockingInfoResponse,
  BugReportResponse,
  CBL,
  CBLAdoptionEntry,
  CBLAdoptionPlan,
  CBLAdoptionSeries,
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
  SetCurrentIssueResponse,
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

export const AUTH_TOKEN_STORAGE_KEY = 'auth_token'

let isRedirectingToLogin = false
let accessToken: string | null = null
let csrfTokenPromise: Promise<string | null> | null = null
let failedQueue: Array<{
  resolve: (value: unknown) => void
  reject: (reason: unknown) => void
  config: ApiRequestConfig
}> = []
let isRefreshing = false

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
        }).then((token) => token).catch((err) => {
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
  setCurrentIssue: (id: number, issueNumber: string) =>
    api.post<SetCurrentIssueResponse, { issue_number: string }>(`/v1/threads/${id}:setCurrentIssue`, { issue_number: issueNumber }),
  previewAdoption: (cblId: number) =>
    api.post<CBLAdoptionPlan>(`/v1/threads/previewAdoption`, { cbl_id: cblId }),
  adoptCBL: (data: { cblId: number; selections: Record<number, { exclude: boolean }> }) =>
    api.post<void>(`/v1/threads/adoptCBL`, data),
  listCBLs: () => api.get<CBL[]>(`/v1/threads/cbls`),
}

export const rollApi = {
  roll: () => api.post<RollResponse>('/v1/roll/'),
  override: (data: { thread_id: number }) => api.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
  dismissPending: () => api.post<void>('/v1/roll/dismiss-pending'),
  skip: () => api.post<RollResponse>('/v1/roll/skip'),
  reroll: () => api.post<RollResponse>('/v1/roll/'),
  setDie: (die: number) => api.post<void>('/v1/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post<void>('/v1/roll/clear-manual-die'),
}

export const rateApi = {
  rate: (data: { thread_id: number; rating: number; issues_read?: number; finish_session?: boolean; issue_number?: string }) =>
    api.post<Thread, { thread_id: number; rating: number; issues_read?: number; finish_session?: boolean; issue_number?: string }>('/v1/rate/', data),
}

export const sessionApi = {
  list: async (params?: Record<string, unknown>, pageToken?: string | null): Promise<SessionListResponse> => {
    const queryParams: Record<string, unknown> = { ...(params ?? {}) };
    if (pageToken) {
      queryParams.page_token = pageToken;
    }
    const response = await api.get<SessionListResponse>('/v1/sessions/', {
      params: Object.keys(queryParams).length ? queryParams : undefined,
    })
    return response
  },
  get: (id: number) => api.get<SessionSummary>(`/v1/sessions/${id}`),
  getCurrent: () => api.get<SessionCurrent>('/v1/sessions/current/'),
  getDetails: (id: number | string) => api.get<SessionDetails>(`/v1/sessions/${id}/details`),
  getSnapshots: (id: number | string) => api.get<SessionSnapshotsResponse>(`/v1/sessions/${id}/snapshots`),
  restoreSessionStart: (id: number | string) => api.post<void>(`/v1/sessions/${id}/restore-session-start`),
}

export const queueApi = {
  moveToPosition: (id: number, position: number) =>
    api.put<void, { new_position: number }>(`/v1/queue/threads/${id}/position/`, { new_position: position }),
  moveToFront: (id: number) => api.put<void>(`/v1/queue/threads/${id}/front/`),
  moveToBack: (id: number) => api.put<void>(`/v1/queue/threads/${id}/back/`),
  shuffle: () => api.post<void>('/v1/queue/shuffle/'),
}

export const undoApi = {
  undo: (sessionId: number | string, snapshotId: number | string) =>
    api.post<void>(`/v1/undo/${sessionId}/undo/${snapshotId}`),
  listSnapshots: (sessionId: number | string) => api.get<SessionSnapshotsResponse>(`/v1/undo/${sessionId}/snapshots`),
}

export const dependenciesApi = {
  listBlockedThreadIds: () => api.get<number[]>('/v1/dependencies/blocked'),
  listThreadDependencies: (threadId: number) =>
    api.get<ThreadDependenciesResponse>(`/v1/threads/${threadId}/dependencies`),
  getIssueDependencies: (issueId: number) =>
    api.get<IssueDependenciesResponse>(`/v1/issues/${issueId}/dependencies`),
  getBlockingInfo: (threadId: number) =>
    api.post<BlockingInfoResponse>(`/v1/threads/${threadId}:getBlockingInfo`),
  getBatchBlockingInfo: (threadIds: number[]) =>
    api.post<BatchBlockingInfoResponse>('/v1/threads:getBlockingInfo', { thread_ids: threadIds }),
  getConnectedThreads: (threadId: number) =>
    api.get<ConnectedDependenciesResponse>(`/v1/threads/${threadId}/connected`),
  createDependency: ({ sourceType = 'thread', sourceId, targetType = 'thread', targetId }: DependencyCreatePayload) =>
    api.post<Dependency, { source_type: 'thread' | 'issue'; source_id: number; target_type: 'thread' | 'issue'; target_id: number }>('/v1/dependencies/', {
      source_type: sourceType,
      source_id: sourceId,
      target_type: targetType,
      target_id: targetId,
    }),
  deleteDependency: (dependencyId: number) => api.delete<void>(`/v1/dependencies/${dependencyId}`),
  updateDependency: (dependencyId: number, note: string | null) =>
    api.patch<Dependency, { note: string | null }>(`/v1/dependencies/${dependencyId}`, { note }),
}

export interface ComicVineCreator {
  creator_id?: number | null
  name: string
  roles: string[]
}

export interface ComicVineComicPileMatch {
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  status: 'read' | 'unread'
}

export interface ComicVineRelatedIssue {
  comicvine_issue_id: string
  series_name: string | null
  issue_number: string | null
  name: string | null
  cover_date: string | null
  comicvine_url: string | null
  comicpile_matches: ComicVineComicPileMatch[]
}

export interface ComicVineStoryArc {
  comicvine_arc_id: number
  name: string
  comicvine_url: string | null
  related_issues: ComicVineRelatedIssue[]
  total_related_count: number | null
}

export interface ComicVineImportIssuePayload {
  title: string
  comicvine_issue_id: number
  issue_number?: string | null
  reading_order_id?: number | null
  anchor_before_thread_id?: number | null
  anchor_after_thread_id?: number | null
}

export interface ComicVineImportIssueResult {
  thread_id: number
  issue_id: number
  external_identity_id: number
  reading_order_id: number | null
  position: number | null
  total_items: number | null
}

export interface ComicVineIssueIntelligence {
  comicvine_issue_id: string
  comicvine_url: string | null
  series_name: string | null
  series_id: number | null
  issue_number: string | null
  name: string | null
  description: string | null
  image_url: string | null
  cover_date: string | null
  store_date: string | null
  creators: ComicVineCreator[]
  story_arcs: ComicVineStoryArc[]
}

export interface ComicVineSeriesResult {
  comicvine_volume_id: number
  name: string
  publisher: string | null
  start_year: number | null
  issue_count: number | null
  site_detail_url: string | null
  image_url: string | null
}

export interface ComicVineSeriesSearchResponse {
  query: string
  results: ComicVineSeriesResult[]
  total_available: number | null
}

export interface ComicVineIssueCandidate {
  comicvine_issue_id: number
  issue_number: string | null
  name: string | null
  cover_date: string | null
  store_date: string | null
  image_url: string | null
  site_detail_url: string | null
}

export interface ComicVineSeriesIssuesResponse {
  comicvine_volume_id: number
  series_name: string
  issues: ComicVineIssueCandidate[]
}

export interface IssueIdentityMapping {
  external_identity_id: number
  provider: string
  comicvine_id: string
  status: string
  confidence: number | null
  evidence_source: string | null
  created_at: string | null
}

export interface IssueIdentityResponse {
  issue_id: number
  thread_id: number
  thread_title: string
  has_confirmed_identity: boolean
  confirmed_mappings: IssueIdentityMapping[]
  candidate_mappings: IssueIdentityMapping[]
  has_unresolved: boolean
}

export interface MetadataRefreshResponse {
  issue_id: number
  refreshed: boolean
  comicvine_issue_id: string | null
}

export interface CanonicalCorrection {
  id: number
  field_name: string
  provider_value: string | null
  canonical_value: string
  provenance: string
  created_by: number
  created_at: string
}

export interface MetadataCorrectionsResponse {
  issue_id: number
  corrections: CanonicalCorrection[]
}

export const comicVineApi = {
  getIssueIntelligence: (issueId: number) =>
    api.get<ComicVineIssueIntelligence | null>(`/v1/issues/${issueId}/comicvine`),
  importIssue: (payload: ComicVineImportIssuePayload) =>
    api.post<ComicVineImportIssueResult, ComicVineImportIssuePayload>('/v1/comicvine/issues:import', payload),
  searchSeries: (query: string, limit = 10) =>
    api.get<ComicVineSeriesSearchResponse>(`/v1/comicvine/search/series`, { params: { q: query, limit } }),
  getSeriesIssues: (volumeId: number, seriesName = '') =>
    api.get<ComicVineSeriesIssuesResponse>(`/v1/comicvine/series/${volumeId}/issues`, { params: { series_name: seriesName } }),
  getIssueIdentity: (issueId: number) =>
    api.get<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity`),
  confirmIdentity: (issueId: number, comicvineIssueId: number) =>
    api.post<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity:confirm`, { comicvine_issue_id: comicvineIssueId }),
  replaceIdentity: (issueId: number, comicvineIssueId: number, reason?: string) =>
    api.post<IssueIdentityResponse>(`/v1/comicvine/issues/${issueId}/identity:replace`, { comicvine_issue_id: comicvineIssueId, reason }),
  refreshMetadata: (issueId: number) =>
    api.post<MetadataRefreshResponse>(`/v1/comicvine/issues/${issueId}/metadata:refresh`),
  applyCorrection: (issueId: number, fieldName: string, canonicalValue: string, reason?: string) =>
    api.post<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:correct`, { field_name: fieldName, canonical_value: canonicalValue, reason }),
  listCorrections: (issueId: number) =>
    api.get<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:corrections`),
  revertCorrection: (issueId: number, correctionId: number) =>
    api.post<MetadataCorrectionsResponse>(`/v1/comicvine/issues/${issueId}/metadata:revert`, { correction_id: correctionId }),
}

export const tasksApi = {
  getMetrics: () => api.get<AnalyticsMetrics>('/v1/analytics/metrics'),
}

export const snoozeApi = {
  snooze: () => api.post<void>('/v1/snooze/'),
  unsnooze: (threadId: number) => api.post<void>(`/v1/snooze/${threadId}/unsnooze`),
}

export const skipApi = {
  skip: () => api.post<RollResponse>('/v1/roll/skip'),
  unskip: (threadId: number) => api.post<void>(`/v1/roll/skip/${threadId}/unskip`),
}

export const migrationApi = {
  migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) =>
    api.post<Thread, { last_issue_read: number; total_issues: number }>(`/v1/threads/${threadId}:migrateToIssues`, data),
}

export const bugReportsApi = {
  create: (data: { title: string; description: string; diagnostics?: unknown }) =>
    api.post<BugReportResponse>('/v1/bug-reports/', data),
}
