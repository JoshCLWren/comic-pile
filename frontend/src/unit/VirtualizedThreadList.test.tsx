import { render, screen } from '@testing-library/react'
import { expect, it, vi, beforeAll } from 'vitest'
import VirtualizedThreadList from '../pages/QueuePage/VirtualizedThreadList'
import type { ReactElement } from 'react'

interface MockThread {
  id: number
  title: string
}

function createMockThreads(count: number): MockThread[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    title: `Thread ${i + 1}`,
  }))
}

// Mock @tanstack/react-virtual's useVirtualizer
const mockGetVirtualItems = vi.fn()
const mockGetTotalSize = vi.fn(() => 0)
const mockMeasureElement = vi.fn()
const mockScrollToIndex = vi.fn()

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: () => ({
    getVirtualItems: mockGetVirtualItems,
    getTotalSize: mockGetTotalSize,
    measureElement: mockMeasureElement,
    scrollToIndex: mockScrollToIndex,
  }),
}))

// Stub ResizeObserver (still needed for the component's own ResizeObserver)
beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    vi.fn(function (this: any) {
      this.observe = vi.fn()
      this.unobserve = vi.fn()
      this.disconnect = vi.fn()
      return this
    }) as unknown as typeof ResizeObserver,
  )
})

beforeAll(() => {
  // Default: virtualizer shows first 5 items of a list
  mockGetVirtualItems.mockReturnValue(
    Array.from({ length: 5 }, (_, i) => ({
      key: i,
      index: i,
      start: i * 160,
      end: (i + 1) * 160,
      size: 160,
      lane: 0,
    })),
  )
  mockGetTotalSize.mockReturnValue(3200)
})

it('renders only the virtualized subset of items (windowing)', () => {
  const threads = createMockThreads(60)

  render(
    <VirtualizedThreadList threads={threads}>
      {(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title} #{index + 1}
        </div>
      )}
    </VirtualizedThreadList>,
  )

  // With our mock returning 5 virtual items, only 5 should render
  const items = screen.getAllByTestId('queue-thread-item')
  expect(items).toHaveLength(5)
  expect(items[0]).toHaveTextContent('Thread 1')
  expect(items[4]).toHaveTextContent('Thread 5')
})

it('preserves container selectors for E2E compatibility', () => {
  const threads = createMockThreads(5)

  const { container } = render(
    <VirtualizedThreadList threads={threads}>
      {(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    </VirtualizedThreadList>,
  )

  expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()
  expect(container.querySelector('#queue-container')).toBeInTheDocument()
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByLabelText('Thread queue')).toBeInTheDocument()
})

it('renders the total-size spacer div', () => {
  mockGetTotalSize.mockReturnValue(9600)

  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList threads={threads}>
      {(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    </VirtualizedThreadList>,
  )

  // The inner spacer div should have height = totalSize
  const scrollEl = container.querySelector('#queue-container')
  expect(scrollEl).toBeInTheDocument()
  const spacer = scrollEl!.firstElementChild as HTMLElement
  expect(spacer.style.height).toBe('9600px')
  expect(spacer.style.position).toBe('relative')
})

it('renders virtual items with correct positioning', () => {
  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList threads={threads}>
      {(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    </VirtualizedThreadList>,
  )

  const items = screen.getAllByTestId('queue-thread-item')
  // Should have 5 items (from mock)
  expect(items).toHaveLength(5)

  // Each item wrapper should have data-index and transform style
  items.forEach((item, i) => {
    const parent = item.parentElement as HTMLElement
    expect(parent.dataset.index).toBe(String(i))
    expect(parent.style.transform).toBe(`translateY(${i * 160}px)`)
  })
})

it('sets aria-label and role on the scroll container', () => {
  const threads = createMockThreads(5)

  render(
    <VirtualizedThreadList threads={threads}>
      {(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    </VirtualizedThreadList>,
  )

  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByLabelText('Thread queue')).toBeInTheDocument()
})
