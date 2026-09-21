import api from './api'

export const queueApi = {
  moveToPosition: (id: number, position: number) =>
    api.put<void, { new_position: number }>(`/v1/queue/threads/${id}/position/`, { new_position: position }),
  moveToFront: (id: number) => api.put<void>(`/v1/queue/threads/${id}/front/`),
  moveToBack: (id: number) => api.put<void>(`/v1/queue/threads/${id}/back/`),
  shuffle: () => api.post<void>('/v1/queue/shuffle/'),
}
