import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RatePayload, RateUndoInfo, Thread } from '../types'

/** Rate response: the updated thread plus the undo record the rating wrote. */
export type RateResponse = Thread & { undo?: RateUndoInfo | null }

/**
 * Build the rating service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every rating request.
 * @returns The rating API bound to `client`.
 */
export function createRateApi(client: HttpClient) {
  return {
    rate: (data: RatePayload) =>
      client.post<RateResponse, RatePayload>('/v1/rate/', data),
  }
}

export const rateApi = createRateApi(defaultHttpClient())
