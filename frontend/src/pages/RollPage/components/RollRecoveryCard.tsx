import { useMemo } from 'react'
import type { RollRecoveryInfo, RollRecoveryPrerequisite } from '../../../types/rollBootstrap'
import CompactIssueCardTrigger from '../../../components/CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../../../hooks/useIssueCards'

interface RollRecoveryCardProps {
  recovery?: RollRecoveryInfo | null
  onReadNow?: (prerequisite: RollRecoveryPrerequisite) => void
  isPending?: boolean
  isLoading?: boolean
  errorMessage?: string | null
}

const diagnosticMessages = {
  cycle_detected: 'This continuity plan contains a cycle, so ComicPile stopped before looping.',
  depth_limit_exceeded: 'This dependency chain is deeper than ComicPile can safely traverse.',
  node_limit_exceeded: 'This dependency graph is larger than ComicPile can safely traverse at once.',
} as const

/** Labels arrive as "Series #number"; split for a truthful identity hint. */
function splitPrerequisiteLabel(label: string) {
  const match = /^(?<title>.+) #(?<number>[^#]+)$/.exec(label)
  return {
    title: match?.groups?.title ?? label,
    number: match?.groups?.number ?? '?',
  }
}

/**
 * Only an owned issue node with a canonical id may mount a shared card.
 * Crossover/group nodes and placeholder ids stay labelled text: the label is a
 * display hint, never an owned issue identity (issue #5904).
 */
function canonicalPrerequisiteIssueId(nodeType: string, nodeId: number): number | null {
  return nodeType === 'issue' && Number.isInteger(nodeId) && nodeId > 0 ? nodeId : null
}

/** Explain a blocked pending roll without replacing the original selection. */
export function RollRecoveryCard({
  recovery,
  onReadNow,
  isPending = false,
  isLoading = false,
  errorMessage = null,
}: RollRecoveryCardProps) {
  // Exact owned issue prerequisites share one bounded card batch; crossover
  // group nodes never produce one. Hooks run before the early returns.
  const issuePrerequisiteIds = useMemo(
    () => (recovery?.readable_prerequisites ?? [])
      .map((prerequisite) => canonicalPrerequisiteIssueId(prerequisite.node_type, prerequisite.node_id))
      .filter((id): id is number => id != null),
    [recovery],
  )
  const cardsQuery = useIssueCards(issuePrerequisiteIds)
  const cardsByIssue = useMemo(() => indexIssueCards(cardsQuery.data), [cardsQuery.data])

  if (isLoading) {
    return (
      <section
        aria-label="Blocked roll recovery"
        aria-busy="true"
        className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/20 p-4 shadow-lg"
      >
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--theme-warning)]">Roll blocked</p>
        <p className="mt-2 text-sm text-[var(--theme-text-primary)]">Checking what needs to be read first…</p>
      </section>
    )
  }

  if (errorMessage) {
    return (
      <section
        aria-label="Blocked roll recovery"
        role="alert"
        className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-error)]/30 bg-[var(--theme-error)]/20 p-4 shadow-lg"
      >
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--theme-error)]">Recovery unavailable</p>
        <p className="mt-2 text-sm text-[var(--theme-text-primary)]">{errorMessage}</p>
        <p className="mt-2 text-xs text-[var(--theme-text-muted)]">Your original roll is still preserved.</p>
      </section>
    )
  }

  if (!recovery) return null

  const primaryBlocker = recovery.direct_blockers[0]
  const recommendations = recovery.readable_prerequisites
  const chains = recovery.chains ?? []
  const diagnostics = recovery.diagnostics ?? []
  const firstReadableIndex = recommendations.findIndex((p) => p.is_readable !== false)

  return (
    <section
      aria-label="Blocked roll recovery"
      className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/20 p-4 shadow-lg"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--theme-warning)]">Roll blocked</p>
      <h2 className="mt-1 text-lg font-black text-[var(--theme-text-primary)]">{recovery.original_thread_title}</h2>
      <p className="mt-2 text-sm text-[var(--theme-text-primary)]">
        Your original roll is still waiting. {primaryBlocker
          ? <><strong>{primaryBlocker.source_label}</strong> has to be read first.</>
          : <>A continuity prerequisite has to be completed first.</>}
      </p>

      {chains.length > 0 && (
        <details className="mt-4 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/20 px-3 py-2">
          <summary className="cursor-pointer text-xs font-black uppercase tracking-widest text-[var(--theme-text-primary)]">
            Why is this blocked? ({chains.length} {chains.length === 1 ? 'path' : 'paths'})
          </summary>
          <div className="mt-3 space-y-3">
            {chains.map((chain, chainIndex) => (
              <ol
                key={chain.map((node) => `${node.node_type}-${node.node_id}`).join(':')}
                aria-label={`Dependency path ${chainIndex + 1}`}
                className="space-y-1"
              >
                <li className="text-xs font-bold text-[var(--theme-text-muted)]">{recovery.original_thread_title}</li>
                {chain.map((node, index) => (
                  <li
                    key={`${node.node_type}-${node.node_id}-${index}`}
                    className="flex items-center gap-2 pl-2 text-sm text-[var(--theme-text-primary)]"
                  >
                    <span aria-hidden="true" className="text-[var(--theme-text-muted)]">↳</span>
                    <span className="min-w-0 flex-1">
                      {node.label}
                      <span className="ml-2 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">
                        {node.node_type}
                      </span>
                    </span>
                    {node.is_readable && (
                      <span className="shrink-0 text-[10px] font-black uppercase tracking-wider text-[var(--theme-success)]">
                        Readable now
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            ))}
          </div>
        </details>
      )}

      {diagnostics.length > 0 && (
        <div role="alert" className="mt-3 rounded-xl border border-[var(--theme-warning)]/30 bg-[var(--theme-warning)]/20 px-3 py-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-warning)]">Continuity warning</p>
          <ul className="mt-1 space-y-1 text-xs text-[var(--theme-text-primary)]">
            {diagnostics.map((diagnostic) => (
              <li key={`${diagnostic.code}-${diagnostic.node_type}-${diagnostic.node_id}`}>
                {diagnosticMessages[diagnostic.code]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {recommendations.length > 0 ? (
        <div className="mt-4 space-y-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-dim)]">
            {primaryBlocker?.source_type === 'issue' || recommendations.length === 1
              ? 'Read this first'
              : 'Readable prerequisites'}
          </p>
          {recommendations.map((prerequisite, index) => {
            const readable = prerequisite.is_readable !== false
            const isClickable = Boolean(onReadNow && readable)
            const isRecommendedFirst = index === firstReadableIndex && recommendations.length > 1
            const content = (
              <>
                <span className="min-w-0">
                  <span className="block text-sm font-black text-[var(--theme-text-primary)]">{prerequisite.label}</span>
                  {isRecommendedFirst && (
                    <span className="mt-0.5 block text-[10px] font-bold uppercase tracking-wider text-[var(--theme-comic-accent)]">
                      Recommended first
                    </span>
                  )}
                </span>
                {readable ? (
                  <span className="shrink-0 text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)]">
                    Read now
                  </span>
                ) : (
                  <span className="shrink-0 text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-dim)]">
                    Blocked
                  </span>
                )}
              </>
            )
            const rowClass =
              'flex w-full flex-col gap-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-hover)] px-4 py-3 text-left sm:flex-row sm:items-center sm:justify-between sm:gap-3'

            const canonicalIssueId = canonicalPrerequisiteIssueId(
              prerequisite.node_type,
              prerequisite.node_id,
            )
            const splitLabel = canonicalIssueId != null ? splitPrerequisiteLabel(prerequisite.label) : null
            return (
              <div key={`${prerequisite.node_type}-${prerequisite.node_id}`} className="space-y-1">
                {isClickable ? (
                  <button
                    type="button"
                    onClick={() => onReadNow?.(prerequisite)}
                    disabled={isPending}
                    className={`${rowClass} transition-colors hover:bg-[var(--theme-bg-hover)] disabled:opacity-60`}
                  >
                    {content}
                  </button>
                ) : (
                  <div
                    className={rowClass}
                  >
                    {content}
                  </div>
                )}
                {canonicalIssueId != null && (
                  <div className="pl-4" data-testid="roll-recovery-issue-actions">
                    <CompactIssueCardTrigger
                      issueId={canonicalIssueId}
                      threadTitle={splitLabel?.title ?? prerequisite.label}
                      issueNumber={splitLabel?.number ?? '?'}
                      card={cardsByIssue.get(canonicalIssueId) ?? null}
                      hideTitle
                      actionLabel="Read directly"
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="mt-4 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)]/20 px-3 py-2 text-xs text-[var(--theme-text-muted)]">
          No readable prerequisite is available yet. Your original roll will stay preserved while the dependency is blocked.
        </p>
      )}
    </section>
  )
}
