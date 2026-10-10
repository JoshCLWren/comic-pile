import { useQuery } from '@tanstack/react-query'

function normalizeKey(key: string | null): string {
  if (!key) return ''
  const trimmed = key.trim()
  return trimmed
}

type AverageDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
  total_rated: number
  total_points: number
}

type MedianDrilldown = {
  calculation: string
  sorted_ratings: Array<{ rank: number; rating: number; determines_median: boolean; issue_number: string; role: string | null; thread_id: number | null; thread_title: string | null }>
  ratings_count: number
}

type DistributionDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
  bucket_count: number
  total_rated: number
}

type FiveStarRateDrilldown = {
  calculation: string
  top_count: number
  rated_count: number
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
}

type RoleAverageDrilldown = {
  calculation: string
  role: string
  issue_count: number
  rated_issue_count: number
  average_rating: number | null
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
}

type SeriesAverageDrilldown = {
  calculation: string
  thread_id: number
  thread_title: string
  issue_count: number
  rated_issue_count: number
  average_rating: number | null
  min_rated_issues_per_series: number
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
}

type ReadWithoutRatingDrilldown = {
  calculation: string
  issues: Array<{ issue_number: string; rating: number | null; role: string | null; thread_id: number | null; thread_title: string | null }>
  count: number
  classification_available: boolean
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
      const search = new URLSearchParams()

      switch (metricType) {
        case 'average':
          url = '/api/v1/creators/compare/average'
          search.set('creator', creatorKey)
          break
        case 'median':
          url = '/api/v1/creators/compare/median'
          search.set('creator', creatorKey)
          break
        case 'distribution':
          if (!bucket) throw new Error('Bucket is required for distribution drilldown')
          url = '/api/v1/creators/compare/distribution'
          search.set('creator', creatorKey)
          search.set('bucket', bucket)
          break
        case '5-star-rate':
          url = '/api/v1/creators/compare/5-star-rate'
          search.set('creator', creatorKey)
          break
        case 'role-average':
          if (!role) throw new Error('Role is required for role-average drilldown')
          url = '/api/v1/creators/compare/role-average'
          search.set('creator', creatorKey)
          search.set('role', role)
          break
        case 'series-average':
          url = '/api/v1/creators/compare/series-average'
          search.set('creator', creatorKey)
          break
        case 'read-without-rating':
          url = '/api/v1/creators/compare/read-without-rating'
          search.set('creator', creatorKey)
          break
      }

      const urlWithParams = new URL(url, window.location.origin)
      urlWithParams.search = search.toString()
      const response = await fetch(urlWithParams.toString(), {
        method: 'GET',
        headers: { Accept: 'application/json' },
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(`HTTP ${response.status}: ${text}`)
      }

      // SAFETY: Response shape matches DrilldownData union by API contract
      return response.json() as Promise<DrilldownData>
    },
    enabled,
    staleTime: 30000,
    gcTime: 300000,
  })

  return { data, isPending, isError, error }
}