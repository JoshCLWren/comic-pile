import { defaultHttpClient, type HttpClient } from './httpClient'
import type { CreatorComparisonResponse } from '../types/index'

/**
 * Build the creator comparison service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator comparison API bound to `client`.
 */
export function createCreatorComparisonApi(client: HttpClient) {
  return {
    getComparison: (keys: string[]) =>
      client.get<CreatorComparisonResponse>('/v1/creators/compare', {
        params: { keys: keys.join(',') },
      }),
  }
}

export const creatorComparisonApi = createCreatorComparisonApi(defaultHttpClient())