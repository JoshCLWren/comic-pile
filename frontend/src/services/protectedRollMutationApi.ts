import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import api, { rateApi, snoozeApi } from './api'
import { rollBootstrapApi } from './rollBootstrapApi'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

function hasConfiguredClient(): boolean {
  return api !== undefined && typeof api.post === 'function' && typeof api.get === 'function'
}

export const protectedRollMutationApi = {
  rate: (data: RatePayload): Promise<Thread> => {
    if (!hasConfiguredClient()) return rateApi.rate(data)
    return api.post<Thread, RatePayload>('/rate/', data, RECOVERY_CONFIG)
  },
  snooze: (): Promise<void> => {
    if (!hasConfiguredClient()) return snoozeApi.snooze()
    return api.post<void>('/snooze/', undefined, RECOVERY_CONFIG)
  },
  bootstrap: (): Promise<RollBootstrapResponse> => {
    if (!hasConfiguredClient()) return rollBootstrapApi.get()
    return api.get<RollBootstrapResponse>('/roll/bootstrap', RECOVERY_CONFIG)
  },
}
