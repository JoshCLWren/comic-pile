import { act, render, screen, waitFor } from '@testing-library/react'
import { afterAll, beforeAll, expect, it, vi } from 'vitest'
import VirtualizedThreadList from '../pages/QueuePage/VirtualizedThreadList'
import { QueueList } from '../pages/QueuePage/QueueList'
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

vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: () => ({
    getVirtualItems: () => virtualItems,
    getTotalSize: () => 9600,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}))

let resizeCallback:
  | ((entries: Array<{ contentRect: { height: number; width: number } }>) => void)
  | undefined

beforeAll(() => {
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
    }) as unknown as typeof ResizeObserver,
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
  const scrollRootRef = { current: null }
  const renderItem = (thread: Thread, index: number) => (
    <div data-testid="queue-thread-item" key={thread.id}>
      {thread.title} #{index + 1}
    </div>
  )

  const { container, rerender } = render(
    <QueueList
      activeThreads={initialThreads}
      filteredThreads={initialThreads}
      reorderError={null}
      renderItem={renderItem}
      isSearching={false}
      sentinelRef={sentinelRef as React.RefObject<HTMLDivElement | null>}
      scrollRootRef={scrollRootRef as React.RefObject<HTMLDivElement | null>}
      hasNextPage
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
      overflowY: style.overflowY as string,
      inlineHeight: (el as HTMLElement).style.height,
    }
  }

  const plainSurface = scrollChannelOf(container.querySelector('#queue-container')!)
  expect(['auto', 'scroll']).not.toContain(plainSurface.overflowY)
  expect(plainSurface.inlineHeight).toBe('')

  // Cross the threshold: VirtualizedThreadList replaces the plain list.
  rerender(
    <QueueList
      activeThreads={grownThreads}
      filteredThreads={grownThreads}
      reorderError={null}
      renderItem={renderItem}
      isSearching={false}
      sentinelRef={sentinelRef as React.RefObject<HTMLDivElement | null>}
      scrollRootRef={scrollRootRef as React.RefObject<HTMLDivElement | null>}
      hasNextPage
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
