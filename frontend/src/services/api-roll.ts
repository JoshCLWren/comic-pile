import api from './api'
import type { RollResponse } from '../types'

export const rollApi = {
  roll: () => api.post<RollResponse>('/v1/roll/'),
  override: (data: { thread_id: number }) => api.post<RollResponse, { thread_id: number }>('/v1/roll/override', data),
  dismissPending: () => api.post<void>('/v1/roll/dismiss-pending'),
  skip: () => api.post<RollResponse>('/v1/roll/skip'),
  reroll: () => api.post<RollResponse>('/v1/roll/'),
  setDie: (die: number) => api.post<void>('/v1/roll/set-die', null, { params: { die } }),
  clearManualDie: () => api.post<void>('/v1/roll/clear-manual-die'),
}
