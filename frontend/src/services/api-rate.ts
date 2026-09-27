import { defaultHttpClient, type HttpClient } from './httpClient'
import type { RatePayload, Thread } from '../types'

/**
 * Build the rating service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every rating request.
 * @returns The rating API bound to `client`.
 */
export function createRateApi(client: HttpClient) {
  return {
    rate: (data: RatePayload) =>
      client.post<Thread, RatePayload>('/v1/rate/', data),
  }
}

export const rateApi = createRateApi(defaultHttpClient())
