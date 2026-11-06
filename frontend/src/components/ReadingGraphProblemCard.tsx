import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  readingGraphProblemApi,
  type ReadingGraphRepairOption,
  type ReadingGraphRepairRequest,
  type ReadingGraphRepairResponse,
} from '../services/api-reading-graph'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterReadingGraphRepair } from '../query/cacheEffects'

/**
 * Owner-scoped reading-graph recovery card.
 *
 * Renders only when the canonical Rust graph reports a persisted cycle or an
 * invalid reference. It never re-derives the graph or invents a repair: the
 * server names each offending edge and each safe action. A repair is always
 * previewed first, and applying it preserves issues, reads, ratings and history.
 */
export function ReadingGraphProblemCard() {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<{
    request: ReadingGraphRepairRequest
    preview: ReadingGraphRepairResponse
  } | null>(null)

  const graph = useQuery({
    queryKey: queryKeys.readingGraph.status(),
    queryFn: () => readingGraphProblemApi.getGraph(),
    staleTime: 30_000,
  })

  const preview = useMutation({
    mutationFn: (request: ReadingGraphRepairRequest) =>
      readingGraphProblemApi.repair({ ...request, confirm: false }),
    onSuccess: (response, request) => {
      setPending({ request, preview: response })
    },
  })

  const apply = useMutation({
    mutationFn: (request: ReadingGraphRepairRequest) =>
      readingGraphProblemApi.repair({ ...request, confirm: true }),
    onSuccess: async () => {
      setPending(null)
      await invalidateAfterReadingGraphRepair(queryClient)
    },
  })

  const problem = graph.data
  if (!problem || problem.status === 'ok') {
    return null
  }

  const busy = preview.isPending || apply.isPending
  const error = preview.error ?? apply.error

  return (
    <section
      aria-labelledby="reading-graph-problem-heading"
      data-testid="reading-graph-problem"
      className="rounded-xl border border-[var(--theme-warning)]/50 bg-[var(--theme-warning)]/10 p-4 md:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2
            id="reading-graph-problem-heading"
            className="text-base font-black text-[var(--theme-warning)]"
          >
            Reading order needs repair
          </h2>
          <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
            Your other series still work. One stored ordering rule conflicts with another, so only
            the affected series wait until this is fixed.
          </p>
        </div>
        <span className="rounded-full border border-[var(--theme-warning)]/50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-[var(--theme-warning)]">
          {problem.status === 'invalid' ? 'Missing reference' : 'Ordering cycle'}
        </span>
      </div>

      {problem.status === 'invalid' ? (
        <p className="mt-3 text-sm text-[var(--theme-text-primary)]">
          {problem.unresolved_reference_count} stored row references a missing issue or series.
          Remove the affected list or prerequisite to restore the rest of the library.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {problem.cycles.map((cycle) => (
            <li
              key={cycle.message}
              className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
            >
              <p className="text-xs font-semibold text-[var(--theme-text-primary)]">
                {cycle.edges.length > 0
                  ? `${cycle.edges[0].source.series_title} #${cycle.edges[0].source.issue_number} starts a loop through ${cycle.edges.length} ordering steps.`
                  : 'A stored ordering cycle was found.'}
              </p>
              <ul className="mt-2 space-y-1">
                {cycle.edges.slice(0, 8).map((edge, index) => (
                  <li
                    key={`${edge.source.issue_id}-${edge.target.issue_id}-${index}`}
                    className="text-xs text-[var(--theme-text-muted)]"
                  >
                    <span className="font-semibold text-[var(--theme-text-primary)]">
                      {edge.source.series_title} #{edge.source.issue_number}
                    </span>{' '}
                    waits for{' '}
                    <span className="font-semibold text-[var(--theme-text-primary)]">
                      {edge.target.series_title} #{edge.target.issue_number}
                    </span>{' '}
                    <span className="text-[var(--theme-text-dim)]">({edge.origin})</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {pending ? (
        <div className="mt-4 rounded-lg border border-[var(--theme-continuity-accent)]/40 bg-[var(--theme-bg-panel)] p-3">
          <p className="text-sm font-semibold text-[var(--theme-text-primary)]">
            {pending.preview.removed}
          </p>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
            {pending.preview.status_after === 'ok'
              ? 'This will restore eligibility for the affected series. Reading history is preserved.'
              : 'This removes the selected constraint, but another ordering problem remains.'}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => apply.mutate(pending.request)}
              className="rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-xs font-black text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50"
            >
              Apply repair
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setPending(null)}
              className="rounded-lg border border-[var(--theme-border)] px-3 py-1.5 text-xs font-semibold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 space-y-2">
          {problem.repairs.length === 0 ? (
            <p className="text-xs text-[var(--theme-text-muted)]">
              No automatic repair was found. Edit the affected series order or remove its Reading
              List to resolve the conflict.
            </p>
          ) : (
            problem.repairs.map((repair, index) => (
              <RepairButton
                key={`${repair.action}-${repair.list_id ?? repair.prerequisite_id ?? repair.issue_id}-${index}`}
                repair={repair}
                busy={busy}
                onSelect={() => {
                  const request: ReadingGraphRepairRequest = {
                    action: repair.action,
                    list_id: repair.list_id,
                    issue_id: repair.issue_id,
                    prerequisite_id: repair.prerequisite_id,
                  }
                  preview.mutate(request)
                }}
              />
            ))
          )}
        </div>
      )}

      {error ? (
        <p role="alert" className="mt-3 text-xs font-semibold text-[var(--theme-error)]">
          Could not repair the reading order. Try again or edit the affected list.
        </p>
      ) : null}
    </section>
  )
}

function RepairButton({
  repair,
  busy,
  onSelect,
}: {
  repair: ReadingGraphRepairOption
  busy: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={onSelect}
      className="block w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-left hover:bg-[var(--theme-bg-hover)] disabled:opacity-50"
    >
      <span className="block text-sm font-bold text-[var(--theme-text-primary)]">
        {repair.label}
      </span>
      <span className="mt-0.5 block text-xs text-[var(--theme-text-muted)]">{repair.detail}</span>
    </button>
  )
}

export default ReadingGraphProblemCard
