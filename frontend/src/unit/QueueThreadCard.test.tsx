import { render, screen } from '@testing-library/react'
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
      Position Menu
    </button>
  ),
}))

vi.mock('../components/Swipeable', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-swipeable">{children}</div>,
}))

vi.mock('../pages/QueuePage/CollectionBadge', () => ({
  CollectionBadge: () => <span data-testid="mock-collection-badge">Collection</span>,
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
    collection_id: null,
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
  return { props: defaults, ...render(<QueueThreadCard {...defaults} />) }
}

describe('QueueThreadCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders mobile dependency action button with correct attributes', () => {
    const thread = createMockThread()
    renderCard(thread)

    const mobileButton = screen.getByTestId('mobile-dependency-action')
    expect(mobileButton).toBeInTheDocument()
    expect(mobileButton).toHaveAttribute('aria-label', 'Manage dependencies')
    expect(mobileButton).toHaveAttribute('aria-haspopup', 'dialog')
    expect(mobileButton).toHaveAttribute('type', 'button')
  })

  it('calls onDependencies when mobile button is clicked', async () => {
    const user = userEvent.setup()
    const thread = createMockThread()
    const onDependencies = vi.fn()
    renderCard(thread, { onDependencies })

    await user.click(screen.getByTestId('mobile-dependency-action'))
    expect(onDependencies).toHaveBeenCalledTimes(1)
  })

  it('stops propagation when mobile button is clicked', async () => {
    const user = userEvent.setup()
    const thread = createMockThread()
    const onCardClick = vi.fn()
    renderCard(thread, { onCardClick })

    await user.click(screen.getByTestId('mobile-dependency-action'))
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

  it('renders collection badge when thread has collection_id', () => {
    const thread = createMockThread({ collection_id: 42 })
    renderCard(thread)
    expect(screen.getByTestId('mock-collection-badge')).toBeInTheDocument()
  })
})
