import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  RollExclusionCategory,
  RollExclusionPageResponse,
} from '../types/rollBootstrap'

/** Query parameters for one Roll exclusion drill-down page. */
export interface RollExclusionPageRequest {
  limit: number
  offset: number
}

/**
 * Build the Roll exclusion drill-down service bound to an HTTP client.
 *
 * Issue #3330: the Roll bootstrap only carries bounded previews, so this
 * service is the authoritative path to every blocked or out-of-pool series.
 *
 * @param client - HTTP transport used for every request.
 * @returns The Roll exclusion service bound to `client`.
 */
export function createRollExclusionsApi(client: HttpClient) {
  return {
    list: (category: RollExclusionCategory, { limit, offset }: RollExclusionPageRequest) =>
      client.get<RollExclusionPageResponse>('/v1/roll/exclusions', {
        params: { category, limit, offset },
      }),
  }
}

export const rollExclusionsApi = createRollExclusionsApi(defaultHttpClient())
