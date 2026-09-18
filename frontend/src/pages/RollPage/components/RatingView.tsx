import { type Ref, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo, ReaderContextResponse } from '../../../types'
import type { RatingThread } from '../types'
import { ComicPillar } from './ComicPillar'
import { ReadingContextPillar } from './ReadingContextPillar'
import { ReadingContextStatusCard } from './ReadingContextStatusCard'
import { YourContextPillar } from './YourContextPillar'
import { hasReadingContextContent } from '../readingContextContent'
import { RatingActionPanel } from './RatingActionPanel'
import { WhyThisRoll } from './WhyThisRoll'
import { readingContextType } from '../readingContextTypography'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult?: boolean
  poolSize?: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  skipIsPending?: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onFetchReadingDetails?: (threadId: number | null) => void
  onFetchReadingContext?: (threadId: number | null) => void
  onFetchReadingBoundaries?: (threadId: number | null) => void
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onSkip?: () => void
  onCancel: () => void
  onRefreshThread: () => void
  readerContext?: ReaderContextResponse | null
  isReaderContextLoading?: boolean
  readerContextError?: string | null
  ratingViewTopRef?: Ref<HTMLDivElement> | null
}

function EdgeEndpoint({
  label,
  fallbackLabel,
  threadId,
  onOpen,
}: {
  label: string | null
  fallbackLabel: string
  threadId: number | null
  onOpen: (threadId: number) => void
}) {
  const endpointStyle = readingContextType('primaryValue')
  if (threadId === null) {
    return (
      <span className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]" style={endpointStyle}>
        {label ?? fallbackLabel}
      </span>
    )
  }
  return (
    <button
      type="button"
      className="inline-flex min-h-6 items-center break-words text-left font-mono underline decoration-dotted underline-offset-2 text-[var(--theme-text-primary)]"
      style={endpointStyle}
      onClick={() => onOpen(threadId)}
      aria-label={`Open series for ${label ?? fallbackLabel}`}
    >
      {label ?? fallbackLabel}
    </button>
  )
}

function ReadingBoundariesSection({ readerContext }: { readerContext: ReaderContextResponse | null }) {
  const navigate = useNavigate()
  const dependencyEdges = useMemo(
    () => readerContext?.local_chain.edges.filter((e) => e.kind === 'dependency') ?? [],
    [readerContext],
  )
  const continuityEdges = useMemo(
    () => readerContext?.local_chain.edges.filter((e) => e.kind === 'continuity') ?? [],
    [readerContext],
  )
  const currentIssueId = readerContext?.issue_id ?? null
  const dependencyHeading = useMemo(() => {
    if (dependencyEdges.length === 0) return null
    if (dependencyEdges.every((e) => e.target_issue_id === currentIssueId)) return 'Blocked by:'
    if (dependencyEdges.every((e) => e.source_issue_id === currentIssueId)) return 'Blocks:'
    return 'Dependency edges:'
  }, [dependencyEdges, currentIssueId])

  const openThread = (threadId: number) => navigate(`/thread/${threadId}`)

  if (dependencyEdges.length === 0 && continuityEdges.length === 0) return null

  return (
    <section
      aria-labelledby="dependency-edges-heading"
      className="rounded-2xl p-4"
      style={{ border: '1px solid rgba(6,182,212,0.3)', backgroundColor: 'rgba(6, 182, 212, 0.09)' }}
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
              {dependencyHeading}
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
                <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(250, 204, 139)' }} />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <EdgeEndpoint
                      label={edge.source_label}
                      fallbackLabel={`#${edge.source_issue_id}`}
                      threadId={edge.source_thread_id}
                      onOpen={openThread}
                    />
                    <span className="text-[var(--theme-text-muted)]" aria-hidden="true">
                      →
                    </span>
                    <EdgeEndpoint
                      label={edge.target_label}
                      fallbackLabel={`#${edge.target_issue_id}`}
                      threadId={edge.target_thread_id}
                      onOpen={openThread}
                    />
                  </div>
                  {(edge.explanation ?? edge.note) && (
                    <div className="break-words italic text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
                      {edge.explanation ?? edge.note}
                    </div>
                  )}
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
                <div className="mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ backgroundColor: 'rgb(165, 243, 252)' }} />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <EdgeEndpoint
                      label={edge.source_label}
                      fallbackLabel={`#${edge.source_issue_id}`}
                      threadId={edge.source_thread_id}
                      onOpen={openThread}
                    />
                    <span className="text-[var(--theme-text-muted)]" aria-hidden="true">
                      ↝
                    </span>
                    <EdgeEndpoint
                      label={edge.target_label}
                      fallbackLabel={`#${edge.target_issue_id}`}
                      threadId={edge.target_thread_id}
                      onOpen={openThread}
                    />
                  </div>
                  {(edge.explanation ?? edge.note) && (
                    <div className="break-words italic text-[var(--theme-text-muted)]" style={readingContextType('bodyCopy')}>
                      {edge.explanation ?? edge.note}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  skipIsPending = false,
  readingOrders,
  connectedThreads,
  onFetchReadingDetails,
  onFetchReadingContext,
  onFetchReadingBoundaries,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onSkip,
  onCancel,
  onRefreshThread,
  readerContext = null,
  isReaderContextLoading = false,
  readerContextError = null,
  ratingViewTopRef = null,
}: RatingViewProps) {
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const hasReadingContextContentValue = hasReadingContextContent(readingOrders, connectedThreads, readerContext)
  const readerContextLoading = isReaderContextLoading && !readerContext
  const readerContextFailure = !!readerContextError && !readerContext
  const showReadingContextStatus = !hasReadingContextContentValue && (readerContextLoading || readerContextFailure)

  const [readingContextExpanded, setReadingContextExpanded] = useState(false)
  const [readingBoundariesExpanded, setReadingBoundariesExpanded] = useState(false)

  const handleFetchReadingContext = useCallback(() => {
    setReadingContextExpanded(true)
    const threadId = activeRatingThread?.id ?? null
    if (onFetchReadingContext) onFetchReadingContext(threadId)
    else onFetchReadingDetails?.(threadId)
  }, [activeRatingThread?.id, onFetchReadingContext, onFetchReadingDetails])

  const handleFetchReadingBoundaries = useCallback(() => {
    setReadingBoundariesExpanded(true)
    const threadId = activeRatingThread?.id ?? null
    if (onFetchReadingBoundaries) onFetchReadingBoundaries(threadId)
    else onFetchReadingDetails?.(threadId)
  }, [activeRatingThread?.id, onFetchReadingBoundaries, onFetchReadingDetails])

  const hasBoundariesContent = useMemo(
    () => (readerContext?.local_chain.edges.length ?? 0) > 0,
    [readerContext],
  )
  const contextReaderContext = useMemo(() => {
    if (!readerContext) return null
    return {
      ...readerContext,
      local_chain: {
        ...readerContext.local_chain,
        edges: [],
      },
    }
  }, [readerContext])
  const hasContextContent = hasReadingContextContent(readingOrders, connectedThreads, contextReaderContext)

  return (
    <div ref={ratingViewTopRef} data-testid="rating-view-top" className="relative z-10 space-y-4 p-3 md:p-4">
      <WhyThisRoll explanation={activeRatingThread?.explanation} />
      <div
        className="grid items-start gap-4 lg:grid-cols-2 lg:gap-6 xl:grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))]"
        data-testid="rating-pillars-grid"
      >
        <div className="min-w-0" data-testid="rating-region-comic">
          <ComicPillar activeRatingThread={activeRatingThread} onRefreshThread={onRefreshThread} />
        </div>

        <div className="min-w-0 order-2 lg:order-none space-y-3" data-testid="rating-region-reading-optional">
          {!readingContextExpanded ? (
            activeRatingThread ? (
              <button
                type="button"
                onClick={handleFetchReadingContext}
                className="w-full flex items-center justify-between px-3 py-2 text-left text-sm rounded-lg border transition-colors group"
                style={{
                  borderColor: 'var(--theme-continuity-accent)',
                  color: 'var(--theme-text-primary)',
                  backgroundColor: 'var(--theme-bg-panel)',
                }}
                data-testid="reading-context-button"
                aria-expanded="false"
                aria-controls="rating-region-reading-context"
              >
                <span>Reading Context</span>
                <span className="text-stone-500 transition-transform group-hover:rotate-180" aria-hidden="true">⌄</span>
              </button>
            ) : null
          ) : (
            <div className="min-w-0" data-testid="rating-region-reading-context" id="rating-region-reading-context">
              <div className="mb-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => setReadingContextExpanded(false)}
                  className="min-h-6 px-2 text-xs font-medium rounded transition-colors"
                  style={{
                    border: '1px solid var(--theme-border)',
                    color: 'var(--theme-text-muted)',
                    backgroundColor: 'var(--theme-bg-panel)',
                  }}
                  aria-label="Minimize Reading Context"
                  aria-expanded="true"
                >
                  Minimize
                </button>
              </div>
              {readerContextLoading ? (
                <ReadingContextStatusCard isLoading error={readerContextError} />
              ) : readerContextFailure ? (
                <ReadingContextStatusCard isLoading={false} error={readerContextError} />
              ) : hasContextContent ? (
                <ReadingContextPillar
                  activeRatingThread={activeRatingThread}
                  readingOrders={readingOrders}
                  connectedThreads={connectedThreads}
                  onRefreshThread={onRefreshThread}
                  rolledResult={rolledResult}
                  currentDie={currentDie}
                  readerContext={contextReaderContext}
                  isReaderContextLoading={isReaderContextLoading}
                  readerContextError={readerContextError}
                />
              ) : (
                <div
                  className="rounded-xl p-3 text-sm text-[var(--theme-text-muted)]"
                  style={{ border: '1px solid var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
                >
                  No reading context available.
                </div>
              )}
            </div>
          )}

          {!readingBoundariesExpanded ? (
            activeRatingThread ? (
              <button
                type="button"
                onClick={handleFetchReadingBoundaries}
                className="w-full flex items-center justify-between px-3 py-2 text-left text-sm rounded-lg border transition-colors group"
                style={{
                  borderColor: 'var(--theme-continuity-accent)',
                  color: 'var(--theme-text-primary)',
                  backgroundColor: 'var(--theme-bg-panel)',
                }}
                data-testid="reading-boundaries-button"
                aria-expanded="false"
                aria-controls="rating-region-reading-boundaries"
              >
                <span>Reading Boundaries</span>
                <span className="text-stone-500 transition-transform group-hover:rotate-180" aria-hidden="true">⌄</span>
              </button>
            ) : null
          ) : (
            <div className="min-w-0" data-testid="rating-region-reading-boundaries" id="rating-region-reading-boundaries">
              <div className="mb-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => setReadingBoundariesExpanded(false)}
                  className="min-h-6 px-2 text-xs font-medium rounded transition-colors"
                  style={{
                    border: '1px solid var(--theme-border)',
                    color: 'var(--theme-text-muted)',
                    backgroundColor: 'var(--theme-bg-panel)',
                  }}
                  aria-label="Minimize Reading Boundaries"
                  aria-expanded="true"
                >
                  Minimize
                </button>
              </div>
              {readerContextLoading ? (
                <ReadingContextStatusCard isLoading error={readerContextError} />
              ) : readerContextFailure ? (
                <ReadingContextStatusCard isLoading={false} error={readerContextError} />
              ) : hasBoundariesContent ? (
                <ReadingBoundariesSection readerContext={readerContext} />
              ) : (
                <div
                  className="rounded-xl p-3 text-sm text-[var(--theme-text-muted)]"
                  style={{ border: '1px solid var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}
                >
                  No reading boundaries available.
                </div>
              )}
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-4 order-1 lg:order-none" data-testid="rating-region-your-context">
          <YourContextPillar
            activeRatingThread={activeRatingThread}
            currentDie={currentDie}
            rating={rating}
            predictedDie={predictedDie}
            onUpdateRating={onUpdateRating}
            readerContext={readerContext}
            isLoading={isReaderContextLoading}
          />

          <div className="min-w-0" data-testid="rating-actions-grid-cell">
            <RatingActionPanel
              errorMessage={errorMessage}
              rateIsPending={rateIsPending}
              snoozeIsPending={snoozeIsPending}
              dismissIsPending={dismissIsPending}
              skipIsPending={skipIsPending}
              issuesRemaining={issuesRemaining}
              onSubmitRating={onSubmitRating}
              onSnooze={onSnooze}
              onSkip={onSkip}
              onCancel={onCancel}
              threadTitle={activeRatingThread?.title ?? null}
              issueNumber={activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null}
            />
          </div>
        </div>
      </div>

      {showReadingContextStatus && !readingContextExpanded && !readingBoundariesExpanded && (
        <ReadingContextStatusCard isLoading={readerContextLoading} error={readerContextError} />
      )}
    </div>
  )
}
