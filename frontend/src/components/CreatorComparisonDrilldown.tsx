import { Link } from 'react-router-dom'
import Modal from './Modal'
import {
  useCreatorComparisonDrilldown,
  type CreatorDrilldownSelection,
} from '../hooks/useCreatorComparisonDrilldown'
import type { CreatorDrilldownIssue, CreatorDrilldownRatingObservation } from '../types/index'

/** URL/query metric identifiers for the drilldown evidence surface (issue #3176). */
export type DrilldownMetricParam =
  | 'average'
  | 'rated-count'
  | 'median'
  | 'distribution'
  | '5-star-rate'
  | 'unread'
  | 'read-without-rating'
  | 'role-average'
  | 'series-average'

/** Every metric that may appear in the drilldown page/query state. */
export const DRILLDOWN_METRICS = [
  'average',
  'rated-count',
  'median',
  'distribution',
  '5-star-rate',
  'unread',
  'read-without-rating',
  'role-average',
  'series-average',
] as const

/**
 * Narrow an untrusted query-state value onto the drilldown metric union.
 *
 * @param value - Raw `metric` query value, if any.
 * @returns Whether `value` names a real drilldown metric.
 */
export function isDrilldownMetricParam(
  value: string | null | undefined,
): value is DrilldownMetricParam {
  // SAFETY: DRILLDOWN_METRICS is a const array with literal string types, so casting to readonly string[] preserves type safety
  return value != null && (DRILLDOWN_METRICS as readonly string[]).includes(value)
}

/**
 * Human-readable title for one drilled metric selection.
 *
 * @param metric - The drilled metric.
 * @param labels - Optional bucket/role/series labels the metric needs to read.
 * @returns The modal title fragment for that metric.
 */
export function drilldownMetricLabel(
  metric: DrilldownMetricParam,
  labels: { bucket?: string; role?: string; seriesTitle?: string } = {},
): string {
  switch (metric) {
    case 'average':
      return 'Average rating'
    case 'rated-count':
      return 'Rated issue count'
    case 'median':
      return 'Median rating'
    case 'distribution':
      return `${labels.bucket ?? ''}★ rating bucket`
    case '5-star-rate':
      return '5★ rate'
    case 'unread':
      return 'Upcoming in ComicPile'
    case 'read-without-rating':
      return 'Read, not rated'
    case 'role-average':
      return `${labels.role ?? 'Role'} average`
    case 'series-average':
      return `${labels.seriesTitle ?? 'Series'} average`
  }
}

/** One drilled metric selection: canonical creator key, metric scoping, and modal title. */
export interface MetricSelection {
  creatorKey: string
  metric: DrilldownMetricParam
  bucket?: string
  role?: string
  series?: string
  title: string
}

interface CreatorComparisonDrilldownModalProps {
  selection: MetricSelection | null
  onClose: () => void
}

function toHookSelection(selection: MetricSelection): CreatorDrilldownSelection {
  return {
    creatorKey: selection.creatorKey,
    metric: selection.metric === 'rated-count' ? 'average' : selection.metric,
    bucket: selection.bucket,
    role: selection.role,
    series: selection.series,
  }
}

function exclusionNote(selection: MetricSelection): string {
  switch (selection.metric) {
    case 'average':
    case 'rated-count':
      return 'Only issues with an effective rating count. Unread issues and read issues without a rating are excluded.'
    case 'median':
      return 'Only rated issues are ranked. Unread issues and read issues without a rating are excluded.'
    case 'distribution':
      return 'Lists exactly the rated issues in this bucket. Issues rated elsewhere are excluded.'
    case '5-star-rate':
      return 'The numerator is the creator\u2019s 5\u2605 issues; the denominator is every rated issue.'
    case 'unread':
      return 'Unread attributed issues are upcoming for this creator, not missing reads.'
    case 'read-without-rating':
      return 'These issues are marked read but have no effective rating event.'
    case 'role-average':
      return 'Every credited issue is listed; only rated issues feed the average.'
    case 'series-average':
      return 'Every attributed issue is listed; only rated issues feed the average.'
  }
}

function IssueRow({ issue }: { issue: CreatorDrilldownIssue }) {
  return (
    <li
      className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg px-2 py-1.5 text-sm"
      style={{ color: 'var(--theme-text-primary)' }}
    >
      <span className="font-semibold">#{issue.issue_number}</span>
      {issue.thread_id != null && issue.thread_title ? (
        <Link
          to={`/thread/${issue.thread_id}`}
          className="min-w-0 truncate underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          style={{ color: 'var(--theme-text-muted)' }}
        >
          {issue.thread_title}
        </Link>
      ) : (
        <span className="min-w-0 truncate" style={{ color: 'var(--theme-text-muted)' }}>
          {issue.thread_title}
        </span>
      )}
      <span style={{ color: 'var(--theme-personal-accent)' }}>
        {issue.rating != null ? `${issue.rating}\u2605` : 'unrated'}
      </span>
      {issue.role && (
        <span className="text-xs" style={{ color: 'var(--theme-text-dim)' }}>
          {issue.role}
        </span>
      )}
    </li>
  )
}

function ObservationRow({ observation }: { observation: CreatorDrilldownRatingObservation }) {
  return (
    <li
      className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg px-2 py-1.5 text-sm"
      style={{ color: 'var(--theme-text-primary)' }}
    >
      <span className="text-xs" style={{ color: 'var(--theme-text-dim)' }}>
        #{observation.rank}
      </span>
      <span className="font-semibold">#{observation.issue_number}</span>
      {observation.thread_id != null && observation.thread_title ? (
        <Link
          to={`/thread/${observation.thread_id}`}
          className="min-w-0 truncate underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          style={{ color: 'var(--theme-text-muted)' }}
        >
          {observation.thread_title}
        </Link>
      ) : (
        <span className="min-w-0 truncate" style={{ color: 'var(--theme-text-muted)' }}>
          {observation.thread_title}
        </span>
      )}
      <span style={{ color: 'var(--theme-personal-accent)' }}>
        {observation.rating}★
      </span>
      {observation.role && (
        <span className="text-xs" style={{ color: 'var(--theme-text-dim)' }}>
          {observation.role}
        </span>
      )}
      {observation.determines_median && (
        <span
          className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: 'var(--theme-continuity-accent)' }}
        >
          median
        </span>
      )}
    </li>
  )
}

/**
 * Bounded evidence surface for one creator-comparison metric (issue #3176).
 *
 * Opens as the shared `Modal` (desktop dialog, mobile bottom sheet) and shows
 * the exact human-readable calculation, the supporting issue evidence with
 * progressive pagination, and the exclusion/missing-data explanation for the
 * drilled metric. No request fires until a metric is actually opened.
 */
export function CreatorComparisonDrilldownModal({
  selection,
  onClose,
}: CreatorComparisonDrilldownModalProps) {
  const { data, issues, observations, isPending, isFetchingMore, isError, hasMore, loadMore } =
    useCreatorComparisonDrilldown(selection ? toHookSelection(selection) : null)

  const rows = data?.metric === 'median' ? observations : issues

  return (
    <Modal
      isOpen={selection != null}
      title={selection?.title ?? ''}
      onClose={onClose}
      size="large"
      data-testid="creator-comparison-drilldown"
    >
      {isPending && (
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Loading evidence…
        </p>
      )}
      {isError && (
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Could not load the evidence for this metric. Your data is unchanged.
        </p>
      )}
      {data && (
        <div className="space-y-4">
          <p className="text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
            {data.calculation}
          </p>
          <p className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            {selection ? exclusionNote(selection) : ''}
          </p>
          {data.metric === 'read-without-rating' && !data.classification_available && (
            <p className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
              The reason each rating is missing has not been classified yet.
            </p>
          )}
          {rows.length > 0 ? (
            <ul
              data-testid="drilldown-issues"
              className="space-y-1 rounded-xl border p-2"
              style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
            >
              {data.metric === 'median'
                ? observations.map((observation) => (
                    <ObservationRow
                      key={`${observation.issue_id}-${observation.rank}`}
                      observation={observation}
                    />
                  ))
                : issues.map((issue) => <IssueRow key={issue.issue_id} issue={issue} />)}
            </ul>
          ) : (
            <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              No issues in this evidence set.
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs" style={{ color: 'var(--theme-text-dim)' }}>
              Showing {rows.length} of {data.total_count}
            </p>
            {hasMore && (
              <button
                type="button"
                data-testid="drilldown-load-more"
                onClick={() => void loadMore()}
                disabled={isFetchingMore}
                className="min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-60"
                style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
              >
                {isFetchingMore ? 'Loading…' : 'Load more'}
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}
