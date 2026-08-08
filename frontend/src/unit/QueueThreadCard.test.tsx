import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueThreadCard from '../pages/QueuePage/QueueThreadCard'
import type { Thread } from '../types'

vi.mock('../components/Tooltip', () => ({
  default: ({ children, content }: { children: React.ReactNode; content?: string }) => (
    <div data-testid="mock-tooltip" data-content={content}>{children}</div>
  ),
}))

vi.mock('../components/MarqueeTitle', () => ({
  MarqueeTitle: ({ title }: { title: string }) => <span data-testid="mock-marquee">{title}</span>,
}))

vi.mock('../components/PositionMenu', () => ({
  default: ({ onDependencies }: { onDependencies: () => void }) => (
    <button type="button" data-testid="mock-position-menu" onClick={onDependencies}>
      More actions
    </button>
  ),
}))

function createMockThread(overrides: Partial<Thread> = {}): Thread {
  return {
    id: 1,
    title: 'Test Thread',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    next_unread_issue_id: null,
    next_unread_issue_number: null,
    reading_progress: '50.0',
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2024-01-01T00:00:00.000Z',
    ...overrides,
  }
}

function renderCard(thread: Thread, overrides: Partial<Parameters<typeof QueueThreadCard>[0]> = {}) {
  const defaults = {
    thread,
    index: 0,
    isBlocked: false,
    blockingReasons: [] as string[],
    isDragOver: false,
    snoozeIcon: '😴',
    snoozeLabel: 'Snooze',
    onCardClick: vi.fn(),
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onDragOver: vi.fn(),
    onDrop: vi.fn(),
    onSwipeRead: vi.fn(),
    onSwipeEdit: vi.fn(),
    onSwipeSnooze: vi.fn(),
    onSwipeDelete: vi.fn(),
    onMoveToFront: vi.fn(),
    onMoveToBack: vi.fn(),
    onReposition: vi.fn(),
    onEdit: vi.fn(),
    onDependencies: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  }
  return { props: defaults, ...render(<QueueThreadCard {...defaults} />) }
}

describe('QueueThreadCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders every former gesture action as a visible labeled button', () => {
    renderCard(createMockThread())

    expect(screen.getByRole('button', { name: /Read/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Edit/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Snooze/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Delete/ })).toBeVisible()
  })

  it('runs visible actions without activating the card', async () => {
    const user = userEvent.setup()
    const onCardClick = vi.fn()
    const onSwipeRead = vi.fn()
    const onSwipeEdit = vi.fn()
    const onSwipeSnooze = vi.fn()
    const onSwipeDelete = vi.fn()
    renderCard(createMockThread(), {
      onCardClick,
      onSwipeRead,
      onSwipeEdit,
      onSwipeSnooze,
      onSwipeDelete,
    })

    await user.click(screen.getByRole('button', { name: /Read/ }))
    await user.click(screen.getByRole('button', { name: /Edit/ }))
    await user.click(screen.getByRole('button', { name: /Snooze/ }))
    await user.click(screen.getByRole('button', { name: /Delete/ }))

    expect(onSwipeRead).toHaveBeenCalledOnce()
    expect(onSwipeEdit).toHaveBeenCalledOnce()
    expect(onSwipeSnooze).toHaveBeenCalledOnce()
    expect(onSwipeDelete).toHaveBeenCalledOnce()
    expect(onCardClick).not.toHaveBeenCalled()
  })

  it('uses the shared action menu for dependency management', async () => {
    const user = userEvent.setup()
    const onDependencies = vi.fn()
    renderCard(createMockThread(), { onDependencies })

    await user.click(screen.getByTestId('mock-position-menu'))
    expect(onDependencies).toHaveBeenCalledTimes(1)
  })

  it('does not treat action-menu keyboard activation as card activation', () => {
    const onCardClick = vi.fn()
    renderCard(createMockThread(), { onCardClick })

    const actionMenu = screen.getByTestId('mock-position-menu')
    fireEvent.keyDown(actionMenu, { key: 'Enter' })
    fireEvent.keyDown(actionMenu, { key: ' ' })

    expect(onCardClick).not.toHaveBeenCalled()
  })

  it('renders blocked thread explanation button when thread is blocked', () => {
    renderCard(createMockThread(), {
      isBlocked: true,
      blockingReasons: ['Blocked by: Prequel Thread'],
    })

    expect(screen.getByRole('button', { name: /View dependencies for Test Thread/ })).toBeInTheDocument()
  })

  it('renders thread metadata and supports keyboard and drag interactions', () => {
    const callbacks = Object.fromEntries([
      'onCardClick', 'onDragStart', 'onDragEnd', 'onDragOver', 'onDrop',
    ].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>
    renderCard(createMockThread({ next_unread_issue_number: '5', notes: 'A note' }), callbacks)

    expect(screen.getByTestId('mock-marquee')).toHaveTextContent('Test Thread')
    expect(screen.getByText('Comic')).toBeInTheDocument()
    expect(screen.getByText(/Up next: #5/)).toBeInTheDocument()
    expect(screen.getByText('A note')).toBeInTheDocument()

    const threadCard = screen.getByText('Comic').closest('[role="button"]') as HTMLElement
    fireEvent.keyDown(threadCard, { key: 'Enter' })
    fireEvent.keyDown(threadCard, { key: ' ' })
    expect(callbacks.onCardClick).toHaveBeenCalledTimes(2)

    const drag = screen.getByRole('button', { name: 'Drag to reorder' })
    fireEvent.dragStart(drag)
    fireEvent.dragEnd(drag)
    fireEvent.dragOver(threadCard)
    fireEvent.drop(threadCard)
    expect(callbacks.onDragStart).toHaveBeenCalled()
    expect(callbacks.onDragEnd).toHaveBeenCalled()
    expect(callbacks.onDragOver).toHaveBeenCalled()
    expect(callbacks.onDrop).toHaveBeenCalled()
  })
})
