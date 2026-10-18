import { useState } from 'react'
import { Link } from 'react-router-dom'
import { creatorRoutePath, parseCreatorKey } from '../utils/creatorKey'
import type {
  CreatorDiscoveryEntry,
  CreatorDiscoveryMode,
  CreatorDiscoveryReason,
  CreatorDiscoveryResponse,
  CreatorDiscoveryView,
} from '../types/index'

const FOCUS_RING =
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]'

/** Comparison symbols so a rule reads the same way the backend enforced it. */
const COMPARISON_SYMBOL: Record<CreatorDiscoveryReason['comparison'], string> = {
  gte: '≥',
  lte: '≤',
  gt: '>',
  lt: '<',
}

function formatCompact(value: number): string {
  return Number(value.toFixed(2)).toString()
}

function formatOneDecimal(value: number): string {
  return value.toFixed(1)
}

function formatSigned(value: number): string {
  const rounded = formatCompact(value)
  return rounded.startsWith('-') ? rounded : `+${rounded}`
}

function reasonText(reason: CreatorDiscoveryReason): string {
  return `${reason.label} ${formatCompact(reason.value)} ${COMPARISON_SYMBOL[reason.comparison]} ${formatCompact(reason.threshold)}`
}

/** One chip stating a single rule that qualified a creator for the view. */
function ReasonChip({ reason }: { reason: CreatorDiscoveryReason }) {
  return (
    <li
      className="rounded-full border px-2 py-0.5 text-[11px]"
      style={{
        borderColor: 'var(--theme-border)',
        backgroundColor: 'var(--theme-bg-panel)',
        color: 'var(--theme-text-muted)',
      }}
    >
      {reasonText(reason)}
    </li>
  )
}

/** Compact trend summary shown only for the warmed/cooled view. */
function TrendSummary({ entry }: { entry: CreatorDiscoveryEntry }) {
  if (
    entry.trend_direction == null ||
    entry.earlier_average_rating == null ||
    entry.recent_average_rating == null ||
    entry.trend_delta == null
  ) {
    return null
  }
  const label = entry.trend_direction === 'warmed' ? 'Warmed to' : 'Cooled on'
  return (
    <span
      style={{ color: 'var(--theme-personal-accent)' }}
      aria-label={`${label} ${entry.display_name}: earlier average ${entry.earlier_average_rating} to recent average ${entry.recent_average_rating} out of 5, a change of ${entry.trend_delta}`}
    >
      {label} <span className="font-bold">{formatSigned(entry.trend_delta)}★</span>{' '}
      <span style={{ color: 'var(--theme-text-muted)' }}>
        ({formatOneDecimal(entry.earlier_average_rating)} → {formatOneDecimal(entry.recent_average_rating)})
      </span>
    </span>
  )
}

/** One canonical creator result with its supporting metrics and rules. */
function DiscoveryRow({ entry }: { entry: CreatorDiscoveryEntry }) {
  const detailPath =
    parseCreatorKey(entry.canonical_creator_key) != null
      ? creatorRoutePath(entry.canonical_creator_key)
      : null
  const roles = entry.normalized_roles.join(', ')

  const name = (
    <span
      className="block min-w-0 break-words text-sm font-semibold"
      style={{ color: 'var(--theme-text-primary)' }}
    >
      {entry.display_name}
    </span>
  )

  return (
    <li
      className="min-w-0 rounded-xl border px-3 py-2"
      style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
    >
      {detailPath ? (
        <Link
          to={detailPath}
          className={`block min-w-0 rounded-lg ${FOCUS_RING}`}
        >
          {name}
        </Link>
      ) : (
        <div className="min-w-0">{name}</div>
      )}

      <div
        className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs"
        style={{ color: 'var(--theme-text-muted)' }}
      >
        {roles.length > 0 && <span className="break-words">{roles}</span>}
        <span>
          {entry.rated_issue_count} rated issue{entry.rated_issue_count === 1 ? '' : 's'}
        </span>
        {entry.average_rating != null ? (
          <span
            className="font-bold"
            style={{ color: 'var(--theme-personal-accent)' }}
            aria-label={`Your average rating ${entry.average_rating} out of 5 from ${entry.rated_issue_count} rated issues`}
          >
            {entry.average_rating.toFixed(1)}★
          </span>
        ) : (
          <span>unrated</span>
        )}
        <TrendSummary entry={entry} />
      </div>

      {entry.reasons.length > 0 && (
        <ul
          className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-1"
          aria-label={`Why ${entry.display_name} appears`}
        >
          {entry.reasons.map((reason) => (
            <ReasonChip key={`${reason.metric}-${reason.threshold}`} reason={reason} />
          ))}
        </ul>
      )}
    </li>
  )
}

function ViewPanel({ view }: { view: CreatorDiscoveryView }) {
  if (view.entries.length === 0) {
    return (
      <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
        No creators match this view yet. {view.description}
      </p>
    )
  }

  return (
    <>
      <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        {view.description}
        {view.min_sample > 1
          ? ` Ranked only from creators with at least ${view.min_sample} rated issues.`
          : ''}
      </p>
      <ul className="mt-2 space-y-2">
        {view.entries.map((entry) => (
          <DiscoveryRow key={entry.canonical_creator_key} entry={entry} />
        ))}
      </ul>
      {view.truncated && (
        <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
          Showing the top {view.entries.length} of {view.total} qualifying creators.
        </p>
      )}
    </>
  )
}

/**
 * Explainable personal taste-discovery section (issue #3093).
 *
 * Renders the authenticated user's own deterministic discovery views as a
 * category tablist, showing one bounded view at a time so the surface stays
 * usable on a phone instead of becoming a dense dashboard wall. Every result
 * links to its canonical creator detail page and displays the values that
 * qualified it; the copy describes what the user rated, never causes or
 * statistical significance.
 */
export default function CreatorDiscoverySection({
  data,
  heading = 'Discover your taste',
}: {
  data: CreatorDiscoveryResponse
  heading?: string
}) {
  const [selectedMode, setSelectedMode] = useState<CreatorDiscoveryMode | null>(null)
  const activeView =
    data.views.find((view) => view.mode === selectedMode) ?? data.views[0] ?? null
  const partialMetadata = !data.coverage.ratings_complete

  return (
    <section aria-labelledby="creator-discovery-heading" className="mt-6">
      <h2
        id="creator-discovery-heading"
        className="text-base font-bold md:text-lg"
        style={{ color: 'var(--theme-text-primary)' }}
      >
        {heading}
      </h2>

      {activeView == null ? (
        <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          No discovery views are available yet.
        </p>
      ) : (
        <>
          <div
            role="tablist"
            aria-label="Taste discovery views"
            className="mt-2 flex flex-wrap gap-2"
          >
            {data.views.map((view) => {
              const isActive = view.mode === activeView.mode
              return (
                <button
                  key={view.mode}
                  id={`creator-discovery-tab-${view.mode}`}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls="creator-discovery-panel"
                  onClick={() => setSelectedMode(view.mode)}
                  className={`min-h-9 rounded-full border px-3 py-1.5 text-xs font-semibold ${FOCUS_RING}`}
                  style={
                    isActive
                      ? {
                          borderColor: 'var(--theme-primary-action)',
                          backgroundColor: 'var(--theme-primary-action)',
                          color: 'var(--theme-text-primary)',
                        }
                      : {
                          borderColor: 'var(--theme-border)',
                          color: 'var(--theme-text-muted)',
                        }
                  }
                >
                  {view.title}
                </button>
              )
            })}
          </div>

          <div
            id="creator-discovery-panel"
            role="tabpanel"
            aria-labelledby={`creator-discovery-tab-${activeView.mode}`}
          >
            <ViewPanel view={activeView} />
          </div>
        </>
      )}

      {partialMetadata && (
        <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
          Partial results: some rated issues are still missing creator metadata. Counts shown are
          lower bounds, not exhaustive totals.
        </p>
      )}

      <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        Descriptive patterns from your own ratings. These simple rules describe what you rated, not
        causes or statistically significant effects.
      </p>
    </section>
  )
}
