import type { ReaderContextRecentRating, ReaderContextSeries } from '../../../services/api-reader-context'
import CompactIssueCardTrigger from '../../../components/CompactIssueCardTrigger'
import { indexIssueCards, useIssueCards } from '../../../hooks/useIssueCards'

interface SeriesPanelProps {
  series: ReaderContextSeries
}

function StarRow({ rating }: { rating: number }) {
  const full = Math.floor(rating)
  const half = rating - full >= 0.25
  const stars: string[] = []
  for (let i = 0; i < full; i++) stars.push('\u2605')
  if (half) stars.push('\u00BD')
  return (
    <span className="text-[var(--theme-comic-accent)] text-xs tabular-nums" aria-label={`${rating.toFixed(1)} out of 5 stars`}>
      {stars.join('')}
    </span>
  )
}

export function SeriesPanel({ series }: SeriesPanelProps) {
  const issueIds = [
    ...(series.previous_issue ? [series.previous_issue.issue_id] : []),
    ...series.recent_ratings.map((rating) => rating.issue_id),
  ]
  const cards = useIssueCards(issueIds, { enabled: series.identity_source !== 'unavailable' && issueIds.length > 0 })
  const cardsByIssue = indexIssueCards(cards.data)

  if (series.identity_source === 'unavailable') {
    return (
      <section
        aria-labelledby="series-panel-heading"
        className="rounded-2xl border border-[var(--theme-personal-accent)]/15 bg-[var(--theme-bg-panel)] p-3 space-y-2"
      >
        <h4
          id="series-panel-heading"
          className="text-[10px] font-black uppercase tracking-[0.15em] text-[var(--theme-text-dim)]"
        >
          Series history
        </h4>
        <p className="text-[11px] text-[var(--theme-text-dim)] italic">
          Canonical series history unavailable
        </p>
      </section>
    )
  }

  const seriesTitle = series.series_name ?? 'Series'

  return (
    <section
      aria-labelledby="series-panel-heading"
      className="rounded-2xl border border-[var(--theme-personal-accent)]/15 bg-[var(--theme-bg-panel)] p-3 space-y-3"
    >
      <h4
        id="series-panel-heading"
        className="text-[10px] font-black uppercase tracking-[0.15em] text-[var(--theme-text-dim)]"
      >
        {series.series_name ? `${series.series_name} history` : 'Series history'}
      </h4>

      {series.average_rating !== null ? (
        <div className="flex items-baseline gap-2">
          <span
            className="text-2xl font-black tabular-nums"
            style={{ color: 'var(--theme-personal-accent)' }}
          >
            {series.average_rating.toFixed(2)}
          </span>
          <span className="text-[11px] font-bold text-[var(--theme-text-muted)]">
            {series.ratings_count} rated
          </span>
        </div>
      ) : (
        <p className="text-[11px] text-[var(--theme-text-dim)]">No ratings yet</p>
      )}

      {series.previous_issue ? (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--theme-text-muted)]">
          <span className="font-bold">Previous:</span>{' '}
          <span>#{series.previous_issue.issue_number}</span>
          {series.previous_issue.rating !== null ? (
            <>
              <span aria-hidden="true"> &middot; </span>
              <StarRow rating={series.previous_issue.rating} />
            </>
          ) : null}
          {/* Exact owned issue: the shared covered entrance keeps direct
              read/rate/map available even when the batch has no cover. */}
          <CompactIssueCardTrigger
            issueId={series.previous_issue.issue_id}
            threadTitle={seriesTitle}
            issueNumber={series.previous_issue.issue_number}
            card={cardsByIssue.get(series.previous_issue.issue_id) ?? null}
            hideTitle
            actionLabel={`Read or rate issue ${series.previous_issue.issue_number}`}
          />
        </div>
      ) : null}

      {series.recent_ratings.length > 0 ? (
        <div className="space-y-1">
          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-[var(--theme-text-dim)]">
            Recent ratings
          </p>
          <div className="flex flex-wrap gap-x-3 gap-y-2">
            {series.recent_ratings.map((r: ReaderContextRecentRating) => (
              <div
                key={r.issue_id}
                className="flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--theme-text-primary)]"
              >
                <div className="min-w-0">
                  <span className="text-[var(--theme-text-dim)]">#{r.issue_number}</span>{' '}
                  <StarRow rating={r.rating} />
                </div>
                <CompactIssueCardTrigger
                  issueId={r.issue_id}
                  threadTitle={seriesTitle}
                  issueNumber={r.issue_number}
                  card={cardsByIssue.get(r.issue_id) ?? null}
                  hideTitle
                  actionLabel={`Read or rate issue ${r.issue_number}`}
                />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(series.highest_rating !== null || series.lowest_rating !== null) ? (
        <div className="flex gap-4 text-[11px] text-[var(--theme-text-muted)]">
          {series.highest_rating !== null ? (
            <div>
              <span className="font-bold">High: </span>
              <span className="tabular-nums text-[var(--theme-comic-accent)]">{series.highest_rating.toFixed(1)}</span>
            </div>
          ) : null}
          {series.lowest_rating !== null ? (
            <div>
              <span className="font-bold">Low: </span>
              <span className="tabular-nums text-[var(--theme-text-dim)]">{series.lowest_rating.toFixed(1)}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
