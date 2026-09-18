import { useState, useMemo } from 'react'

interface PositionSliderThread {
  id: number
  title: string
  queue_position: number
}

interface PositionSliderProps {
  threads: PositionSliderThread[]
  currentThread: PositionSliderThread
  onPositionSelect: (position: number) => void
  onCancel: () => void
  /**
   * Authoritative number of active threads in the whole queue. When omitted the
   * loaded `threads` length is used, which keeps older callers and tests
   * working. The slider range always spans this total so a thread can be
   * repositioned beyond the currently loaded page (issue #2568).
   */
  queueSize?: number
}

/**
 * A visual position slider for repositioning threads in the queue.
 *
 * The slider spans the authoritative queue size rather than the loaded page,
 * so target positions beyond the fetched slice remain selectable.
 */
export default function PositionSlider({
  threads,
  currentThread,
  onPositionSelect,
  onCancel,
  queueSize,
}: PositionSliderProps) {
  const truncate = (text: string, maxLen = 20): string => {
    if (text.length <= maxLen) return text
    return text.slice(0, maxLen - 1) + '…'
  }
  const sortedThreads = useMemo(() => {
    return [...threads].sort((a, b) => a.queue_position - b.queue_position)
  }, [threads])

  const queueTotal = Math.max(queueSize ?? sortedThreads.length, 0)
  const maxPosition = Math.max(queueTotal - 1, 0)

  // Prefer the authoritative queue position; fall back to the loaded slice for
  // threads whose position is missing or outside the known queue (issue #2568).
  const currentIndex = useMemo(() => {
    const authoritative = currentThread.queue_position - 1
    if (authoritative >= 0 && authoritative <= maxPosition) {
      return authoritative
    }
    return sortedThreads.findIndex((t) => t.id === currentThread.id)
  }, [currentThread, maxPosition, sortedThreads])

  const [sliderValue, setSliderValue] = useState(Math.max(0, currentIndex))
  const clampedValue = Math.min(Math.max(sliderValue, 0), maxPosition)

  const selectedOffset = currentIndex - clampedValue
  const formattedOffset = selectedOffset > 0 ? `+${selectedOffset}` : `${selectedOffset}`

  const threadsByPosition = useMemo(() => {
    return new Map(sortedThreads.map((thread) => [thread.queue_position, thread]))
  }, [sortedThreads])

  // Get context positions (2-3 above and below current slider position).
  // Positions beyond the loaded page render as placeholders rather than being
  // dropped, so the preview still reflects the authoritative queue.
  const contextThreads = useMemo(() => {
    if (queueTotal <= 0) return []
    const contextRange = 2
    const targetPosition = clampedValue + 1
    const start = Math.max(1, targetPosition - contextRange)
    const end = Math.min(queueTotal, targetPosition + contextRange)

    const preview: Array<{ thread: PositionSliderThread | null; position: number }> = []
    for (let position = start; position <= end; position += 1) {
      preview.push({ thread: threadsByPosition.get(position) ?? null, position })
    }
    return preview
  }, [clampedValue, queueTotal, threadsByPosition])

  // Determine position context message
  const positionContext = useMemo(() => {
    if (clampedValue === currentIndex) {
      return 'Current position (no change)'
    }

    if (clampedValue === 0) {
      return 'Move to front of queue'
    }

    if (clampedValue === maxPosition) {
      return 'Move to back of queue'
    }

    const threadAbove = threadsByPosition.get(clampedValue)
    const threadBelow = threadsByPosition.get(clampedValue + 1)

    // If moving to a position occupied by another thread
    if (threadBelow && threadBelow.id !== currentThread.id) {
      if (threadAbove && threadAbove.id !== currentThread.id) {
        return `Between "${truncate(threadAbove.title)}" and "${truncate(threadBelow.title)}"`
      }
      return `Before "${truncate(threadBelow.title)}"`
    }

    return `Position ${clampedValue + 1}`
  }, [clampedValue, currentIndex, maxPosition, threadsByPosition, currentThread.id])

  const handleConfirm = () => {
    // Convert slider index to normalized position (1-based)
    // The UI displays sequential positions (1, 2, 3...) regardless of gaps in queue_position values
    const targetPosition = clampedValue + 1
    onPositionSelect(targetPosition)
  }

  return (
    <div className="space-y-6">
      {/* Header with direction labels */}
      <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest text-stone-500">
        <span>Front (Position 1)</span>
        <span>Back (Position {queueTotal})</span>
      </div>

      {/* Slider track */}
      <div className="relative py-4">
        <input
          type="range"
          min={0}
          max={maxPosition}
          value={clampedValue}
          onChange={(e) => setSliderValue(Number(e.target.value))}
          aria-label={`Position slider: ${clampedValue} of ${maxPosition}`}
          aria-valuemin={0}
          aria-valuemax={maxPosition}
          aria-valuenow={clampedValue}
          aria-valuetext={`Position ${clampedValue === 0 ? 'Front' : clampedValue === maxPosition ? 'Back' : clampedValue}`}
          className="w-full h-2 bg-white/10 rounded-full appearance-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-5
            [&::-webkit-slider-thumb]:h-5
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-amber-500
            [&::-webkit-slider-thumb]:shadow-lg
            [&::-webkit-slider-thumb]:shadow-amber-500/30
            [&::-webkit-slider-thumb]:cursor-grab
            [&::-webkit-slider-thumb]:active:cursor-grabbing
            [&::-webkit-slider-thumb]:transition-transform
            [&::-webkit-slider-thumb]:hover:scale-110
            [&::-moz-range-thumb]:w-5
            [&::-moz-range-thumb]:h-5
            [&::-moz-range-thumb]:rounded-full
            [&::-moz-range-thumb]:bg-amber-500
            [&::-moz-range-thumb]:border-0
            [&::-moz-range-thumb]:shadow-lg
            [&::-moz-range-thumb]:shadow-amber-500/30
            [&::-moz-range-thumb]:cursor-grab
            [&::-moz-range-thumb]:active:cursor-grabbing"
        />

        {/* Position marks positioned against the authoritative queue range */}
        <div className="absolute top-1/2 left-0 right-0 -translate-y-1/2 pointer-events-none px-[10px]">
          <div className="relative h-1.5">
            {sortedThreads.map((thread) => {
              const positionIndex = thread.queue_position - 1
              if (positionIndex < 0 || positionIndex > maxPosition) return null
              const left = maxPosition === 0 ? 0 : (positionIndex / maxPosition) * 100
              return (
                <div
                  key={thread.id}
                  style={{ left: `${left}%` }}
                  className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full transition-all ${
                    positionIndex === clampedValue
                      ? 'bg-amber-500 scale-150'
                      : positionIndex === currentIndex
                        ? 'bg-amber-400'
                        : 'bg-white/30'
                  }`}
                />
              )
            })}
          </div>
        </div>
      </div>

      {/* Position indicator */}
      <div className="text-center">
        <div className="text-lg font-bold text-white">Position {clampedValue + 1}</div>
        <div className="text-sm text-stone-400 mt-1">{positionContext}</div>
      </div>

      {/* Context threads preview */}
      <div className="space-y-2">
        <div className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Preview</div>
        <div className="glass-card p-3 space-y-1 max-h-48 overflow-y-auto">
          {contextThreads.map(({ thread, position }) => {
            const isCurrentThread = thread?.id === currentThread.id
            const isTargetPosition = position - 1 === clampedValue
            const willBeDisplaced = !!thread && !isCurrentThread && isTargetPosition && clampedValue !== currentIndex

            return (
              <div
                key={thread?.id ?? `position-${position}`}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${
                  isCurrentThread
                    ? 'bg-amber-500/20 border border-amber-500/40'
                    : isTargetPosition
                      ? 'bg-amber-400/10 border border-amber-400/30'
                      : 'bg-white/5'
                }`}
              >
                <span className="text-[10px] font-bold text-stone-500 w-6">{position}</span>
                <span
                  className={`text-sm flex-1 truncate ${
                    isCurrentThread
                      ? 'text-amber-400 font-bold'
                      : thread
                        ? 'text-stone-300'
                        : 'text-stone-500 italic'
                  }`}
                >
                  {thread ? thread.title : `Position ${position}`}
                </span>
                {isCurrentThread && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-amber-500">Moving</span>
                )}
                {willBeDisplaced && (
                  <span
                    data-testid="position-slider-offset"
                    className="text-[9px] font-bold uppercase tracking-wider text-amber-400"
                  >
                    {formattedOffset}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={onCancel}
          data-testid="position-slider-cancel"
          className="flex-1 py-3 bg-white/5 border border-white/10 rounded-xl text-xs font-black uppercase tracking-widest text-stone-400 hover:bg-white/10 transition-all"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={clampedValue === currentIndex}
          data-testid="position-slider-confirm"
          className={`flex-1 py-3 bg-white/5 border border-white/10 rounded-xl text-xs font-black uppercase tracking-widest transition-all hover:bg-white/10 ${
            clampedValue === currentIndex
              ? 'opacity-30 cursor-not-allowed'
              : 'opacity-100 cursor-pointer'
          }`}
        >
          Confirm
        </button>
      </div>
    </div>
  )
}
