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
  ConnectedDependenciesResponse,
  Dependency,
  DependencyCreatePayload,
  IssueDependenciesResponse,
  RollResponse,
  Thread,
  ThreadDependenciesResponse,
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
// SAFETY: rawApi is an AxiosInstance; response interceptor unwraps .data at the boundary so the ApiClient contract holds.
const api = rawApi as ApiClient

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

export async function refreshSession(options?: { skipAuthRedirect?: boolean }): Promise<string> {
  if (sessionRefreshRejected) {
    throw buildRejectedRefreshError()
  }
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      const response = options?.skipAuthRedirect
        ? await api.post<AuthTokens>('/v1/auth/refresh', undefined, { skipAuthRedirect: true })
        : await api.post<AuthTokens>('/v1/auth/refresh')
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

async function ensureCsrfToken(): Promise<string | null> {
  const existingToken = getCookieValue(CSRF_COOKIE_NAME)
  if (existingToken) {
    return existingToken
  }

  if (!csrfTokenPromise) {
    // SAFETY: only the skipAuthRedirect flag is needed from ApiRequestConfig; other fields have sensible defaults.
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

  // SAFETY: axios 403 responses always carry a JSON body; narrowing to check for auth-failure detail.
  const responseData = error.response.data as { detail?: unknown } | undefined
  return responseData?.detail === 'Not authenticated'
}

rawApi.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    config.headers = config.headers ?? {}

    if (token) {
      // SAFETY: InternalAxiosRequestHeaders is indexable by string key; setting Authorization is safe.
      (config.headers as Record<string, string>).Authorization = `Bearer ${token}`
    }

    if (shouldAttachCsrfToken(config)) {
      const csrfToken = await ensureCsrfToken()
      if (csrfToken) {
        // SAFETY: InternalAxiosRequestHeaders is indexable by string key; CSRF header assignment is safe.
        (config.headers as Record<string, string>)[CSRF_HEADER_NAME] = csrfToken
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
      // SAFETY: headers is initialized above and is indexable by string; Authorization assignment is safe.
      const authHeaders = prom.config.headers as Record<string, string>
      authHeaders.Authorization = `Bearer ${token}`
      prom.resolve(api.request(prom.config))
    }
  })
  failedQueue = []
}

rawApi.interceptors.response.use(
  (response) => response.data,
  async (error: AxiosError) => {
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
          failedQueue.push({ resolve, reject, config: originalRequest })
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
        const access_token = await refreshSession({
          skipAuthRedirect: originalRequest.skipAuthRedirect,
        })

        processQueue(null, access_token)
        isRefreshing = false

        originalRequest.headers = originalRequest.headers ?? {}
        // SAFETY: headers is initialized above and is indexable by string; Authorization assignment is safe.
        const authHeaders = originalRequest.headers as Record<string, string>
        authHeaders.Authorization = `Bearer ${access_token}`
        return api.request(originalRequest)
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
  },
)

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
  offset: number
  limit: number
  has_more: boolean
  next_offset: number | null
}

export interface ComicVineResolvedIssue {
  comicvine_issue_id: number
  series_name: string | null
  volume_id: number | null
  issue_number: string | null
  name: string | null
  cover_date: string | null
  store_date: string | null
  image_url: string | null
  site_detail_url: string | null
}

export type ComicVineResolveKind = 'issue' | 'volume' | 'search'

export interface ComicVineResolveResponse {
  input: string
  kind: ComicVineResolveKind
  validation_error: string | null
  issue: ComicVineResolvedIssue | null
  volume: ComicVineSeriesResult | null
  issues: ComicVineIssueCandidate[]
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
  comicvine_issue_id: string | null
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
  searchSeries: (query: string, limit = 10, offset = 0) =>
    api.get<ComicVineSeriesSearchResponse>(`/v1/comicvine/search/series`, { params: { q: query, limit, offset } }),
  resolveIdentity: (input: string) =>
    api.get<ComicVineResolveResponse>(`/v1/comicvine/resolve`, { params: { input } }),
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

/** Headline personal summary for one stable creator identity (issue #2028). */
export interface CreatorSummaryItem {
  canonical_creator_key: string
  display_name: string
  normalized_roles: string[]
  average_rating: number | null
  ratings_count: number
  read_unrated_count: number
  upcoming_count: number
}

/** Library-wide metadata coverage state distinguishing complete from lower-bound stats. */
export interface CreatorSummaryCoverage {
  rated_issues_total: number
  rated_issues_with_creator_metadata: number
  ratings_complete: boolean
  read_unrated_issues_total: number
  read_unrated_issues_with_creator_metadata: number
  read_unrated_complete: boolean
  unread_issues_total: number
  unread_issues_with_creator_metadata: number
  upcoming_complete: boolean
}

export interface CreatorRoleStat {
  role: string
  issue_count: number
  average_rating: number | null
}

export interface CreatorIssueRow {
  issue_id: number
  issue_number: string
  thread_id: number
  thread_title: string
  status: string
  roles: string[]
  effective_rating: number | null
  rating_timestamp: string | null
  sort_key: string
}

/** Full personal creator detail payload (issue #2037). */
export interface CreatorDetailResponse {
  summary: CreatorSummaryItem
  coverage: CreatorSummaryCoverage
  role_stats: CreatorRoleStat[]
  rated_issues: CreatorIssueRow[]
  read_unrated_issues: CreatorIssueRow[]
  upcoming_issues: CreatorIssueRow[]
  next_cursor: string | null
}

export interface CreatorDetailPageParams {
  limit?: number
  offset?: number
}

export const creatorsApi = {
  getDetail: (creatorKey: string, params: CreatorDetailPageParams = {}) => {
    const queryParams: Record<string, string | number> = {}
    if (params.limit !== undefined) {
      queryParams.limit = params.limit
    }
    if (params.offset !== undefined && params.offset > 0) {
      queryParams.offset = params.offset
    }
    return api.get<CreatorDetailResponse>(
      `/v1/creators/${encodeURIComponent(creatorKey)}`,
      { params: queryParams },
    )
  },
}

// Temporary reading-runtime re-exports keep this slice independently shippable.
// TODO(#2785): remove these re-exports once every call site imports the focused domain clients.
export { snoozeApi } from './api-snooze'
export { skipApi } from './api-skip'

export const migrationApi = {
  migrateThread: (threadId: number, data: { last_issue_read: number; total_issues: number }) =>
    api.post<Thread, { last_issue_read: number; total_issues: number }>(`/v1/threads/${threadId}:migrateToIssues`, data),
}

export const bugReportsApi = {
  create: (data: { title: string; description: string; diagnostics?: unknown }) =>
    api.post<BugReportResponse>('/v1/bug-reports/', data),
}

export interface IdentityInboxCandidate {
  external_identity_id: number
  provider: string
  comicvine_id: string | null
  external_url: string | null
  metadata_json: Record<string, string | Record<string, string> | null>
  status: string
  confidence: number | null
  evidence_source: string | null
  evidence_json: Record<string, string | string[] | null>
  rejection_reason: string | null
}

export interface IdentityInboxItem {
  mapping_id: number
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  status: string
  provider: string | null
  source_entry_summary: string
  why_stopped: string
  candidates: IdentityInboxCandidate[]
  created_at: number | null
  updated_at: number | null
}

export interface IdentityInboxResponse {
  items: IdentityInboxItem[]
  total: number
  offset: number
  limit: number
}

export interface IdentityInboxConfirmPayload {
  external_identity_id: number
}

export interface IdentityInboxRejectPayload {
  external_identity_id: number
  rejection_reason: string
}

export const identityInboxApi = {
  list: (offset: number, limit: number) =>
    api.get<IdentityInboxResponse>('/v1/identity-inbox', { params: { offset, limit } }),
  confirm: (mappingId: number, payload: IdentityInboxConfirmPayload) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/confirm`, payload),
  reject: (mappingId: number, payload: IdentityInboxRejectPayload) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/reject`, payload),
  defer: (mappingId: number) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/defer`),
  skip: (mappingId: number) =>
    api.post<void>(`/v1/identity-inbox/${mappingId}/skip`),
}

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
