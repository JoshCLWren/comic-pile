import { defaultHttpClient, type HttpClient } from './httpClient'

const RECOVERY_CONFIG = { skipAuthRedirect: true }

/** Headline personal summary for one stable creator identity (issue #2028). */
export interface CreatorSummaryItem {
  canonical_creator_key: string
  display_name: string
  normalized_roles: string[]
  average_rating: number | null
  ratings_count: number
  read_unrated_count: number
  upcoming_count: number
}

/** Library-wide metadata coverage state distinguishing complete from lower-bound stats. */
export interface CreatorSummaryCoverage {
  rated_issues_total: number
  rated_issues_with_creator_metadata: number
  ratings_complete: boolean
  read_unrated_issues_total: number
  read_unrated_issues_with_creator_metadata: number
  read_unrated_complete: boolean
  unread_issues_total: number
  unread_issues_with_creator_metadata: number
  upcoming_complete: boolean
}

export interface CreatorRoleStat {
  role: string
  issue_count: number
  rated_issue_count: number
  average_rating: number | null
}

export interface CreatorIssueRow {
  issue_id: number
  issue_number: string
  thread_id: number
  thread_title: string
  status: string
  roles: string[]
  effective_rating: number | null
  rating_timestamp: string | null
  sort_key: string
}

/** One half-star bucket in a creator's rating distribution (issue #3087). */
export interface CreatorRatingBucket {
  rating: number
  count: number
}

/** Rating distribution, median, range, mean, and sample strength (issue #3087). */
export interface CreatorRatingDistribution {
  buckets: CreatorRatingBucket[]
  sample_count: number
  mean_rating: number
  median_rating: number
  min_rating: number
  max_rating: number
}

/** Full personal creator detail payload (issue #2037). */
export interface CreatorDetailResponse {
  summary: CreatorSummaryItem
  coverage: CreatorSummaryCoverage
  role_stats: CreatorRoleStat[]
  rated_issues: CreatorIssueRow[]
  read_unrated_issues: CreatorIssueRow[]
  upcoming_issues: CreatorIssueRow[]
  next_cursor: string | null
  rating_distribution: CreatorRatingDistribution | null
}

export interface CreatorDetailPageParams {
  limit?: number
  offset?: number
}

/** One row in the bounded creator discovery collection (issue #2775). */
export interface CreatorListItem {
  canonical_creator_key: string
  display_name: string
  normalized_roles: string[]
  average_rating: number | null
  ratings_count: number
}

/** Response body for the bounded personal creator list endpoint (issue #2775). */
export interface CreatorListResponse {
  items: CreatorListItem[]
  total: number
  limit: number
  offset: number
  coverage: CreatorSummaryCoverage
}

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
        `/v1/creators/${encodeURIComponent(creatorKey)}`,
        { params: queryParams, ...RECOVERY_CONFIG },
      )
    },

    getList: (params: CreatorListParams = {}) => {
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
      return client.get<CreatorListResponse>('/v1/creators', { params: queryParams, ...RECOVERY_CONFIG })
    },
  }
}

export const creatorsApi = createCreatorsApi(defaultHttpClient())
