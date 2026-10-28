import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  RollBootstrapResponse,
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
    get: (_timezone?: string) => {
      // Idle Roll uses v2 as the single authoritative bootstrap source. Timezone
      // is no longer required for the bootstrap contract; the client always
      // requests v2 regardless of browser timezone availability.
      return client.get<RollBootstrapResponse>('/v2/roll/bootstrap')
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())
