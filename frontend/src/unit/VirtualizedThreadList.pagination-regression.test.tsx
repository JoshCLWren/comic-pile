import { act, render, screen, waitFor } from '@testing-library/react'
import { afterAll, beforeAll, expect, it, vi } from 'vitest'
import VirtualizedThreadList from '../pages/QueuePage/VirtualizedThreadList'

interface MockThread {
  id: number
  title: string
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

it('does not wrap the queue panel in an internal scroll container (#2184)', () => {
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

  const panel = screen.getByTestId('queue-thread-list')
  expect(panel).toBe(container.querySelector('#queue-container'))
  // No internal scrolling: the page is the single scroll owner.
  expect(panel.style.overflowY).not.toBe('auto')
  expect(panel.style.overflow).not.toBe('auto')
  // The panel must not own a viewport-derived fixed height; it sits in document flow.
  expect(panel.style.height).not.toMatch(/^\d+(\.\d+)?(px|dvh|vh|%)$/)
  // The next-page sentinel is not rendered when the host does not pass `sentinelRef`.
  expect(screen.queryByTestId('queue-infinite-scroll-sentinel')).not.toBeInTheDocument()
})

it('renders the next-page sentinel at the spacer bottom when `sentinelRef` is provided', () => {
  const sentinelRef = { current: null } as React.RefObject<HTMLDivElement | null>
  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={thread.id}>
          {thread.title} #{index + 1}
        </div>
      )}
      sentinelRef={sentinelRef}
      hasNextPage
    />,
  )

  const sentinel = screen.getByTestId('queue-infinite-scroll-sentinel')
  expect(sentinel).toBeInTheDocument()
  expect(sentinelRef.current).toBe(sentinel)
  // The sentinel must sit at the spacer bottom so the window IntersectionObserver
  // fires exactly when the user scrolls past the last virtual row.
  expect(container.contains(sentinel)).toBe(true)
})
