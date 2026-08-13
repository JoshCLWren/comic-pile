import type { components } from '../generated/openapi'
import api from './api'

export type Release = components['schemas']['PublicReleaseResponse']
export type ReleaseListResponse = components['schemas']['ReleaseListResponse']

export const releasesApi = {
  list: (limit = 20, offset = 0) =>
    api.get<ReleaseListResponse>('/v1/releases/', {
      params: { limit, offset },
    }),
}
