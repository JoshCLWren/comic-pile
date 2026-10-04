import api from './api'
import type { components } from '../generated/openapi'

export type SeriesMappingPreviewRequest = components['schemas']['SeriesMappingPreviewRequest']
export type SeriesMappingPreviewResponse = components['schemas']['SeriesMappingPreviewResponse']
export type SeriesMappingCommitRequest = components['schemas']['SeriesMappingCommitRequest']
export type SeriesMappingCommitResponse = components['schemas']['SeriesMappingCommitResponse']

export const seriesMappingsApi = {
  preview: (payload: SeriesMappingPreviewRequest) =>
    api.post<SeriesMappingPreviewResponse, SeriesMappingPreviewRequest>(
      '/v1/catalog/series-mappings/preview',
      payload,
    ),
  commit: (payload: SeriesMappingCommitRequest) =>
    api.post<SeriesMappingCommitResponse, SeriesMappingCommitRequest>(
      '/v1/catalog/series-mappings/commit',
      payload,
    ),
}
