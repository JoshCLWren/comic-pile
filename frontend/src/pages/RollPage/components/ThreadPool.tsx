import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { scrollToTopSemantic } from '../../../scroll/scrollCoordinator'
import { ThreadTagChips } from '../../../components/Tags/ThreadTagChips'
import type { RollBootstrapThread, RollPoolReason } from '../../../types/rollBootstrap'
import type { IssueCardsResponse } from '../../../generated/nativeV2Client'

interface ThreadPoolProps {
  pool: RollBootstrapThread[]
  dieSize?: number
  isRatingView: boolean
  selectedThreadId: number | null
  /**
   * Minimal empty-pool explanation from the same Option E inputs. It never
   * carries a list or whole-library report, only why the dice have no faces.
   */
  emptyPoolReason?: RollPoolReason
  snoozedThreads: Array<{ id: number; title: string; format: string }>
  snoozedCount?: number
  snoozedExpanded: boolean
  onThreadClick: (thread: RollBootstrapThread) => void
  onUnsnooze: (threadId: number) => void
  onToggleSnoozed: () => void
  onShuffle: () => void
  unsnoozeIsPending: boolean
  shuffleIsPending: boolean
  eligibleThreadIds?: number[] | null
  issueCards?: IssueCardsResponse | null
}

export function ThreadPool({
  pool,
  dieSize,
  isRatingView,
  selectedThreadId,
  emptyPoolReason,
  snoozedThreads,
  snoozedCount,
  snoozedExpanded,
  onThreadClick,
  onUnsnooze,
  onToggleSnoozed,
  onShuffle,
  unsnoozeIsPending,
  shuffleIsPending,
  eligibleThreadIds,
  issueCards,
}: ThreadPoolProps) {
  const navigate = useNavigate()
  const wasRatingView = useRef(isRatingView)
  const snoozedTotal = snoozedCount ?? snoozedThreads.length
  const cardIssueById = new Map((issueCards?.items ?? []).map((card) => [card.issue_id, card.issue_number]))
  // An explicitly empty scoped result means zero eligible faces, not a bootstrap fallback.
  const displayPool = eligibleThreadIds != null
    ? [...pool].sort((a, b) => {
        const rankA = eligibleThreadIds.indexOf(a.id)
        const rankB = eligibleThreadIds.indexOf(b.id)
        return (rankA === -1 ? Number.MAX_SAFE_INTEGER : rankA) - (rankB === -1 ? Number.MAX_SAFE_INTEGER : rankB)
      }).filter((thread) => eligibleThreadIds.includes(thread.id))
    : pool

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
          <p className="text-[10px] font-black uppercase tracking-wider text-stone-300">{displayPool.length} in play</p>
          {dieSize && displayPool.length > 0 && displayPool.length < dieSize && (
            <p className="text-[10px] text-stone-500 mt-1" data-smaller-than-die>
              Only {displayPool.length} of d{dieSize} faces are mapped to an in-play series — the roll picks among these visible faces.
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onShuffle}
          disabled={shuffleIsPending || displayPool.length < 2}
          aria-describedby="shuffle-queue-description"
          className="h-8 px-3 rounded-lg border border-[var(--theme-danger)]/40 bg-[var(--theme-danger)]/10 text-[10px] font-black uppercase tracking-widest text-[var(--theme-danger)] hover:bg-[var(--theme-danger)]/20 disabled:opacity-50 transition-colors"
        >
          Shuffle queue
        </button>
        <span id="shuffle-queue-description" className="sr-only">Randomizes the complete active queue, then refreshes these die mappings.</span>
      </div>}

      {!isRatingView && <div className="space-y-2" data-roll-pool aria-label={`${displayPool.length} in play, ${displayPool.length} mapped result${displayPool.length === 1 ? '' : 's'}`}>
        {displayPool.length === 0 && emptyPoolReason === 'all_blocked' ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">🔒</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
                Series are waiting on earlier issues
              </p>
              <p className="text-xs text-stone-500 mt-1">
                Your in-play series are blocked by an earlier issue. Check your queue to see what needs to be read to unlock the dice.
              </p>
            </div>
            <button
              onClick={() => navigate('/queue')}
              className="w-full h-11 min-h-[44px] bg-[var(--theme-comic-accent)]/10 hover:bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)]/20 rounded-xl text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors"
            >
              Go to Queue
            </button>
          </div>
        ) : displayPool.length === 0 && emptyPoolReason === 'all_completed' ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">📚</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
                Every series is completed
              </p>
              <p className="text-xs text-stone-500 mt-1">
                You&apos;ve read every issue in your queue. Add a new series to keep rolling.
              </p>
            </div>
            <button
              onClick={() => navigate('/queue', { state: { openCreate: true } })}
              className="w-full h-11 min-h-[44px] bg-[var(--theme-comic-accent)]/10 hover:bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)]/20 rounded-xl text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors"
            >
              + Add a Series
            </button>
          </div>
        ) : displayPool.length === 0 && emptyPoolReason === 'all_out_of_pool' ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">📚</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
                No series are in play
              </p>
              <p className="text-xs text-stone-500 mt-1">
                Your unread issues are not in the active queue or are excluded from the pool. Check your queue to put them back in play.
              </p>
            </div>
            <button
              onClick={() => navigate('/queue')}
              className="w-full h-11 min-h-[44px] bg-[var(--theme-comic-accent)]/10 hover:bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)]/20 rounded-xl text-xs font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors"
            >
              Go to Queue
            </button>
          </div>
        ) : displayPool.length === 0 && (snoozedTotal === 0 || emptyPoolReason === 'no_series') ? (
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
        ) : displayPool.length === 0 && snoozedTotal > 0 ? (
          <div className="text-center py-6 space-y-4">
            <div className="text-4xl">🔒</div>
            <div>
              <p className="text-sm text-stone-300 font-bold uppercase tracking-widest">
                Every series is snoozed
              </p>
              <p className="text-xs text-stone-500 mt-1">
                Reset Dice or visit your queue to choose what to read next.
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
          displayPool.map((thread, index) => {
            const isSelected = selectedThreadId && Number(selectedThreadId) === thread.id
            const routeLabels = (thread.route_labels ?? []).filter(Boolean)
            const tags = thread.tags ?? []
            const tagNames = tags.map((tag) => tag.name)
            const cardIssueNumber = thread.issue_id != null ? cardIssueById.get(thread.issue_id) : undefined
            const issueNumber = thread.issue_number ?? cardIssueNumber
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
                aria-label={`Die face ${index + 1}: ${thread.title}${issueNumber ? `, issue ${issueNumber}` : ''}${tagNames.length ? `, tagged ${tagNames.join(', ')}` : ''}${routeLabels.length ? `, connected to ${routeLabels.join(', ')}` : ''}${(thread.overflow_routes_count ?? 0) > 0 ? `, ${thread.overflow_routes_count} more connected routes` : ''}. Open series actions.`}
                className={`flex items-center gap-3 px-4 py-3 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl group transition-all cursor-pointer hover:bg-white/10 ${isSelected ? 'pool-thread-selected border-[var(--theme-comic-accent)]/30' : ''
                  }`}
              >
                <span className="text-lg font-black text-stone-500/50 group-hover:text-stone-400/50 transition-colors w-6 text-center">
                  {index + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-stone-200 truncate text-sm">{thread.title}</p>
                  <p className="truncate text-xs text-stone-400">
                    {issueNumber ? `#${issueNumber}` : 'Next unread issue'}
                  </p>
                  <p className="text-[10px] font-black text-stone-500 uppercase tracking-widest mt-0.5">{thread.format}</p>
                  <ThreadTagChips
                    tags={tags}
                    label={`Tags for ${thread.title}`}
                    className="mt-1"
                  />
                  {routeLabels.length || (thread.overflow_routes_count ?? 0) > 0 ? (
                    <p className="mt-1 truncate text-[10px] text-[var(--theme-continuity-accent)]">
                      Connected to: {routeLabels.join(' · ')}{routeLabels.length && (thread.overflow_routes_count ?? 0) > 0 ? ' · ' : ''}{(thread.overflow_routes_count ?? 0) > 0 ? `+${thread.overflow_routes_count} more` : ''}
                    </p>
                  ) : null}
                </div>
              </div>
            )
          })
        )}
      </div>}

      {snoozedThreads && snoozedTotal > 0 && !isRatingView && (
        <div className="mt-4 md:mt-8">
          <button
            type="button"
            onClick={onToggleSnoozed}
            aria-expanded={snoozedExpanded}
            className="w-full px-4 py-2 bg-stone-500/5 border border-stone-500/10 rounded-xl flex items-center gap-2 hover:bg-stone-500/10 transition-colors"
          >
            <span
              className={`text-stone-400 text-xs transition-transform ${snoozedExpanded ? 'rotate-90' : ''}`}
            >
              ▶
            </span>
            <span className="text-[10px] font-black text-stone-400 uppercase tracking-widest cursor-help border-b border-dashed border-stone-600">
              Snoozed ({snoozedTotal})
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


    </div>
  )
}
