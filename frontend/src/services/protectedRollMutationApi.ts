import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import api from './api'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

export const protectedRollMutationApi = {
  rate: (data: RatePayload): Promise<Thread> =>
    api.post<Thread, RatePayload>('/v1/rate/', data, RECOVERY_CONFIG),
  snooze: (): Promise<void> =>
    api.post<void>('/snooze/', undefined, RECOVERY_CONFIG),
  bootstrap: (): Promise<RollBootstrapResponse> =>
    api.get<RollBootstrapResponse>('/v1/roll/bootstrap', RECOVERY_CONFIG),
}
