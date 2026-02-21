import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

// Create base axios instance
const axiosInstance = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

let refreshTokenPromise: Promise<{ access_token: string; refresh_token: string }> | null = null
let isRedirectingToLogin = false

axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => Promise.reject(error)
)

axiosInstance.interceptors.response.use(
  <T>(response: AxiosResponse<T>): T => response.data,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // Log full error details for debugging
    if (error.response?.status === 400) {
      console.error('API Validation Error Details:', {
        status: error.response.status,
        data: error.response.data,
        config: error.config
      })
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      const isAuthEndpoint = originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/register')
      if (isAuthEndpoint) {
        return Promise.reject(error)
      }

      originalRequest._retry = true

      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          if (!refreshTokenPromise) {
            refreshTokenPromise = axiosInstance.post<{ access_token: string; refresh_token: string }>('/auth/refresh', {
              refresh_token: refreshToken,
            }).then(response => response.data) as Promise<{ access_token: string; refresh_token: string }>
          }

          const tokens = await refreshTokenPromise
          refreshTokenPromise = null

          localStorage.setItem('auth_token', tokens.access_token)
          localStorage.setItem('refresh_token', tokens.refresh_token)

          originalRequest.headers.Authorization = `Bearer ${tokens.access_token}`
          return axiosInstance(originalRequest)
        } catch (refreshError) {
          refreshTokenPromise = null
          if (!isRedirectingToLogin) {
            isRedirectingToLogin = true
            localStorage.removeItem('auth_token')
            localStorage.removeItem('refresh_token')
            window.location.href = '/login'
          }
          return Promise.reject(refreshError)
        }
      } else {
        if (!isRedirectingToLogin) {
          isRedirectingToLogin = true
          localStorage.removeItem('auth_token')
          localStorage.removeItem('refresh_token')
          window.location.href = '/login'
        }
      }
    }

    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// Type-safe API wrapper that ensures interceptor types are correctly applied
const api = {
  get: <T = unknown>(url: string, config?: object): Promise<T> => 
    axiosInstance.get<T>(url, config) as unknown as Promise<T>,
  post: <T = unknown>(url: string, data?: unknown, config?: object): Promise<T> =>
    axiosInstance.post<T>(url, data, config) as unknown as Promise<T>,
  put: <T = unknown>(url: string, data?: unknown, config?: object): Promise<T> =>
    axiosInstance.put<T>(url, data, config) as unknown as Promise<T>,
  delete: <T = unknown>(url: string, config?: object): Promise<T> =>
    axiosInstance.delete<T>(url, config) as unknown as Promise<T>,
}

export default api

interface Thread {
  id: number
  title: string
  format: string
  issues_remaining: number
  notes: string | null
  queue_position: number
  last_rating: number | null
  status: string
  last_activity_at: string | null
  review_url: string | null
  last_review_at: string | null
  is_test: boolean
  created_at: string
}

interface CreateThreadData {
  title: string
  format: string
  issues_remaining: number
  notes?: string | null
}

interface UpdateThreadData extends Partial<CreateThreadData> {}

interface ReactivateThreadData {
  thread_id: number
  issues_to_add: number
}

interface RollResponse {
  thread_id: number
  title: string
  format: string
  issues_remaining: number
  queue_position: number
  die_size: number
  result: number
  offset: number
  snoozed_count: number
}

interface RateData {
  rating: number
  issues_read: number
  finish_session: boolean
}

interface SessionListParams {
  page?: number
  per_page?: number
}

interface ActiveThreadInfo {
  id: number | null
  title: string
  format: string
}

interface SnoozedThreadInfo {
  id: number
  title: string
  format: string
}

interface Session {
  id: number
  started_at: string
  ended_at: string | null
  start_die: number
  manual_die: number | null
  user_id: number
  ladder_path: string
  active_thread: ActiveThreadInfo | null
  current_die: number
  last_rolled_result: number | null
  has_restore_point: boolean
  snapshot_count: number
  snoozed_thread_ids: number[]
  snoozed_threads: SnoozedThreadInfo[]
  pending_thread_id: number | null
}

interface SnapshotData {
  id: number
  timestamp: string
  action: string
}

interface MetricsData {
  total_threads: number
  active_threads: number
  completed_threads: number
  completion_rate: number
  average_rating: number
  average_session_hours: number
  recent_sessions: {
    id: number
    start_die: number
    started_at: string
    ended_at: string | null
  }[]
  event_stats: { [eventType: string]: number }
  top_rated_threads: {
    id: number
    title: string
    rating: number
    format: string | null
  }[]
}

interface SessionEvent {
  id: number
  timestamp: string
  type: string
  thread_title: string | null
  rating: number | null
  result: number | null
  die: number | null
  queue_move: string | null
}

interface SessionDetails {
  session_id: number
  started_at: string
  ended_at: string | null
  start_die: number
  current_die: number
  ladder_path: string
  narrative_summary: { [key: string]: string[] } | null
  events: SessionEvent[]
}

export const threadsApi = {
  list: () => api.get<Thread[]>('/threads/'),
  get: (id: number) => api.get<Thread>(`/threads/${id}`),
  create: (data: CreateThreadData) => api.post<Thread>('/threads/', data),
  update: (id: number, data: UpdateThreadData) => api.put<Thread>(`/threads/${id}`, data),
  delete: (id: number) => api.delete(`/threads/${id}`),
  reactivate: (data: ReactivateThreadData) => api.post<Thread>('/threads/reactivate', data),
  listStale: (days = 30) => api.get<Thread[]>('/threads/stale', { params: { days } }),
  setPending: (id: number) => api.post<Thread>(`/threads/${id}/set-pending`),
}

export const rollApi = {
  roll: () => api.post<RollResponse>('/roll/'),
  override: (data: { thread_id: number }) => api.post<RollResponse>('/roll/override', data),
  setDie: (die: number) => api.post('/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post('/roll/clear-manual-die'),
  dismissPending: () => api.post('/roll/dismiss-pending'),
  reroll: () => api.post('/roll/reroll'),
}

export const rateApi = {
  rate: (data: RateData) => api.post('/rate/', data),
}

export type { Thread, CreateThreadData, UpdateThreadData, ReactivateThreadData, RollResponse, RateData, Session, ActiveThreadInfo, SnoozedThreadInfo, SnapshotData, MetricsData, SessionDetails, SessionEvent }

export const sessionApi = {
  list: (params?: SessionListParams) => api.get<Session[]>('/sessions/', { params }),
  get: (id: number) => api.get<Session>(`/sessions/${id}`),
  getCurrent: () => api.get<Session>('/sessions/current/'),
  getDetails: (id: number) => api.get<SessionDetails>(`/sessions/${id}/details`),
  getSnapshots: (id: number) => api.get<SnapshotData[]>(`/sessions/${id}/snapshots`),
  restoreSessionStart: (id: number) => api.post(`/sessions/${id}/restore-session-start`),
}

export const queueApi = {
  moveToPosition: (id: number, position: number) => api.put(`/queue/threads/${id}/position/`, { new_position: position }),
  moveToFront: (id: number) => api.put(`/queue/threads/${id}/front/`),
  moveToBack: (id: number) => api.put(`/queue/threads/${id}/back/`),
}

export const undoApi = {
  undo: (sessionId: number, snapshotId: number) => api.post(`/undo/${sessionId}/undo/${snapshotId}`),
  listSnapshots: (sessionId: number) => api.get<SnapshotData[]>(`/undo/${sessionId}/snapshots`),
}

export const tasksApi = {
  getMetrics: () => api.get<MetricsData>('/analytics/metrics'),
}

export const snoozeApi = {
  snooze: () => api.post('/snooze/'),
  unsnooze: (threadId: number) => api.post(`/snooze/${threadId}/unsnooze`),
}
