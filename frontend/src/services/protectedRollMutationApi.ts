import type { RollResponse, SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollPendingUserId } from './apiTypes'
import { createRollBootstrapApi } from './rollBootstrapApi'
import { createNativeRollMutationApi } from './nativeRollMutationApi'
import { defaultHttpClient, type HttpClient } from './httpClient'
import { createRollApi } from './api-roll'

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
    snooze: async (): Promise<SnoozeSessionResponse & RollResponse> => {
      // The Roll action-sheet snooze is the same native offer as Reroll: the
      // Rust writer records the snooze event, advances the die and selects the
      // replacement atomically. The legacy v1 snooze route is retired (#4338).
      // Keep the full offer alongside the snooze projection so callers can seed
      // the browser-owned pending selection with the exact replacement issue.
      const response = await rollOffers.reroll()
      return {
        ...response,
        current_die: response.die_size,
        pending_thread_id: response.thread_id ?? null,
        reading_mode_suggested: false,
        correction: null,
      }
    },
    /**
     * Recovery reads only scoped resources; no aggregate/session endpoint is
     * touched even when the ordinary auth redirect is suppressed. The view is
     * built lazily so transports can be injected in focused tests.
     */
    bootstrap: async (userId?: RollPendingUserId): Promise<RollBootstrapResponse> =>
      createRollBootstrapApi(client).get(userId),
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
