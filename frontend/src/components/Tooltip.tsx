import { useState, type PropsWithChildren } from 'react'

interface TooltipProps {
  content: string
}

/**
 * A tooltip component that displays additional information on hover/focus.
 *
 */
export default function Tooltip({ children, content }: PropsWithChildren<TooltipProps>) {
  const [isVisible, setIsVisible] = useState(false)

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
      onFocus={() => setIsVisible(true)}
      onBlur={() => setIsVisible(false)}
    >
      {children}
      {isVisible && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] text-[10px] rounded-lg shadow-xl border border-[var(--theme-border)] z-50">
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 rotate-45 w-2 h-2 bg-[var(--theme-bg-panel)] border-r border-b border-[var(--theme-border)]"></div>
          {content}
        </div>
      )}
    </div>
  )
}
