import type { RatePayload, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { rollBootstrapApi } from './rollBootstrapApi'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

async function loadApiModule() {
  return import('./api')
}

export const protectedRollMutationApi = {
  rate: async (data: RatePayload): Promise<Thread> => {
    const apiModule = await loadApiModule()
    if (!('default' in apiModule)) return apiModule.rateApi.rate(data)
    return apiModule.default.post<Thread, RatePayload>('/rate/', data, RECOVERY_CONFIG)
  },
  snooze: async (): Promise<void> => {
    const apiModule = await loadApiModule()
    if (!('default' in apiModule)) return apiModule.snoozeApi.snooze()
    return apiModule.default.post<void>('/snooze/', undefined, RECOVERY_CONFIG)
  },
  bootstrap: async (): Promise<RollBootstrapResponse> => {
    const apiModule = await loadApiModule()
    if (!('default' in apiModule)) return rollBootstrapApi.get()
    return apiModule.default.get<RollBootstrapResponse>('/roll/bootstrap', RECOVERY_CONFIG)
  },
}
