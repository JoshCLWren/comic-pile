import axios from 'axios'
import { QueryClient, QueryCache } from '@tanstack/react-query'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

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
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token')
      window.location.href = '/login'
    }
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30000,
    },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      console.error('Query error:', error)
    },
  }),
})

export default api

export const threadsApi = {
  list: () => api.get('/threads/'),
  get: (id) => api.get(`/threads/${id}`),
  create: (data) => api.post('/threads/', data),
  update: (id, data) => api.put(`/threads/${id}`, data),
  delete: (id) => api.delete(`/threads/${id}`),
  reactivate: (data) => api.post('/threads/reactivate', data),
  listStale: (days = 30) => api.get('/threads/stale', { params: { days } }),
}

export const rollApi = {
  roll: () => api.post('/roll/'),
  override: (data) => api.post('/roll/override', data),
  dismissPending: () => api.post('/roll/dismiss-pending'),
  setDie: (die) => api.post('/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post('/roll/clear-manual-die'),
  reroll: () => api.post('/roll/reroll'),
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

export const tasksApi = {
  getMetrics: () => api.get('/tasks/metrics'),
}
