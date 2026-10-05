import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ConnectedThreadInfo, ReaderContextResponse } from '../../../types'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import { rollUtilityActionClass } from '../actionClasses'
import { SeriesPanel } from './SeriesPanel'
import { CrossoverAnalytics } from './CrossoverAnalytics'
import type { RatingThread } from '../types'

interface OptionalReadingCardsProps {
  activeRatingThread: RatingThread | null
  readerContext: ReaderContextResponse | null
  isReaderContextLoading: boolean
  readerContextError: Error | null
  readingContextRequested: boolean
  readingBoundariesRequested: boolean
  readingOrders: ReadingOrder[]
  readingOrdersIsLoading: boolean
  readingOrdersError: Error | null
  connectedThreads: ConnectedThreadInfo[]
  connectedThreadsIsLoading: boolean
  connectedThreadsError: Error | null
  onShowContext: () => void
  onShowBoundaries: () => void
}

function errorMessage(error: Error | null): string | null {
  return error?.message ?? null
}

/**
 * Compact collapsed card shell shared by the two optional Roll surfaces
 * (issue #2764). The header row wraps instead of squeezing so the label and
 * the touch target stay readable at phone widths, and the card never reserves
 * width beyond its stack: expanded content renders inline below the header
 * inside the right-side stack, never in a peer middle column and never in a
 * modal. Opening a card never scrolls the viewport.
 */
function OptionalCardShell({
  cardTestId,
  buttonTestId,
  contentTestId,
  label,
  copy,
  icon,
  open,
  expandedLabel,
  onToggle,
  children,
}: {
  cardTestId: string
  buttonTestId: string
  contentTestId: string
  label: string
  copy: string
  icon: ReactNode
  open: boolean
  expandedLabel: string
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <section
      aria-label={label}
      data-testid={cardTestId}
      className="w-full min-w-0 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span aria-hidden="true" className="shrink-0 text-[var(--theme-text-muted)]">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
            {label}
          </h3>
          <p className="mt-0.5 min-w-0 break-words text-[11px] leading-relaxed text-stone-400">
            {copy}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          data-testid={buttonTestId}
          className={`min-h-9 shrink-0 ${rollUtilityActionClass()}`}
        >
          {open ? `Hide ${expandedLabel.toLowerCase()}` : `Show ${expandedLabel.toLowerCase()}`}
        </button>
      </div>
      {open ? (
        <div data-testid={contentTestId} className="mt-3 min-w-0 max-w-full space-y-3">
          {children}
        </div>
      ) : null}
    </section>
  )
}

function OptionalLoading({ testId, label }: { testId: string; label: string }) {
  return (
    <div data-testid={testId} role="status" aria-live="polite" className="space-y-2">
      <span className="sr-only">{label}</span>
      <div className="h-3 w-24 animate-pulse rounded bg-white/5" aria-hidden="true" />
      <div className="h-5 w-16 animate-pulse rounded bg-white/5" aria-hidden="true" />
      <div className="h-3 w-20 animate-pulse rounded bg-white/5" aria-hidden="true" />
    </div>
  )
}

function OptionalError({ testId, messages }: { testId: string; messages: string[] }) {
  return (
    <div
      data-testid={testId}
      role="alert"
      className="min-w-0 break-words rounded-xl border border-[var(--theme-danger)]/30 bg-[var(--theme-danger)]/10 p-3"
    >
      <p className="text-[11px] font-bold text-[var(--theme-danger)]">
        This optional detail failed to load, but rating still works.
      </p>
      <ul className="mt-1 space-y-0.5">
        {messages.map((message) => (
          <li key={message} className="min-w-0 break-words text-[11px] text-stone-400">
            {message}
          </li>
        ))}
      </ul>
    </div>
  )
}

function BookIcon() {
  return (
    <svg
      className="h-4 w-4"
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
  )
}

function BoundaryIcon() {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 6h18" />
      <path d="M7 12h10" />
      <path d="M10 18h4" />
      <circle cx="17" cy="12" r="2" />
    </svg>
  )
}

function relationCopy(relation: string, seriesName: string | null): string {
  switch (relation) {
    case 'previous':
      return seriesName ? `Earlier in ${seriesName}` : 'Earlier issue'
    case 'current':
      return 'You are here'
    case 'next':
      return 'Next up'
    default:
      return seriesName ? `Later in ${seriesName}` : 'Later issue'
  }
}

function ReadingContextContent({
  readerContext,
  readingOrders,
  connectedThreads,
}: {
  readerContext: ReaderContextResponse | null
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
}) {
  const navigate = useNavigate()
  const seriesName = readerContext?.series.series_name ?? null
  const hasSeriesContent =
    readerContext?.series != null && readerContext.series.identity_source !== 'unavailable'
  const localIssues = readerContext?.local_chain.issues ?? []
  const hasLocalIssues = localIssues.some((issue) => issue.relation !== 'current')
  const crossovers = readerContext?.crossovers ?? []
  const hasCrossovers = crossovers.some(
    (crossover) =>
      crossover.applies_to_current_issue &&
      (crossover.ratings_count > 0 || crossover.read_count > 0 || crossover.average_rating !== null),
  )

  if (!readerContext) {
    return (
      <p className="min-w-0 break-words text-[11px] italic leading-relaxed text-stone-400">
        No additional reading context is recorded for this issue.
      </p>
    )
  }

  if (!hasSeriesContent && !hasLocalIssues && readingOrders.length === 0 && !hasCrossovers) {
    return (
      <p className="min-w-0 break-words text-[11px] italic leading-relaxed text-stone-400">
        No additional reading context is recorded for this issue.
      </p>
    )
  }

  return (
    <div className="min-w-0 space-y-3">
      {hasSeriesContent ? <SeriesPanel series={readerContext.series} /> : null}
      {hasLocalIssues ? (
        <section
          aria-label="Nearby issues in this series"
          className="min-w-0 space-y-1.5 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
        >
          <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">
            {seriesName ? `Nearby in ${seriesName}` : 'Nearby issues'}
          </h4>
          <ul className="min-w-0 space-y-1">
            {localIssues.map((issue) => (
              <li
                key={issue.issue_id}
                className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px]"
              >
                <span className="shrink-0 font-mono text-[var(--theme-text-primary)]">
                  #{issue.issue_number}
                </span>
                <span className="min-w-0 break-words text-stone-400">
                  {relationCopy(issue.relation, seriesName)}
                  {issue.status === 'read' ? ' · Already read' : ' · Not read yet'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {readingOrders.length > 0 ? (
        <section
          aria-label="Your reading plans"
          className="min-w-0 space-y-1.5 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
        >
          <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">
            Your reading plans
          </h4>
          <ul className="min-w-0 space-y-1.5">
            {readingOrders.map((order) => {
              const progress =
                order.total_items > 0
                  ? Math.round((order.completed_items / order.total_items) * 100)
                  : 0
              return (
                <li key={order.id} className="min-w-0">
                  <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2">
                    <span className="min-w-0 break-words text-[11px] font-bold text-stone-200">
                      {order.name}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-stone-400">
                      {order.completed_items}/{order.total_items} · {progress}%
                    </span>
                  </div>
                  <div
                    className="mt-1 h-1.5 overflow-hidden rounded-full"
                    style={{ backgroundColor: 'rgba(255,255,255,0.1)' }}
                    aria-hidden="true"
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        backgroundColor: 'var(--theme-primary-action)',
                        width: `${progress}%`,
                      }}
                    />
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}
      {connectedThreads.length > 0 ? (
        <section
          aria-label="Connected series"
          className="min-w-0 space-y-1.5 rounded-2xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
        >
          <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">
            Connected series
          </h4>
          <ul className="min-w-0 space-y-1">
            {connectedThreads.map((thread) => (
              <li key={thread.thread_id} className="min-w-0">
                <button
                  type="button"
                  onClick={() => navigate(`/thread/${thread.thread_id}`)}
                  aria-label={`Open series for ${thread.title}`}
                  className="inline-flex min-h-6 min-w-0 items-center break-words text-left font-mono text-[11px] text-[var(--theme-text-primary)] underline decoration-dotted underline-offset-2"
                >
                  <span className="min-w-0 break-words">
                    {thread.title} · {thread.connection_type}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {hasCrossovers ? <CrossoverAnalytics crossovers={crossovers} /> : null}
    </div>
  )
}

function ReadingBoundariesContent({
  readerContext,
}: {
  readerContext: ReaderContextResponse | null
}) {
  const navigate = useNavigate()
  const currentIssueId = readerContext?.issue_id ?? null
  const edges = readerContext?.local_chain.edges ?? []
  const prerequisites = edges.filter((edge) => edge.target_issue_id === currentIssueId)
  const downstream = edges.filter(
    (edge) => edge.source_issue_id === currentIssueId && edge.target_issue_id !== currentIssueId,
  )
  const related = edges.filter(
    (edge) =>
      edge.source_issue_id !== currentIssueId && edge.target_issue_id !== currentIssueId,
  )

  if (!readerContext || edges.length === 0) {
    return (
      <p className="min-w-0 break-words text-[11px] italic leading-relaxed text-stone-400">
        No prerequisites or continuity boundaries are recorded for this issue.
      </p>
    )
  }

  const groups: { heading: string; items: typeof edges }[] = []
  if (prerequisites.length > 0) groups.push({ heading: 'Before this issue', items: prerequisites })
  if (downstream.length > 0) groups.push({ heading: 'After this issue', items: downstream })
  if (related.length > 0) groups.push({ heading: 'Related continuity', items: related })

  return (
    <div className="min-w-0 space-y-3">
      {groups.map((group) => (
        <section key={group.heading} aria-label={group.heading} className="min-w-0 space-y-1.5">
          <h4 className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500">
            {group.heading}
          </h4>
          <ul className="min-w-0 space-y-1.5">
            {group.items.map((edge) => {
              const copy = edge.explanation ?? edge.note
              const sourceThreadId = edge.source_thread_id
              const targetThreadId = edge.target_thread_id
              return (
                <li
                  key={`${edge.kind}-${edge.id}`}
                  className="min-w-0 space-y-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2"
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                    {sourceThreadId !== null ? (
                      <button
                        type="button"
                        onClick={() => navigate(`/thread/${sourceThreadId}`)}
                        aria-label={`Open series for ${edge.source_label ?? 'the earlier issue'}`}
                        className="inline-flex min-h-6 min-w-0 items-center break-words text-left font-mono text-[var(--theme-text-primary)] underline decoration-dotted underline-offset-2"
                      >
                        <span className="min-w-0 break-words">
                          {edge.source_label ?? `#${edge.source_issue_id}`}
                        </span>
                      </button>
                    ) : (
                      <span className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]">
                        {edge.source_label ?? `#${edge.source_issue_id}`}
                      </span>
                    )}
                    <span className="shrink-0 text-[var(--theme-text-muted)]" aria-hidden="true">
                      {edge.kind === 'dependency' ? '→' : '↝'}
                    </span>
                    {targetThreadId !== null ? (
                      <button
                        type="button"
                        onClick={() => navigate(`/thread/${targetThreadId}`)}
                        aria-label={`Open series for ${edge.target_label ?? 'the later issue'}`}
                        className="inline-flex min-h-6 min-w-0 items-center break-words text-left font-mono text-[var(--theme-text-primary)] underline decoration-dotted underline-offset-2"
                      >
                        <span className="min-w-0 break-words">
                          {edge.target_label ?? `#${edge.target_issue_id}`}
                        </span>
                      </button>
                    ) : (
                      <span className="min-w-0 break-words font-mono text-[var(--theme-text-primary)]">
                        {edge.target_label ?? `#${edge.target_issue_id}`}
                      </span>
                    )}
                  </div>
                  {copy ? (
                    <p className="min-w-0 break-words text-[11px] italic leading-relaxed text-stone-400">
                      {copy}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

/**
 * The two compact optional cards restored below the Roll decision (issue
 * #2764). They consume the split request scopes from #2767: opening one card
 * requests only the data that card needs, failures stay inside the card, and
 * the rating workflow never waits on either surface. Expanded content renders
 * inline inside the right-side stack; there is no middle column, no modal, no
 * `Why this?`, and no viewport scroll correction.
 */
export function OptionalReadingCards({
  activeRatingThread,
  readerContext,
  isReaderContextLoading,
  readerContextError,
  readingContextRequested,
  readingBoundariesRequested,
  readingOrders,
  readingOrdersIsLoading,
  readingOrdersError,
  connectedThreads,
  connectedThreadsIsLoading,
  connectedThreadsError,
  onShowContext,
  onShowBoundaries,
}: OptionalReadingCardsProps) {
  const [contextOpen, setContextOpen] = useState(readingContextRequested)
  const [boundariesOpen, setBoundariesOpen] = useState(readingBoundariesRequested)

  if (!activeRatingThread) return null

  // React Query reports a disabled query as pending, so loading renders only
  // after the user actually opens a card. Collapsed cards stay lightweight:
  // no skeleton for unrequested data.
  const contextLoading =
    readingContextRequested &&
    (isReaderContextLoading || readingOrdersIsLoading || connectedThreadsIsLoading)
  const boundariesLoading = readingBoundariesRequested && isReaderContextLoading

  const contextErrors = [
    errorMessage(readerContextError),
    errorMessage(readingOrdersError),
    errorMessage(connectedThreadsError),
  ].filter((message): message is string => message !== null)
  const boundariesErrors = [errorMessage(readerContextError)].filter(
    (message): message is string => message !== null,
  )

  return (
    <div data-testid="rating-region-reading-optional" className="w-full min-w-0 space-y-3">
      <OptionalCardShell
        cardTestId="reading-context-card"
        buttonTestId="reading-context-button"
        contentTestId="reading-context-content"
        label="Reading Context (optional)"
        copy="See how this issue fits into your reading plans and continuity."
        icon={<BookIcon />}
        open={contextOpen}
        expandedLabel="Context"
        onToggle={() => {
          if (!contextOpen) onShowContext()
          setContextOpen(!contextOpen)
        }}
      >
        {contextLoading ? (
          <OptionalLoading testId="reading-context-loading" label="Loading reading context" />
        ) : (
          <>
            {contextErrors.length > 0 ? (
              <OptionalError testId="reading-context-error" messages={contextErrors} />
            ) : null}
            <ReadingContextContent
              readerContext={readerContext}
              readingOrders={readingOrders}
              connectedThreads={connectedThreads}
            />
          </>
        )}
      </OptionalCardShell>

      <OptionalCardShell
        cardTestId="reading-boundaries-card"
        buttonTestId="reading-boundaries-button"
        contentTestId="reading-boundaries-content"
        label="Reading Boundaries (optional)"
        copy="Review recorded prerequisites and continuity edges around this issue."
        icon={<BoundaryIcon />}
        open={boundariesOpen}
        expandedLabel="Boundaries"
        onToggle={() => {
          if (!boundariesOpen) onShowBoundaries()
          setBoundariesOpen(!boundariesOpen)
        }}
      >
        {boundariesLoading ? (
          <OptionalLoading testId="reading-boundaries-loading" label="Loading reading boundaries" />
        ) : (
          <>
            {boundariesErrors.length > 0 ? (
              <OptionalError testId="reading-boundaries-error" messages={boundariesErrors} />
            ) : null}
            <ReadingBoundariesContent readerContext={readerContext} />
          </>
        )}
      </OptionalCardShell>
    </div>
  )
}
