import type { components } from '../generated/openapi'
import api from './api'

export type Release = components['schemas']['PublicReleaseResponse']
export type ReleaseListResponse = {
  releases: Release[]
  next_page_token: string | null
}

export const releasesApi = {
  list: (limit = 20, pageToken?: string | null) =>
    api.get<ReleaseListResponse>('/v1/releases/', {
      params: {
        ...(limit !== 20 ? { page_size: limit } : {}),
        ...(pageToken ? { page_token: pageToken } : {}),
      },
    }),
}
