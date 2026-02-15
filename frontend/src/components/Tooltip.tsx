import { useState, ReactNode } from 'react'

interface TooltipProps {
  children: ReactNode
  content: string
}

/**
 * A tooltip component that displays additional information on hover/focus.
 *
 * @param props - Component props
 * @param props.children - The element that triggers the tooltip
 * @param props.content - The text content to display in the tooltip
 * @returns The tooltip wrapper component
 */
export default function Tooltip({ children, content }: TooltipProps) {
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
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 px-3 py-2 bg-slate-900/95 text-slate-200 text-[10px] rounded-lg shadow-xl border border-white/10 z-50">
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 rotate-45 w-2 h-2 bg-slate-900/95 border-r border-b border-white/10"></div>
          {content}
        </div>
      )}
    </div>
  )
}
