import type { RollResponse } from '../types'
import type { RollState } from '../types/rollState'
import type { RollPendingUserId } from './apiTypes'
import { createRollStateApi } from './rollStateApi'
import { createNativeRollMutationApi } from './nativeRollMutationApi'
import {
  defaultHttpClient,
  type ApiRequestConfig,
  type HttpClient,
} from './httpClient'
import { createRollApi } from './api-roll'

/** Keep recovery reads inside the retry loop instead of redirecting to login. */
function withRollRecoveryConfig(client: HttpClient): HttpClient {
  return {
    get: <T = unknown>(url: string, config?: ApiRequestConfig) =>
      client.get<T>(url, { ...config, skipAuthRedirect: true }),
    post: <T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>) =>
      client.post<T, D>(url, data, { ...config, skipAuthRedirect: true }),
    patch: <T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>) =>
      client.patch<T, D>(url, data, { ...config, skipAuthRedirect: true }),
    put: <T = unknown, D = unknown>(url: string, data?: D, config?: ApiRequestConfig<D>) =>
      client.put<T, D>(url, data, { ...config, skipAuthRedirect: true }),
    delete: <T = unknown>(url: string, config?: ApiRequestConfig) =>
      client.delete<T>(url, { ...config, skipAuthRedirect: true }),
  }
}

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
    snooze: async (): Promise<RollResponse> => {
      // The Roll action-sheet snooze is the same native offer as Reroll: the
      // Rust writer records the snooze event, advances the die and selects the
      // replacement atomically. Keep the exact response so browser-owned
      // pending can be replaced with the new issue, not reconstructed later.
      return rollOffers.reroll()
    },
    /**
     * Recovery reads only scoped resources; no aggregate/session endpoint is
     * touched even when the ordinary auth redirect is suppressed. The view is
     * built lazily so transports can be injected in focused tests.
     */
    bootstrap: async (userId?: RollPendingUserId): Promise<RollState> =>
      createRollStateApi(withRollRecoveryConfig(client)).get(userId),
  }
}

export const protectedRollMutationApi = createProtectedRollMutationApi(defaultHttpClient())
