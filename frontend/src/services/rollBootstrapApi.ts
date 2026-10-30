import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
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
    get: async (timezone?: string): Promise<RollBootstrapResponse> => {
      const response = timezone
        ? await client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap', {
            params: { timezone },
          })
        : await client.get<RollV2BootstrapResponse>('/v2/roll/bootstrap')
      return adaptRollV2Bootstrap(response)
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())
