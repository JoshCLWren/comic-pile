import type { RatePayload, RollResponse, SnoozeSessionResponse, Thread } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { normalizeRollV2Bootstrap } from './rollBootstrapNormalize'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Build the protected roll-mutation service bound to an HTTP client.
 *
 * Recovery reads the same single v2 bootstrap authority as the idle screen so
 * a reconciled cache never drops back to a v1-shaped pool that cannot render
 * comic-first rows.
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
    bootstrap: async (): Promise<RollBootstrapResponse> => {
      const response = await client.get<RollV2BootstrapResponse>(
        '/v2/roll/bootstrap',
        RECOVERY_CONFIG,
      )
      return normalizeRollV2Bootstrap(response)
    },
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
