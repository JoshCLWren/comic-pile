import type { KeyboardEvent } from 'react'
import { useState } from 'react'
import LazyDice3D from '../../../components/LazyDice3D'
import { isDiceSide } from '../../../components/diceTypes'
import Tooltip from '../../../components/Tooltip'
import IssueCorrectionDialog from '../../../components/IssueCorrectionDialog'
import { RATING_THRESHOLD, getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type { ConnectedThreadInfo } from '../../../types'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult: boolean
  poolSize: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
  onRefreshThread: () => void
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  hasValidRolledResult,
  poolSize,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  readingOrders,
  connectedThreads,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
  onRefreshThread,
}: RatingViewProps) {
  const [isCorrectionDialogOpen, setIsCorrectionDialogOpen] = useState(false)
  const previewDie = isDiceSide(currentDie) ? currentDie : 6
  const threadTitle = activeRatingThread?.title ?? 'Loading...'
  const issueNumber = activeRatingThread?.next_issue_number ?? activeRatingThread?.issue_number ?? null
  const totalIssues = activeRatingThread?.total_issues ?? null
  const issuesRemaining = activeRatingThread?.issues_remaining ?? 0
  const readingProgress = activeRatingThread?.reading_progress ?? null

  return (
    <div className="p-3 md:p-4 space-y-5 md:space-y-8 relative z-10">
      <div id="thread-info" role="status" aria-live="polite">
        <div className="space-y-2 md:space-y-3 text-center">
      <>
        <h2 className="text-xl md:text-2xl font-black text-stone-200 truncate">
          {threadTitle}
          {issueNumber != null && (
            <span className="text-stone-400"> #{issueNumber}</span>
          )}
        </h2>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          {issueNumber != null && (
            <button
              type="button"
              onClick={() => setIsCorrectionDialogOpen(true)}
              disabled={!activeRatingThread?.id}
              className="w-11 h-11 min-w-[44px] flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-stone-400 hover:text-stone-300 transition-all disabled:opacity-30 disabled:cursor-not-allowed focus:ring-2 focus:ring-amber-500"
              aria-label="Correct issue number"
              title="Correct issue number"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                <path d="M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z" />
              </svg>
            </button>
          )}
          {totalIssues && issueNumber != null && (
            <span className="text-stone-400 text-xs font-bold">
              (#{issueNumber} of {totalIssues})
            </span>
          )}
          {!issueNumber && (
            <span className="bg-red-800/20 text-red-600 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-red-800/20">
              {activeRatingThread?.format || '...'}
            </span>
          )}
        </div>
        <div className="flex items-center justify-center gap-2 flex-wrap">
          <span className="text-stone-400 text-xs font-bold">
            {getProgressPercentage(activeRatingThread)}% complete
          </span>
          <span className="text-stone-600">·</span>
          <span className="text-stone-500 text-xs font-bold">{issuesRemaining} issues left</span>
        </div>
        {hasValidRolledResult && (
          <div className="flex items-center justify-center">
            <span className="bg-amber-600/20 text-amber-400 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-amber-600/20">
              You rolled a {rolledResult}!
            </span>
          </div>
        )}
      </>
          {readingProgress && totalIssues && (
            <div className="reading-progress max-w-md mx-auto">
              <div className="h-3 bg-white/10 rounded-full overflow-hidden">
                <div
                  className="h-full bg-amber-600 transition-all duration-300"
                  style={{
                    width: `${getProgressPercentage(activeRatingThread)}%`
                  }}
                />
              </div>
              <span className="mt-1 block text-[10px] text-stone-400 font-bold uppercase tracking-wider">
                {readingProgress === 'completed' ? 'Completed' : 'In Progress'}
              </span>
            </div>
          )}
        </div>
      </div>

      {connectedThreads.length > 0 && (
        <div className="text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-900/20 border border-blue-700/30 rounded-lg">
            <span className="text-[10px] font-black uppercase tracking-wider text-blue-400">Connected</span>
            <Tooltip content={`This thread is linked to ${connectedThreads.length} other thread${connectedThreads.length !== 1 ? 's' : ''} via dependencies.`}>
              <span tabIndex={0} className="text-[9px] text-blue-500 cursor-help border-b border-dashed border-blue-800">
                {connectedThreads.map((ct, i) => (
                  <span key={ct.thread_id}>
                    {i > 0 && ', '}
                    {ct.title}
                  </span>
                ))}
              </span>
            </Tooltip>
          </div>
        </div>
      )}

      <div className="space-y-5 md:space-y-8">
        <div id="rating-preview-dice" className="dice-perspective">
          <div
            id="die-preview-wrapper"
            className="dice-state-rate-flow relative flex items-center justify-center w-[96px] h-[96px] md:w-[120px] md:h-[120px] mx-auto"
          >
            <LazyDice3D
              sides={previewDie}
              value={rolledResult || 1}
              isRolling={false}
              showValue={false}
              freeze
              color={0xffffff}
            />
          </div>
          {hasValidRolledResult && (
            <div className="mt-3 md:mt-6 text-center space-y-1">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-stone-400">
                Rolled {rolledResult} on d{currentDie}
              </p>
              {currentDie > poolSize && (
                <p
                  className="text-[9px] font-bold uppercase tracking-wider text-amber-500/80"
                  data-pool-size-info
                >
                  pool size: {poolSize}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="text-center space-y-4">
          <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the thread to the front and step the die down. Lower ratings move it past the next roll range and step the die up.`}>
            <p className="text-[10px] font-black uppercase tracking-[0.4em] text-stone-500 cursor-help">How was it?</p>
          </Tooltip>
          <div id="rating-value" className={`text-4xl font-black ${rating >= RATING_THRESHOLD ? 'text-amber-500' : 'text-red-700'}`}>
            {rating.toFixed(1)}
          </div>
          <input
            type="range"
            id="rating-input"
            name="rating"
            min="0.5"
            max="5.0"
            step="0.5"
            value={rating}
            className="w-full h-4"
            aria-label="Rating from 0.5 to 5.0 in steps of 0.5"
            onChange={(e) => onUpdateRating(e.target.value)}
          />
        </div>

        <div
          className={`p-4 rounded-3xl border shadow-xl ${rating >= RATING_THRESHOLD
            ? 'bg-amber-600/5 border-amber-600/20'
            : 'bg-red-800/5 border-red-800/20'
            }`}
        >
          <p id="queue-effect" className="text-[10px] font-black text-stone-300 text-center uppercase tracking-[0.15em] leading-relaxed">
            {rating >= RATING_THRESHOLD
              ? `Excellent! Die steps down 🎲 Move to front${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`
              : `Okay. Die steps up 🎲 Move past next roll range${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`}
          </p>
        </div>

        {activeRatingThread?.issues_remaining === 1 && (
          <div className="p-3 rounded-xl bg-amber-600/10 border border-amber-600/20 text-center">
            <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
              🎉 This is the last issue!
            </p>
          </div>
        )}

        <div
          className="rating-actions relative -mx-3 md:-mx-4 px-3 md:px-4 pt-4 pb-3 bg-gradient-to-t from-[#1a1410] via-[#1a1410]/95 to-transparent z-20 space-y-2 md:space-y-3"
          data-testid="rating-actions"
        >
          <button
            type="button"
            onClick={() => onSubmitRating(false)}
            disabled={rateIsPending}
            data-testid="save-and-continue"
            className="w-full py-3.5 md:py-4 bg-amber-600/25 hover:bg-amber-600/35 border border-amber-600/50 rounded-xl text-xs font-black uppercase tracking-[0.15em] md:tracking-[0.2em] transition-all disabled:opacity-50 active:scale-[0.98]"
          >
            {rateIsPending ? 'Saving...' : (issuesRemaining === 1 ? 'Save & Complete' : 'Save & Continue')}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSnooze}
              disabled={snoozeIsPending}
              className="flex-1 py-3 md:py-4 glass-button text-sm font-black uppercase tracking-[0.2em] shadow-[0_15px_40px_rgba(20,184,166,0.3)] disabled:opacity-50 active:scale-[0.98] rounded-xl"
            >
              {snoozeIsPending ? 'Snoozing...' : 'Snooze'}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={dismissIsPending}
              className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 bg-white/5 border border-white/10 rounded-xl transition-all disabled:opacity-50 active:scale-[0.98]"
            >
              Cancel
            </button>
          </div>
        </div>

        {errorMessage && (
          <div id="error-message" className="text-[10px] text-rose-500 text-center font-bold">
            {errorMessage}
          </div>
        )}
      </div>

      {readingOrders.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-stone-500 text-center">Reading Orders</h3>
          <div className="space-y-2">
            {readingOrders.map((order) => (
              <div key={order.id} className="bg-white/5 border border-white/10 rounded-xl p-3">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-bold text-stone-300 truncate">{order.name}</h4>
                  <span className="text-[10px] text-stone-500 font-bold shrink-0 ml-2">
                    {order.completed_items}/{order.total_items}
                  </span>
                </div>
                {order.description && (
                  <p className="text-[10px] text-stone-500 mb-2">{order.description}</p>
                )}
                <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-amber-600 transition-all duration-300 rounded-full"
                    style={{
                      width: `${order.total_items > 0 ? Math.round((order.completed_items / order.total_items) * 100) : 0}%`
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeRatingThread && (
        <IssueCorrectionDialog
          isOpen={isCorrectionDialogOpen}
          threadId={activeRatingThread.id}
          currentIssueNumber={activeRatingThread.next_issue_number ?? activeRatingThread.issue_number}
          totalIssues={activeRatingThread.total_issues}
          threadTitle={activeRatingThread.title}
          onClose={() => setIsCorrectionDialogOpen(false)}
          onSuccess={() => {
            setIsCorrectionDialogOpen(false)
            onRefreshThread()
          }}
        />
      )}
    </div>
  )
}
