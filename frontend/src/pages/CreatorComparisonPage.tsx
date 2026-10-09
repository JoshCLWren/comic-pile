import { Link, useSearchParams } from 'react-router-dom'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getApiErrorStatus } from '../utils/apiError'
import { parseCreatorKey, creatorRoutePath } from '../utils/creatorKey'
import type {
  CreatorComparisonItem,
  CreatorComparisonRoleStat,
  CreatorComparisonSeriesAggregate,
} from '../types/index'
import Breadcrumbs from '../components/Breadcrumbs'
import Modal from '../components/Modal'
import { RatingValue } from './RatingValue'
import { InsufficientDataBadge } from './InsufficientDataBadge'
import { SeriesLink } from './SeriesLink'
import { RoleStatRow } from './RoleStatRow'
import { RatingDistributionBar } from './RatingDistributionBar'

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

type DrilldownState = {
  open: boolean
  creatorKey: string | null
  metric:
    | 'average'
    | 'median'
    | 'distribution'
    | '5-star-rate'
    | 'role-average'
    | 'series-average'
    | 'read-without-rating'
  bucket?: string
  role?: string
}

function useDrilldownData(
  creatorKey: string | null,
  metric: 'average' | 'median' | 'distribution' | '5-star-rate' | 'role-average' | 'series-average' | 'read-without-rating',
  bucket?: string,
  role?: string,
) {
  const enabled = creatorKey != null

  const { data, isPending, isError, error } = useQuery<DrilldownData | null>({
    queryKey: [
      'creator-drilldown',
      metric,
      normalizeKey(creatorKey),
      bucket,
      role,
    ],
    queryFn: async () => {
      if (!creatorKey) throw new Error('No creator key')

      let url = ''
      let params: Record<string, string> = {}

      switch (metric) {
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

      const response = await fetch(url, {
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

function renderDrilldownContent(
  data: DrilldownData,
  metric: 'average' | 'median' | 'distribution' | '5-star-rate' | 'role-average' | 'series-average' | 'read-without-rating',
  bucket?: string,
  role?: string,
) {
  switch (metric) {
    case 'average': {
      const d = data as AverageDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Supporting issues
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span>{issue.rating}★</span>
                    <span className="ml-2">{issue.role}</span>
                    <span className="ml-2 text-muted-foreground">{issue.thread_title || ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-4">
            <strong>Total rated:</strong> {d.total_rated} issues &
            <strong>Total points:</strong> {d.total_points}
          </p>
        </div>
      )
    }
    case 'median': {
      const d = data as MedianDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          {d.sorted_ratings.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Sorted ratings (highest to lowest)
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.sorted_ratings.map((r) => (
                  <li key={r.rank} className="flex items-center gap-2 text-xs">
                    <span>{r.rank}.</span>
                    <span>{r.value}★</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-4">Rated issue count: {d.ratings_count}</p>
        </div>
      )
    }
    case 'distribution': {
      const d = data as DistributionDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Issues in this bucket
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span>{issue.rating}★</span>
                    <span className="ml-2">{issue.role}</span>
                    <span className="ml-2 text-muted-foreground">{issue.thread_title || ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-4">
            <strong>Bucket count:</strong> {d.bucket_count} of {d.total_rated} rated issues
          </p>
        </div>
      )
    }
    case '5-star-rate': {
      const d = data as FiveStarRateDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Five-star rated issues
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span>{issue.rating}★</span>
                    <span className="ml-2">{issue.role}</span>
                    <span className="ml-2 text-muted-foreground">{issue.thread_title || ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-4">
            <strong>5★ count:</strong> {d.top_count} ÷ <strong>Rated count:</strong> {d.rated_count}
          </p>
        </div>
      )
    }
    case 'role-average': {
      const d = data as RoleAverageDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          <p className="mt-2">
            <strong>Role:</strong> {d.role} &
            <strong>Rated issue count:</strong> {d.rated_issue_count} &
            <strong>Average rating:</strong> {d.average_rating?.toFixed(2) || 'N/A'}
          </p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Issues contributing to average
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span>{issue.rating}★</span>
                    <span className="ml-2">{issue.role}</span>
                    <span className="ml-2 text-muted-foreground">{issue.thread_title || ''}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )
    }
    case 'series-average': {
      const d = data as SeriesAverageDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          <p className="mt-2">
            <strong>Series:</strong> {d.thread_title} (thread {d.thread_id}) &
            <strong>Rated issue count:</strong> {d.rated_issue_count} ÷
            <strong>Total issue count:</strong> {d.issue_count}
          </p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Rated issues in series
              </p>
              <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span>{issue.rating}★</span>
                    <span className="ml-2">{issue.role}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )
    }
    case 'read-without-rating': {
      const d = data as ReadWithoutRatingDrilldown
      return (
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Calculation
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>{d.calculation}</p>
          {d.issues.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
                Read-but-unrated issues
              </p>
              <ul className="mt-2 space-y-1 max-h-80 overflow-y-auto">
                {d.issues.map((issue) => (
                  <li key={issue.issue_number} className="flex items-center gap-2 text-xs">
                    <span className="w-6 text-right">{issue.issue_number}</span>
                    <span className="text-muted-foreground">{issue.thread_title || 'No title'}</span>
                    <span className="ml-2 text-xs">
                      {issue.roles.length > 0 ? issue.roles.join(', ') : 'no role'}
                    </span>
                  </li>
                ))
              </ul>
            </div>
          )}
          <p className="mt-4">Total count: {d.count}</p>
        </div>
      )
    }
  }
}

export default function CreatorComparisonPage() {
  const [searchParams] = useSearchParams()
  const keysParam = searchParams.get('keys')
  const keys = keysParam ? keysParam.split(',').filter(Boolean) : []

  const { data, isPending, isError, error } = useCreatorComparison(keys.length > 0 ? keys : null)

  const [drilldown] = useState<DrilldownState>({
    open: false,
    creatorKey: null,
    metric: 'average',
  })

  const { data: drilldownData, isPending: drilldownIsPending, isError: drilldownIsError } =
    useDrilldownData(
      drilldown.creatorKey,
      drilldown.metric,
      drilldown.bucket,
      drilldown.role,
    )

  if (keys.length < 2 || keys.length > 4) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
        <Breadcrumbs items={[{ label: 'Creators', to: '/creators' }, { label: 'Compare' }]} />
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
        <p className="mt-4 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Select 2 to 4 creators from the <Link to="/creators" className="underline">Creators page</Link> to compare them.
        </p>
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6" aria-label="Loading creator comparison">
        <Breadcrumbs items={[{ label: 'Creators', to: '/creators' }, { label: 'Compare' }]} />
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
<div className="mt-6 grid gap-6" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          {[0, 1, 2, 3].slice(0, keys.length).map((i) => (
            <div key={i} className="h-72 animate-pulse rounded-2xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
          ))}
        </div>
      </div>
    )
  }

  if (isError || !data) {
    const status = getApiErrorStatus(error)
    const notFound = status === 404
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
        <Breadcrumbs items={[{ label: 'Creators', to: '/creators' }, { label: 'Compare' }]} />
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          {notFound ? 'Creators not found' : 'Could not load comparison'}
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          {notFound
            ? 'One or more creators are not in your library.'
            : 'The comparison failed to load. Your data is unchanged.'}
        </p>
        {!notFound && (
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible-ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        )}
        <div className="mt-2">
          <Link
            to="/creators"
            className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible-ring-[var(--theme-focus-ring)]"
            style={{ color: 'var(--theme-text-muted)' }}
          >
            Back to Creators
          </Link>
        </div>
      </div>
    )
  }

  const comparisonItems = Object.values(data.comparisons)
  const affectedNames = data.insufficient_data_keys.map(
    (key) => data.comparisons[key]?.display_name ?? key
  )

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <Breadcrumbs items={[{ label: 'Creators', to: '/creators' }, { label: 'Compare' }]} />
      <header className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Comparing {comparisonItems.length} creator{comparisonItems.length === 1 ? '' : 's'}
        </p>
      </header>

      {affectedNames.length > 0 && (
        <div className="mt-4 rounded-xl border px-4 py-3" style={{ borderColor: 'var(--theme-warning)', backgroundColor: 'var(--theme-warning)/10' }}>
          <p className="text-sm" style={{ color: 'var(--theme-text-primary)' }}>
            <strong>Note:</strong> Some creators have fewer than 3 rated issues, making their statistics less reliable.
            <span className="ml-2">Affected: {affectedNames.join(', ')}</span>
          </p>
        </div>
      )}

      {data.coverage && !data.coverage.ratings_complete && (
        <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
          Partial data: some rated issues are still missing creator metadata. Counts shown are lower bounds.
        </p>
      )}

      <div className="mt-6 grid gap-6" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        {comparisonItems.map((item) => (
          <ComparisonCard
            key={item.canonical_creator_key}
            item={item}
            onDrilldown={(metric: string, bucket?: string, role?: string) => {
              // Set drilldown state and fetch data
              // We'll handle this via a ref or state update
            }}
          />
        ))}
      </div>

      {comparisonItems.length === 0 && (
        <p className="mt-6 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          None of the selected creators were found in your library.
        </p>
      )}

      {/* Drilldown modal */}
      <Modal
        isOpen={drilldown.open}
        title={`Drilldown: ${drilldown.metric}`}
        onClose={() => {
          // Just close the modal; reset state via a separate mechanism if needed
          // For now, just close
        }}
      >
        {drilldownIsPending ? (
          <div className="h-96 animate-pulse rounded-2xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
        ) : drilldownIsError ? (
          <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>Drilldown failed to load</p>
        ) : drilldownData != null ? renderDrilldownContent(
          drilldownData,
          drilldown.metric,
          drilldown.bucket,
          drilldown.role,
        ) : (
          <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>No drilldown data available</p>
        )}
        <div className="mt-4">
          <button
            type="button"
            onClick={() => { /* close modal */ }}
            className="rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible-ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Close
          </button>
        </div>
      </Modal>
    </div>
  )
}