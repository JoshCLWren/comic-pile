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
    get: (timezone?: string) => {
      if (!timezone) return client.get<RollBootstrapResponse>('/v1/roll/bootstrap')
      return client.get<RollBootstrapResponse>('/v1/roll/bootstrap', {
        params: { timezone },
      })
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())
