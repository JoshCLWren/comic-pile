import { useState, useMemo } from 'react'

/**
 * A visual position slider for repositioning threads in the queue.
 *
 * @param {Object} props - Component props
 * @param {Array} props.threads - Array of all threads with {id, title, queue_position}
 * @param {Object} props.currentThread - The thread being repositioned
 * @param {Function} props.onPositionSelect - Callback when position is confirmed
 * @param {Function} props.onCancel - Callback to close without selecting
 * @returns {JSX.Element} The position slider component
 */
export default function PositionSlider({ threads, currentThread, onPositionSelect, onCancel }) {
  const sortedThreads = useMemo(() => {
    return [...threads].sort((a, b) => a.queue_position - b.queue_position)
  }, [threads])

  const currentIndex = useMemo(() => {
    return sortedThreads.findIndex((t) => t.id === currentThread.id)
  }, [sortedThreads, currentThread])

  const [sliderValue, setSliderValue] = useState(currentIndex)

  const maxPosition = sortedThreads.length - 1

  // Get context threads (2-3 above and below current slider position)
  const contextThreads = useMemo(() => {
    const contextRange = 2
    const start = Math.max(0, sliderValue - contextRange)
    const end = Math.min(sortedThreads.length - 1, sliderValue + contextRange)

    return sortedThreads.slice(start, end + 1).map((thread, idx) => ({
      ...thread,
      displayIndex: start + idx,
    }))
  }, [sortedThreads, sliderValue])

  // Determine position context message
  const positionContext = useMemo(() => {
    if (sliderValue === currentIndex) {
      return 'Current position (no change)'
    }

    if (sliderValue === 0) {
      return 'Move to front of queue'
    }

    if (sliderValue === maxPosition) {
      return 'Move to back of queue'
    }

    const threadAbove = sortedThreads[sliderValue - 1]
    const threadBelow = sortedThreads[sliderValue]

    // If moving to a position occupied by another thread
    if (threadBelow && threadBelow.id !== currentThread.id) {
      if (threadAbove && threadAbove.id !== currentThread.id) {
        return `Between "${truncate(threadAbove.title)}" and "${truncate(threadBelow.title)}"`
      }
      return `Before "${truncate(threadBelow.title)}"`
    }

    if (threadAbove && threadAbove.id !== currentThread.id) {
      return `After "${truncate(threadAbove.title)}"`
    }

    return `Position ${sliderValue + 1}`
  }, [sliderValue, currentIndex, maxPosition, sortedThreads, currentThread.id])

  const handleConfirm = () => {
    // Convert slider index to actual queue position
    const targetPosition = sortedThreads[sliderValue].queue_position
    onPositionSelect(targetPosition)
  }

  const truncate = (text, maxLen = 20) => {
    if (text.length <= maxLen) return text
    return text.slice(0, maxLen - 1) + '…'
  }

  return (
    <div className="space-y-6">
      {/* Header with direction labels */}
      <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500">
        <span>Front (Position 1)</span>
        <span>Back (Position {sortedThreads.length})</span>
      </div>

      {/* Slider track */}
      <div className="relative py-4">
        <input
          type="range"
          min={0}
          max={maxPosition}
          value={sliderValue}
          onChange={(e) => setSliderValue(Number(e.target.value))}
          className="w-full h-2 bg-white/10 rounded-full appearance-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-5
            [&::-webkit-slider-thumb]:h-5
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:bg-teal-400
            [&::-webkit-slider-thumb]:shadow-lg
            [&::-webkit-slider-thumb]:shadow-teal-400/30
            [&::-webkit-slider-thumb]:cursor-grab
            [&::-webkit-slider-thumb]:active:cursor-grabbing
            [&::-webkit-slider-thumb]:transition-transform
            [&::-webkit-slider-thumb]:hover:scale-110
            [&::-moz-range-thumb]:w-5
            [&::-moz-range-thumb]:h-5
            [&::-moz-range-thumb]:rounded-full
            [&::-moz-range-thumb]:bg-teal-400
            [&::-moz-range-thumb]:border-0
            [&::-moz-range-thumb]:shadow-lg
            [&::-moz-range-thumb]:shadow-teal-400/30
            [&::-moz-range-thumb]:cursor-grab
            [&::-moz-range-thumb]:active:cursor-grabbing"
        />

        {/* Position marks */}
        <div className="absolute top-1/2 left-0 right-0 -translate-y-1/2 flex justify-between pointer-events-none px-[10px]">
          {sortedThreads.map((thread, idx) => (
            <div
              key={thread.id}
              className={`w-1.5 h-1.5 rounded-full transition-all ${
                idx === sliderValue
                  ? 'bg-teal-400 scale-150'
                  : idx === currentIndex
                    ? 'bg-amber-400'
                    : 'bg-white/30'
              }`}
            />
          ))}
        </div>
      </div>

      {/* Position indicator */}
      <div className="text-center">
        <div className="text-lg font-bold text-white">Position {sliderValue + 1}</div>
        <div className="text-sm text-slate-400 mt-1">{positionContext}</div>
      </div>

      {/* Context threads preview */}
      <div className="space-y-2">
        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Preview</div>
        <div className="glass-card p-3 space-y-1 max-h-48 overflow-y-auto">
          {contextThreads.map((thread) => {
            const isCurrentThread = thread.id === currentThread.id
            const isTargetPosition = thread.displayIndex === sliderValue
            const willBeDisplaced = !isCurrentThread && isTargetPosition && sliderValue !== currentIndex

            return (
              <div
                key={thread.id}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all ${
                  isCurrentThread
                    ? 'bg-teal-400/20 border border-teal-400/40'
                    : isTargetPosition
                      ? 'bg-amber-400/10 border border-amber-400/30'
                      : 'bg-white/5'
                }`}
              >
                <span className="text-[10px] font-bold text-slate-500 w-6">{thread.displayIndex + 1}</span>
                <span
                  className={`text-sm flex-1 truncate ${
                    isCurrentThread ? 'text-teal-300 font-bold' : 'text-slate-300'
                  }`}
                >
                  {thread.title}
                </span>
                {isCurrentThread && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-teal-400">Moving</span>
                )}
                {willBeDisplaced && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-amber-400">
                    {sliderValue < currentIndex ? '+1' : '-1'}
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
          className="flex-1 py-3 bg-white/5 border border-white/10 rounded-xl text-xs font-black uppercase tracking-widest text-slate-400 hover:bg-white/10 transition-all"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={sliderValue === currentIndex}
          className="flex-1 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Confirm
        </button>
      </div>
    </div>
  )
}
