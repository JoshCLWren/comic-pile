import type { RatePayload, RollResponse, SnoozeSessionResponse, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import api from './api'
import type { HttpClient } from './httpClient'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Build the protected roll-mutation service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The protected roll-mutation service bound to `client`.
 */
export function createProtectedRollMutationApi(client: HttpClient) {
  return {
  rate: (data: RatePayload): Promise<Thread> =>
    client.post<Thread, RatePayload>('/v1/rate/', data, RECOVERY_CONFIG),
  snooze: (): Promise<SnoozeSessionResponse> =>
    client.post<SnoozeSessionResponse>('/v1/snooze/', undefined, RECOVERY_CONFIG),
  skip: (): Promise<RollResponse> =>
    client.post<RollResponse>('/v1/roll/skip', undefined, RECOVERY_CONFIG),
  bootstrap: (): Promise<RollBootstrapResponse> =>
    client.get<RollBootstrapResponse>('/v1/roll/bootstrap', RECOVERY_CONFIG),
}
}

export const protectedRollMutationApi = createProtectedRollMutationApi(api)
