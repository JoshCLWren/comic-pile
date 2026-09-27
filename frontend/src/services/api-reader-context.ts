import { defaultHttpClient, type HttpClient } from './httpClient'

export interface ReaderContextPreviousIssue {
  issue_id: number
  issue_number: string
  rating: number | null
}

export interface ReaderContextRecentRating {
  issue_id: number
  issue_number: string
  rating: number
}

export interface ReaderContextSeries {
  identity_source: 'comicvine' | 'unavailable'
  canonical_series_id: string | null
  series_name: string | null
  average_rating: number | null
  ratings_count: number
  previous_issue: ReaderContextPreviousIssue | null
  recent_ratings: ReaderContextRecentRating[]
  highest_rating: number | null
  lowest_rating: number | null
}

export interface ReaderContextCrossoverNextMember {
  issue_id: number
  issue_number: string
}

export interface ReaderContextCrossoverMembership {
  id: number
  name: string
}

export interface ReaderContextCrossover {
  id: number
  name: string
  applies_to_current_issue: boolean
  membership_kind: 'issue' | 'thread'
  next_member: ReaderContextCrossoverNextMember | null
  average_rating: number | null
  ratings_count: number
  read_count: number
}

export interface ReaderContextLocalIssue {
  issue_id: number
  issue_number: string
  position: number
  status: string
  relation: 'previous' | 'current' | 'next' | 'future'
  rating: number | null
  crossover_memberships: ReaderContextCrossoverMembership[]
}

export interface ReaderContextEdge {
  id: number
  kind: 'dependency' | 'continuity'
  source_issue_id: number
  target_issue_id: number
  source_thread_id: number | null
  target_thread_id: number | null
  source_label: string | null
  target_label: string | null
  note: string | null
  explanation: string | null
}

export interface ReaderContextLocalChain {
  issues: ReaderContextLocalIssue[]
  edges: ReaderContextEdge[]
}

export interface ReaderContextResponse {
  issue_id: number
  series: ReaderContextSeries
  crossovers: ReaderContextCrossover[]
  local_chain: ReaderContextLocalChain
}

/**
 * Build the reader-context service bound to an HTTP client.
 *
 * @param client - HTTP transport used for every request.
 * @returns The reader-context service bound to `client`.
 */
export function createReaderContextApi(client: HttpClient) {
  return {
  get: (issueId: number) =>
    client.get<ReaderContextResponse>(`/v1/issues/${issueId}/reader-context`),
}
}

export const readerContextApi = createReaderContextApi(defaultHttpClient())
