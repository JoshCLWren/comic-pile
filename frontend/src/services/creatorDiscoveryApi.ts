import { defaultHttpClient, type HttpClient } from './httpClient'
import type { CreatorDiscoveryResponse } from '../types/index'

/**
 * Build the creator taste-discovery service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator taste-discovery API bound to `client`.
 */
export function createCreatorDiscoveryApi(client: HttpClient) {
  return {
    getDiscoveries: () =>
      client.get<CreatorDiscoveryResponse>('/v1/creators/discoveries'),
  }
}

export const creatorDiscoveryApi = createCreatorDiscoveryApi(defaultHttpClient())
