import { useQuery } from '@tanstack/react-query'
import type { CreatorComparisonItem } from '../types/index'

function normalizeKey(key: string): string {
  const trimmed = key.trim()
  return trimmed
}

type AverageDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; rating: string; role: string; thread_id: number | null; thread_title: string }>
  total_rated: number
  total_points: number
}

type MedianDrilldown = {
  calculation: string
  sorted_ratings: Array<{ rank: number; value: string }>
  ratings_count: number
}

type DistributionDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; rating: string; role: string; thread_id: number | null; thread_title: string }>
  bucket_count: number
  total_rated: number
}

type FiveStarRateDrilldown = {
  calculation: string
  top_issue_ids: number[]
  rated_count: number
  top_count: number
  issues: Array<{ issue_number: string; rating: string; role: string; thread_id: number | null; thread_title: string }>
}

type RoleAverageDrilldown = {
  calculation: string
  role: string
  issue_count: number
  rated_issue_count: number
  average_rating: number | null
  issues: Array<{ issue_number: string; rating: string; role: string; thread_id: number | null; thread_title: string }>
}

type SeriesAverageDrilldown = {
  calculation: string
  thread_id: number
  thread_title: string
  issue_count: number
  rated_issue_count: number
  average_rating: number | null
  issues: Array<{ issue_number: string; rating: string; role: string }>
}

type ReadWithoutRatingDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; thread_id: number | null; thread_title: string; roles: string[] }>
  count: number
}

type DrilldownData =
  | AverageDrilldown
  | MedianDrilldown
  | DistributionDrilldown
  | FiveStarRateDrilldown
  | RoleAverageDrilldown
  | SeriesAverageDrilldown
  | ReadWithoutRatingDrilldown

export function useCreatorComparisonDrilldown(
  creatorKey: string | null,
  metricType: 'average' | 'median' | 'distribution' | '5-star-rate' | 'role-average' | 'series-average' | 'read-without-rating',
  bucket?: string,
  role?: string,
) {
  const enabled = creatorKey != null

  const { data, isPending, isError, error } = useQuery<DrilldownData | null>({
    queryKey: [
      'creator-drilldown',
      metricType,
      normalizeKey(creatorKey),
      bucket,
      role,
    ],
    queryFn: async () => {
      if (!creatorKey) throw new Error('No creator key')

      let url = ''
      let params: Record<string, string> = {}

      switch (metricType) {
        case 'average':
          url = '/api/v1/creators/compare/average'
          params = { creator: creatorKey }
          break
        case 'median':
          url = '/api/v1/creators/compare/median'
          params = { creator: creatorKey }
          break
        case 'distribution':
          if (!bucket) throw new Error('Bucket is required for distribution drilldown')
          url = '/api/v1/creators/compare/distribution'
          params = { creator: creatorKey, bucket }
          break
        case '5-star-rate':
          url = '/api/v1/creators/compare/5-star-rate'
          params = { creator: creatorKey }
          break
        case 'role-average':
          if (!role) throw new Error('Role is required for role-average drilldown')
          url = '/api/v1/creators/compare/role-average'
          params = { creator: creatorKey, role }
          break
        case 'series-average':
          url = '/api/v1/creators/compare/series-average'
          params = { creator: creatorKey }
          break
        case 'read-without-rating':
          url = '/api/v1/creators/compare/read-without-rating'
          params = { creator: creatorKey }
          break
      }

      const urlWithParams = new URL(url, window.location.origin)
      if (Object.keys(params).length > 0) {
        urlWithParams.search = new URLSearchParams(params).toString()
      }
      const response = await fetch(urlWithParams.toString(), {
        method: 'GET',
        headers: { Accept: 'application/json' },
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(`HTTP ${response.status}: ${text}`)
      }

      return response.json() as Promise<DrilldownData>
    },
    enabled,
    staleTime: 30000,
    gcTime: 300000,
  })

  return { data, isPending, isError, error }
}