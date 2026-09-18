import api from './api'
import type { components } from '../generated/openapi'

export type CreatorSummariesResponse = components['schemas']['CreatorSummariesResponse']
export type CreatorSummaryItem = components['schemas']['CreatorSummaryItem']
export type CreatorSummaryCoverage = components['schemas']['CreatorSummaryCoverage']

export const creatorsApi = {
  getSummaries: (keys: string[]) =>
    api.get<CreatorSummariesResponse>('/v1/creators/summaries', {
      params: { keys: keys.join(',') },
    }),
}
