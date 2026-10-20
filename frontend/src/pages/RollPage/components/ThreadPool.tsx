import { EligibilityExplanation } from '../../../components/EligibilityExplanation'
import { useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { scrollToTopSemantic } from '../../../scroll/scrollCoordinator'
import { ThreadTagChips } from '../../../components/Tags/ThreadTagChips'
import type { BlockingDependency } from '../../../types'
import type { RollBootstrapThread, ThreadExclusionReason } from '../../../types/rollBootstrap'

const EXCLUSION_REASON_LABELS: Record<ThreadExclusionReason['reason'], string> = {
  completed: 'Read the full series',
  not_in_queue: 'Not in the active queue',
  blocked: 'Waiting on an earlier issue',
  snoozed: 'Snoozed',
  skipped: 'Skipped this session',
}

function exclusionReasonLabel(thread: ThreadExclusionReason): string {
  return thread.detail ?? EXCLUSION_REASON_LABELS[thread.reason]
}

/**
 * Ordinary secondary action styling for the paged-section controls.
 *
 * The visual grammar reserves the small uppercase eyebrow treatment for status
 * and category labels, and requires ordinary controls to use the semantic
 * theme roles instead of raw palette colors.
 */
const SECTION_ACTION_CLASS =
  'w-full min-h-11 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-2 text-sm font-semibold text-[var(--theme-text-primary)] transition-colors hover:border-[var(--theme-text-muted)]/50 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]'

interface LoadMoreControlProps {
  /** Total records the section counts. */
  total: number
  /** Records the section currently renders. */
  shown: number
  /** True while a page request is in flight. */
  loading: boolean
  /** True when the last page request failed. */
  failed: boolean
  /** Human name of the section, used in the recovery copy. */
  label: string
  onLoadMore: () => void
}

/**
 * The load-more control of one bounded Roll category section.
 *
 * A failed page keeps the rows already listed and offers a working retry, so a
 * reader never gets an enabled control that does nothing.
 */
function LoadMoreControl({
  total,
  shown,
  loading,
  failed,
  label,
  onLoadMore,
}: LoadMoreControlProps) {
  const remaining = Math.max(total - shown, 0)
  return (
    <div className="space-y-2 pt-1">
      <p className="text-xs text-[var(--theme-text-muted)]">
        Showing {shown} of {total} series.
      </p>
      {failed && (
        <p role="alert" className="text-xs text-[var(--theme-text-muted)]">
          Could not load more {label}. The series already listed are still shown.
        </p>
      )}
      <button
        type="button"
        onClick={onLoadMore}
        disabled={loading}
        className={SECTION_ACTION_CLASS}
      >
        {loading ? 'Loading more…' : failed ? 'Retry' : `Load more (${remaining} remaining)`}
      </button>
    </div>
  )
}

interface ThreadPoolProps {
  pool: RollBootstrapThread[]
  blockedThreads: RollBootstrapThread[]
  blockingDependencyMap: Record<number, BlockingDependency[]>
  dieSize?: number
  isRatingView: boolean
  selectedThreadId: number | null
  staleThread: (RollBootstrapThread & { days: number }) | null
  staleThreadCount: number
  snoozedThreads: Array<{ id: number; title: string; format: string }>
  snoozedExpanded: boolean
  blockedExpanded: boolean
  skippedThreads: Array<{ id: number; title: string; format: string }>
  skippedExpanded: boolean
  staleExpanded: boolean
  inactiveExpanded?: boolean
  inactiveThreads?: ThreadExclusionReason[]
  /**
   * Accurate category totals from the bootstrap (issue #3330). They may exceed
   * the rendered preview length; the section header must report these counts so
   * a reader never sees "20" when the server counted more.
   */
  blockedCount?: number
  inactiveCount?: number
  /** True while more counted records exist beyond the rendered rows. */
  blockedHasMore?: boolean
  inactiveHasMore?: boolean
  blockedLoadingMore?: boolean
  inactiveLoadingMore?: boolean
  /** True when the last blocked page request failed. */
  blockedLoadError?: boolean
  /** True when the last inactive page request failed. */
  inactiveLoadError?: boolean
  onLoadMoreBlocked?: () => void
  onLoadMoreInactive?: () => void
  onToggleInactive?: () => void
  onThreadClick: (thread: RollBootstrapThread) => void
  onUnsnooze: (threadId: number) => void
  onUnskip: (threadId: number) => void
  onReadStale: (threadId: number) => void
  onToggleSnoozed: () => void
  onToggleSkipped: () => void
  onToggleStale: () => void
  onToggleBlocked: () => void
  onShuffle: () => void
  unsnoozeIsPending: boolean
  unskipIsPending: boolean
  shuffleIsPending: boolean
}

export function ThreadPool({
  pool,
  blockedThreads,
  blockingDependencyMap,
  dieSize,
  isRatingView,
  selectedThreadId,
  staleThread,
  staleThreadCount,
  snoozedThreads,
  snoozedExpanded,
  blockedExpanded,
  skippedThreads,
  skippedExpanded,
  staleExpanded,
  inactiveExpanded,
  inactiveThreads = [],
  blockedCount,
  inactiveCount,
  blockedHasMore = false,
  inactiveHasMore = false,
  blockedLoadingMore = false,
  inactiveLoadingMore = false,
  blockedLoadError = false,
  inactiveLoadError = false,
  onLoadMoreBlocked,
  onLoadMoreInactive,
  onToggleInactive,
  onThreadClick,
  onUnsnooze,
  onUnskip,
  onReadStale,
  onToggleSnoozed,
  onToggleSkipped,
  onToggleStale,
  onToggleBlocked,
  onShuffle,
  unsnoozeIsPending,
  unskipIsPending,
  shuffleIsPending,
}: ThreadPoolProps) {
  const navigate = useNavigate()
  const wasRatingView = useRef(isRatingView)
  // The bootstrap bounds each preview list but reports the true category
  // totals. Report the accurate total so a truncated preview never claims the
  // whole category was only 20 series (issue #3330).
  const totalBlocked = blockedCount ?? blockedThreads.length
  const totalInactive = inactiveCount ?? inactiveThreads.length

  useEffect(() => {
    const returnedToRoll = wasRatingView.current && !isRatingView
    wasRatingView.current = isRatingView

    if (returnedToRoll) {
      // Explicit semantic scroll for the intentional rating→dice transition
      // (#2582). Gated by the scroll coordinator so it defers while a route
      // restore is actively settling instead of racing it.
      scrollToTopSemantic()
    }
  }, [isRatingView])

  return (
    <div
      className={`px-3 md:px-4 pb-20 md:pb-28 flex flex-col ${!isRatingView ? 'flex-1 min-h-[300px]' : 'border-t border-[var(--theme-border)] pt-4 md:pt-8'}`}
    >
      {!isRatingView && <div className="flex items-center gap-2 shrink-0 mb-4">
        <div className="w-2 h-2 rounded-full bg-[var(--theme-comic-accent)] shadow-[0_0_15px_var(--accent-red)]"></div>
        <div className="flex-1">
          <p className="text-[10px] font-black uppercase tracking-wider text-stone-300">{pool.length} in play</p>
          {dieSize && pool.length > 0 && pool.length < dieSize && (
            <p className="text-[10px] text-stone-500 mt-1" data-smaller-than-die>
              Only {pool.length} of d{dieSize} faces are mapped to an in-play series — the roll picks among these visible faces.
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onShuffle}
          disabled={shuffleIsPending || pool.length < 2}
          aria-describedby="shuffle-queue-description"
          className="h-8 px-3 rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 text-[10px] font-black uppercase tracking-widest text-[var(--theme-danger)] hover:bg-[var(--theme-danger)]/20 disabled:opacity-50 transition-colors"
        >
          Shuffle queue
        </button>
        <span id="shuffle-queue-description" className="sr-only">Randomizes the complete active queue, then refreshes these die mappings.</span>
      </div>}

      {!isRatingView && <div className="space-y-2" data-roll-pool aria-label={`${pool.length} in play, ${pool.length} mapped result${pool.length === 1 ? '' : 's'}`}>
        {pool.length === 0 && blockedThreads.length === 0 && snoozedThreads.length === 0 && inactiveThreads.length === 0 ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">🎲</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">Nothing to roll yet</p>
              <p className="text-xs text-stone-500 mt-1">Your reading queue is empty — add some comic series to get started.</p>
            </div>
            <button
              onClick={() => navigate('/queue', { state: { openCreate: true } })}
              className="w-full h-11 min-h-[44px] bg-[var(--theme-comic-accent)]/10 hover:bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)]/20 rounded-xl text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors"
            >
              + Add a Series
            </button>
            <div className="text-left bg-[var(--theme-bg-panel)] rounded-xl p-4 mt-4">
              <p className="text-[10px] font-bold text-stone-400 uppercase tracking-wider mb-2">How it works:</p>
              <ul className="text-xs text-stone-500 space-y-1">
                <li>• Add the series you&apos;re reading</li>
                <li>• Roll the dice to pick what to read next</li>
                <li>• Set dependencies to enforce reading order between series</li>
              </ul>
            </div>
          </div>
        ) : pool.length === 0 && (blockedThreads.length > 0 || snoozedThreads.length > 0 || inactiveThreads.length > 0) ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">🔒</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
                {inactiveThreads.length > 0
                  ? 'No series in play right now'
                  : 'Every series is blocked or snoozed'}
              </p>
              <p className="text-xs text-stone-500 mt-1">
                {inactiveThreads.length > 0
                  ? 'Every series is waiting on something. The lists below say which reason applies to each one.'
                  : 'Check your queue to see what needs to be read to unlock more options.'}
              </p>
            </div>
            <button
              onClick={() => navigate('/queue')}
              className="w-full h-11 min-h-[44px] bg-[var(--theme-comic-accent)]/10 hover:bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)]/20 rounded-xl text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors"
            >
              Go to Queue
            </button>
          </div>
        ) : (
          pool.map((thread, index) => {
            const isSelected = selectedThreadId && Number(selectedThreadId) === thread.id
            const routeLabels = (thread.route_labels ?? []).filter(Boolean)
            const tags = thread.tags ?? []
            const tagNames = tags.map((tag) => tag.name)
            return (
              <div
                key={thread.id}
                onClick={() => onThreadClick(thread)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onThreadClick(thread)
                  }
                }}
                role="button"
                tabIndex={0}
                aria-label={`Die face ${index + 1}: ${thread.title}${thread.issue_number ? `, issue ${thread.issue_number}` : ''}${tagNames.length ? `, tagged ${tagNames.join(', ')}` : ''}${routeLabels.length ? `, connected to ${routeLabels.join(', ')}` : ''}. Open series actions.`}
                className={`flex items-center gap-3 px-4 py-3 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl group transition-all cursor-pointer hover:bg-white/10 ${isSelected ? 'pool-thread-selected border-[var(--theme-comic-accent)]/30' : ''
                  }`}
              >
                <span className="text-lg font-black text-stone-500/50 group-hover:text-stone-400/50 transition-colors w-6 text-center">
                  {index + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-stone-200 truncate text-sm">{thread.title}</p>
                  <p className="truncate text-xs text-stone-400">
                    {thread.issue_number ? `#${thread.issue_number}` : 'Next unread issue'}
                  </p>
                  <p className="text-[10px] font-black text-stone-500 uppercase tracking-widest mt-0.5">{thread.format}</p>
                  <ThreadTagChips
                    tags={tags}
                    label={`Tags for ${thread.title}`}
                    className="mt-1"
                  />
                  {routeLabels.length ? (
                    <p className="mt-1 truncate text-[10px] text-sky-300">
                      Connected to: {routeLabels.join(' · ')}
                    </p>
                  ) : null}
                </div>
              </div>
            )
          })
        )}
      </div>}

      {totalBlocked > 0 && !isRatingView && (
        <div className="mt-4">
          <button
            type="button"
            onClick={onToggleBlocked}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${blockedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
              {totalBlocked} series waiting for earlier issues
            </span>
          </button>
          {blockedExpanded && (
            <div className="mt-2 space-y-1">
              {blockedThreads.map((thread) => (
                <div
                  key={thread.id}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg"
                >
                  <span className="text-sm">🔒</span>
                  <div className="flex-1 min-w-0">
                    <Link to={`/thread/${thread.id}`} className="text-sm text-[var(--theme-text-muted)] underline">{thread.title}</Link>
                    <EligibilityExplanation isBlocked reasons={thread.blocking_reasons} dependencies={blockingDependencyMap[thread.id]} />
                  </div>
                </div>
              ))}
              {blockedHasMore && onLoadMoreBlocked && (
                <LoadMoreControl
                  total={totalBlocked}
                  shown={blockedThreads.length}
                  loading={blockedLoadingMore}
                  failed={blockedLoadError}
                  label="blocked series"
                  onLoadMore={onLoadMoreBlocked}
                />
              )}
            </div>
          )}
        </div>
      )}

      {staleThread && !isRatingView && (
        <div className="mt-4 md:mt-8">
          <button
            type="button"
            onClick={onToggleStale}
            aria-expanded={staleExpanded}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${staleExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
              {staleThreadCount} series you haven&apos;t opened recently
            </span>
          </button>
          {staleExpanded && (
            <div className="mt-2 space-y-1">
              <div
                key={staleThread.id}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--theme-comic-accent)]/5 border border-[var(--theme-comic-accent)]/10 rounded-lg"
              >
                <div className="w-8 h-8 bg-[var(--theme-comic-accent)]/10 rounded-lg flex items-center justify-center shrink-0">
                  <span className="text-sm">⏳</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[var(--theme-comic-accent)]/70 font-medium">
                    {staleThread.title}
                  </p>
                  <p className="text-[9px] text-[var(--theme-comic-accent)]/50">
                    Last opened {staleThread.days} days ago
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onReadStale(staleThread.id)}
                  className="inline-flex min-h-7 min-w-7 items-center justify-center px-2 text-xs text-[var(--theme-comic-accent)] hover:text-[var(--theme-comic-accent)]/80 hover:bg-[var(--theme-comic-accent)]/10 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                  title="Roll this series now"
                  aria-label="Roll this series now"
                >
                  🎲
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {snoozedThreads && snoozedThreads.length > 0 && !isRatingView && (
        <div className="mt-4 md:mt-8">
          <button
            type="button"
            onClick={onToggleSnoozed}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${snoozedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest cursor-help border-b border-dashed border-stone-600">
              Snoozed ({snoozedThreads.length})
            </span>
          </button>
          {snoozedExpanded && (
            <div className="mt-2 space-y-1">
              {snoozedThreads.map((thread) => (
                <div
                  key={thread.id}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg"
                >
                  <p className="flex-1 text-sm text-stone-400 truncate">{thread.title}</p>
                  <button
                    type="button"
                    onClick={() => onUnsnooze(thread.id)}
                    disabled={unsnoozeIsPending}
                    className="inline-flex min-h-7 min-w-7 items-center justify-center px-2 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50 focus:ring-2 focus:ring-rose-500"
                    title="Unsnooze this comic"
                    aria-label="Unsnooze this comic"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {skippedThreads && skippedThreads.length > 0 && !isRatingView && (
        <div className="mt-4 md:mt-8">
          <button
            type="button"
            onClick={onToggleSkipped}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${skippedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest cursor-help border-b border-dashed border-stone-600">
              Skipped ({skippedThreads.length})
            </span>
          </button>
          {skippedExpanded && (
            <div className="mt-2 space-y-1">
              {skippedThreads.map((thread) => (
                <div
                  key={thread.id}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg"
                >
                  <p className="flex-1 text-sm text-stone-400 truncate">{thread.title}</p>
                  <button
                    type="button"
                    onClick={() => onUnskip(thread.id)}
                    disabled={unskipIsPending}
                    className="inline-flex min-h-7 min-w-7 items-center justify-center px-2 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition-colors disabled:opacity-50 focus:ring-2 focus:ring-rose-500"
                    title="Unskip this comic"
                    aria-label="Unskip this comic"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {totalInactive > 0 && !isRatingView && onToggleInactive && (
        <div className="mt-4 md:mt-8">
          <button
            type="button"
            onClick={onToggleInactive}
            aria-expanded={inactiveExpanded ?? false}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${(inactiveExpanded ?? false) ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest">
              {totalInactive} series out of the roll pool
            </span>
          </button>
          {inactiveExpanded && (
            <div className="mt-2 space-y-1">
              {inactiveThreads.map((thread) => (
                <div
                  key={thread.thread_id}
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-lg"
                >
                  <Link
                    to={`/thread/${thread.thread_id}`}
                    className="flex-1 min-w-0 text-sm text-[var(--theme-text-muted)] underline truncate"
                  >
                    {thread.title}
                  </Link>
                  <span className="shrink-0 text-xs text-stone-500">
                    {exclusionReasonLabel(thread)}
                  </span>
                </div>
              ))}
              {inactiveHasMore && onLoadMoreInactive && (
                <LoadMoreControl
                  total={totalInactive}
                  shown={inactiveThreads.length}
                  loading={inactiveLoadingMore}
                  failed={inactiveLoadError}
                  label="out-of-pool series"
                  onLoadMore={onLoadMoreInactive}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
