import type { RollResponse, SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
import { createNativeRollMutationApi } from './nativeRollMutationApi'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { createRollApi } from './api-roll'

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
  const rollOffers = createRollApi(client)
  const { rate } = createNativeRollMutationApi(client)
  return {
    rate,
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
    bootstrap: async (): Promise<RollBootstrapResponse> =>
      adaptRollV2Bootstrap(
        await client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap', RECOVERY_CONFIG),
      ),
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
