import type { ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import type { Virtualizer } from '@tanstack/react-virtual'
import {
  getRowThreads,
  EDGE_SCROLL_ZONE,
  ROW_GAP,
  ROW_HEIGHT_WITH_GAP,
  OVERSCAN_PX,
} from './VirtualizedThreadList.helpers'

/** Threshold above which the queue switches from a plain list to a virtualized list. */
export const VIRTUALIZATION_THRESHOLD = 50

/** The options accepted by the window-virtualizer hook. */
export type UseWindowVirtualizerOptions = Parameters<typeof useWindowVirtualizer>[0]

/** The minimal window-virtualizer contract the list consumes. */
export type QueueVirtualizer = Pick<
  Virtualizer<Window, HTMLElement>,
  'getVirtualItems' | 'getTotalSize' | 'measureElement' | 'scrollToIndex'
>

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
   * Optional explicit column count retained for deterministic legacy tests.
   * Production Queue rendering intentionally leaves this unset so the
   * virtualized and non-virtualized presentations are both one full-width row.
   */
  explicitColumnCount?: number
  sentinelRef?: React.RefObject<HTMLDivElement | null>
  scrollRootRef?: React.RefObject<HTMLDivElement | null>
  hasNextPage?: boolean
  /**
   * Injectable window-virtualizer hook. Production uses the real
   * `@tanstack/react-virtual` hook; tests substitute a faithful deterministic
   * virtualizer so windowing can be exercised without a real browser layout.
   */
  useVirtualizer?: (options: UseWindowVirtualizerOptions) => QueueVirtualizer
}

/**
 * Virtualized list for large queues (>50 threads).
 *
 * Production renders exactly one full-width thread per virtual row so crossing
 * the virtualization threshold does not change Queue's visual grammar. This
 * mirrors the non-virtualized list introduced by #2088/#2099.
 *
 * `explicitColumnCount` preserves the older multi-column path only as a
 * deterministic test hook. Queue itself never supplies that prop.
 *
 * ### `data-index` contract
 * In the production single-column path, `data-index` is the thread index. When
 * an explicit multi-column count is supplied by a test, it represents the
 * virtual row index and consumers must use `renderItem`'s second argument for
 * thread-level identity.
 *
 * Uses `@tanstack/react-virtual` with `useWindowVirtualizer` for efficient DOM
 * virtualization. The window scroll surface owns Queue before and after the
 * virtualization threshold is crossed, preventing nested scroll containers.
 *
 * Preserves existing selectors (`data-testid="queue-thread-list"`,
 * `id="queue-container"`, `role="list"`, `aria-label="Series queue"`)
 * for E2E compatibility, including in the empty state.
 */
export default function VirtualizedThreadList<T>({
  threads,
  renderItem,
  explicitColumnCount,
  sentinelRef,
  scrollRootRef: _scrollRootRef,
  hasNextPage,
  useVirtualizer,
}: VirtualizedThreadListProps<T>) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  const [columnCount, setColumnCount] = useState(() =>
    explicitColumnCount !== undefined ? Math.max(1, explicitColumnCount) : 1,
  )

  // Read the initial wrapper offset synchronously to avoid a 0 → measured
  // layout jump. Production stays single-column regardless of wrapper width.
  useLayoutEffect(() => {
    if (wrapperRef.current) {
      const rect = wrapperRef.current.getBoundingClientRect()
      setScrollMargin(rect.top + window.scrollY)
    }
    setColumnCount(explicitColumnCount !== undefined ? Math.max(1, explicitColumnCount) : 1)
  }, [explicitColumnCount])

  // React to offset changes (e.g. window resize or layout shifts above the list).
  useEffect(() => {
    let rafId: number | null = null

    const observer = new ResizeObserver(() => {
      if (rafId !== null) return
      rafId = requestAnimationFrame(() => {
        rafId = null
        if (wrapperRef.current) {
          const rect = wrapperRef.current.getBoundingClientRect()
          setScrollMargin(rect.top + window.scrollY)
        }
      })
    })

    observer.observe(document.body)
    return () => {
      observer.disconnect()
      if (rafId !== null) {
        cancelAnimationFrame(rafId)
      }
    }
  }, [])

  const rowCount = Math.ceil(threads.length / columnCount)

  // Memoize virtualizer options to avoid unnecessary setOptions()
  // calls on every render.
  const virtualizerOptions = useMemo(
    () => ({
      count: rowCount,
      estimateSize: () => ROW_HEIGHT_WITH_GAP,
      overscan: Math.ceil(OVERSCAN_PX / ROW_HEIGHT_WITH_GAP),
      scrollMargin,
    }),
    [rowCount, scrollMargin],
  )

  // SAFETY: the injected prop and the production hook both satisfy the same
  // structural QueueVirtualizer contract, so the single assertion is safe.
  const windowVirtualizer = (useVirtualizer ?? useWindowVirtualizer) as (
    options: UseWindowVirtualizerOptions,
  ) => QueueVirtualizer

  const virtualizer = windowVirtualizer(virtualizerOptions)

  // Keep a ref to the latest virtualizer so the drag-over handler stays
  // referentially stable. useWindowVirtualizer returns a new object every render,
  // so putting it in a useCallback deps array would recreate the handler.
  const virtualizerRef = useRef(virtualizer)
  virtualizerRef.current = virtualizer

  // ── Drag-reorder edge auto-scroll (583-D) ──
  // Throttle timestamp to avoid calling scrollToIndex faster than the virtualizer
  // can re-measure (~50ms is generous for the resize → remeasure cycle).
  const lastEdgeScrollRef = useRef<number>(0)

  const handleContainerDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const now = performance.now()
      // Throttle to avoid flooding scrollToIndex with 60+ calls per second.
      if (now - lastEdgeScrollRef.current < 50) return

      const vz = virtualizerRef.current
      const y = event.clientY
      const visibleItems = vz.getVirtualItems()
      if (visibleItems.length === 0) return

      const firstIndex = visibleItems[0].index
      const lastIndex = visibleItems[visibleItems.length - 1].index

      if (y < EDGE_SCROLL_ZONE) {
        lastEdgeScrollRef.current = now
        vz.scrollToIndex(Math.max(0, firstIndex - 1), {
          align: 'start',
        })
      } else if (y > window.innerHeight - EDGE_SCROLL_ZONE) {
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
  if (threads.length === 0) {
    return (
      <div ref={wrapperRef}>
        <div
          data-testid="queue-thread-list"
          id="queue-container"
          role="list"
          aria-label="Series queue"
          className="@container rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
        >
          <div className="flex items-center justify-center text-stone-500 py-8">
            No series in queue
          </div>
        </div>
      </div>
    )
  }

  return (
    <div ref={wrapperRef}>
      <div
        data-testid="queue-thread-list"
        id="queue-container"
        role="list"
        aria-label="Series queue"
        className="@container rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
        onDragOver={handleContainerDragOver}
        onDrop={(event) => event.preventDefault()}
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize() + (hasNextPage ? 16 : 0)}px`,
            position: 'relative',
            width: '100%',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const rowIndex = virtualItem.index
            return columnCount === 1 ? (
              <div
                key={virtualItem.key}
                data-index={rowIndex}
                ref={virtualizer.measureElement}
                className={rowIndex < threads.length - 1 ? 'border-b border-[var(--theme-border)]' : undefined}
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
              <div
                key={virtualItem.key}
                data-index={rowIndex}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  paddingBottom: `${ROW_GAP}px`,
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
                    (thread, colIndex) => renderItem(thread, rowIndex * columnCount + colIndex),
                  )}
                </div>
              </div>
            )
          })}
          {hasNextPage && (
            <div
              ref={sentinelRef}
              style={{
                position: 'absolute',
                top: virtualizer.getTotalSize(),
                left: 0,
                width: '100%',
                height: '16px',
              }}
              data-testid="queue-infinite-scroll-sentinel"
              aria-hidden="true"
            />
          )}
        </div>
      </div>
    </div>
  )
}
