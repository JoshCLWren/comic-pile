import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { QueueList } from '../pages/QueuePage/QueueList'
import { VIRTUALIZATION_THRESHOLD } from '../pages/QueuePage/VirtualizedThreadList'

interface MockThread {
  id: number
  title: string
  format: string
  issues_remaining: number
  total_issues: number | null
  next_unread_issue_number?: string | null
  queue_position: number
  status: string
  is_blocked: boolean
  blocking_reasons: string[]
  created_at: string
}

function makeThreads(count: number): MockThread[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    title: `Thread ${i + 1}`,
    format: 'issue',
    issues_remaining: 1,
    total_issues: 1,
    next_unread_issue_number: null,
    queue_position: i + 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: new Date().toISOString(),
  }))
}

const virtualItems = ({ start }: { start: number }) => ({
  key: start / 160,
  index: start / 160,
  start,
  end: start + 160,
  size: 160,
  lane: 0,
})

// Window-virtualized rows: three virtual items are enough to assert the
// structural scroll contract below.
const mockGetVirtualItems = vi.fn(() => [
  virtualItems({ start: 0 }),
  virtualItems({ start: 160 }),
  virtualItems({ start: 320 }),
])

vi.mock('@tanstack/react-virtual', () => ({
  useWindowVirtualizer: () => ({
    getVirtualItems: mockGetVirtualItems,
    getTotalSize: () => 480,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}))

function renderList(count: number) {
  const threads = makeThreads(count)
  return render(
    <QueueList
      activeThreads={threads}
      filteredThreads={threads}
      reorderError={null}
      isSearching={false}
      renderItem={(thread) => (
        <div data-testid="queue-thread-item" key={thread.id}>
          {thread.title}
        </div>
      )}
    />,
  )
}

/** Asserts a `#queue-container` is not a nested/independent scroll region. */
function expectNotInternalScrollRegion(container: HTMLElement) {
  // No overflow that turns the element into its own scrolling surface.
  const overflowY = getComputedStyle(container).overflowY
  expect(['auto', 'scroll'].includes(overflowY)).toBe(false)
  // No viewport-derived fixed inline height that would "box in" the queue.
  expect(container.style.height).toBe('')
}

it('keeps the plain list (< threshold) on document scroll with no internal region', () => {
  const { container } = renderList(VIRTUALIZATION_THRESHOLD)

  const list = container.querySelector('#queue-container') as HTMLElement
  expect(list).toBeInTheDocument()
  expectNotInternalScrollRegion(list)
  expect(screen.getAllByTestId('queue-thread-item')).toHaveLength(VIRTUALIZATION_THRESHOLD)
})

it('keeps the virtualized list (> threshold) on document scroll with no internal region or fixed height box', () => {
  const { container } = renderList(VIRTUALIZATION_THRESHOLD + 1)

  const list = container.querySelector('#queue-container') as HTMLElement
  expect(list).toBeInTheDocument()
  expectNotInternalScrollRegion(list)
  // The spacer grows in document flow rather than clamping to the viewport.
  const spacer = list.firstElementChild as HTMLElement
  expect(spacer.style.position).toBe('relative')
  expect(parseFloat(spacer.style.height)).toBeGreaterThan(0)
})

it('uses the identical queue-container selectors for both presentations', () => {
  const plain = renderList(VIRTUALIZATION_THRESHOLD)
  const virtualized = renderList(VIRTUALIZATION_THRESHOLD + 1)

  const plainList = plain.container.querySelector('#queue-container')
  const virtualizedList = virtualized.container.querySelector('#queue-container')
  if (!plainList || !virtualizedList) {
    console.log('plain container innerHTML:', plain.container.innerHTML)
    console.log('virtualized container innerHTML:', virtualized.container.innerHTML)
  }
  expect(plainList).toBeInTheDocument()
  expect(virtualizedList).toBeInTheDocument()
  for (const node of [plainList, virtualizedList]) {
    expect(node.getAttribute('data-testid')).toBe('queue-thread-list')
    expect(node.getAttribute('role')).toBe('list')
    expect(node.getAttribute('aria-label')).toBe('Thread queue')
  }
  // Neither presentation boxes the queue into a fixed-height inset region.
  expectNotInternalScrollRegion(plainList as HTMLElement)
  expectNotInternalScrollRegion(virtualizedList as HTMLElement)
})
