import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  CreatorAverageDrilldownResponse,
  CreatorComparisonResponse,
  CreatorDistributionDrilldownResponse,
  CreatorFiveStarRateDrilldownResponse,
  CreatorMedianDrilldownResponse,
  CreatorReadWithoutRatingDrilldownResponse,
  CreatorRoleAverageDrilldownResponse,
  CreatorSeriesAverageDrilldownResponse,
  CreatorUnreadDrilldownResponse,
} from '../types/index'

/** Bounded evidence page size requested from every drilldown endpoint. */
export const DRILLDOWN_PAGE_SIZE = 50

/** Shared query parameters for paginated drilldown evidence pages. */
export interface CreatorDrilldownParams {
  creator: string
  limit?: number
  cursor?: string | null
}

/** Query parameters for one rating-distribution bucket evidence page. */
export interface CreatorDistributionDrilldownParams extends CreatorDrilldownParams {
  bucket: string
}

/** Query parameters for one role average evidence page. */
export interface CreatorRoleAverageDrilldownParams extends CreatorDrilldownParams {
  role: string
}

/** Query parameters for one series average evidence page. */
export interface CreatorSeriesAverageDrilldownParams extends CreatorDrilldownParams {
  series: string
}

function drilldownQueryParams(params: CreatorDrilldownParams): Record<string, string | number> {
  const queryParams: Record<string, string | number> = { creator: params.creator }
  if (params.limit !== undefined) {
    queryParams.limit = params.limit
  }
  if (params.cursor) {
    queryParams.cursor = params.cursor
  }
  return queryParams
}

/**
 * Build the creator comparison service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The creator comparison API bound to `client`.
 */
export function createCreatorComparisonApi(client: HttpClient) {
  return {
    getComparison: (keys: string[]) =>
      client.get<CreatorComparisonResponse>('/v1/creators/compare', {
        params: { keys: keys.join(',') },
      }),
    getAverageDrilldown: (params: CreatorDrilldownParams) =>
      client.get<CreatorAverageDrilldownResponse>(
        '/v1/creators/compare/average',
        { params: drilldownQueryParams(params) },
      ),
    getMedianDrilldown: (params: CreatorDrilldownParams) =>
      client.get<CreatorMedianDrilldownResponse>(
        '/v1/creators/compare/median',
        { params: drilldownQueryParams(params) },
      ),
    getDistributionDrilldown: (params: CreatorDistributionDrilldownParams) =>
      client.get<CreatorDistributionDrilldownResponse>('/v1/creators/compare/distribution', {
        params: { ...drilldownQueryParams(params), bucket: params.bucket },
      }),
    getFiveStarRateDrilldown: (params: CreatorDrilldownParams) =>
      client.get<CreatorFiveStarRateDrilldownResponse>(
        '/v1/creators/compare/5-star-rate',
        { params: drilldownQueryParams(params) },
      ),
    getRoleAverageDrilldown: (params: CreatorRoleAverageDrilldownParams) =>
      client.get<CreatorRoleAverageDrilldownResponse>('/v1/creators/compare/role-average', {
        params: { ...drilldownQueryParams(params), role: params.role },
      }),
    getSeriesAverageDrilldown: (params: CreatorSeriesAverageDrilldownParams) =>
      client.get<CreatorSeriesAverageDrilldownResponse>('/v1/creators/compare/series-average', {
        params: { ...drilldownQueryParams(params), series: params.series },
      }),
    getReadWithoutRatingDrilldown: (params: CreatorDrilldownParams) =>
      client.get<CreatorReadWithoutRatingDrilldownResponse>(
        '/v1/creators/compare/read-without-rating',
        { params: drilldownQueryParams(params) },
      ),
    getUnreadDrilldown: (params: CreatorDrilldownParams) =>
      client.get<CreatorUnreadDrilldownResponse>(
        '/v1/creators/compare/unread',
        { params: drilldownQueryParams(params) },
      ),
  }
}

export type CreatorComparisonApi = ReturnType<typeof createCreatorComparisonApi>

export const creatorComparisonApi = createCreatorComparisonApi(defaultHttpClient())
