import api from './api'
import type { RatePayload, Thread } from '../types'

export const rateApi = {
  rate: (data: RatePayload) =>
    api.post<Thread, RatePayload>('/v1/rate/', data),
}
