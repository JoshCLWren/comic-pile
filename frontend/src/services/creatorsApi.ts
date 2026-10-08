import { defaultHttpClient, type HttpClient } from './httpClient'
import type { components } from '../generated/openapi'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

export type CreatorSummariesResponse = components['schemas']['CreatorSummariesResponse']
export type CreatorSummaryItem = components['schemas']['CreatorSummaryItem']
export type CreatorSummaryCoverage = components['schemas']['CreatorSummaryCoverage']

/**
 * Build the creator-summaries service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator summaries API bound to `client`.
 */
export function createCreatorSummariesApi(client: HttpClient) {
  return {
    getSummaries: (keys: string[]) =>
      client.get<CreatorSummariesResponse>('/v1/creators/summaries', {
        params: { keys: keys.join(',') },
        ...RECOVERY_CONFIG,
      }),
  }
}

export const creatorsApi = createCreatorSummariesApi(defaultHttpClient())
