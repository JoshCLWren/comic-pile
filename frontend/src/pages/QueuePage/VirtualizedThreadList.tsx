import type { ReactNode } from 'react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import type { VirtualItem, Virtualizer } from '@tanstack/react-virtual'
import {
  EDGE_SCROLL_ZONE,
  ROW_GAP,
  ROW_HEIGHT_WITH_GAP,
  OVERSCAN_PX,
} from './VirtualizedThreadList.helpers'

/** Threshold above which the queue switches from a plain list to a virtualized list. */
export const VIRTUALIZATION_THRESHOLD = 50

/** The options accepted by the window-virtualizer hook. */
export type UseWindowVirtualizerOptions = Parameters<typeof useWindowVirtualizer>[0]

/**
 * The minimal window-virtualizer contract the list consumes.
 *
 * `getVirtualItems` is declared as the bare call signature because the library
 * type also attaches an internal `updateDeps` method that a deterministic test
 * double cannot (and should not) reproduce. The component only calls it as a
 * function.
 */
export type QueueVirtualizer = Pick<
  Virtualizer<Window, HTMLElement>,
  'getTotalSize' | 'measureElement' | 'scrollToIndex'
> & { getVirtualItems: () => VirtualItem[] }

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
  sentinelRef?: React.Ref<HTMLDivElement>
  hasNextPage?: boolean
  /**
   * Injectable window-virtualizer hook. Production uses the real
   * `@tanstack/react-virtual` hook; tests substitute a faithful deterministic
   * virtualizer so windowing can be exercised without a real browser layout.
   */
  useVirtualizer?: (options: UseWindowVirtualizerOptions) => QueueVirtualizer
}

/**
 * Virtualized list backing the queue at every page size.
 *
 * Production renders exactly one full-width thread per virtual row so Queue
 * keeps a single rendering path (and a single window-owned scroll surface)
 * from the first page through the final page. This mirrors the
 * non-virtualized list introduced by #2088/#2099.
 *
 * Uses `@tanstack/react-virtual` with `useWindowVirtualizer` for efficient DOM
 * virtualization. The window scroll surface owns Queue before and after the
 * virtualization threshold is crossed, preventing nested scroll containers.
 *
 * Scroll ownership (#2582): this component owns measurement/rendering only.
 * It never repositions the window for navigation or resume — route
 * restoration belongs exclusively to the route restoration layer. The single
 * `scrollToIndex` call below serves an explicit user drag gesture (edge
 * auto-scroll while reordering) and is not a restore path.
 *
 * Preserves existing selectors (`data-testid="queue-thread-list"`,
 * `id="queue-container"`, `role="list"`, `aria-label="Series queue"`)
 * for E2E compatibility, including in the empty state.
 */
export default function VirtualizedThreadList<T>({
  threads,
  renderItem,
  sentinelRef,
  hasNextPage,
  useVirtualizer,
}: VirtualizedThreadListProps<T>) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)

  // Read the initial wrapper offset synchronously to avoid a 0 → measured
  // layout jump. Production stays single-column regardless of wrapper width.
  // @tanstack/react-virtual's window virtualizer reads the raw window.scrollY
  // as its scroll offset and lays virtual items out starting at scrollMargin,
  // so scrollMargin must be the distance from the start of the window scroll
  // content (the document top) to the wrapper top — a stable document-space
  // offset. `rect.top` is viewport-relative, so the current scroll is added
  // back: `rect.top + window.scrollY`. Because virtual item `start` values
  // already include scrollMargin, items must be rendered at
  // `start - scrollMargin` (see the render below); a bare `start` shifts every
  // virtual row down by the page-chrome offset above the list and blanks the
  // viewport once the queue crosses the virtualization threshold.
  useLayoutEffect(() => {
    if (wrapperRef.current) {
      const rect = wrapperRef.current.getBoundingClientRect()
      setScrollMargin(rect.top + window.scrollY)
    }
  }, [])

  // React to offset changes (e.g. window resize or layout shifts above the list).
  // Guarded so server-side rendering and layout-less test environments
  // (jsdom without a ResizeObserver stub) keep the initial synchronous
  // measurement instead of crashing the whole queue.
  useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return

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

  const rowCount = threads.length

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
            return (
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
                  transform: `translateY(${virtualItem.start - scrollMargin}px)`,
                }}
              >
                {renderItem(threads[rowIndex], rowIndex)}
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
