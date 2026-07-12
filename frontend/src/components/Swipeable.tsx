import { useState, useRef, type TouchEvent, type ReactNode } from 'react'

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
  const SWIPE_THRESHOLD = 48

  function handleTouchStart(e: TouchEvent) {
    const touch = e.touches[0]
    startXRef.current = touch.clientX
    startYRef.current = touch.clientY
    startOffsetRef.current = offset
    isHorizontalRef.current = null
    setIsSwiping(false)
  }

  function handleTouchMove(e: TouchEvent) {
    const touch = e.touches[0]
    const dx = touch.clientX - startXRef.current
    const dy = touch.clientY - startYRef.current

    if (isHorizontalRef.current === null) {
      if (Math.abs(dx) < 5 && Math.abs(dy) < 5) return
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
    setTimeout(() => setIsSwiping(false), 50)
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
        className="relative z-10 bg-[#1a1410] transition-transform"
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
