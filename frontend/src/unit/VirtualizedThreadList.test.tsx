import { render, screen } from '@testing-library/react'
import { expect, it, vi, beforeAll } from 'vitest'
import { getColumnCount } from '../pages/QueuePage/VirtualizedThreadList.helpers'
import VirtualizedThreadList from '../pages/QueuePage/VirtualizedThreadList'

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
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title} #{index + 1}
        </div>
      )}
    />,
  )

  const items = screen.getAllByTestId('queue-thread-item')
  expect(items).toHaveLength(5)
  expect(items[0]).toHaveTextContent('Thread 1')
  expect(items[4]).toHaveTextContent('Thread 5')
})

it('preserves container selectors for E2E compatibility', () => {
  const threads = createMockThreads(5)

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    />,
  )

  expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()
  expect(container.querySelector('#queue-container')).toBeInTheDocument()
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByLabelText('Thread queue')).toBeInTheDocument()
})

it('renders the total-size spacer div', () => {
  mockGetTotalSize.mockReturnValueOnce(9600)

  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    />,
  )

  const scrollEl = container.querySelector('#queue-container')
  expect(scrollEl).toBeInTheDocument()
  const spacer = scrollEl!.firstElementChild as HTMLElement
  expect(spacer.style.height).toBe('9600px')
  expect(spacer.style.position).toBe('relative')
})

it('renders virtual items with correct positioning', () => {
  const threads = createMockThreads(60)

  render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    />,
  )

  const items = screen.getAllByTestId('queue-thread-item')
  expect(items).toHaveLength(5)

  items.forEach((item, i) => {
    const parent = item.parentElement as HTMLElement
    expect(parent.dataset.index).toBe(String(i))
    expect(parent.style.transform).toBe(`translateY(${i * 160}px)`)
  })
})

// ── Pure breakpoint tests (no DOM required) ──

it('getColumnCount returns 1 below sm breakpoint', () => {
  expect(getColumnCount(0)).toBe(1)
  expect(getColumnCount(375)).toBe(1)
  expect(getColumnCount(767)).toBe(1)
})

it('getColumnCount returns 2 at md breakpoint (768-1023)', () => {
  expect(getColumnCount(768)).toBe(2)
  expect(getColumnCount(800)).toBe(2)
  expect(getColumnCount(1023)).toBe(2)
})

it('getColumnCount returns 2 at lg breakpoint (1024-1279)', () => {
  expect(getColumnCount(1024)).toBe(2)
  expect(getColumnCount(1152)).toBe(2)
  expect(getColumnCount(1279)).toBe(2)
})

it('getColumnCount returns 3 at xl breakpoint (1280+)', () => {
  expect(getColumnCount(1280)).toBe(3)
  expect(getColumnCount(1440)).toBe(3)
  expect(getColumnCount(1920)).toBe(3)
})

// ── Multi-column render tests ──

it('renders 3 columns of items when columnCount=3', () => {
  const threads = createMockThreads(60)

  // 5 virtual rows × 3 columns = 15 items visible
  mockGetVirtualItems.mockReturnValue(
    Array.from({ length: 5 }, (_, i) => ({
      key: i,
      index: i,
      start: i * 176,
      end: (i + 1) * 176,
      size: 176,
      lane: 0,
    })),
  )

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      columnCount={3}
      renderItem={(thread, _index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Thread {(thread as MockThread).title}
        </div>
      )}
    />,
  )

  const items = screen.getAllByTestId('queue-thread-item')
  expect(items).toHaveLength(15)

  // First row's grid should have 3 columns
  const firstRow = container.querySelector('[data-index="0"]')!
  const grid = firstRow.firstElementChild as HTMLElement
  expect(grid.style.gridTemplateColumns).toBe('repeat(3, minmax(0, 1fr))')
})

it('renders 1 column when columnCount=1 (single-column fallback)', () => {
  const threads = createMockThreads(60)

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

  render(
    <VirtualizedThreadList
      threads={threads}
      columnCount={1}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title} #{index + 1}
        </div>
      )}
    />,
  )

  const items = screen.getAllByTestId('queue-thread-item')
  expect(items).toHaveLength(5)
  expect(items[0]).toHaveTextContent('Thread 1')
  expect(items[4]).toHaveTextContent('Thread 5')
})

it('sets aria-label and role on the scroll container', () => {
  const threads = createMockThreads(5)

  render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          Item {index + 1}
        </div>
      )}
    />,
  )

  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByLabelText('Thread queue')).toBeInTheDocument()
})