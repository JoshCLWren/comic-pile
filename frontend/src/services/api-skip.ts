import api from './api'
import type { RollResponse } from '../types'

export const skipApi = {
  skip: () => api.post<RollResponse>('/v1/roll/skip'),
  unskip: (threadId: number) => api.post<void>(`/v1/roll/skip/${threadId}/unskip`),
}
