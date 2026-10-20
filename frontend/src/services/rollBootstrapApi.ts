import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  RollBlockedThreadsPage,
  RollBootstrapResponse,
  RollInactiveThreadsPage,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'

/**
 * Build the roll-bootstrap service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The roll-bootstrap service bound to `client`.
 */
export function createRollBootstrapApi(client: HttpClient) {
  return {
    get: (timezone?: string) => {
      if (!timezone) return client.get<RollBootstrapResponse>('/v1/roll/bootstrap')
      return client.get<RollBootstrapResponse>('/v1/roll/bootstrap', {
        params: { timezone },
      })
    },
    /**
     * Fetch one offset page of the blocked-series category (issue #3330).
     *
     * @param offset - Rows to skip, matching the bootstrap preview length.
     * @param limit - Page size.
     */
    getBlockedThreadsPage: (offset: number, limit: number) =>
      client.get<RollBlockedThreadsPage>('/v1/roll/blocked-threads', {
        params: { offset, limit },
      }),
    /**
     * Fetch one offset page of the out-of-pool category (issue #3330).
     *
     * @param offset - Rows to skip, matching the bootstrap preview length.
     * @param limit - Page size.
     */
    getInactiveThreadsPage: (offset: number, limit: number) =>
      client.get<RollInactiveThreadsPage>('/v1/roll/inactive-threads', {
        params: { offset, limit },
      }),
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())
