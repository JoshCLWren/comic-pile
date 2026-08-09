import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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
      Position Menu
    </button>
  ),
}))

vi.mock('../components/Swipeable', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-swipeable">{children}</div>,
}))

vi.mock('../hooks/useCrossoverGroups', () => ({
  useCrossoverGroups: () => ({ groupsByThreadId: {}, isPending: false, error: null }),
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
    snoozeIcon: '',
    snoozeLabel: '',
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
  return {
    props: defaults,
    ...render(
      <MemoryRouter>
        <QueueThreadCard {...defaults} />
      </MemoryRouter>,
    ),
  }
}

describe('QueueThreadCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the shared thread action menu as the discoverable card action', () => {
    renderCard(createMockThread())

    expect(screen.getAllByTestId('mock-position-menu')).toHaveLength(1)
    expect(screen.queryByTestId('mobile-dependency-action')).not.toBeInTheDocument()
  })

  it('uses the shared action menu for dependency management', async () => {
    const user = userEvent.setup()
    const onDependencies = vi.fn()
    renderCard(createMockThread(), { onDependencies })

    await user.click(screen.getByTestId('mock-position-menu'))
    expect(onDependencies).toHaveBeenCalledTimes(1)
  })

  it('does not treat shared action-menu keyboard activation as card activation', () => {
    const onCardClick = vi.fn()
    renderCard(createMockThread(), { onCardClick })

    const actionMenu = screen.getByTestId('mock-position-menu')
    fireEvent.keyDown(actionMenu, { key: 'Enter' })
    fireEvent.keyDown(actionMenu, { key: ' ' })

    expect(onCardClick).not.toHaveBeenCalled()
  })

  it('renders blocked thread explanation button when thread is blocked', () => {
    const thread = createMockThread()
    renderCard(thread, {
      isBlocked: true,
      blockingReasons: ['Blocked by: Prequel Thread'],
    })

    const blockedButton = screen.getByRole('button', { name: /View dependencies for Test Thread/ })
    expect(blockedButton).toBeInTheDocument()
  })

  it('does not render blocked explanation when thread is not blocked', () => {
    const thread = createMockThread()
    renderCard(thread)

    expect(screen.queryByRole('button', { name: /View dependencies for/ })).not.toBeInTheDocument()
  })

  it('renders thread title', () => {
    const thread = createMockThread({ title: 'Amazing Spider-Man' })
    renderCard(thread)
    expect(screen.getByTestId('mock-marquee')).toHaveTextContent('Amazing Spider-Man')
  })

  it('renders format label', () => {
    const thread = createMockThread({ format: 'Trade Paperback' })
    renderCard(thread)
    expect(screen.getByText('Trade Paperback')).toBeInTheDocument()
  })

  it('renders issues remaining count', () => {
    const thread = createMockThread({ issues_remaining: 7 })
    renderCard(thread)
    expect(screen.getByText('7 issues remaining')).toBeInTheDocument()
  })

  it('renders next unread issue number when migrated and available', () => {
    const thread = createMockThread({
      issues_remaining: 3,
      next_unread_issue_number: '5',
    })
    renderCard(thread)
    expect(screen.getByText(/Up next: #5/)).toBeInTheDocument()
    expect(screen.getByText(/3 remaining/)).toBeInTheDocument()
  })

  it('renders notes when present', () => {
    const thread = createMockThread({ notes: 'This is a note' })
    renderCard(thread)
    expect(screen.getByText('This is a note')).toBeInTheDocument()
  })

  it('renders multiple crossover memberships supplied by the Queue batch loader', () => {
    renderCard(createMockThread(), {
      crossoverGroups: [
        { id: 11, name: 'Rotworld' },
        { id: 12, name: 'Night of the Owls' },
      ],
    })

    expect(screen.getByRole('link', { name: 'Rotworld' })).toHaveAttribute('href', '/crossovers?group=11')
    expect(screen.getByRole('link', { name: 'Night of the Owls' })).toHaveAttribute('href', '/crossovers?group=12')
  })

  it('shows a crossover loading state without inventing empty membership', () => {
    renderCard(createMockThread(), { crossoverGroups: [], crossoverGroupsLoading: true })

    expect(screen.getByText('Loading crossovers…')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Crossovers' })).not.toBeInTheDocument()
  })

  it('shows a non-blocking crossover error state when membership loading fails', () => {
    renderCard(createMockThread(), { crossoverGroups: [], crossoverGroupsError: true })

    expect(screen.getByText('Crossovers unavailable')).toBeInTheDocument()
    expect(screen.getByText('Test Thread')).toBeInTheDocument()
  })

  it('keeps the empty crossover state visually quiet once loading completes', () => {
    renderCard(createMockThread(), { crossoverGroups: [], crossoverGroupsLoading: false })

    expect(screen.queryByText('Loading crossovers…')).not.toBeInTheDocument()
    expect(screen.queryByText('Crossovers unavailable')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Crossovers' })).not.toBeInTheDocument()
  })

  it('handles keyboard, drag, blocked dependency, and all position-menu callbacks', async () => {
    const user = userEvent.setup()
    const callbacks = Object.fromEntries([
      'onCardClick', 'onDragStart', 'onDragEnd', 'onDragOver', 'onDrop', 'onDependencies',
      'onMoveToFront', 'onMoveToBack', 'onReposition', 'onEdit', 'onDelete',
    ].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>
    renderCard(createMockThread({ total_issues: null, issues_remaining: 0, notes: null }), {
      isBlocked: true,
      blockingReasons: ['Read A first', 'Read B first'],
      isDragOver: true,
      ...callbacks,
    })
    const card = screen.getByRole('button', { name: /view dependencies/i })
    await user.click(card)
    expect(callbacks.onDependencies).toHaveBeenCalled()
    const threadCard = screen.getByText('Comic').closest('[role="button"]') as HTMLElement
    fireEvent.keyDown(threadCard, { key: 'Enter' })
    fireEvent.keyDown(threadCard, { key: ' ' })
    expect(callbacks.onCardClick).toHaveBeenCalledTimes(2)
    const drag = screen.getByRole('button', { name: 'Drag to reorder' })
    await user.click(drag)
    fireEvent.dragStart(drag)
    fireEvent.dragEnd(drag)
    fireEvent.dragOver(threadCard)
    fireEvent.drop(threadCard)
    expect(callbacks.onDragStart).toHaveBeenCalled()
    expect(callbacks.onDragEnd).toHaveBeenCalled()
    expect(callbacks.onDragOver).toHaveBeenCalled()
    expect(callbacks.onDrop).toHaveBeenCalled()
    await user.click(screen.getByTestId('mock-position-menu'))
    expect(callbacks.onDependencies).toHaveBeenCalledTimes(2)
  })
})