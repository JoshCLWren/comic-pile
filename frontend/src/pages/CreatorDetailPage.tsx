import { Link, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useCreatorDetail } from '../hooks/useCreatorDetail'
import { getApiErrorStatus } from '../utils/apiError'
import { parseCreatorKey } from '../utils/creatorKey'
import type { CreatorIssueRow } from '../services/api'

function formatRatingDate(value: string | null): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(parsed)
}

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

function IssueRow({ row, showRating }: { row: CreatorIssueRow; showRating: boolean }) {
  const ratedAt = formatRatingDate(row.rating_timestamp)
  return (
    <li className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <Link
        to={`/thread/${row.thread_id}`}
        className="block min-w-0 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
      >
        <span className="block min-w-0 truncate text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
          {row.thread_title} #{row.issue_number}
        </span>
        <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
          {row.roles.length > 0 && <span className="break-words">{row.roles.join(', ')}</span>}
          {showRating && row.effective_rating != null && (
            <RatingValue value={row.effective_rating} label={`Rated ${row.effective_rating} out of 5`} />
          )}
          {ratedAt && <span>{ratedAt}</span>}
        </span>
      </Link>
    </li>
  )
}

function SectionHeading({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="text-base font-bold md:text-lg" style={{ color: 'var(--theme-text-primary)' }}>
      {children}
    </h2>
  )
}

export default function CreatorDetailPage() {
  const { creatorKey } = useParams<{ creatorKey: string }>()
  const isValidKey = parseCreatorKey(creatorKey) != null

  const {
    summary,
    coverage,
    roleStats,
    ratedIssues,
    readUnratedIssues,
    upcomingIssues,
    isPending,
    isFetchingMore,
    isError,
    error,
    hasMore,
    loadMore,
    refetch,
  } = useCreatorDetail(isValidKey ? creatorKey : null)

  if (!isValidKey) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
        <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
          Creator
        </p>
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          Creator not found
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          This creator link is invalid. Creators without a stable identity are never linked.
        </p>
        <Link
          to="/"
          className="mt-4 inline-block rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
        >
          Back to Roll
        </Link>
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6" aria-label="Loading creator details">
        <div className="h-4 w-24 animate-pulse rounded" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
        <div className="mt-2 h-8 w-2/3 animate-pulse rounded" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
        <div className="mt-4 h-28 animate-pulse rounded-xl" style={{ backgroundColor: 'var(--theme-bg-panel)' }} />
      </div>
    )
  }

  if (!summary || !coverage) {
    const status = getApiErrorStatus(error)
    const notFound = status === 404
    return (
      <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
        <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
          Creator
        </p>
        <h1 className="mt-1 text-xl font-bold md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
          {notFound ? 'Creator not found' : 'Could not load creator'}
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          {notFound
            ? 'This creator is not in your library.'
            : 'The creator page failed to load. Your data is unchanged.'}
        </p>
        {!notFound && (
          <button
            type="button"
            onClick={refetch}
            className="mt-4 min-h-11 rounded-lg px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ backgroundColor: 'var(--theme-primary-action)', color: 'var(--theme-text-primary)' }}
          >
            Try again
          </button>
        )}
        <div className="mt-2">
          <Link
            to="/"
            className="rounded-lg text-sm font-bold underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            style={{ color: 'var(--theme-text-muted)' }}
          >
            Back to Roll
          </Link>
        </div>
      </div>
    )
  }

  const ratingsPartial = !coverage.ratings_complete
  const upcomingPartial = !coverage.upcoming_complete
  const readUnratedPartial = !coverage.read_unrated_complete

  return (
    <div className="mx-auto w-full max-w-5xl px-4 md:px-6">
      <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
        Creator
      </p>
      <h1 className="mt-1 break-words text-xl font-bold leading-tight md:text-2xl" style={{ color: 'var(--theme-text-primary)' }}>
        {summary.display_name}
      </h1>

      <section aria-labelledby="creator-summary-heading" className="mt-4 rounded-2xl border p-4 md:p-6" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
        <h2 id="creator-summary-heading" className="sr-only">Summary</h2>
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="min-w-0">
            <p className="text-[10px] font-black uppercase tracking-[0.18em]" style={{ color: 'var(--theme-text-dim)' }}>
              Your average
            </p>
            {summary.average_rating != null ? (
              <p className="text-3xl font-black leading-tight" style={{ color: 'var(--theme-personal-accent)' }} aria-label={`Average rating ${summary.average_rating} out of 5 from ${summary.ratings_count} ratings`}>
                {summary.average_rating.toFixed(1)}★
              </p>
            ) : (
              <p className="text-lg font-bold" style={{ color: 'var(--theme-text-muted)' }}>
                No ratings yet
              </p>
            )}
          </div>
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>Rated</dt>
              <dd className="font-bold" style={{ color: 'var(--theme-text-primary)' }}>{summary.ratings_count}</dd>
            </div>
            <div>
              <dt className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>Upcoming</dt>
              <dd className="font-bold" style={{ color: 'var(--theme-text-primary)' }}>{summary.upcoming_count}</dd>
            </div>
            {summary.read_unrated_count > 0 && (
              <div>
                <dt className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>Read, not rated</dt>
                <dd className="font-bold" style={{ color: 'var(--theme-text-primary)' }}>{summary.read_unrated_count}</dd>
              </div>
            )}
          </dl>
        </div>
        {(ratingsPartial || upcomingPartial || readUnratedPartial) && (
          <p className="mt-3 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
            {[
              ratingsPartial ? 'Rated results are partial: some rated issues are still missing creator metadata.' : null,
              upcomingPartial ? 'Upcoming results are partial: some unread issues are still missing creator metadata.' : null,
              readUnratedPartial ? 'Read-but-unrated results are partial: some read issues are still missing creator metadata.' : null,
            ].filter(Boolean).join(' ')}
            {' '}Counts shown are lower bounds, not exhaustive totals.
          </p>
        )}
      </section>

      {roleStats.length > 0 && (
        <section aria-labelledby="creator-roles-heading" className="mt-6">
          <SectionHeading id="creator-roles-heading">Roles</SectionHeading>
          <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {roleStats.map((stat) => (
              <li key={stat.role} className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
                <p className="break-words text-sm font-bold" style={{ color: 'var(--theme-text-primary)' }}>{stat.role}</p>
                <p className="mt-0.5 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                  {stat.issue_count} {stat.issue_count === 1 ? 'issue' : 'issues'}
                  {stat.average_rating != null ? (
                    <> · <RatingValue value={stat.average_rating} label={`Average ${stat.average_rating} out of 5 as ${stat.role}`} /></>
                  ) : (
                    ' · unrated'
                  )}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <section aria-labelledby="creator-rated-heading" className="min-w-0">
          <SectionHeading id="creator-rated-heading">
            Rated{summary.ratings_count > 0 ? ` (${summary.ratings_count})` : ''}
          </SectionHeading>
          {ratingsPartial && (
            <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
              Partial list: some rated issues are still missing creator metadata.
            </p>
          )}
          {ratedIssues.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {ratedIssues.map((row) => (
                <IssueRow key={row.issue_id} row={row} showRating />
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Nothing rated for this creator yet.
            </p>
          )}
        </section>

        <section aria-labelledby="creator-upcoming-heading" className="min-w-0">
          <SectionHeading id="creator-upcoming-heading">
            Upcoming in ComicPile{summary.upcoming_count > 0 ? ` (${summary.upcoming_count})` : ''}
          </SectionHeading>
          {upcomingPartial && (
            <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
              Partial list: only unread issues already in your ComicPile are shown, and some are still missing creator metadata.
            </p>
          )}
          {upcomingIssues.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {upcomingIssues.map((row) => (
                <IssueRow key={row.issue_id} row={row} showRating={false} />
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
              Nothing coming up for this creator in your pile.
            </p>
          )}
        </section>
      </div>

      {readUnratedIssues.length > 0 && (
        <section aria-labelledby="creator-read-unrated-heading" className="mt-6">
          <SectionHeading id="creator-read-unrated-heading">
            Read, not rated ({readUnratedIssues.length})
          </SectionHeading>
          {readUnratedPartial && (
            <p className="mt-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
              Partial list: some read issues are still missing creator metadata.
            </p>
          )}
          <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {readUnratedIssues.map((row) => (
              <IssueRow key={row.issue_id} row={row} showRating={false} />
            ))}
          </ul>
        </section>
      )}

      {isError && (
        <p role="alert" className="mt-4 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          Could not load more creator details. Your loaded comics are still shown. Please try again.
        </p>
      )}
      {hasMore && (
        <button
          type="button"
          onClick={() => { void loadMore() }}
          disabled={isFetchingMore}
          className="mt-6 min-h-11 w-full rounded-xl border px-4 py-2 text-sm font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-60 sm:w-auto"
          style={{ borderColor: 'var(--theme-border)', color: 'var(--theme-text-primary)' }}
        >
          {isFetchingMore ? 'Loading more…' : 'Load more'}
        </button>
      )}
    </div>
  )
}
