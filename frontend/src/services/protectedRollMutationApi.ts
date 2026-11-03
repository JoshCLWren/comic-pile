import type { RatePayload, RateResponsePayload, RollResponse, SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { createRollApi } from './api-roll'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Build the protected roll-mutation service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The protected roll-mutation service bound to `client`.
 */
export function createProtectedRollMutationApi(client: HttpClient) {
  const rollOffers = createRollApi(client)
  return {
    rate: (data: RatePayload): Promise<RateResponsePayload> =>
      client.post<RateResponsePayload, RatePayload>('/v1/rate/', data, RECOVERY_CONFIG),
    snooze: async (): Promise<SnoozeSessionResponse> => {
      // The Roll action-sheet snooze is the same native offer as Reroll: the
      // Rust writer records the snooze event, advances the die and selects the
      // replacement atomically. The legacy v1 snooze route is retired (#4338).
      const response = await rollOffers.reroll()
      return {
        current_die: response.die_size,
        pending_thread_id: response.thread_id ?? null,
        reading_mode_suggested: false,
        correction: null,
      }
    },
    skip: (): Promise<RollResponse> =>
      client.post<RollResponse>('/v1/roll/skip', undefined, RECOVERY_CONFIG),
    bootstrap: async (): Promise<RollBootstrapResponse> =>
      adaptRollV2Bootstrap(
        await client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap', RECOVERY_CONFIG),
      ),
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
