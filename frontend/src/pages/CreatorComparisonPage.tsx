import { Link, useSearchParams } from 'react-router-dom'
import { useCreatorComparison } from '../hooks/useCreatorComparison'
import { getApiErrorStatus } from '../utils/apiError'
import { parseCreatorKey, creatorRoutePath } from '../utils/creatorKey'
import type { CreatorComparisonItem, CreatorComparisonRoleStat, CreatorComparisonSeriesAggregate } from '../types/index'
import Breadcrumbs from '../components/Breadcrumbs'

function RatingValue({ value, label }: { value: number; label: string }) {
  return (
    <span
      className="font-bold"
      style={{ color: 'var(--theme-personal-accent)' }}
      aria-label={label}
    >
      {value.toFixed(1)}★
    </span>
  )
}

function InsufficientDataBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full bg-[var(--theme-warning)]/15 px-2 py-0.5 text-xs font-semibold"
      style={{ color: 'var(--theme-warning)' }}
    >
      Insufficient data
    </span>
  )
}

function SeriesLink({ aggregate }: { aggregate: CreatorComparisonSeriesAggregate }) {
  return (
    <Link
      to={`/thread/${aggregate.thread_id}`}
      className="block min-w-0 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
    >
      <span className="block min-w-0 truncate text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
        {aggregate.thread_title}
      </span>
      <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        <span>{aggregate.issue_count} {aggregate.issue_count === 1 ? 'issue' : 'issues'}</span>
        <span>{aggregate.rated_issue_count} rated</span>
        <RatingValue value={aggregate.average_rating} label={`Average ${aggregate.average_rating} out of 5`} />
      </span>
    </Link>
  )
}

function RoleStatRow({ stat }: { stat: CreatorComparisonRoleStat }) {
  return (
    <li className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <p className="truncate text-sm font-bold" title={stat.role} style={{ color: 'var(--theme-text-primary)' }}>{stat.role}</p>
      <p className="mt-0.5 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        {stat.issue_count} {stat.issue_count === 1 ? 'issue' : 'issues'}
        <> · {stat.rated_issue_count} rated</>
        {stat.average_rating != null ? (
          <> · <RatingValue value={stat.average_rating} label={`Average ${stat.average_rating} out of 5 as ${stat.role}`} /></>
        ) : (
          ' · unrated'
        )}
      </p>
    </li>
  )
}

function RatingDistributionBar({ distribution, totalCount }: { distribution: Record<string, number>; totalCount: number }) {
  // ComicPile rates on a 1-5 scale with 0.5 increments; every bucket the API
  // can emit gets a row so half-star ratings are never silently dropped.
  //
  // Bar length uses a shared 0-100% scale: bucket_count / total_ratings.
  // This makes bars directly comparable across creators with very different
  // sample sizes. Each non-empty bucket exposes both raw count and
  // percentage, while screen readers receive bucket, count, percentage and
  // the region communicates the creator's sample size.
  const ratings = ['5', '4.5', '4', '3.5', '3', '2.5', '2', '1.5', '1']
  const total = totalCount > 0 ? totalCount : 0

  return (
    <div
      role="list"
      aria-label={`Rating distribution across ${total} rated issue${total === 1 ? '' : 's'}`}
      data-testid="rating-distribution"
      className="space-y-1"
    >
      {ratings.map((rating) => {
        const count = distribution[rating] ?? 0
        const percentage = total > 0 ? (count / total) * 100 : 0
        const isEmpty = count === 0
        return (
          <div
            key={rating}
            role="listitem"
            className="flex items-center gap-2 text-xs"
            style={{ color: 'var(--theme-text-muted)' }}
            aria-label={
              isEmpty
                ? `${rating}★: 0 ratings (0.0%)`
                : `${rating}★: ${count} rating${count === 1 ? '' : 's'}, ${percentage.toFixed(1)}%`
            }
          >
            <span className="w-6 text-right font-medium">{rating}★</span>
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
            {!isEmpty && (
              <span
                className="w-20 text-right"
                aria-hidden="true"
              >
                {`${count} · ${percentage.toFixed(1)}%`}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

function ComparisonCard({ item }: { item: CreatorComparisonItem }) {
  const totalRatings = item.ratings_count
  const hasRatings = totalRatings > 0
  const isValidKey = parseCreatorKey(item.canonical_creator_key) != null
  const detailPath = isValidKey ? creatorRoutePath(item.canonical_creator_key) : null

  return (
    <section className="min-w-0 flex-1 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
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
          {item.insufficient_data && <InsufficientDataBadge />}
        </div>
      </header>

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Average rating
          </p>
          {hasRatings ? (
<p className="text-3xl font-black leading-tight" style={{ color: 'var(--theme-personal-accent)' }} aria-label={`Average rating ${item.average_rating} out of 5 from ${item.ratings_count} ${item.ratings_count === 1 ? 'rating' : 'ratings'}`}>
<RatingValue value={item.average_rating!} label={`Average ${item.average_rating} out of 5 from ${item.ratings_count} ${item.ratings_count === 1 ? 'rating' : 'ratings'}`} />
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
            <p className="text-3xl font-black leading-tight" style={{ color: 'var(--theme-personal-accent)' }} aria-label={`Median rating ${item.median_rating} out of 5`}>
              <RatingValue value={item.median_rating} label={`Median ${item.median_rating} out of 5`} />
            </p>
          ) : (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>{hasRatings ? 'N/A' : 'No ratings yet'}</p>
          )}
        </div>

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Rated issues
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-text-primary)' }}>{item.ratings_count}</p>
        </div>

        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            5★ rate
          </p>
          {item.top_rating_rate != null ? (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-personal-accent)' }}>
              {(item.top_rating_rate * 100).toFixed(1)}%
            </p>
          ) : (
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>{hasRatings ? '0%' : 'N/A'}</p>
          )}
        </div>

        <div className="sm:col-span-2">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Rating distribution
          </p>
          <RatingDistributionBar distribution={item.rating_distribution} totalCount={totalRatings} />
        </div>

        <div className="sm:col-span-2">
          <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
            Upcoming in ComicPile
          </p>
          <p className="text-lg font-bold" style={{ color: 'var(--theme-text-primary)' }}>{item.unread_upcoming_count}</p>
        </div>

        {item.read_unrated_count > 0 && (
          <div className="sm:col-span-2">
            <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
              Read, not rated
            </p>
            <p className="text-lg font-bold" style={{ color: 'var(--theme-text-primary)' }}>{item.read_unrated_count}</p>
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
  const keys = keysParam ? keysParam.split(',').filter(Boolean) : []

  const { data, isPending, isError, error } = useCreatorComparison(keys.length > 0 ? keys : null)

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
            className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        )}
        <div className="mt-2">
          <Link
            to="/creators"
            className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ color: 'var(--theme-text-muted)' }}
          >
            Back to Creators
          </Link>
        </div>
      </div>
    )
  }

  const comparisonItems = Object.values(data.comparisons)
  // Name the affected creators the way the reader knows them. A key the
  // response could not resolve (omitted because it is not in the library) still
  // falls back to its canonical key so the caveat is never silently dropped.
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
          <ComparisonCard key={item.canonical_creator_key} item={item} />
        ))}
      </div>

      {comparisonItems.length === 0 && (
        <p className="mt-6 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          None of the selected creators were found in your library.
        </p>
      )}
    </div>
  )
}
