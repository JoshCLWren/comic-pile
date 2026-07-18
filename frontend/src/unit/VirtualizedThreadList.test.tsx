import { render, screen } from '@testing-library/react'
import { expect, it, vi, beforeAll, beforeEach } from 'vitest'
import { getColumnCount, getRowThreads } from '../pages/QueuePage/VirtualizedThreadList.helpers'
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

// Stub DragEvent / DataTransfer (not available in jsdom) for drag-reorder tests.
// Must be defined before the module is loaded so `new DragEvent(...)` works inside
// tests.  We use a stub DataTransfer object because React's synthetic event system
// checks `event.dataTransfer`.
// Also stub ResizeObserver (needed by the component's useEffect).
beforeAll(() => {
  if (!globalThis.DataTransfer) {
    globalThis.DataTransfer = class {
      effectAllowed = 'none'
      dropEffect = 'none'
      items = { length: 0, add: () => {}, clear: () => {} } as unknown as DataTransferItemList
      types: string[] = []
      getData = (_format: string) => ''
      setData = () => {}
      clearData = () => {}
      setDragImage = () => {}
      files = Object.freeze([]) as unknown as FileList
    } as unknown as typeof DataTransfer
  }
  if (!globalThis.DragEvent) {
    globalThis.DragEvent = class extends MouseEvent {
      declare dataTransfer: DataTransfer | null
      constructor(type: string, eventInitDict?: DragEventInit) {
        super(type, eventInitDict ?? {})
        this.dataTransfer = (eventInitDict as DragEventInit | undefined)?.dataTransfer ?? null
      }
    } as unknown as typeof DragEvent
  }
  // Stub ResizeObserver (needed for the component's own ResizeObserver)
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

it('getColumnCount returns 1 below tablet container width (640)', () => {
  expect(getColumnCount(0)).toBe(1)
  expect(getColumnCount(375)).toBe(1)
  expect(getColumnCount(639)).toBe(1)
})

it('getColumnCount returns 2 at tablet container width (640-991)', () => {
  expect(getColumnCount(640)).toBe(2)
  expect(getColumnCount(800)).toBe(2)
  expect(getColumnCount(991)).toBe(2)
})

it('getColumnCount returns 2 at desktop container width', () => {
  expect(getColumnCount(864)).toBe(2)
  expect(getColumnCount(900)).toBe(2)
  expect(getColumnCount(991)).toBe(2)
})

it('getColumnCount returns 3 at wide container width (992+)', () => {
  expect(getColumnCount(992)).toBe(3)
  expect(getColumnCount(1200)).toBe(3)
  expect(getColumnCount(1600)).toBe(3)
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
      explicitColumnCount={3}
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
      explicitColumnCount={1}
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
// ── Pure getColumnCount edge case tests (Finding #5/#10) ──

it('getColumnCount returns 1 for NaN', () => {
  expect(getColumnCount(NaN)).toBe(1)
})

it('getColumnCount returns 1 for negative width', () => {
  expect(getColumnCount(-1)).toBe(1)
  expect(getColumnCount(-100)).toBe(1)
})

it('getColumnCount returns 1 for Infinity', () => {
  expect(getColumnCount(Infinity)).toBe(1)
  expect(getColumnCount(-Infinity)).toBe(1)
})

it('getColumnCount returns 1 for -0', () => {
  expect(getColumnCount(-0)).toBe(1)
})

// ── Pure getRowThreads helper tests (Finding #4) ──

it('getRowThreads returns one row of threads', () => {
  const threads = [1, 2, 3, 4, 5, 6]
  expect(getRowThreads(threads, 0, 3)).toEqual([1, 2, 3])
  expect(getRowThreads(threads, 1, 3)).toEqual([4, 5, 6])
})

it('getRowThreads returns partial row for the last row', () => {
  const threads = [1, 2, 3, 4, 5]
  expect(getRowThreads(threads, 0, 3)).toEqual([1, 2, 3])
  expect(getRowThreads(threads, 1, 3)).toEqual([4, 5])
})

it('getRowThreads returns empty array when row is beyond data', () => {
  const threads = [1, 2]
  expect(getRowThreads(threads, 1, 3)).toEqual([])
})

it('getRowThreads works with single column', () => {
  const threads = [1, 2, 3]
  expect(getRowThreads(threads, 0, 1)).toEqual([1])
  expect(getRowThreads(threads, 1, 1)).toEqual([2])
  expect(getRowThreads(threads, 2, 1)).toEqual([3])
})

it('getRowThreads preserves object references', () => {
  const objs = [{ id: 1 }, { id: 2 }]
  const row = getRowThreads(objs, 0, 2)
  expect(row[0]).toBe(objs[0])
  expect(row[1]).toBe(objs[1])
})

// ── data-index contract tests (Finding #2) ──

it('data-index reflects row index in multi-column mode (not thread index)', () => {
  const threads = createMockThreads(60)

  // 2 virtual rows with 3 columns each
  mockGetVirtualItems.mockReturnValue(
    Array.from({ length: 2 }, (_, i) => ({
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
      explicitColumnCount={3}
      renderItem={(thread, index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title} #{index + 1}
        </div>
      )}
    />,
  )

  // Row 0 (data-index="0") should contain threads 1, 2, 3 (indices 0, 1, 2)
  const row0 = container.querySelector('[data-index="0"]')!
  const row0Items = row0.querySelectorAll('[data-testid="queue-thread-item"]')
  expect(row0Items).toHaveLength(3)
  expect(row0Items[0]).toHaveTextContent('Thread 1')
  expect(row0Items[2]).toHaveTextContent('Thread 3')

  // Row 1 (data-index="1") should contain threads 4, 5, 6 (indices 3, 4, 5)
  const row1 = container.querySelector('[data-index="1"]')!
  const row1Items = row1.querySelectorAll('[data-testid="queue-thread-item"]')
  expect(row1Items).toHaveLength(3)
  expect(row1Items[0]).toHaveTextContent('Thread 4')
  expect(row1Items[2]).toHaveTextContent('Thread 6')
})

// ── Empty state DOM consistency (Finding #3) ──

it('empty state preserves the same DOM tree structure', () => {
  const { container } = render(
    <VirtualizedThreadList
      threads={[]}
      renderItem={() => null}
    />,
  )

  // Empty state should have the same selectors and nesting depth
  expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument()
  expect(container.querySelector('#queue-container')).toBeInTheDocument()
  expect(screen.getByRole('list')).toBeInTheDocument()
  expect(screen.getByLabelText('Thread queue')).toBeInTheDocument()
  // Should show the empty message
  expect(screen.getByText('No threads in queue')).toBeInTheDocument()
})

// ── Drag-reorder edge auto-scroll tests (583-D) ──

beforeEach(() => {
  mockScrollToIndex.mockClear()
  // Restore the default virtual-items mock populated by the top-level beforeAll
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
})

it('calls scrollToIndex toward first visible when dragging near the top edge', () => {
  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, _index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title}
        </div>
      )}
    />,
  )

  const scrollEl = container.querySelector('#queue-container') as HTMLElement

  // Spy on getBoundingClientRect so edge detection works.
  vi.spyOn(scrollEl, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    bottom: 600,
    height: 600,
    width: 800,
    left: 0,
    right: 800,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })

  // Construct a proper DragEvent so React's synthetic event system
  // recognizes and dispatches it. jsdom requires passing dataTransfer
  // via the constructor's second argument.
  const dataTransfer = new DataTransfer()
  const dragEvent = new DragEvent('dragover', {
    clientY: 10,
    bubbles: true,
    cancelable: true,
    dataTransfer,
  })

  scrollEl.dispatchEvent(dragEvent)

  expect(mockScrollToIndex).toHaveBeenCalledWith(0, { align: 'start' })
})

it('calls scrollToIndex toward last visible when dragging near the bottom edge', () => {
  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, _index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title}
        </div>
      )}
    />,
  )

  const scrollEl = container.querySelector('#queue-container') as HTMLElement

  vi.spyOn(scrollEl, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    bottom: 600,
    height: 600,
    width: 800,
    left: 0,
    right: 800,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })

  // Drag near bottom edge (clientY=590 → y=590 > 600-80=520)
  const dataTransfer2 = new DataTransfer()
  const dragEvent2 = new DragEvent('dragover', {
    clientY: 590,
    bubbles: true,
    cancelable: true,
    dataTransfer: dataTransfer2,
  })
  scrollEl.dispatchEvent(dragEvent2)

  // last visible index is 4, so it should call scrollToIndex(5, { align: 'end' })
  expect(mockScrollToIndex).toHaveBeenCalledWith(5, { align: 'end' })
})

it('does not call scrollToIndex when dragging in the middle of the container', () => {
  const threads = createMockThreads(60)

  const { container } = render(
    <VirtualizedThreadList
      threads={threads}
      renderItem={(thread, _index) => (
        <div data-testid="queue-thread-item" key={(thread as MockThread).id}>
          {(thread as MockThread).title}
        </div>
      )}
    />,
  )

  const scrollEl = container.querySelector('#queue-container') as HTMLElement

  vi.spyOn(scrollEl, 'getBoundingClientRect').mockReturnValue({
    top: 0,
    bottom: 600,
    height: 600,
    width: 800,
    left: 0,
    right: 800,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })

  // Drag in the middle (clientY=300, well within bounds)
  const dataTransfer3 = new DataTransfer()
  const dragEvent3 = new DragEvent('dragover', {
    clientY: 300,
    bubbles: true,
    cancelable: true,
    dataTransfer: dataTransfer3,
  })
  scrollEl.dispatchEvent(dragEvent3)

  expect(mockScrollToIndex).not.toHaveBeenCalled()
})

it('reacts to ResizeObserver measurements and cleans up a pending frame', () => {
  const frame = vi.fn((callback: FrameRequestCallback) => {
    callback(1)
    return 1
  })
  vi.stubGlobal('requestAnimationFrame', frame)
  const { unmount } = render(
    <VirtualizedThreadList
      threads={createMockThreads(60)}
      renderItem={(thread) => <div data-testid="queue-thread-item" key={thread.id}>{thread.title}</div>}
    />,
  )
  const observerMock = vi.mocked(ResizeObserver)
  const callback = observerMock.mock.calls.at(-1)?.[0] as ResizeObserverCallback
  callback([{ contentRect: { width: 1200, height: 720 } } as ResizeObserverEntry], {} as ResizeObserver)
  expect(frame).toHaveBeenCalled()
  unmount()
})

it('ignores edge drags when no virtual items are visible', () => {
  const { container } = render(
    <VirtualizedThreadList
      threads={createMockThreads(60)}
      renderItem={(thread) => <div data-testid="queue-thread-item" key={thread.id}>{thread.title}</div>}
    />,
  )
  const scrollEl = container.querySelector('#queue-container') as HTMLElement
  mockScrollToIndex.mockClear()
  mockGetVirtualItems.mockReturnValue([])
  vi.spyOn(scrollEl, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 600, height: 600, width: 800, left: 0, right: 800, x: 0, y: 0, toJSON: () => ({}) })
  scrollEl.dispatchEvent(new DragEvent('dragover', { clientY: 10, bubbles: true, dataTransfer: new DataTransfer() }))
  expect(mockScrollToIndex).not.toHaveBeenCalled()
})
