import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

let refreshTokenPromise: Promise<{ access_token: string; refresh_token: string }> | null = null
let isRedirectingToLogin = false

api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: AxiosError) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response.data,
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
            refreshTokenPromise = api.post<{ access_token: string; refresh_token: string }>('/auth/refresh', {
              refresh_token: refreshToken,
            })
          }

          const response = await refreshTokenPromise
          refreshTokenPromise = null

          const { access_token, refresh_token: newRefreshToken } = response
          localStorage.setItem('auth_token', access_token)
          localStorage.setItem('refresh_token', newRefreshToken)

          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return api(originalRequest)
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

export default api

interface Thread {
  id: number
  title: string
  format: string
  issues_remaining: number
  notes?: string
  queue_position?: number
  last_rating?: number
  is_pending?: boolean
}

interface CreateThreadData {
  title: string
  format: string
  issues_remaining: number
  notes?: string
}

interface UpdateThreadData extends Partial<CreateThreadData> {}

interface ReactivateThreadData {
  thread_id: number
}

interface RollResponse {
  title: string
  format: string
  issues_remaining: number
  thread_id: number
  queue_position: number
  is_pending: boolean
}

interface RateData {
  thread_id: number
  rating: number
}

interface SessionListParams {
  page?: number
  per_page?: number
}

interface Session {
  id: number
  created_at: string
  updated_at: string
  roll_result?: string
  rating?: number
}

interface SnapshotData {
  id: number
  timestamp: string
  action: string
}

interface MetricsData {
  total_threads: number
  completed_threads: number
  average_rating: number
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
}

export const rateApi = {
  rate: (data: RateData) => api.post('/rate/', data),
}

export const sessionApi = {
  list: (params?: SessionListParams) => api.get<Session[]>('/sessions/', { params }),
  get: (id: number) => api.get<Session>(`/sessions/${id}`),
  getCurrent: () => api.get<Session>('/sessions/current/'),
  getDetails: (id: number) => api.get(`/sessions/${id}/details`),
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
