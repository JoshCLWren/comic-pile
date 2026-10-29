import { createContext, useContext, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import { getApiErrorStatus } from '../utils/apiError'
import { parseCreatorKey, creatorRoutePath } from '../utils/creatorKey'
import { SMALL_SAMPLE_THRESHOLD } from '../utils/creatorUtils'
import { threadIssueRoutePath } from '../utils/threadRoutes'
import type { CreatorComparisonIssueRef, CreatorComparisonItem, CreatorComparisonRoleStat, CreatorComparisonSeriesAggregate } from '../types/index'
import { CreatorMetricDrilldownModal } from '../components/CreatorMetricDrilldownModal'
import Breadcrumbs from '../components/Breadcrumbs'
import GlossaryLink from '../components/GlossaryLink'

interface MetricClickParams {
  role?: string
  ratingValue?: string
  seriesKey?: string
}

type MetricClickHandler = (metricType: string, metricLabel: string, params?: MetricClickParams) => void

// Evidence-view wiring (issue #3460). Every headline metric, distribution
// bucket, role and series rating opens the metric drilldown. The handler is
// supplied by a per-card provider so a metric control is automatically scoped
// to the creator it belongs to without threading callbacks through every leaf.
const MetricClickContext = createContext<MetricClickHandler | null>(null)

function useMetricClick(): MetricClickHandler {
  return useContext(MetricClickContext) ?? (() => {})
}

function RatingValue({
  value,
  label,
  metricType,
  metricLabel,
  params,
  className = 'font-bold',
}: {
  value: number
  label: string
  metricType: string
  metricLabel: string
  params?: MetricClickParams
  className?: string
}) {
  const onMetricClick = useMetricClick()
  return (
    <button
      type="button"
      onClick={() => onMetricClick(metricType, metricLabel, params)}
      className={`${className} rounded hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]`}
      style={{ color: 'var(--theme-personal-accent)' }}
      aria-label={label}
      title={`View details for ${label}`}
    >
      {value.toFixed(1)}★
    </button>
  )
}

function MetricValueButton({
  metricType,
  metricLabel,
  params,
  className,
  style,
  ariaLabel,
  title,
  children,
}: {
  metricType: string
  metricLabel: string
  params?: MetricClickParams
  className: string
  style: React.CSSProperties
  ariaLabel: string
  title: string
  children: React.ReactNode
}) {
  const onMetricClick = useMetricClick()
  return (
    <button
      type="button"
      onClick={() => onMetricClick(metricType, metricLabel, params)}
      className={`${className} rounded hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]`}
      style={style}
      aria-label={ariaLabel}
      title={title}
    >
      {children}
    </button>
  )
}

function SmallSampleBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-[var(--theme-warning)]/15 px-2 py-0.5 text-xs font-semibold"
      style={{ color: 'var(--theme-warning)' }}
      title={`Small sample: fewer than ${SMALL_SAMPLE_THRESHOLD} rated comics`}
    >
      Small sample
    </span>
  )
}

function SeriesLink({ aggregate }: { aggregate: CreatorComparisonSeriesAggregate }) {
  return (
    <div className="min-w-0">
      <Link
        to={`/thread/${aggregate.thread_id}`}
        className="block min-w-0 truncate rounded-lg text-sm font-semibold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        style={{ color: 'var(--theme-text-primary)' }}
      >
        {aggregate.thread_title}
      </Link>
      <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        <span>{aggregate.issue_count} {aggregate.issue_count === 1 ? 'issue' : 'issues'}</span>
        <span>{aggregate.rated_issue_count} rated</span>
        <RatingValue
          value={aggregate.average_rating}
          label={`Average ${aggregate.average_rating} out of 5`}
          metricType="series-stats"
          metricLabel={`Series: ${aggregate.thread_title}`}
          params={{ seriesKey: `thread:${aggregate.thread_id}` }}
        />
      </span>
    </div>
  )
}

function RoleStatRow({ stat }: { stat: CreatorComparisonRoleStat }) {
  const onMetricClick = useMetricClick()
  const openRoleDrilldown = () => onMetricClick('role-stats', `Role: ${stat.role}`, { role: stat.role })

  return (
    <li className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <button
        type="button"
        onClick={openRoleDrilldown}
        className="block w-full truncate rounded text-left text-sm font-bold hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        style={{ color: 'var(--theme-text-primary)' }}
        title={stat.role}
      >
        {stat.role}
      </button>
      <p className="mt-0.5 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        {stat.issue_count} {stat.issue_count === 1 ? 'issue' : 'issues'}
        <> · {stat.rated_issue_count} rated</>
        {stat.average_rating != null ? (
          <> · <RatingValue value={stat.average_rating} label={`Average ${stat.average_rating} out of 5 as ${stat.role}`} metricType="role-stats" metricLabel={`Role: ${stat.role}`} params={{ role: stat.role }} /></>
        ) : (
          ' · unrated'
        )}
      </p>
    </li>
  )
}

function RatingDistributionBar({ distribution, totalCount }: { distribution: Record<string, number>; totalCount: number }) {
  // ComicPile rates on a 1-5 scale with 0.5 increments. Only buckets with at
  // least one rating render (issue #3329): zero-count steps are noise that
  // buries the actual distribution on low-data cards. Buckets sort
  // numerically descending so the strongest ratings read first.
  //
  // Bar length uses a shared 0-100% scale: bucket_count / total_ratings.
  // This makes bars directly comparable across creators with very different
  // sample sizes. Each rendered bucket keeps count and percentage in the row
  // label, while the bucket marker is a keyboard-accessible control that opens
  // the evidence behind it (issue #3460).
  const onMetricClick = useMetricClick()
  const total = totalCount > 0 ? totalCount : 0
  const buckets = Object.entries(distribution)
    .map(([rating, count]) => ({ rating, count }))
    .filter(({ rating, count }) => count > 0 && Number.isFinite(Number(rating)))
    .sort((a, b) => Number(b.rating) - Number(a.rating))

  if (total === 0 || buckets.length === 0) {
    return (
      <p
        data-testid="rating-distribution"
        aria-label={`Rating distribution across ${total} rated issue${total === 1 ? '' : 's'}`}
        className="text-xs"
        style={{ color: 'var(--theme-text-muted)' }}
      >
        No ratings yet
      </p>
    )
  }

  return (
    <div
      role="list"
      aria-label={`Rating distribution across ${total} rated issue${total === 1 ? '' : 's'}`}
      data-testid="rating-distribution"
      className="space-y-1"
    >
      {buckets.map(({ rating, count }) => {
        const percentage = total > 0 ? (count / total) * 100 : 0
        return (
          <div
            key={rating}
            role="listitem"
            className="flex items-center gap-2 text-xs"
            style={{ color: 'var(--theme-text-muted)' }}
            aria-label={`${rating}★: ${count} rating${count === 1 ? '' : 's'}, ${percentage.toFixed(1)}%`}
          >
            <button
              type="button"
              onClick={() => onMetricClick('rating-distribution', `Rating distribution for ${rating}★`, { ratingValue: rating })}
              className="w-6 rounded text-right font-medium hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              aria-label={`View the ${count} issue${count === 1 ? '' : 's'} rated ${rating}★`}
              title={`View the ${count} issue${count === 1 ? '' : 's'} rated ${rating}★ (${percentage.toFixed(1)}%)`}
            >
              {rating}★
            </button>
            <div className="flex-1 h-2 rounded bg-[var(--theme-border)] overflow-hidden">
              <div
                className="h-full rounded"
                style={{
                  width: `${percentage}%`,
                  backgroundColor: 'var(--theme-personal-accent)',
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
            <span
              className="w-20 text-right"
              aria-hidden="true"
            >
              {`${count} · ${percentage.toFixed(1)}%`}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function IssueDrilldown({
  refs,
  totalCount,
  maxRefs,
  detailPath,
  groupLabel,
}: {
  refs: CreatorComparisonIssueRef[]
  totalCount: number
  maxRefs: number
  detailPath: string | null
  groupLabel: string
}) {
  // Bounded drilldown (issue #3174): surprising counts link back to the actual
  // supporting issues instead of standing alone as bare numbers. The sample is
  // truncated at maxRefs while the headline count stays the full total.
  if (refs.length === 0) {
    return null
  }
  return (
    <div className="mt-2">
      <ul className="space-y-1" aria-label={groupLabel}>
        {refs.map((ref) => (
          <li key={ref.issue_id} className="min-w-0">
            <Link
              to={threadIssueRoutePath(ref.thread_id, ref.issue_id)}
              className="block min-w-0 truncate rounded text-sm font-semibold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ color: 'var(--theme-text-primary)' }}
            >
              {ref.thread_title} #{ref.issue_number}
            </Link>
          </li>
        ))}
      </ul>
      {totalCount > refs.length && (
        <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
          Showing {refs.length} of {totalCount} (first {maxRefs}).
          {detailPath ? (
            <>
              {' '}
              <Link
                to={detailPath}
                className="font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              >
                See the full list on creator detail.
              </Link>
            </>
          ) : null}
        </p>
      )}
    </div>
  )
}

/**
 * Column template for the comparison-card grid.
 *
 * Four creators must never leave a single orphaned card on its own row
 * (issue #3459), so four uses an explicit two-column layout. The previous
 * `repeat(auto-fit, minmax(280px, 1fr))` packing resolved to 3 + 1 at desktop
 * widths because the capped 1024px container only fits three 280px tracks.
 * Two creators sit side by side; three keep the wider packing so the row still
 * fills on desktop.
 */
function comparisonGridClasses(count: number): string {
  if (count <= 1) {
    return 'grid-cols-1'
  }
  if (count === 3) {
    return 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
  }
  return 'grid-cols-1 md:grid-cols-2'
}

function ComparisonCard({ item }: { item: CreatorComparisonItem }) {
  const totalRatings = item.ratings_count
  const hasRatings = totalRatings > 0
  const isValidKey = parseCreatorKey(item.canonical_creator_key) != null
  const detailPath = isValidKey ? creatorRoutePath(item.canonical_creator_key) : null

  return (
    <section
      data-testid="creator-comparison-card"
      className="min-w-0 rounded-2xl border p-4 md:p-6"
      style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
    >
      <header className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {detailPath ? (
              <Link
                to={detailPath}
                className="break-words text-xl font-bold leading-tight hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] rounded"
                style={{ color: 'var(--theme-text-primary)' }}
              >
                {item.display_name}
              </Link>
            ) : (
              <h2 className="break-words text-xl font-bold leading-tight" style={{ color: 'var(--theme-text-primary)' }}>
                {item.display_name}
              </h2>
            )}
            {item.normalized_roles.length > 0 && (
              <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                {item.normalized_roles.join(', ')}
              </p>
            )}
          </div>
          {item.insufficient_data && <SmallSampleBadge />}
        </div>
      </header>

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Average rating
          </p>
          {hasRatings ? (
<p className="text-3xl font-black leading-tight" style={{ color: 'var(--theme-personal-accent)' }} aria-label={`Average rating ${item.average_rating} out of 5 from ${item.ratings_count} ${item.ratings_count === 1 ? 'rating' : 'ratings'}`}>
<RatingValue value={item.average_rating!} label={`Average ${item.average_rating} out of 5 from ${item.ratings_count} ${item.ratings_count === 1 ? 'rating' : 'ratings'}`} metricType="average-rating" metricLabel={`Average rating for ${item.display_name}`} />
            </p>
          ) : (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>No ratings yet</p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Median rating
          </p>
          {item.median_rating != null ? (
            <RatingValue
              value={item.median_rating}
              label={`Median ${item.median_rating} out of 5`}
              className="text-3xl font-black leading-tight"
              metricType="median-rating"
              metricLabel={`Median rating for ${item.display_name}`}
            />
          ) : (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>{hasRatings ? 'N/A' : 'No ratings yet'}</p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Rated issues
          </p>
          <MetricValueButton
            metricType="rated-issue-count"
            metricLabel={`Rated issues for ${item.display_name}`}
            className="text-lg font-bold"
            style={{ color: 'var(--theme-text-primary)' }}
            ariaLabel={`View details for ${item.ratings_count} rated issues`}
            title={`View details for ${item.ratings_count} rated issues`}
          >
            {item.ratings_count}
          </MetricValueButton>
        </div>

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            5★ rate
          </p>
          {item.top_rating_rate != null ? (
            <MetricValueButton
              metricType="five-star-rate"
              metricLabel={`5★ rating rate for ${item.display_name}`}
              className="text-lg font-bold"
              style={{ color: 'var(--theme-personal-accent)' }}
              ariaLabel={`View details for ${(item.top_rating_rate * 100).toFixed(1)}% 5-star rate`}
              title={`View details for ${(item.top_rating_rate * 100).toFixed(1)}% 5-star rate`}
            >
              {(item.top_rating_rate * 100).toFixed(1)}%
            </MetricValueButton>
          ) : (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>{hasRatings ? '0%' : 'N/A'}</p>
          )}
        </div>

        <div className="col-span-full">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Rating distribution
          </p>
          <RatingDistributionBar distribution={item.rating_distribution} totalCount={totalRatings} />
        </div>

        <div className="col-span-full">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Unread in your library
          </p>
          <MetricValueButton
            metricType="unread-count"
            metricLabel={`Unread issues for ${item.display_name}`}
            className="text-lg font-bold"
            style={{ color: 'var(--theme-text-primary)' }}
            ariaLabel={`View details for ${item.unread_upcoming_count} unread issues`}
            title={`View details for ${item.unread_upcoming_count} unread issues`}
          >
            {item.unread_upcoming_count}
          </MetricValueButton>
          <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            Unread issues by this creator already in your library — not queue order or roll eligibility.
          </p>
          <IssueDrilldown
            refs={item.unread_issue_refs}
            totalCount={item.unread_upcoming_count}
            maxRefs={item.max_issue_refs_per_group}
            detailPath={detailPath}
            groupLabel={`Unread issues by ${item.display_name}`}
          />
        </div>

        {item.read_unrated_count > 0 && (
          <div className="col-span-full">
            <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
              Read with no stored rating
            </p>
            <MetricValueButton
              metricType="read-unrated-count"
              metricLabel={`Read unrated issues for ${item.display_name}`}
              className="text-lg font-bold"
              style={{ color: 'var(--theme-text-primary)' }}
              ariaLabel={`View details for ${item.read_unrated_count} read issues with no stored rating`}
              title={`View details for ${item.read_unrated_count} read issues with no stored rating`}
            >
              {item.read_unrated_count}
            </MetricValueButton>
            <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
              Read issues by this creator with no stored rating.
            </p>
            <IssueDrilldown
              refs={item.read_unrated_issue_refs}
              totalCount={item.read_unrated_count}
              maxRefs={item.max_issue_refs_per_group}
              detailPath={detailPath}
              groupLabel={`Read issues by ${item.display_name} with no stored rating`}
            />
          </div>
        )}
      </div>

      {item.role_stats.length > 0 && (
        <div className="mt-6">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Role breakdown
          </p>
          <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            Issues may appear under multiple roles. The average rating uses only the rated subset.
          </p>
          <ul className="mt-2 grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
            {item.role_stats.map((stat) => (
              <RoleStatRow key={stat.role} stat={stat} />
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6">
        <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
          Strongest series
        </p>
        {item.strongest_series.length > 0 ? (
          <ul className="mt-2 space-y-2">
            {item.strongest_series.map((aggregate) => (
              <li key={aggregate.thread_id}>
                <SeriesLink aggregate={aggregate} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            No series has {item.min_rated_issues_per_series} rated issues yet, so there is no
            strongest series to rank.
          </p>
        )}
      </div>
    </section>
  )
}

export default function CreatorComparisonPage() {
  const [searchParams] = useSearchParams()
  const keysParam = searchParams.get('keys')
  // Trim each key before any validation so the page's checks accept exactly
  // what useCreatorComparison's normalizeKeys accepts (#3462): a deep link
  // like ?keys=creator:7,%20creator:12 loads successfully instead of being
  // rejected as malformed while the hook would have trimmed it.
  const keys = keysParam ? keysParam.split(',').map((k: string) => k.trim()).filter(Boolean) : []

  // Deduplicate the raw URL keys up front so a deep link that repeats an
  // identity (or mixes in an unknown one) does not blank the whole comparison
  // (#4208). The hook also normalizes, but the page's validation and return
  // links must use the cleaned set.
  const uniqueKeys = Array.from(new Set(keys))

  // Route back to the list with the cleaned (deduped) identities; refined below
  // once the comparison resolves which keys are actually available.
  const creatorsReturnUrl =
    uniqueKeys.length > 0 ? `/creators?keys=${encodeURIComponent(uniqueKeys.join(','))}` : '/creators'

  const { data, isPending, isError, error } = useCreatorComparison(uniqueKeys.length > 0 ? uniqueKeys : null)

  // Metric evidence view state (issue #3460). Clicking any headline metric,
  // distribution bucket, role or series rating opens this drilldown so the
  // displayed value can be traced back to the issues that produced it.
  const [activeModal, setActiveModal] = useState<{
    isOpen: boolean
    creatorKey: string
    metricType: string
    metricLabel: string
    initialParams?: MetricClickParams
  }>({
    isOpen: false,
    creatorKey: '',
    metricType: '',
    metricLabel: '',
  })

  // The per-card provider binds the creator key, so a click from any metric
  // control resolves to the creator whose card actually rendered it.
  const handleMetricClick = (
    creatorKey: string,
    metricType: string,
    metricLabel: string,
    params?: MetricClickParams,
  ) => {
    setActiveModal({ isOpen: true, creatorKey, metricType, metricLabel, initialParams: params })
  }

  const invalidSyntax = uniqueKeys.some((k: string) => parseCreatorKey(k.trim()) === null)
  const inputInvalid = uniqueKeys.length < 2 || uniqueKeys.length > 4 || invalidSyntax

  if (inputInvalid) {
    // A count problem (fewer than 2 or more than 4 keys) states the accepted
    // input explicitly and still names the Creators page, so the generic
    // prompt and the accepted-input explanation both stay discoverable (#3462).
    // Malformed syntax keeps its own readable explanation; duplicate keys fall
    // back to the pre-existing generic prompt.
    const countExplanation = uniqueKeys.length > 4
      ? 'Comparison accepts 2 to 4 creator keys (format creator:<id>, separated by commas). Select 2 to 4 creators from the Creators page to compare them.'
      : uniqueKeys.length < 2
        ? 'Comparison requires 2 to 4 creator keys (format creator:<id>, separated by commas). Select 2 to 4 creators from the Creators page to compare them.'
        : null
    const syntaxExplanation = invalidSyntax
      ? 'Invalid creator key format: expected creator:<external-person-id> (stable ComicVine person id, no display names).'
      : null
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
        <Breadcrumbs items={[{ label: 'Creators', to: creatorsReturnUrl }, { label: 'Compare' }]} />
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
        <div className="mt-4">
          <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            {countExplanation ?? syntaxExplanation ?? (
              <>
                Select 2 to 4 creators from the{' '}
                <Link to={creatorsReturnUrl} className="underline">
                  Creators page
                </Link>{' '}
                to compare them.
              </>
            )}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Link
              to={creatorsReturnUrl}
              className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ color: 'var(--theme-text-muted)' }}
            >
              Back to Creators
            </Link>
            {uniqueKeys.length > 0 && (
              <Link
                to={creatorsReturnUrl}
                className="min-h-10 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
              >
                Change selection
              </Link>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6" aria-label="Loading creator comparison">
        <Breadcrumbs items={[{ label: 'Creators', to: creatorsReturnUrl }, { label: 'Compare' }]} />
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
<div className={`mt-6 grid gap-6 ${comparisonGridClasses(uniqueKeys.length)}`}>
          {[0, 1, 2, 3].slice(0, uniqueKeys.length).map((i) => (
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
        <Breadcrumbs items={[{ label: 'Creators', to: creatorsReturnUrl }, { label: 'Compare' }]} />
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
            className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          <Link
            to={creatorsReturnUrl}
            className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ color: 'var(--theme-text-muted)' }}
          >
            Back to Creators
          </Link>
          {uniqueKeys.length > 0 && (
            <Link
              to={creatorsReturnUrl}
              className="min-h-10 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
            >
              Change selection
            </Link>
          )}
        </div>
      </div>
    )
  }

  const comparisonItems = Object.values(data.comparisons)
  // The banner explains the shared "Small sample" threshold once; each resolved
  // affected card carries the single per-creator Small sample badge (#4237).
  // Naming the creators here as well duplicated the same warning on their
  // cards. Keys that did not resolve to a card are covered by the mixed-result
  // or empty-state message instead of being mislabeled as a visible sample.
  const hasSmallSample = data.insufficient_data_keys.some(
    (key) => data.comparisons[key] !== undefined,
  )

  const resolvedKeys = new Set(Object.keys(data.comparisons))
  // Keys that did not resolve to a visible creator, so feedback can name them
  // instead of silently dropping them (#4208).
  const missingKeys = uniqueKeys.filter((k: string) => !resolvedKeys.has(k))
  const hasMixedResult = missingKeys.length > 0 && comparisonItems.length > 0

  // Every route back to the list once the comparison has resolved carries only
  // the identities that actually resolved, so unknown or unavailable keys are
  // dropped instead of being handed straight back to the selection URL (#4208).
  // Before resolution (invalid input or a failed request) the deduped request
  // set is the best available answer.
  const resolvedReturnUrl =
    resolvedKeys.size > 0
      ? `/creators?keys=${encodeURIComponent(Array.from(resolvedKeys).join(','))}`
      : creatorsReturnUrl

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <Breadcrumbs items={[{ label: 'Creators', to: resolvedReturnUrl }, { label: 'Compare' }]} />
      <header className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator Comparison
        </h1>
        <div className="flex items-center gap-3">
          <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            Comparing {comparisonItems.length} creator{comparisonItems.length === 1 ? '' : 's'}
          </p>
          {comparisonItems.length > 0 && (
            <Link
              to={resolvedReturnUrl}
              className="min-h-10 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
            >
              Change selection
            </Link>
          )}
        </div>
      </header>

      {hasMixedResult && (
        <div
          className="mt-4 rounded-xl border px-4 py-3"
          style={{
            borderColor: 'var(--theme-warning)',
            backgroundColor: 'color-mix(in srgb, var(--theme-warning) 10%, transparent)',
          }}
          role="alert"
        >
          <p className="text-sm" style={{ color: 'var(--theme-text-primary)' }}>
            <strong>Note:</strong> One or more requested creators could not be included in this comparison.
            The comparison reflects only the creators available in your library.
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-primary)' }}>
            Unknown or unavailable creator keys: {missingKeys.join(', ')}.
          </p>
        </div>
      )}

      {hasSmallSample && (
        <div
          className="mt-4 rounded-xl border px-4 py-3"
          style={{
            borderColor: 'var(--theme-warning)',
            backgroundColor: 'color-mix(in srgb, var(--theme-warning) 10%, transparent)',
          }}
        >
          <p className="text-sm" style={{ color: 'var(--theme-text-primary)' }}>
            <strong>Small sample:</strong> fewer than {SMALL_SAMPLE_THRESHOLD} rated comics
            (distinct comics you have rated). Average ratings based on a small sample may be
            less representative.{' '}
            <GlossaryLink id="small-sample">Glossary</GlossaryLink>
          </p>
        </div>
      )}

      {data.coverage && (!data.coverage.ratings_complete || !data.coverage.read_unrated_complete || !data.coverage.upcoming_complete) && (
        <div className="mt-2" role="note">
          <p className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            Partial creator metadata: {data.coverage.rated_issues_with_creator_metadata} of{' '}
            {data.coverage.rated_issues_total} rated issues,{' '}
            {data.coverage.read_unrated_issues_with_creator_metadata} of{' '}
            {data.coverage.read_unrated_issues_total} read issues with no stored rating, and{' '}
            {data.coverage.unread_issues_with_creator_metadata} of{' '}
            {data.coverage.unread_issues_total} unread issues have creator metadata.
            Counts shown are lower bounds.
          </p>
          <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
            Issues without creator metadata cannot be attributed to any creator, so a
            creator&apos;s totals may be incomplete rather than proof of less work.
          </p>
        </div>
      )}

      <div className={`mt-6 grid gap-6 ${comparisonGridClasses(comparisonItems.length)}`}>
        {comparisonItems.map((item) => (
          <MetricClickContext.Provider
            key={item.canonical_creator_key}
            value={(metricType, metricLabel, params) =>
              handleMetricClick(item.canonical_creator_key, metricType, metricLabel, params)
            }
          >
            <ComparisonCard item={item} />
          </MetricClickContext.Provider>
        ))}
      </div>

      {comparisonItems.length === 0 && (
        <div className="mt-6">
          <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
            None of the selected creators are available in your library — the comparison can
            only include creators with issues credited to them in your library.
          </p>
          {missingKeys.length > 0 && (
            <p className="mt-1 text-sm" style={{ color: 'var(--theme-text-primary)' }}>
              Unknown or unavailable creator keys: {missingKeys.join(', ')}.
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <Link
              to={resolvedReturnUrl}
              className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
              style={{ color: 'var(--theme-text-muted)' }}
            >
              Back to Creators
            </Link>
            {keys.length > 0 && (
              <Link
                to={resolvedReturnUrl}
                className="min-h-10 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
              >
                Change selection
              </Link>
            )}
          </div>
        </div>
      )}

      <CreatorMetricDrilldownModal
        isOpen={activeModal.isOpen}
        onClose={() => setActiveModal((prev) => ({ ...prev, isOpen: false }))}
        creatorKey={activeModal.creatorKey}
        metricType={activeModal.metricType}
        metricLabel={activeModal.metricLabel}
        initialParams={activeModal.initialParams}
      />
    </div>
  )
}
