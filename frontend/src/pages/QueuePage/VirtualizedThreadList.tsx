import type { ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  getColumnCount,
  getRowThreads,
  EDGE_SCROLL_ZONE,
  ROW_GAP,
  ROW_HEIGHT_WITH_GAP,
  OVERSCAN_PX,
} from './VirtualizedThreadList.helpers'

/** Threshold above which the queue switches from a plain grid to a virtualized list. */
export const VIRTUALIZATION_THRESHOLD = 50

interface VirtualizedThreadListProps<T> {
  /** Threads to render in the virtualized list. */
  threads: T[]
  /**
   * Render-prop called for each visible virtual item.
   * @param thread — the thread at the current virtual index
   * @param index — the thread's position in the `threads` array.
   *   **Not a stable identifier** — it changes if the array is reordered.
   */
  renderItem: (thread: T, index: number) => ReactNode
  /**
   * Optional explicit column count. When provided, skips the `ResizeObserver`
   * width derivation used in production. Useful for deterministic tests
   * in environments without real layout (e.g. jsdom).
   */
  explicitColumnCount?: number
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
 * grid's spacing). Vertical gap is achieved via `paddingBottom` derived from
 * the `ROW_GAP` constant, measured by `measureElement`.
 *
 * Column count is derived from a `ResizeObserver` on the scroll container,
 * matching the Tailwind breakpoints. An optional `explicitColumnCount` prop
 * can override this for testing.
 *
 * ### `data-index` contract
 * The `data-index` attribute on each virtual row **always** represents the
 * virtual row index. In single-column mode this incidentally equals the thread
 * index; in multi-column mode consumers must use `renderItem`'s second argument
 * for thread-level identity.
 *
 * Uses `@tanstack/react-virtual` with `useVirtualizer` for efficient
 * DOM virtualization. Container height is derived from a `ResizeObserver`
 * on the wrapper element — **never** `window.innerHeight` during render
 * (non-reactive to resize/orientation).
 *
 * Preserves existing selectors (`data-testid="queue-thread-list"`,
 * `id="queue-container"`, `role="list"`, `aria-label="Thread queue"`)
 * for E2E compatibility, including in the empty state.
 */
export default function VirtualizedThreadList<T>({
  threads,
  renderItem,
  explicitColumnCount,
}: VirtualizedThreadListProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [containerHeight, setContainerHeight] = useState(0)
  // Default to 1; useLayoutEffect below is the single source of truth
  // for both dynamic and prop-driven column counts (Finding #6).
  const [columnCount, setColumnCount] = useState(1)

  // Read the initial wrapper dimensions synchronously to avoid a
  // 0 → measured layout jump on mount. Handles both the explicit prop
  // and the width-derived default, so the separate sync useEffect for
  // explicitColumnCount is not needed.
  useLayoutEffect(() => {
    if (wrapperRef.current) {
      setContainerHeight(wrapperRef.current.offsetHeight)
      if (explicitColumnCount !== undefined) {
        setColumnCount(Math.max(1, explicitColumnCount))
      } else {
        setColumnCount(getColumnCount(wrapperRef.current.offsetWidth))
      }
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
      estimateSize: () => ROW_HEIGHT_WITH_GAP,
      overscan: Math.ceil(OVERSCAN_PX / ROW_HEIGHT_WITH_GAP),
    }),
    [rowCount],
  )

  const virtualizer = useVirtualizer(virtualizerOptions)

  // Keep a ref to the latest virtualizer so the drag-over handler stays
  // referentially stable. useVirtualizer returns a new object every render,
  // so putting it in a useCallback deps array would recreate the handler
  // (and the onDragOver prop) each render — ineffective memoization.
  const virtualizerRef = useRef(virtualizer)
  virtualizerRef.current = virtualizer

  // ── Drag-reorder edge auto-scroll (583-D) ──
  // Throttle timestamp to avoid calling scrollToIndex faster than the virtualizer
  // can re-measure (~50ms is generous for the resize → remeasure cycle).
  const lastEdgeScrollRef = useRef<number>(0)

  const handleContainerDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const container = scrollRef.current
      if (!container) return

      const now = performance.now()
      // Throttle to avoid flooding scrollToIndex with 60+ calls per second.
      if (now - lastEdgeScrollRef.current < 50) return

      const vz = virtualizerRef.current
      const rect = container.getBoundingClientRect()
      const y = event.clientY - rect.top
      const visibleItems = vz.getVirtualItems()
      if (visibleItems.length === 0) return

      const firstIndex = visibleItems[0].index
      const lastIndex = visibleItems[visibleItems.length - 1].index

      if (y < EDGE_SCROLL_ZONE) {
        lastEdgeScrollRef.current = now
        vz.scrollToIndex(Math.max(0, firstIndex - 1), {
          align: 'start',
        })
      } else if (y > rect.height - EDGE_SCROLL_ZONE) {
        lastEdgeScrollRef.current = now
        vz.scrollToIndex(Math.min(rowCount - 1, lastIndex + 1), {
          align: 'end',
        })
      }
    },
    [rowCount],
  )

  // Defensive empty state — QueuePage gates on empty/filtered-empty before reaching this
  // component, but this ensures standalone reuse also shows a graceful fallback.
  // Wraps in the same `wrapperRef > scrollRef` tree structure as the populated state
  // for consistent DOM ancestry (Finding #3).
  if (threads.length === 0) {
    return (
      <div ref={wrapperRef} style={{ height: 'calc(100dvh - 14rem)' }}>
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
          <div className="flex items-center justify-center text-stone-500 py-8">
            No threads in queue
          </div>
        </div>
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
        onDragOver={handleContainerDragOver}
        onDrop={(event) => event.preventDefault()}
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
              // `data-index` always represents the virtual row index.
              // Use `renderItem`'s second argument for thread-level identity.
              <div
                key={virtualItem.key}
                data-index={rowIndex}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  paddingBottom: `${ROW_GAP}px`, // vertical gap matching gap-4
                  transform: `translateY(${virtualItem.start}px)`,
                }}
              >
                <div
                  className="grid gap-4"
                  style={{
                    gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
                    rowGap: `${ROW_GAP}px`,
                  }}
                >
                  {getRowThreads(threads, rowIndex, columnCount).map(
                    (thread, colIndex) =>
                      renderItem(thread, rowIndex * columnCount + colIndex),
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
