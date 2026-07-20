import { useState, useRef, useEffect, type TouchEvent, type ReactNode } from 'react'

interface SwipeableProps {
  children: ReactNode
  actions: Array<{
    icon: string
    label: string
    onClick: () => void
    color: string
  }>
  onCardClick: () => void
  className?: string
  'data-testid'?: string
}

export default function Swipeable({
  children,
  actions,
  onCardClick,
  className = '',
  'data-testid': testId,
}: SwipeableProps) {
  const [offset, setOffset] = useState(0)
  const [isSwiping, setIsSwiping] = useState(false)
  const startXRef = useRef(0)
  const startYRef = useRef(0)
  const startOffsetRef = useRef(0)
  const isHorizontalRef = useRef<boolean | null>(null)
  const ACTION_WIDTH = 192
  const swipeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const SWIPE_THRESHOLD = 64

  // Clear any pending swipe state timeout on unmount to prevent React 19
  // from accessing a torn-down `window` in its update-priority resolution
  // (the "ReferenceError: window is not defined" flake in tests).
  useEffect(() => {
    return () => {
      if (swipeTimeoutRef.current !== null) {
        clearTimeout(swipeTimeoutRef.current)
        swipeTimeoutRef.current = null
      }
    }
  }, [])

  const DIRECTION_LOCK_THRESHOLD = 12

  function handleTouchStart(e: TouchEvent) {
    const touch = e.touches[0]
    startXRef.current = touch.clientX
    startYRef.current = touch.clientY
    startOffsetRef.current = offset
    isHorizontalRef.current = null
    setIsSwiping(false)
    // Clear any pending swipe-end timeout so a rapid re-touch within 50ms
    // doesn't fire mid-gesture and incorrectly set isSwiping to false.
    if (swipeTimeoutRef.current !== null) {
      clearTimeout(swipeTimeoutRef.current)
      swipeTimeoutRef.current = null
    }
  }

  function handleTouchMove(e: TouchEvent) {
    const touch = e.touches[0]
    const dx = touch.clientX - startXRef.current
    const dy = touch.clientY - startYRef.current

    if (isHorizontalRef.current === null) {
      if (Math.abs(dx) < DIRECTION_LOCK_THRESHOLD && Math.abs(dy) < DIRECTION_LOCK_THRESHOLD) return
      isHorizontalRef.current = Math.abs(dx) > Math.abs(dy)
    }

    if (!isHorizontalRef.current) return

    const raw = startOffsetRef.current + dx
    const clamped = Math.max(-ACTION_WIDTH, Math.min(0, raw))
    setOffset(clamped)
    setIsSwiping(true)
  }

  function handleTouchEnd() {
    if (offset <= -SWIPE_THRESHOLD) {
      setOffset(-ACTION_WIDTH)
    } else {
      setOffset(0)
    }
    if (swipeTimeoutRef.current !== null) {
      clearTimeout(swipeTimeoutRef.current)
    }
    swipeTimeoutRef.current = setTimeout(() => {
      swipeTimeoutRef.current = null
      setIsSwiping(false)
    }, 50)
  }

  function handleCardClick() {
    if (isSwiping) return
    if (offset < 0) {
      setOffset(0)
      return
    }
    onCardClick()
  }

  return (
    <div className={`relative overflow-hidden ${className}`} data-testid={testId}>
      <div className="absolute right-0 top-0 bottom-0 flex items-center gap-1 px-2 z-0">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setOffset(0)
              action.onClick()
            }}
            className={`flex flex-col items-center justify-center w-12 h-full ${action.color} transition-colors`}
            aria-label={action.label}
          >
            <span className="text-lg">{action.icon}</span>
            <span className="text-[8px] font-black uppercase tracking-wider mt-0.5">{action.label}</span>
          </button>
        ))}
      </div>
      <div
        className="relative z-10 h-full bg-[#1a1410] transition-transform"
        style={{
          transform: `translateX(${offset}px)`,
          transitionDuration: isSwiping ? '0ms' : '200ms',
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={handleCardClick}
      >
        {children}
      </div>
    </div>
  )
}
