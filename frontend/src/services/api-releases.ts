import type { components } from '../generated/openapi'
import api from './api'
import type { HttpClient } from './httpClient'

export type Release = components['schemas']['PublicReleaseResponse']
export type ReleaseListResponse = components['schemas']['ReleaseListResponse']

/**
 * Build the public release service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every release request.
 * @returns The releases API bound to `client`.
 */
export function createReleasesApi(client: HttpClient) {
  return {
    list: (limit = 20, offset = 0) =>
      client.get<ReleaseListResponse>('/v1/releases/', {
        params: { limit, offset },
      }),
  }
}

export const releasesApi = createReleasesApi(api)
