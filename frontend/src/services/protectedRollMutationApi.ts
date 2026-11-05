import type { RatePayload, RateResponsePayload, RollResponse, SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
import { createNativeRollMutationApi } from './nativeRollMutationApi'
import { defaultHttpClient, type HttpClient } from './httpClient'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Build the protected roll-mutation service bound to an HTTP client.
 *
 * The rating is delegated to the issue-rating writer rather than re-implemented
 * here, so one code path serves Roll completions and direct Thread-row ratings
 * and every caller gets the same retry-safe key handling.
 *
 * @param client - HTTP transport used for every request.
 * @returns The protected roll-mutation service bound to `client`.
 */
export function createProtectedRollMutationApi(client: HttpClient) {
  const { rate } = createNativeRollMutationApi(client)

  return {
    rate,
    snooze: (): Promise<SnoozeSessionResponse> =>
      client.post<SnoozeSessionResponse>('/v1/snooze/', undefined, RECOVERY_CONFIG),
    skip: (): Promise<RollResponse> =>
      client.post<RollResponse>('/v1/roll/skip', undefined, RECOVERY_CONFIG),
    bootstrap: async (): Promise<RollBootstrapResponse> =>
      adaptRollV2Bootstrap(
        await client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap', RECOVERY_CONFIG),
      ),
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
