import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

let refreshTokenPromise = null
let isRedirectingToLogin = false
let redirectTimeoutId = null

/**
 * Check if currently on an auth page to prevent redirect loops.
 * @returns {boolean} True if on login or register page
 */
function isOnAuthPage() {
  const pathname = window.location.pathname
  return pathname === '/login' || pathname === '/register'
}

/**
 * Safely redirect to login page with protection against loops.
 * Clears invalid tokens before redirecting.
 */
function redirectToLogin() {
  // Prevent redirect if already on auth pages
  if (isOnAuthPage()) {
    return
  }

  // Prevent multiple rapid redirects
  if (isRedirectingToLogin) {
    return
  }

  isRedirectingToLogin = true

  // Clear any existing timeout to prevent memory leaks
  if (redirectTimeoutId) {
    clearTimeout(redirectTimeoutId)
  }

  // Clear invalid tokens before redirect
  localStorage.removeItem('auth_token')
  localStorage.removeItem('refresh_token')

  // Set a timeout to reset the flag in case redirect doesn't complete
  redirectTimeoutId = setTimeout(() => {
    isRedirectingToLogin = false
    redirectTimeoutId = null
  }, 5000)

  window.location.href = '/login'
}

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const originalRequest = error.config

    // Handle network errors (no response object)
    if (!error.response) {
      console.error('Network Error:', error.message)
      return Promise.reject(new Error('Network error. Please check your connection and try again.'))
    }

    // Log full error details for debugging
    if (error.response?.status === 400) {
      console.error('API Validation Error Details:', {
        status: error.response.status,
        data: error.response.data,
        config: error.config
      })
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      const isAuthEndpoint = originalRequest.url.includes('/auth/login') || originalRequest.url.includes('/auth/register')
      if (isAuthEndpoint) {
        return Promise.reject(error)
      }

      // Skip redirect if explicitly requested (for graceful auth handling)
      if (originalRequest.skipAuthRedirect) {
        return Promise.reject(error)
      }

      originalRequest._retry = true

      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          if (!refreshTokenPromise) {
            refreshTokenPromise = api.post('/auth/refresh', {
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
          redirectToLogin()
          return Promise.reject(refreshError)
        }
      } else {
        redirectToLogin()
      }
    }

    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default api

export const threadsApi = {
  list: (params) => api.get('/threads/', { params }),
  get: (id) => api.get(`/threads/${id}`),
  create: (data) => api.post('/threads/', data),
  update: (id, data) => api.put(`/threads/${id}`, data),
  delete: (id) => api.delete(`/threads/${id}`),
  reactivate: (data) => api.post('/threads/reactivate', data),
  listStale: (days = 30) => api.get('/threads/stale', { params: { days } }),
  setPending: (id) => api.post(`/threads/${id}/set-pending`),
}

export const rollApi = {
  roll: () => api.post('/roll/'),
  override: (data) => api.post('/roll/override', data),
  dismissPending: () => api.post('/roll/dismiss-pending'),
  reroll: () => api.post('/roll/'),
  setDie: (die) => api.post('/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post('/roll/clear-manual-die'),
}

export const rateApi = {
  rate: (data) => api.post('/rate/', data),
}

export const sessionApi = {
  list: (params) => api.get('/sessions/', { params }),
  get: (id) => api.get(`/sessions/${id}`),
  getCurrent: () => api.get('/sessions/current/'),
  getDetails: (id) => api.get(`/sessions/${id}/details`),
  getSnapshots: (id) => api.get(`/sessions/${id}/snapshots`),
  restoreSessionStart: (id) => api.post(`/sessions/${id}/restore-session-start`),
}

export const queueApi = {
  moveToPosition: (id, position) => api.put(`/queue/threads/${id}/position/`, { new_position: position }),
  moveToFront: (id) => api.put(`/queue/threads/${id}/front/`),
  moveToBack: (id) => api.put(`/queue/threads/${id}/back/`),
}

export const undoApi = {
  undo: (sessionId, snapshotId) => api.post(`/undo/${sessionId}/undo/${snapshotId}`),
  listSnapshots: (sessionId) => api.get(`/undo/${sessionId}/snapshots`),
}

export const dependenciesApi = {
  listBlockedThreadIds: () => api.get('/v1/dependencies/blocked'),
  listThreadDependencies: (threadId) => api.get(`/v1/threads/${threadId}/dependencies`),
  getBlockingInfo: (threadId) => api.post(`/v1/threads/${threadId}:getBlockingInfo`),
  createDependency: ({ sourceType = 'thread', sourceId, targetType = 'thread', targetId }) =>
    api.post('/v1/dependencies/', {
      source_type: sourceType,
      source_id: sourceId,
      target_type: targetType,
      target_id: targetId,
    }),
  deleteDependency: (dependencyId) => api.delete(`/v1/dependencies/${dependencyId}`),
}

export const tasksApi = {
  getMetrics: () => api.get('/analytics/metrics'),
}

export const snoozeApi = {
  snooze: () => api.post('/snooze/'),
  unsnooze: (threadId) => api.post(`/snooze/${threadId}/unsnooze`),
}

export const collectionsApi = {
  list: () => api.get('/v1/collections/'),
  get: (id) => api.get(`/v1/collections/${id}`),
  create: (data) => api.post('/v1/collections/', data),
  update: (id, data) => api.put(`/v1/collections/${id}`, data),
  delete: (id) => api.delete(`/v1/collections/${id}`),
  moveThreadToCollection: (threadId, collectionId) =>
    api.post(`/threads/${threadId}:moveToCollection`, null, { params: { collection_id: collectionId } }),
}

export const migrationApi = {
  migrateThread: (threadId, data) => api.post(`/threads/${threadId}:migrateToIssues`, data),
}
