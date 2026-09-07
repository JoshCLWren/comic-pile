import type { ReactNode } from 'react'
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import {
  getRowThreads,
  EDGE_SCROLL_ZONE,
  ROW_GAP,
  ROW_HEIGHT_WITH_GAP,
  OVERSCAN_PX,
} from './VirtualizedThreadList.helpers'

/** Threshold above which the queue switches from a plain list to a virtualized list. */
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
   * Optional explicit column count retained for deterministic legacy tests.
   * Production Queue rendering intentionally leaves this unset so the
   * virtualized and non-virtualized presentations are both one full-width row.
   */
  explicitColumnCount?: number
  sentinelRef?: React.RefObject<HTMLDivElement | null>
  scrollRootRef?: React.RefObject<HTMLDivElement | null>
  hasNextPage?: boolean
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
 * ### Scrolling contract (#2184)
 * The virtualized list scrolls the **window/document**, never an internal
 * fixed-height container. `useWindowVirtualizer` positions virtual rows inside
 * a relative spacer that grows in document flow, so the page keeps exactly one
 * scroll surface before and after the >50 virtualization threshold is crossed.
 * There is no `overflowY: auto` wrapper and no viewport-derived fixed height.
 *
 * ### `data-index` contract
 * In the production single-column path, `data-index` is the thread index. When
 * an explicit multi-column count is supplied by a test, it represents the
 * virtual row index and consumers must use `renderItem`'s second argument for
 * thread-level identity.
 *
 * Preserves existing selectors (`data-testid="queue-thread-list"`,
 * `id="queue-container"`, `role="list"`, `aria-label="Thread queue"`)
 * for E2E compatibility, including in the empty state.
 */
export default function VirtualizedThreadList<T>({
  threads,
  renderItem,
  explicitColumnCount,
  sentinelRef,
  scrollRootRef: _scrollRootRef,
  hasNextPage,
}: VirtualizedThreadListProps<T>) {
  // The bordered panel that owns the list presentation. It sits in normal
  // document flow (no fixed height, no overflowY), so the page scrolls.
  const panelRef = useRef<HTMLDivElement>(null)
  // Document-top offset of the relative spacer that holds the absolute rows.
  // Used as the virtualizer scrollMargin so window coordinates map onto the
  // spacer's coordinate space.
  const [scrollMargin, setScrollMargin] = useState(0)
  const [columnCount, setColumnCount] = useState(() =>
    explicitColumnCount !== undefined ? Math.max(1, explicitColumnCount) : 1,
  )

  // Measure the spacer's document-top offset synchronously before paint so the
  // first window-virtualized layout is already correct (no 0 → measured jump).
  // The spacer is the first child of the panel; its offset equals the panel's
  // top plus its border, close enough that virtual rows align with page flow.
  useLayoutEffect(() => {
    if (panelRef.current) {
      setScrollMargin(panelRef.current.getBoundingClientRect().top + window.scrollY)
    }
    setColumnCount(explicitColumnCount !== undefined ? Math.max(1, explicitColumnCount) : 1)
  }, [explicitColumnCount, threads.length])

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

  const virtualizer = useWindowVirtualizer(virtualizerOptions)

  // Keep a ref to the latest virtualizer so the drag-over handler stays
  // referentially stable. useWindowVirtualizer returns a new object every
  // render, so putting it in a useCallback deps array would recreate the
  // handler.
  const virtualizerRef = useRef(virtualizer)
  virtualizerRef.current = virtualizer

  // ── Drag-reorder edge auto-scroll (583-D) ──
  // Throttle timestamp to avoid calling scrollToIndex faster than the virtualizer
  // can re-measure (~50ms is generous for the resize → remeasure cycle). The
  // scroll owner is the window, so edge zones are measured against the viewport.
  const lastEdgeScrollRef = useRef<number>(0)

  const handlePanelDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const now = performance.now()
      // Throttle to avoid flooding scrollToIndex with 60+ calls per second.
      if (now - lastEdgeScrollRef.current < 50) return

      const vz = virtualizerRef.current
      const visibleItems = vz.getVirtualItems()
      if (visibleItems.length === 0) return

      const firstIndex = visibleItems[0].index
      const lastIndex = visibleItems[visibleItems.length - 1].index
      const viewportHeight = window.innerHeight

      if (event.clientY < EDGE_SCROLL_ZONE) {
        lastEdgeScrollRef.current = now
        vz.scrollToIndex(Math.max(0, firstIndex - 1), {
          align: 'start',
        })
      } else if (event.clientY > viewportHeight - EDGE_SCROLL_ZONE) {
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
      <div
        ref={panelRef}
        data-testid="queue-thread-list"
        id="queue-container"
        role="list"
        aria-label="Thread queue"
        className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
        style={{ height: 'calc(100dvh - 14rem)' }}
      >
        <div className="flex items-center justify-center text-stone-500 py-8">
          No threads in queue
        </div>
      </div>
    )
  }

  return (
    <div
      ref={panelRef}
      data-testid="queue-thread-list"
      id="queue-container"
      role="list"
      aria-label="Thread queue"
      className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)]"
      onDragOver={handlePanelDragOver}
      onDrop={(event) => event.preventDefault()}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          position: 'relative',
          width: '100%',
        }}
      >
        {hasNextPage && sentinelRef && (
          <div
            ref={sentinelRef}
            style={{
              position: 'absolute',
              top: `${virtualizer.getTotalSize() - 4}px`,
              left: 0,
              width: '100%',
              height: '4px',
            }}
            data-testid="queue-infinite-scroll-sentinel"
            aria-hidden="true"
          />
        )}
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
                transform: `translateY(${virtualItem.start - scrollMargin}px)`,
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
                transform: `translateY(${virtualItem.start - scrollMargin}px)`,
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
      </div>
    </div>
  )
}
