import { defaultHttpClient, type ApiRequestConfig, type HttpClient } from './httpClient'
import type {
  CreatorsListResponse as NativeCreatorsListResponse,
  DetailResponse as NativeCreatorDetailResponse,
  SeriesIssuesResponse as NativeCreatorSeriesIssuesResponse,
} from '../generated/nativeV2Client'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

// Resolve response types through the generated v2 operations, not component
// names that can collide with frozen legacy schemas during contract merging.
export type CreatorDetailResponse = NativeCreatorDetailResponse
export type CreatorListResponse = NativeCreatorsListResponse
export type CreatorSeriesIssueListResponse = NativeCreatorSeriesIssuesResponse

/** Headline personal summary for one stable creator identity (issue #2028). */
export type CreatorSummaryItem = CreatorDetailResponse['summary']

/** Library-wide metadata coverage state distinguishing complete from lower-bound stats. */
export type CreatorSummaryCoverage = CreatorDetailResponse['coverage']

export type CreatorRoleStat = CreatorDetailResponse['role_stats'][number]

export type CreatorIssueRow = CreatorDetailResponse['rated_issues'][number]

/** One half-star bucket in a creator's rating distribution (issue #3087). */
export type CreatorRatingBucket = CreatorRatingDistribution['buckets'][number]

/** Rating distribution, median, range, mean, and sample strength (issue #3087). */
export type CreatorRatingDistribution = NonNullable<CreatorDetailResponse['rating_distribution']>

/** Series/run-level aggregate of one creator's attributed rated work (issue #3099). */
export type CreatorSeriesGroup = CreatorDetailResponse['series_groups'][number]

/** One individual issue extreme behind a creator highlight (issue #3092). */
export type CreatorIssueInsight = CreatorInsights['highest_rated_issues'][number]

/** One series/run extreme backed by a minimum rated-issue sample (issue #3092). */
export type CreatorSeriesInsight = NonNullable<CreatorInsights['strongest_series']>

/** Evidence-backed strongest/weakest/most-read highlights (issue #3092). */
export type CreatorInsights = NonNullable<CreatorDetailResponse['insights']>

export interface CreatorDetailPageParams {
  limit?: number
  offset?: number
}

/** One row in the bounded creator discovery collection (issue #2775). */
export type CreatorListItem = CreatorListResponse['items'][number]

export interface CreatorListParams {
  search?: string
  sort?: 'name' | 'ratings_count' | 'average_rating'
  limit?: number
  offset?: number
  min_ratings?: number
}

/**
 * Build the creator service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every creator request.
 * @returns The creator API bound to `client`.
 */
export function createCreatorsApi(client: HttpClient) {
  return {
    getDetail: (creatorKey: string, params: CreatorDetailPageParams = {}) => {
      const queryParams: Record<string, string | number> = {}
      if (params.limit !== undefined) {
        queryParams.limit = params.limit
      }
      if (params.offset !== undefined && params.offset > 0) {
        queryParams.offset = params.offset
      }
      return client.get<CreatorDetailResponse>(
        `/v2/creators/${encodeURIComponent(creatorKey)}`,
        { params: queryParams, ...RECOVERY_CONFIG },
      )
    },

    getSeriesIssues: (
      creatorKey: string,
      seriesKey: string,
      params: CreatorDetailPageParams = {},
    ) => {
      const queryParams: Record<string, string | number> = {}
      if (params.limit !== undefined) {
        queryParams.limit = params.limit
      }
      if (params.offset !== undefined && params.offset > 0) {
        queryParams.offset = params.offset
      }
      return client.get<CreatorSeriesIssueListResponse>(
        `/v2/creators/${encodeURIComponent(creatorKey)}/series/${encodeURIComponent(seriesKey)}/issues`,
        { params: queryParams, ...RECOVERY_CONFIG },
      )
    },

    getList: (params: CreatorListParams = {}, { signal }: { signal?: AbortSignal } = {}) => {
      const queryParams: Record<string, string | number> = {}
      const search = params.search?.trim()
      if (search) {
        queryParams.search = search
      }
      if (params.sort !== undefined) {
        queryParams.sort = params.sort
      }
      if (params.limit !== undefined) {
        queryParams.limit = params.limit
      }
      if (params.offset !== undefined && params.offset > 0) {
        queryParams.offset = params.offset
      }
      if (params.min_ratings !== undefined && params.min_ratings > 0) {
        queryParams.min_ratings = params.min_ratings
      }
      const config: ApiRequestConfig = { params: queryParams, ...RECOVERY_CONFIG }
      if (signal) {
        config.signal = signal
      }
      return client.get<CreatorListResponse>('/v2/creators', config)
    },
  }
}

export const creatorsApi = createCreatorsApi(defaultHttpClient())
