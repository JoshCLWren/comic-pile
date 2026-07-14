import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { ReactNode } from 'react'

/** Threshold above which the queue switches from a plain grid to a virtualized list. */
export const VIRTUALIZATION_THRESHOLD = 50

interface VirtualizedThreadListProps<T> {
  /** Threads to render in the virtualized list. */
  threads: T[]
  /**
   * Render-prop called for each visible virtual item.
   * @param thread — the thread at the current virtual index
   * @param index — the virtual array index (not the DB id)
   */
  renderItem: (thread: T, index: number) => ReactNode
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
  renderItem,
}: VirtualizedThreadListProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [containerHeight, setContainerHeight] = useState(0)

  // Read the initial wrapper height synchronously to avoid a
  // 0 → measured layout jump on mount (🔴 council finding #1).
  useLayoutEffect(() => {
    if (wrapperRef.current) {
      setContainerHeight(wrapperRef.current.offsetHeight)
    }
  }, [])

  // Reactive container height via ResizeObserver, throttled with
  // requestAnimationFrame to prevent layout thrashing (🟠 finding #4).
  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return

    let rafId: number | null = null

    const observer = new ResizeObserver((entries) => {
      if (rafId !== null) return
      rafId = requestAnimationFrame(() => {
        rafId = null
        for (const entry of entries) {
          setContainerHeight(entry.contentRect.height)
        }
      })
    })

    observer.observe(wrapper)
    return () => {
      observer.disconnect()
      if (rafId !== null) {
        cancelAnimationFrame(rafId)
      }
    }
  }, [])

  // Memoize virtualizer options to avoid unnecessary setOptions()
  // calls on every render (🟡 finding #8).
  const virtualizerOptions = useMemo(
    () => ({
      count: threads.length,
      getScrollElement: () => scrollRef.current,
      estimateSize: () => 160,
      overscan: 10, // bumped from 4 (🔴 council finding #2)
    }),
    [threads.length],
  )

  const virtualizer = useVirtualizer(virtualizerOptions)

  // Empty state guard (🟠 finding #3)
  if (threads.length === 0) {
    return (
      <div
        data-testid="queue-thread-list"
        id="queue-container"
        role="list"
        aria-label="Thread queue"
        className="flex items-center justify-center text-stone-500 py-8"
      >
        No threads in queue
      </div>
    )
  }

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
              {renderItem(threads[virtualItem.index], virtualItem.index)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
