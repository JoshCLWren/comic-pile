import { readingContextType } from '../readingContextTypography'
import { ReadingContextStatusCard } from './ReadingContextStatusCard'

interface ReadingBoundariesCardProps {
  isLoading: boolean
  error: string | null
  readerContext: import('../../types').ReaderContextResponse | null
  isOpen: boolean
  onToggle: () => void
}

export function ReadingBoundariesCard({
  isLoading,
  error,
  readerContext,
  isOpen,
  onToggle,
}: ReadingBoundariesCardProps) {
  const dependencyEdges = readerContext?.local_chain.edges.filter(
    (e) => e.kind === 'dependency',
  ) ?? []
  const continuityEdges = readerContext?.local_chain.edges.filter(
    (e) => e.kind === 'continuity',
  ) ?? []

  function renderEdgeExplanation(edge: { explanation: string | null; note: string | null }) {
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

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2.5 text-left transition hover:bg-white/5 focus:ring-2 focus:ring-[var(--theme-focus-ring)]"
        aria-expanded={isOpen}
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
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
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
        <div className="animate-in slide-in-from-top-2 duration-150">
          {isLoading ? (
            <ReadingContextStatusCard isLoading error={error} />
          ) : error ? (
            <ReadingContextStatusCard isLoading={false} error={error} />
          ) : (
            <div className="space-y-3">
              {dependencyEdges.length > 0 && (
                <section
                  aria-labelledby="dependency-edges-heading"
                  className="rounded-2xl p-4"
                  style={{
                    border: '1px solid rgba(6,182,212,0.3)',
                    backgroundColor: 'rgba(6, 182, 212, 0.09)',
                  }}
                >
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h3
                      id="dependency-edges-heading"
                      className="font-bold text-[var(--theme-text-primary)]"
                      style={readingContextType('sectionHeading')}
                    >
                      Your Reading Boundaries
                    </h3>
                  </div>

                  <div className="space-y-3">
                    {dependencyEdges.length > 0 && (
                      <div className="space-y-2">
                        <div
                          className="font-bold uppercase tracking-wider text-[var(--theme-text-muted)]"
                          style={readingContextType('statLabel')}
                        >
                          {dependencyEdges.length === 1 ? 'Dependency:' : 'Dependency edges:'}
                        </div>
                        {dependencyEdges.map((edge) => (
                          <div
                            key={`dependency-${edge.id}`}
                            className="flex items-start gap-3 rounded-lg px-3 py-2"
                            style={{
                              borderLeft: '3px solid rgb(250, 204, 139)',
                              backgroundColor: 'rgba(250, 204, 139, 0.05)',
                            }}
                          >
                            <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }}></div>
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <span
                                  className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
                                  style={readingContextType('primaryValue')}
                                >
                                  # {edge.source_issue_id}
                                </span>
                                <span className="text-[var(--theme-text-muted)]" aria-hidden="true">→</span>
                                <span
                                  className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
                                  style={readingContextType('primaryValue')}
                                >
                                  # {edge.target_issue_id}
                                </span>
                              </div>
                            </div>
                          </div>
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
                          <div
                            key={`continuity-${edge.id}`}
                            className="flex items-start gap-3 rounded-lg px-3 py-2"
                            style={{
                              borderLeft: '3px solid rgb(165, 243, 252)',
                              backgroundColor: 'rgba(165, 243, 252, 0.05)',
                            }}
                          >
                            <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(165, 243, 252)' }}></div>
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <span
                                  className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
                                  style={readingContextType('primaryValue')}
                                >
                                  # {edge.source_issue_id}
                                </span>
                                <span className="text-[var(--theme-text-muted)]" aria-hidden="true">↝</span>
                                <span
                                  className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]"
                                  style={readingContextType('primaryValue')}
                                >
                                  # {edge.target_issue_id}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </section>
              )}}
            </div>
          )}
        </div>
      )}
    </div>
  )
}