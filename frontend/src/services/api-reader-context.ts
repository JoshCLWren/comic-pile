import api from './api'

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

export interface ReaderContextResponse {
  issue_id: number
  series: ReaderContextSeries
  crossovers: ReaderContextCrossover[]
}

export const readerContextApi = {
  get: (issueId: number) =>
    api.get<ReaderContextResponse>(`/v1/issues/${issueId}/reader-context`),
}
