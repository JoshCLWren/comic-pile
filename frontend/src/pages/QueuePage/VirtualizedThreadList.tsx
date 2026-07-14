import { useEffect, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { ReactNode } from 'react'

interface VirtualizedThreadListProps<T> {
  /** Threads to render in the virtualized list */
  threads: T[]
  /**
   * Render-prop for each thread.
   * The caller provides the full `<QueueThreadCard>` with all handlers bound.
   */
  children: (thread: T, index: number) => ReactNode
}

/**
 * Single-column virtualized list for large queues (>50 threads).
 *
 * Uses `@tanstack/react-virtual` with `useVirtualizer` for efficient
 * DOM virtualization. Container height is derived from a `ResizeObserver`
 * on the wrapper element — **never** `window.innerHeight` during render
 * (non-reactive to resize/orientation).
 *
 * Preserves existing selectors (`data-testid="queue-thread-list"`,
 * `id="queue-container"`, `role="list"`, `aria-label="Thread queue"`)
 * for E2E compatibility.
 */
export default function VirtualizedThreadList<T>({
  threads,
  children,
}: VirtualizedThreadListProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [containerHeight, setContainerHeight] = useState(0)

  // Reactive container height via ResizeObserver
  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height)
      }
    })

    observer.observe(wrapper)
    return () => observer.disconnect()
  }, [])

  const virtualizer = useVirtualizer({
    count: threads.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 160,
    overscan: 4,
    measureElement: (element) =>
      element.getBoundingClientRect().height,
  })

  return (
    <div ref={wrapperRef} className="flex-1 min-h-0">
      <div
        ref={scrollRef}
        data-testid="queue-thread-list"
        id="queue-container"
        role="list"
        aria-label="Thread queue"
        style={{
          height: containerHeight || 600,
          overflowY: 'auto',
        }}
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            position: 'relative',
            width: '100%',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualItem) => (
            <div
              key={virtualItem.key}
              data-index={virtualItem.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualItem.start}px)`,
              }}
            >
              {children(threads[virtualItem.index], virtualItem.index)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
