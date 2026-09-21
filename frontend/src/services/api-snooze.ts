import api from './api'

export const snoozeApi = {
  snooze: () => api.post<void>('/v1/snooze/'),
  unsnooze: (threadId: number) => api.post<void>(`/v1/snooze/${threadId}/unsnooze`),
}
