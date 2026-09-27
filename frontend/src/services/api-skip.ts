import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RollResponse } from '../types'

/**
 * Build the skip service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every skip request.
 * @returns The skip API bound to `client`.
 */
export function createSkipApi(client: HttpClient) {
  return {
    skip: () => client.post<RollResponse>('/v1/roll/skip'),
    unskip: (threadId: number) => client.post<void>(`/v1/roll/skip/${threadId}/unskip`),
  }
}

export const skipApi = createSkipApi(defaultHttpClient())
