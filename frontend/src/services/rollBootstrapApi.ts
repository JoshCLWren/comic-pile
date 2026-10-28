import { defaultHttpClient, type HttpClient } from './httpClient'
import { normalizeRollV2Bootstrap } from './rollBootstrapNormalize'
import type {
  RollBootstrapResponse,
  RollPrerequisiteSwitchRequest,
  RollPrerequisiteSwitchResponse,
} from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'

/**
 * Build the roll-bootstrap service bound to an HTTP client.
 *
 * The idle Roll screen has exactly one bootstrap source: the v2 projection.
 * The response is normalized once here so every consumer keeps the bounded
 * session-chrome shape while pool rows carry the v2 comic-first enrichment.
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
      return normalizeRollV2Bootstrap(response)
    },
    switchPrerequisite: (request: RollPrerequisiteSwitchRequest) =>
      client.post<RollPrerequisiteSwitchResponse>('/v1/roll/switch-prerequisite', request),
  }
}

export const rollBootstrapApi = createRollBootstrapApi(defaultHttpClient())
