import { defaultHttpClient, type HttpClient } from './httpClient'
import type { SummariesResponse } from '../generated/nativeV2Client'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

export type CreatorSummariesResponse = SummariesResponse
export type CreatorSummaryItem = CreatorSummariesResponse['summaries'][string]
export type CreatorSummaryCoverage = CreatorSummariesResponse['coverage']

/**
 * Build the creator-summaries service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator summaries API bound to `client`.
 */
export function createCreatorSummariesApi(client: HttpClient) {
  return {
    getSummaries: (keys: string[]) =>
      client.get<CreatorSummariesResponse>('/v2/creators/summaries', {
        params: { keys: keys.join(',') },
        ...RECOVERY_CONFIG,
      }),
  }
}

export const creatorsApi = createCreatorSummariesApi(defaultHttpClient())
