import type { RatePayload, RateResponsePayload, RollResponse, SnoozeSessionResponse } from '../types'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import type { RollV2BootstrapResponse } from '../types/rollV2'
import { adaptRollV2Bootstrap } from './adaptRollV2Bootstrap'
import { adaptNativeV2Rate } from './adaptNativeV2Rate'
import { createNativeV2Client } from '../generated/nativeV2Client'
import { defaultHttpClient, type HttpClient } from './httpClient'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/**
 * Build the protected roll-mutation service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The protected roll-mutation service bound to `client`.
 */
export function createProtectedRollMutationApi(client: HttpClient) {
  const nativeClient = createNativeV2Client(client)

  return {
    rate: (data: RatePayload): Promise<RateResponsePayload> => {
      const { issue_id, idempotency_key, source = 'roll_offer', ...rest } = data
      if (!issue_id) {
        return Promise.reject(new Error('issue_id is required for native V2 rate endpoint'))
      }
      return nativeClient.issueReadRate({
        path: { issue_id },
        body: {
          status: 'read',
          rating: rest.rating,
          idempotency_key: idempotency_key ?? `rate-${issue_id}-${Date.now()}`,
          source,
        },
      }).then(adaptNativeV2Rate)
    },
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
