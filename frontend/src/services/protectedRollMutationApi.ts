import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import api from './api'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

export const protectedRollMutationApi = {
  rate: (data: RatePayload) =>
    api.post<Thread, RatePayload>('/rate/', data, RECOVERY_CONFIG),
  snooze: () => api.post<void>('/snooze/', undefined, RECOVERY_CONFIG),
  bootstrap: () => api.get<RollBootstrapResponse>('/roll/bootstrap', RECOVERY_CONFIG),
}
