import type { ReactNode } from 'react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { COL_BREAKPOINTS, getColumnCount } from './VirtualizedThreadList.helpers'

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
  /**
   * Optional explicit column count. When provided, skips the `ResizeObserver`
   * width derivation used in production. Useful for deterministic tests
   * in environments without real layout (e.g. jsdom).
   */
  columnCount?: number
}

/**
 * Responsive multi-column virtualized list for large queues (>50 threads).
 *
 * On mobile (`columnCount === 1`) this keeps the exact single-column rendering
 * path from 583-B: one card per virtual row, absolute-positioned with
 * `data-index` and `translateY`. Existing unit tests continue to pass unchanged.
 *
 * On desktop (`columnCount >= 2`) it virtualizes **rows** of N cards:
 * `count = Math.ceil(threads.length / columnCount)`. Each virtual row renders
 * `columnCount` cards in a CSS grid with `gap-4` (matching the non-virtualized
 * grid's spacing). Vertical gap is achieved via `paddingBottom: '1rem'` on
 * each row, measured by `measureElement`.
 *
 * Column count is derived from a `ResizeObserver` on the scroll container,
 * matching the Tailwind breakpoints. An optional `columnCount` prop can
 * override this for testing.
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
  columnCount: explicitColumnCount,
}: VirtualizedThreadListProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [containerHeight, setContainerHeight] = useState(0)
  const [columnCount, setColumnCount] = useState(() =>
    explicitColumnCount ?? 1,
  )

  // Read the initial wrapper dimensions synchronously to avoid a
  // 0 → measured layout jump on mount.
  useLayoutEffect(() => {
    if (wrapperRef.current) {
      setContainerHeight(wrapperRef.current.offsetHeight)
      if (explicitColumnCount === undefined) {
        setColumnCount(getColumnCount(wrapperRef.current.offsetWidth))
      }
    }
  }, [explicitColumnCount])

  // Keep columnCount in sync when the prop changes externally.
  useEffect(() => {
    if (explicitColumnCount !== undefined) {
      setColumnCount(explicitColumnCount)
    }
  }, [explicitColumnCount])

  // Reactive container height and column count via ResizeObserver,
  // throttled with requestAnimationFrame to prevent layout thrashing.
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
          if (explicitColumnCount === undefined) {
            setColumnCount(getColumnCount(entry.contentRect.width))
          }
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
  }, [explicitColumnCount])

  const rowCount = Math.ceil(threads.length / columnCount)

  // Memoize virtualizer options to avoid unnecessary setOptions()
  // calls on every render.
  const virtualizerOptions = useMemo(
    () => ({
      count: rowCount,
      getScrollElement: () => scrollRef.current,
      estimateSize: () => 176, // card height (~160) + vertical gap (16)
      overscan: 5, // ~800px buffer prevents blank flash during fast scroll
    }),
    [rowCount],
  )

  const virtualizer = useVirtualizer(virtualizerOptions)

  // Defensive empty state — QueuePage gates on empty/filtered-empty before reaching this
  // component, but this ensures standalone reuse also shows a graceful fallback.
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
    <div
      ref={wrapperRef}
      // Use dvh (dynamic viewport height) instead of vh for mobile browser chrome.
      // The 14rem offset accounts for the header (~8rem), sort/search bar (~3rem),
      // padding/spacing (~3rem). ResizeObserver handles orientation changes.
      style={{ height: containerHeight || 'calc(100dvh - 14rem)' }}
    >
      <div
        ref={scrollRef}
        data-testid="queue-thread-list"
        id="queue-container"
        role="list"
        aria-label="Thread queue"
        style={{
          height: '100%',
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
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const rowIndex = virtualItem.index
            return columnCount === 1 ? (
              // ═══ Single-column path (preserved from 583-B) ═══
              // Keeps the exact DOM structure: absolute div with
              // data-index, translateY, measureElement, and renderItem
              // directly inside. Existing unit tests continue to pass.
              <div
                key={virtualItem.key}
                data-index={rowIndex}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                {renderItem(threads[rowIndex], rowIndex)}
              </div>
            ) : (
              // ═══ Multi-column path (desktop parity) ═══
              // Each virtual row is a CSS grid of columnCount cards.
              <div
                key={virtualItem.key}
                data-index={rowIndex}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  paddingBottom: '1rem', // vertical gap matching gap-4
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                <div
                  className="grid gap-4"
                  style={{
                    gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
                  }}
                >
                  {Array.from(
                    { length: columnCount },
                    (_, colIndex) => {
                      const threadIndex = rowIndex * columnCount + colIndex
                      if (threadIndex >= threads.length) return null
                      return renderItem(
                        threads[threadIndex],
                        threadIndex,
                      )
                    },
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
