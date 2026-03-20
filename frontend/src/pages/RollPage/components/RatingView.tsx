import type { KeyboardEvent } from 'react'
import LazyDice3D from '../../../components/LazyDice3D'
import Tooltip from '../../../components/Tooltip'
import { RATING_THRESHOLD, getProgressPercentage } from '../utils'
import type { RatingThread } from '../types'

interface RatingViewProps {
  activeRatingThread: RatingThread | null
  currentDie: number
  rolledResult: number | null
  rating: number
  predictedDie: number
  hasValidRolledResult: boolean
  ratingThreadVisualPosition: number | null
  poolSize: number
  errorMessage: string
  rateIsPending: boolean
  snoozeIsPending: boolean
  dismissIsPending: boolean
  onUpdateRating: (value: string) => void
  onSubmitRating: (finishSession: boolean) => void
  onSnooze: () => void
  onCancel: () => void
}

export function RatingView({
  activeRatingThread,
  currentDie,
  rolledResult,
  rating,
  predictedDie,
  hasValidRolledResult,
  ratingThreadVisualPosition,
  poolSize,
  errorMessage,
  rateIsPending,
  snoozeIsPending,
  dismissIsPending,
  onUpdateRating,
  onSubmitRating,
  onSnooze,
  onCancel,
}: RatingViewProps) {
  return (
    <div className="p-4 space-y-8 relative z-10">
      <div id="thread-info" role="status" aria-live="polite">
        <div className="space-y-3 text-center">
          {activeRatingThread?.issue_number ? (
            <>
              <h2 className="text-2xl font-black text-stone-200">{activeRatingThread?.title || 'Loading...'}</h2>
              <div className="flex items-center justify-center gap-3 flex-wrap">
                <span className="bg-amber-500/20 text-amber-300 px-3 py-1 rounded-lg text-sm font-black uppercase tracking-[0.2em] border border-amber-500/20">
                  #{activeRatingThread.issue_number}
                </span>
                {activeRatingThread.total_issues && (
                  <span className="text-stone-400 text-xs font-bold">
                    (#{activeRatingThread.issue_number} of {activeRatingThread.total_issues})
                  </span>
                )}
                <span className="bg-amber-600/20 text-amber-400 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-amber-600/20">
                  Queue #{ratingThreadVisualPosition ?? '-'}
                </span>
              </div>
            </>
          ) : (
            <>
              <h2 className="text-2xl font-black text-stone-200">{activeRatingThread?.title || 'Loading...'}</h2>
              <div className="flex items-center justify-center gap-3">
                <span className="bg-amber-600/20 text-amber-400 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-amber-600/20">
                  Queue #{ratingThreadVisualPosition ?? '-'}
                </span>
                <span className="bg-red-800/20 text-red-600 px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-[0.2em] border border-red-800/20">
                  {activeRatingThread?.format || '...'}
                </span>
                <span className="text-stone-500 text-xs font-bold">{activeRatingThread?.issues_remaining || 0} Issues left</span>
              </div>
            </>
          )}
          {activeRatingThread?.reading_progress && activeRatingThread?.total_issues && (
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
                {activeRatingThread.reading_progress === 'completed' ? 'Completed' : 'In Progress'}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-8">
        <div id="rating-preview-dice" className="dice-perspective">
          <div
            id="die-preview-wrapper"
            className="dice-state-rate-flow relative flex items-center justify-center"
            style={{ width: '120px', height: '120px', margin: '0 auto' }}
          >
            <LazyDice3D
              sides={currentDie}
              value={rolledResult || 1}
              isRolling={false}
              showValue={false}
              freeze
              color={0xffffff}
            />
          </div>
          {hasValidRolledResult && (
            <div className="mt-6 text-center space-y-1">
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
          <Tooltip content={`Ratings of ${RATING_THRESHOLD.toFixed(1)}+ move the thread to the front and step the die down. Lower ratings move it back and step the die up.`}>
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
              : `Okay. Die steps up 🎲 Move to back${predictedDie !== currentDie ? ` (d${predictedDie})` : ''}`}
          </p>
        </div>

        {activeRatingThread?.issues_remaining === 1 && (
          <div className="p-3 rounded-xl bg-amber-600/10 border border-amber-600/20 text-center">
            <p className="text-[10px] font-black uppercase tracking-[0.15em] text-amber-500">
              🎉 This is the last issue!
            </p>
          </div>
        )}

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => onSubmitRating(false)}
              disabled={rateIsPending}
              className="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
            >
              {rateIsPending ? 'Saving...' : (activeRatingThread?.issues_remaining === 1 ? 'Save & Complete' : 'Save & Continue')}
            </button>
            <button
              type="button"
              onClick={() => onSubmitRating(true)}
              disabled={rateIsPending}
              className="w-full py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
            >
              Finish Session
            </button>
          </div>
          <button
            type="button"
            onClick={onSnooze}
            disabled={snoozeIsPending}
            className="w-full py-4 glass-button text-sm font-black uppercase tracking-[0.2em] relative shadow-[0_15px_40px_rgba(20,184,166,0.3)] disabled:opacity-50"
          >
            {snoozeIsPending ? 'Snoozing...' : 'Snooze'}
          </button>
          <div className="flex justify-center">
            <button
              type="button"
              onClick={onCancel}
              disabled={dismissIsPending}
              className="px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-stone-500 hover:text-stone-300 hover:bg-white/5 border border-transparent hover:border-white/10 rounded-lg transition-all disabled:opacity-50"
            >
              Cancel Pending Roll
            </button>
          </div>
        </div>

        {errorMessage && (
          <div id="error-message" className="text-[10px] text-rose-500 text-center font-bold">
            {errorMessage}
          </div>
        )}
      </div>
    </div>
  )
}