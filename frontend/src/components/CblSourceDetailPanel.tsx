import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router-dom'
import { cblSourcesApi } from '../services/api-cbl-sources'
import { queryKeys } from '../query/queryKeys'
import { displayCblRepository, displayCblSourcePath, displayCblSourceTitle } from '../utils/cblSourceDisplay'
import { isString } from '../utils/runtimeChecks'

/** One bounded page of source occurrences. */
const PAGE_SIZE = 200

interface CblSourceDetailPanelProps {
  /** CBL source list ID taken from the `list` query parameter. */
  listId: number
}

/**
 * Read the reader's return destination from the router state.
 *
 * @param state - The router location state supplied by the comparison list.
 * @returns The return path and its human label.
 */
function backDestination(state: unknown): { path: string; label: string } {
  const candidate = state as { from?: unknown; label?: unknown } | null
  const path = isString(candidate?.from) && candidate.from ? candidate.from : '/continuity-plans'
  const label = isString(candidate?.label) && candidate.label ? candidate.label : 'Reading Plans'
  return { path, label }
}

/**
 * Show one shared CBL source list with its ordered source occurrences.
 *
 * The panel is read-only shared-catalog evidence: it never adopts a source and
 * never reports reader-owned state. Every occurrence keeps its original
 * position and its exact Comic Vine issue and volume identities so a reader can
 * tell same-titled volumes apart.
 *
 * @param props - The source list to show.
 * @returns The source detail panel.
 */
export function CblSourceDetailPanel({ listId }: CblSourceDetailPanelProps) {
  const [limit, setLimit] = useState(PAGE_SIZE)
  const location = useLocation()
  const back = backDestination(location.state)
  const detailQuery = useQuery({
    queryKey: queryKeys.cblSources.detail(listId, limit),
    queryFn: () => cblSourcesApi.detail(listId, { limit }),
  })

  if (detailQuery.isPending) {
    return (
      <section
        className="space-y-2 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
        aria-label="CBL source detail"
      >
        <p className="text-sm text-[var(--theme-text-muted)]">Loading source detail…</p>
      </section>
    )
  }

  if (detailQuery.isError) {
    return (
      <section
        className="space-y-2 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
        aria-label="CBL source detail"
      >
        <p role="alert" className="text-sm text-[var(--theme-danger)]">
          Unable to load this CBL source.
        </p>
        <button
          type="button"
          onClick={() => void detailQuery.refetch()}
          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
        >
          Retry
        </button>
      </section>
    )
  }

  const detail = detailQuery.data
  const title = displayCblSourceTitle(detail?.name, detail?.source_path ?? '') ?? 'CBL source'
  const entries = detail?.entries ?? []
  const shown = entries.length

  return (
    <section
      className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
      aria-label="CBL source detail"
      data-testid="cbl-source-detail"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-1">
          <h2 className="text-base font-black text-[var(--theme-text-primary)]">{title}</h2>
          <p className="text-xs text-[var(--theme-text-muted)]">
            {displayCblRepository(detail?.source_repository ?? '') ?? 'Shared CBL source'} ·{' '}
            {detail?.entries_total ?? 0} positions
            {detail?.revision_sha ? ` · revision ${detail.revision_sha.slice(0, 8)}` : ''}
          </p>
          {displayCblSourcePath(detail?.source_path ?? '') && (
            <p className="text-xs text-[var(--theme-text-dim)]">
              {displayCblSourcePath(detail?.source_path ?? '')}
            </p>
          )}
        </div>
        <Link
          to={back.path}
          className="inline-flex min-h-9 items-center text-xs font-bold text-[var(--theme-continuity-accent)] hover:text-[var(--theme-text-primary)]"
        >
          Back to {back.label}
        </Link>
      </div>

      <ol className="max-h-96 space-y-1 overflow-y-auto text-xs text-[var(--theme-text-muted)]">
        {entries.map((entry) => (
          <li
            key={`${entry.position}-${entry.comicvine_issue_id}`}
            className="flex flex-wrap items-baseline gap-2"
          >
            <span className="w-8 shrink-0 text-right font-mono text-[var(--theme-text-dim)]">
              {entry.position}
            </span>
            <span className="font-semibold text-[var(--theme-text-primary)]">
              {entry.series_name} #{entry.issue_number}
            </span>
            <span className="font-mono text-[var(--theme-text-dim)]">
              {entry.comicvine_issue_id}
            </span>
            {entry.comicvine_volume_id && (
              <span className="font-mono text-[var(--theme-text-dim)]">
                vol {entry.comicvine_volume_id}
              </span>
            )}
          </li>
        ))}
      </ol>

      {shown < (detail?.entries_total ?? 0) && (
        <button
          type="button"
          onClick={() => setLimit((current) => current + PAGE_SIZE)}
          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
        >
          Show more positions ({shown} of {detail?.entries_total ?? 0})
        </button>
      )}
    </section>
  )
}

export default CblSourceDetailPanel
