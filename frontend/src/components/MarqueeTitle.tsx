import { useRef, useState, useLayoutEffect } from 'react'

interface MarqueeTitleProps {
  title: string
  className?: string
}

export function MarqueeTitle({ title, className = '' }: MarqueeTitleProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const h3Ref = useRef<HTMLHeadingElement>(null)
  const [overflows, setOverflows] = useState(false)

  useLayoutEffect(() => {
    const checkOverflow = () => {
      const container = containerRef.current
      const h3 = h3Ref.current
      if (!container || !h3) return
      setOverflows(h3.scrollWidth > container.clientWidth)
    }
    checkOverflow()

    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(checkOverflow)
    if (containerRef.current) ro.observe(containerRef.current)
    if (h3Ref.current) ro.observe(h3Ref.current)

    return () => ro.disconnect()
  }, [title])

  return (
    <div ref={containerRef} className="overflow-hidden flex-1 whitespace-nowrap">
      <h3
        ref={h3Ref}
        className={`text-lg font-bold text-white ${overflows ? 'inline-block marquee-runner' : 'truncate'} ${className}`}
      >
        <span>{title}</span>
        {overflows && <span className="ml-8" aria-hidden="true">{title}</span>}
      </h3>
    </div>
  )
}
