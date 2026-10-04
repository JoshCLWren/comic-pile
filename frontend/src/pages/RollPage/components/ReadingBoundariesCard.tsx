import type { ReaderContextEdge, ReaderContextResponse } from '../../../types'
import { readingContextType } from '../readingContextTypography'
import { ReadingContextStatusCard } from './ReadingContextStatusCard'

interface ReadingBoundariesCardProps {
  isLoading: boolean
  error: string | null
  readerContext: ReaderContextResponse | null
  isOpen: boolean
  onToggle: () => void
}

function EdgeExplanation({ edge }: { edge: ReaderContextEdge }) {
  const copy = edge.explanation ?? (edge.note ? edge.note : null)
  if (!copy) return null
  return (
    <div
      className="break-words italic text-[var(--theme-text-muted)]"
      style={readingContextType('bodyCopy')}
    >
      {copy}
    </div>
  )
}

function EdgeRow({ edge, accent, arrow }: { edge: ReaderContextEdge; accent: string; arrow: string }) {
  const sourceLabel = edge.source_label ?? `#${edge.source_issue_id}`
  const targetLabel = edge.target_label ?? `#${edge.target_issue_id}`
  return (
    <div
      className="flex items-start gap-3 rounded-lg px-3 py-2"
      style={{
        borderLeft: `3px solid ${accent}`,
        backgroundColor: 'rgba(255, 255, 255, 0.02)',
      }}
    >
      <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: accent }} />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
            style={readingContextType('primaryValue')}
          >
            {sourceLabel}
          </span>
          <span className="text-[var(--theme-text-muted)]" aria-hidden="true">
            {arrow}
          </span>
          <span
            className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
            style={readingContextType('primaryValue')}
          >
            {targetLabel}
          </span>
        </div>
        <EdgeExplanation edge={edge} />
      </div>
    </div>
  )
}

export function ReadingBoundariesCard({
  isLoading,
  error,
  readerContext,
  isOpen,
  onToggle,
}: ReadingBoundariesCardProps) {
  const dependencyEdges =
    readerContext?.local_chain.edges.filter((e) => e.kind === 'dependency') ?? []
  const continuityEdges =
    readerContext?.local_chain.edges.filter((e) => e.kind === 'continuity') ?? []
  const hasBoundaries = dependencyEdges.length > 0 || continuityEdges.length > 0

  return (
    <div className="space-y-3" data-testid="reading-boundaries-card">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2.5 text-left transition hover:bg-white/5 focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-expanded={isOpen}
        data-testid="reading-boundaries-button"
      >
        <div className="flex items-center gap-3">
          <svg
            className="h-4 w-4 shrink-0 text-stone-400"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 6h16M7 12h10M10 18h4" />
          </svg>
          <div className="flex flex-col">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
              Reading Boundaries (Optional)
            </span>
            <span className="text-[11px] text-stone-400" style={readingContextType('bodyCopy')}>
              See prerequisite and continuity boundary information.
            </span>
          </div>
        </div>
        <span className="text-[10px] font-black uppercase tracking-wider text-stone-500 hover:text-stone-300 transition-colors">
          {isOpen ? 'Hide Boundaries' : 'Show Boundaries'}
        </span>
      </button>

      {isOpen && (
        <div
          className="animate-in slide-in-from-top-2 duration-150"
          data-testid="reading-boundaries-content"
        >
          {isLoading ? (
            <ReadingContextStatusCard isLoading error={error} />
          ) : error ? (
            <ReadingContextStatusCard isLoading={false} error={error} />
          ) : !hasBoundaries ? (
            <p
              className="rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 text-stone-400"
              style={readingContextType('bodyCopy')}
            >
              No prerequisite or continuity boundaries were found for this issue.
            </p>
          ) : (
            <section
              aria-labelledby="reading-boundaries-heading"
              className="space-y-3 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
            >
              <h3
                id="reading-boundaries-heading"
                className="font-bold text-[var(--theme-text-primary)]"
                style={readingContextType('sectionHeading')}
              >
                Your Reading Boundaries
              </h3>

              {dependencyEdges.length > 0 && (
                <div className="space-y-2">
                  <div
                    className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                    style={readingContextType('statLabel')}
                  >
                    {dependencyEdges.length === 1 ? 'Dependency:' : 'Dependency edges:'}
                  </div>
                  {dependencyEdges.map((edge) => (
                    <EdgeRow
                      key={`dependency-${edge.id}`}
                      edge={edge}
                      accent="rgb(250, 204, 139)"
                      arrow="→"
                    />
                  ))}
                </div>
              )}

              {continuityEdges.length > 0 && (
                <div className="space-y-2">
                  <div
                    className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                    style={readingContextType('statLabel')}
                  >
                    {continuityEdges.length === 1 ? 'Continuity:' : 'Continuity edges:'}
                  </div>
                  {continuityEdges.map((edge) => (
                    <EdgeRow
                      key={`continuity-${edge.id}`}
                      edge={edge}
                      accent="rgb(165, 243, 252)"
                      arrow="↝"
                    />
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  )
}
