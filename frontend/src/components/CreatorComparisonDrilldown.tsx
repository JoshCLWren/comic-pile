import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
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

/** Optional scoping a drilled metric may need beyond the creator key. */
export interface DrilldownMetricScope {
  /** Rating-distribution bucket key (`"5"`, `"4.5"`, ...). */
  bucket?: string
  /** Creator role name. */
  role?: string
  /** Canonical series key the backend addresses (`thread:<id>`). */
  series?: string
  /** Display title for `series`, used only in the modal heading. */
  seriesTitle?: string
}

/**
 * Build the metric selection for one drilled metric, deriving its title.
 *
 * @param creatorKey - Canonical creator key the metric belongs to.
 * @param metric - The drilled metric.
 * @param scope - Optional bucket/role/series scoping the metric needs.
 * @returns The complete selection the modal and query state share.
 */
export function drilldownSelection(
  creatorKey: string,
  metric: DrilldownMetricParam,
  scope: DrilldownMetricScope = {},
): MetricSelection {
  return {
    creatorKey,
    metric,
    bucket: scope.bucket,
    role: scope.role,
    series: scope.series,
    title: drilldownMetricLabel(metric, scope),
  }
}

/** Query-parameter keys that encode one open drilldown selection. */
export const DRILLDOWN_PARAM_KEYS = {
  creator: 'metric_creator',
  metric: 'metric',
  bucket: 'metric_bucket',
  role: 'metric_role',
  series: 'metric_series',
} as const

/**
 * Write one selection's identity into a search-params object in place.
 *
 * Encoding the open metric in route state keeps refresh and browser Back
 * truthful, which the issue requires for every drillable metric.
 *
 * @param params - Search params to mutate.
 * @param selection - The selection being opened.
 */
export function writeDrilldownParams(params: URLSearchParams, selection: MetricSelection): void {
  params.set(DRILLDOWN_PARAM_KEYS.metric, selection.metric)
  params.set(DRILLDOWN_PARAM_KEYS.creator, selection.creatorKey)
  if (selection.bucket) {
    params.set(DRILLDOWN_PARAM_KEYS.bucket, selection.bucket)
  } else {
    params.delete(DRILLDOWN_PARAM_KEYS.bucket)
  }
  if (selection.role) {
    params.set(DRILLDOWN_PARAM_KEYS.role, selection.role)
  } else {
    params.delete(DRILLDOWN_PARAM_KEYS.role)
  }
  if (selection.series) {
    params.set(DRILLDOWN_PARAM_KEYS.series, selection.series)
  } else {
    params.delete(DRILLDOWN_PARAM_KEYS.series)
  }
}

/**
 * Remove every drilldown query parameter, leaving other page state intact.
 *
 * @param params - Search params to mutate.
 */
export function clearDrilldownParams(params: URLSearchParams): void {
  params.delete(DRILLDOWN_PARAM_KEYS.metric)
  params.delete(DRILLDOWN_PARAM_KEYS.creator)
  params.delete(DRILLDOWN_PARAM_KEYS.bucket)
  params.delete(DRILLDOWN_PARAM_KEYS.role)
  params.delete(DRILLDOWN_PARAM_KEYS.series)
}

/**
 * Rehydrate an open selection from route state, e.g. after a refresh or Back.
 *
 * Scoped metrics that lost their scope in the URL are rejected rather than
 * opened with an undefined bucket/role/series, which the backend would reject.
 *
 * @param params - Current search params.
 * @param seriesTitleFor - Resolves a canonical series key to its display title
 *   so a restored selection keeps the same heading a click would have produced.
 * @returns The decoded selection, or `null` when no valid metric is open.
 */
export function readDrilldownParams(
  params: URLSearchParams,
  seriesTitleFor: (seriesKey: string) => string | undefined = () => undefined,
): MetricSelection | null {
  const metric = params.get(DRILLDOWN_PARAM_KEYS.metric)
  const creatorKey = params.get(DRILLDOWN_PARAM_KEYS.creator)
  if (!isDrilldownMetricParam(metric) || !creatorKey) return null

  const bucket = params.get(DRILLDOWN_PARAM_KEYS.bucket) ?? undefined
  const role = params.get(DRILLDOWN_PARAM_KEYS.role) ?? undefined
  const series = params.get(DRILLDOWN_PARAM_KEYS.series) ?? undefined
  if (metric === 'distribution' && !bucket) return null
  if (metric === 'role-average' && !role) return null
  if (metric === 'series-average' && !series) return null

  return drilldownSelection(creatorKey, metric, {
    bucket,
    role,
    series,
    seriesTitle: series ? seriesTitleFor(series) : undefined,
  })
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

interface MetricDrilldownTriggerProps {
  selection: MetricSelection
  onOpen: (selection: MetricSelection) => void
  /** Class applied to the button; callers own the layout/typography role. */
  className?: string
  /** Accessible label overriding the button's own text content. */
  label?: string
  children: ReactNode
}

/**
 * Interactive readout for one comparison metric (issue #3176).
 *
 * Every meaningful derived value on the comparison page is a real button so it
 * is reachable by keyboard and announced as a control, while the visible
 * treatment stays a plain numeric readout rather than a sea of links. The
 * affordance is the shared dotted underline plus the canonical focus ring.
 */
export function MetricDrilldownTrigger({
  selection,
  onOpen,
  className = '',
  label,
  children,
}: MetricDrilldownTriggerProps) {
  return (
    <button
      type="button"
      data-testid="drilldown-trigger"
      aria-label={label}
      onClick={() => onOpen(selection)}
      className={`min-h-11 min-w-0 cursor-pointer rounded-lg px-1 text-left underline decoration-dotted underline-offset-4 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] ${className}`}
    >
      {children}
    </button>
  )
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
