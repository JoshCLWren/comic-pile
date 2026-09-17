import { act, render, screen, waitFor } from '@testing-library/react'
import { afterAll, beforeAll, expect, it, vi } from 'vitest'
import type {
  QueueVirtualizer,
  UseWindowVirtualizerOptions,
} from '../pages/QueuePage/VirtualizedThreadList'
import VirtualizedThreadList from '../pages/QueuePage/VirtualizedThreadList'
import { ROW_HEIGHT_WITH_GAP } from '../pages/QueuePage/VirtualizedThreadList.helpers'
import { QueueList } from '../pages/QueuePage/QueueList'
import { cast } from '../utils/cast'
import type { Thread } from '../types'

interface MockThread {
  id: number
  title: string
}

function createMockThread(id: number): Thread {
  return {
    id,
    title: `Thread ${id}`,
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    queue_position: id,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2024-01-01T00:00:00.000Z',
  }
}

const threads: MockThread[] = Array.from({ length: 60 }, (_, index) => ({
  id: index + 1,
  title: `Thread ${index + 1}`,
}))

const virtualItems = [
  { key: 0, index: 0, start: 0, end: 160, size: 160, lane: 0 },
  { key: 1, index: 1, start: 160, end: 320, size: 160, lane: 0 },
]

// Deterministic virtualizer injected through the real `useVirtualizer` prop —
// no module mocking of @tanstack/react-virtual.
function fakeUseVirtualizer(_options: UseWindowVirtualizerOptions): QueueVirtualizer {
  return {
    getVirtualItems: () => virtualItems,
    getTotalSize: () => 9600,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }
}

let resizeCallback:
  | ((entries: Array<{ contentRect: { height: number; width: number } }>) => void)
  | undefined

beforeAll(() => {
  // SAFETY: stub function satisfies ResizeObserver constructor contract for testing
  vi.stubGlobal(
    'ResizeObserver',
    vi.fn(function (
      this: { observe: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> },
      callback: (entries: Array<{ contentRect: { height: number; width: number } }>) => void,
    ) {
      resizeCallback = callback
      this.observe = vi.fn()
      this.disconnect = vi.fn()
      return this
    }),
  )
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      callback(0)
      return 1
    }),
  )
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterAll(() => {
  vi.unstubAllGlobals()
})

it('keeps paginated queue items as full-width rows on a wide viewport', async () => {
  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={thread.id}>
          {thread.title} #{index + 1}
        </div>
      )}
      useVirtualizer={fakeUseVirtualizer}
    />,
  )

  act(() => {
    resizeCallback?.([{ contentRect: { height: 600, width: 1400 } }])
  })

  await waitFor(() => {
    expect(screen.getAllByTestId('queue-thread-item')).toHaveLength(2)
  })

  expect(screen.getByText('Thread 1 #1')).toBeInTheDocument()
  expect(screen.getByText('Thread 2 #2')).toBeInTheDocument()
  expect(container.querySelector('[style*="grid-template-columns"]')).not.toBeInTheDocument()
  expect(screen.getByTestId('queue-thread-list')).toHaveClass(
    'rounded-xl',
    'border',
    'bg-[var(--theme-bg-panel)]',
  )
})

/**
 * Acceptance criterion #6 for issue #2184: begin with ≤50 items, append enough
 * to cross the threshold, and verify the same user-facing scroll surface
 * (the window) owns Queue before and after — no nested vertical scroll channel
 * or fixed-height box is introduced.
 */
it('keeps a single scroll surface when the queue crosses the virtualization threshold', async () => {
  const initialThreads: Thread[] = Array.from({ length: 50 }, (_, i) => createMockThread(i + 1))
  const grownThreads: Thread[] = Array.from({ length: 60 }, (_, i) => createMockThread(i + 1))

  const sentinelRef = { current: null }
  const renderItem = (thread: Thread, index: number) => (
    <div data-testid="queue-thread-item" key={thread.id}>
      {thread.title} #{index + 1}
    </div>
  )

  // SAFETY: sentinelRef is a nullable ref; cast to match QueueList prop types
  const { container, rerender } = render(
    <QueueList
      activeThreads={initialThreads}
      filteredThreads={initialThreads}
      reorderError={null}
      renderItem={renderItem}
      isSearching={false}
      sentinelRef={sentinelRef as React.RefObject<HTMLDivElement | null>}
      hasNextPage
      useVirtualizer={fakeUseVirtualizer}
    />,
  )

  act(() => {
    resizeCallback?.([{ contentRect: { height: 600, width: 1400 } }])
  })

  await waitFor(() => {
    expect(screen.getAllByTestId('queue-thread-item')).toHaveLength(50)
  })
  expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()

  const scrollChannelOf = (el: Element) => {
    const style = getComputedStyle(el)
    return {
      // SAFETY: getComputedStyle returns CSSStyleDeclaration; overflowY is always a string
      overflowY: style.overflowY as string,
      // SAFETY: el is known to be an HTMLElement from the querySelector result
      inlineHeight: (el as HTMLElement).style.height,
    }
  }

  const plainSurface = scrollChannelOf(container.querySelector('#queue-container')!)
  expect(['auto', 'scroll']).not.toContain(plainSurface.overflowY)
  expect(plainSurface.inlineHeight).toBe('')

  // Cross the threshold: VirtualizedThreadList replaces the plain list.
  // SAFETY: same ref cast as the initial render for QueueList prop types
  rerender(
    <QueueList
      activeThreads={grownThreads}
      filteredThreads={grownThreads}
      reorderError={null}
      renderItem={renderItem}
      isSearching={false}
      sentinelRef={sentinelRef as React.RefObject<HTMLDivElement | null>}
      hasNextPage
      useVirtualizer={fakeUseVirtualizer}
    />,
  )

  await waitFor(() => {
    expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()
  })

  const virtualizedSurface = scrollChannelOf(container.querySelector('#queue-container')!)
  expect(['auto', 'scroll']).not.toContain(virtualizedSurface.overflowY)
  expect(virtualizedSurface.inlineHeight).toBe('')

  // Presentation stays single-column (no multi-column grid is introduced).
  expect(container.querySelector('[style*="grid-template-columns"]')).not.toBeInTheDocument()
  // Infinite-scroll sentinel survives the threshold crossing.
  expect(screen.getByTestId('queue-infinite-scroll-sentinel')).toBeInTheDocument()
})

/**
 * Regression test for #2523: Queue infinite scroll blanks after ~50 items.
 *
 * The window virtualizer reads raw `window.scrollY` as its scroll offset and
 * lays virtual items out starting at `scrollMargin`, so `scrollMargin` must be
 * the stable document-space distance from the start of the window scroll
 * content to the top of the virtual list (`rect.top + window.scrollY`), and
 * each virtual item must be rendered at `start - scrollMargin` to land at its
 * natural document position. Bare `translateY(start)` shifts every virtual row
 * down by the page-chrome offset above the Queue list, so once the plain list
 * crosses the virtualization threshold the painted rows no longer line up with
 * the scroll positions the virtualizer computes and the viewport blanks /
 * load-more sticks.
 *
 * The virtualizer is a faithful deterministic double that derives virtual item
 * `start` values from the `scrollMargin` it receives (as @tanstack/react-virtual
 * does). The wrapper is given a non-zero chrome offset to model the queue
 * sitting below the page header. This test fails on both the previous
 * `rect.top + window.scrollY` + bare-`start` rendering and on the intermediate
 * `rect.top`-only scrollMargin variant, because each shifts the virtual rows.
 */
it('paints virtual rows at natural document offsets when the wrapper sits below the page top', async () => {
  const threads: Thread[] = Array.from({ length: 60 }, (_, i) => createMockThread(i + 1))

  const sentinelRef = { current: null }
  const renderItem = (thread: Thread, index: number) => (
    <div data-testid="queue-thread-item" key={thread.id}>
      {thread.title} #{index + 1}
    </div>
  )

  // Fake virtualizer that mirrors the library contract: item `start` values
  // include the supplied scrollMargin and total size excludes it.
  const scrollMargins: number[] = []
  const scrollMarginAwareUseVirtualizer = (
    options: UseWindowVirtualizerOptions,
  ): QueueVirtualizer => {
    const margin = options.scrollMargin ?? 0
    scrollMargins.push(margin)
    const count = options.count
    const items = Array.from({ length: count }, (_, i) => {
      const start = margin + i * ROW_HEIGHT_WITH_GAP
      return {
        key: i,
        index: i,
        start,
        end: start + ROW_HEIGHT_WITH_GAP,
        size: ROW_HEIGHT_WITH_GAP,
        lane: 0,
      }
    })
    return {
      getVirtualItems: () => items,
      getTotalSize: () => count * ROW_HEIGHT_WITH_GAP,
      measureElement: vi.fn(),
      scrollToIndex: vi.fn(),
    }
  }

  const previousScrollY = window.scrollY
  try {
    Object.defineProperty(window, 'scrollY', { value: 300, writable: true, configurable: true })

    const { container } = render(
      <QueueList
        activeThreads={threads}
        filteredThreads={threads}
        reorderError={null}
        renderItem={renderItem}
        isSearching={false}
        sentinelRef={sentinelRef as React.RefObject<HTMLDivElement | null>}
        hasNextPage
        useVirtualizer={scrollMarginAwareUseVirtualizer}
      />,
    )

    // Model the wrapper as sitting 120px down the initial viewport while the
    // window is scrolled 300px: its document-space offset is 420px.
    const wrapper = container.firstElementChild as HTMLElement
    // SAFETY: wrapper is the VirtualizedThreadList root div handled by the component.
    vi.spyOn(wrapper, 'getBoundingClientRect').mockReturnValue(cast<DOMRect>({ top: 120 }))

    act(() => {
      resizeCallback?.([{ contentRect: { height: 600, width: 1400 } }])
    })

    await waitFor(() => {
      expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()
    })

    // scrollMargin must be computed in document space (rect.top + scrollY).
    // The intermediate `scrollMargin = rect.top` variant pins 120 here; the
    // correct document-space value is 420.
    expect(scrollMargins.at(-1)).toBe(420)

    // Every virtual row must be painted at its container-relative offset so it
    // lands at the same document position the plain list used. Rendering at
    // bare `start` shifts each row down by the 420px scrollMargin and blanked
    // the viewport past the threshold.
    const rows = container.querySelectorAll('[data-index]')
    expect(rows.length).toBeGreaterThan(50)
    rows.forEach((row, index) => {
      const style = (row as HTMLElement).style
      expect(style.transform).toBe(`translateY(${index * ROW_HEIGHT_WITH_GAP}px)`)
    })

    // Spacer height (total size + sentinel padding) and sentinel placement
    // stay consistent so infinite scroll keeps firing past the threshold.
    const scrollEl = container.querySelector('#queue-container')
    expect(scrollEl).toBeInTheDocument()
    const spacer = (scrollEl as HTMLElement).firstElementChild as HTMLElement
    expect(spacer.style.position).toBe('relative')
    expect(spacer.style.height).toBe(
      `${threads.length * ROW_HEIGHT_WITH_GAP + 16}px`,
    )
    const sentinel = screen.getByTestId('queue-infinite-scroll-sentinel')
    expect(sentinel.style.top).toBe(`${threads.length * ROW_HEIGHT_WITH_GAP}px`)
  } finally {
    Object.defineProperty(window, 'scrollY', {
      value: previousScrollY,
      writable: true,
      configurable: true,
    })
  }
})
