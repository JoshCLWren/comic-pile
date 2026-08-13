import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueThreadCard from '../pages/QueuePage/QueueThreadCard'
import type { Thread } from '../types'

const { useCrossoverGroups } = vi.hoisted(() => ({
  useCrossoverGroups: vi.fn(() => ({ groupsByThreadId: {}, isPending: false, error: null })),
}))

vi.mock('../components/Tooltip', () => ({
  default: ({ children, content }: { children: React.ReactNode; content?: string }) => (
    <div data-testid="mock-tooltip" data-content={content}>{children}</div>
  ),
}))

vi.mock('../components/MarqueeTitle', () => ({
  MarqueeTitle: ({ title }: { title: string }) => <span data-testid="mock-marquee">{title}</span>,
}))

vi.mock('../components/PositionMenu', () => ({
  default: ({ 
    onDependencies, 
    onMoveToFront, 
    onMoveToBack, 
    onEdit, 
    onDelete 
  }: { 
    onDependencies: () => void; 
    onMoveToFront: () => void; 
    onMoveToBack: () => void; 
    onEdit: () => void; 
    onDelete: () => void 
  }) => (
    <div data-testid="mock-position-menu">
      <button type="button" data-testid="mock-position-move-to-front" onClick={onMoveToFront}>
        Move to Front
      </button>
      <button type="button" data-testid="mock-position-move-to-back" onClick={onMoveToBack}>
        Move to Back
      </button>
      <button type="button" data-testid="mock-position-edit" onClick={onEdit}>
        Edit
      </button>
      <button type="button" data-testid="mock-position-dependencies" onClick={onDependencies}>
        Dependencies
      </button>
      <button type="button" data-testid="mock-position-delete" onClick={onDelete}>
        Delete
      </button>
    </div>
  ),
}))

vi.mock('../hooks/useCrossoverGroups', () => ({
  useCrossoverGroups,
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
    snoozeDisabled: false,
    onCardClick: vi.fn(),
    onDragStart: vi.fn(),
    onDragEnd: vi.fn(),
    onDragOver: vi.fn(),
    onDrop: vi.fn(),
    onRead: vi.fn(),
    onOpenThread: vi.fn(),
    onSnooze: vi.fn(),
    onActionDelete: vi.fn(),
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

  it('opens thread details when the card surface is clicked', async () => {
    const user = userEvent.setup()
    const onCardClick = vi.fn()
    renderCard(createMockThread(), { onCardClick })

    await user.click(screen.getByTestId('queue-thread-item'))

    expect(onCardClick).toHaveBeenCalledTimes(1)
  })

  it('opens thread details from the focused card with Enter or Space', async () => {
    const user = userEvent.setup()
    const onCardClick = vi.fn()
    renderCard(createMockThread(), { onCardClick })

    const card = screen.getByRole('link', { name: 'Open Test Thread details' })
    card.focus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')

    expect(onCardClick).toHaveBeenCalledTimes(2)
  })

    it('uses the shared action menu for dependency management without opening details', async () => {
      const user = userEvent.setup()
      const onDependencies = vi.fn()
      const onCardClick = vi.fn()
      renderCard(createMockThread(), { onDependencies, onCardClick })

      await user.click(screen.getByTestId('mock-position-dependencies'))

      expect(onDependencies).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
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
    expect(useCrossoverGroups).toHaveBeenCalledWith([])
  })

  it('uses the per-thread fallback only when no batch result was supplied', () => {
    renderCard(createMockThread({ id: 27 }))

    expect(useCrossoverGroups).toHaveBeenCalledWith([27])
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
    const dependencyButton = screen.getByRole('button', { name: /view dependencies/i })
    await user.click(dependencyButton)
    expect(callbacks.onDependencies).toHaveBeenCalled()

    const openButton = screen.getByRole('button', { name: 'Open Test Thread' })
    openButton.focus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    expect(callbacks.onCardClick).toHaveBeenCalledTimes(2)

    const threadCard = screen.getByTestId('queue-thread-item')
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
    await user.click(screen.getByTestId('mock-position-dependencies'))
    expect(callbacks.onDependencies).toHaveBeenCalledTimes(2)
    })
    
    it('exercises PositionMenu descendants and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const onDependencies = vi.fn()
      const onMoveToFront = vi.fn()
      const onMoveToBack = vi.fn()
      const onEdit = vi.fn()
      const onDelete = vi.fn()
      
      renderCard(createMockThread(), { onCardClick, onDependencies, onMoveToFront, onMoveToBack, onEdit, onDelete })

      // Test PositionMenu buttons using specific testids
      const moveToFrontBtn = screen.getByTestId('mock-position-move-to-front')
      const moveToBackBtn = screen.getByTestId('mock-position-move-to-back')
      const editBtn = screen.getByTestId('mock-position-edit')
      const dependenciesBtn = screen.getByTestId('mock-position-dependencies')
      const deleteBtn = screen.getByTestId('mock-position-delete')
      
      // Test Move to Front
      await user.click(moveToFrontBtn)
      expect(onMoveToFront).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Move to Back
      await user.click(moveToBackBtn)
      expect(onMoveToBack).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Edit
      await user.click(editBtn)
      expect(onEdit).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Dependencies
      await user.click(dependenciesBtn)
      expect(onDependencies).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Delete
      await user.click(deleteBtn)
      expect(onDelete).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })
    
    it('exercises QueueThreadActions descendants and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const onRead = vi.fn()
      const onOpenThread = vi.fn()
      const onSnooze = vi.fn()
      const onActionDelete = vi.fn()
      
      renderCard(createMockThread(), { 
        onCardClick, 
        onRead, 
        onOpenThread, 
        onSnooze, 
        onActionDelete,
        snoozeLabel: 'Snooze',
        snoozeIcon: ''
      })
      
      // Get the QueueThreadActions container (it has aria-label="Actions for Test Thread")
      const actionsContainer = screen.getByRole('group', { name: /Actions for Test Thread/i })
      
      // Test QueueThreadActions buttons within the container using label text
      const readButton = actionsContainer.querySelector('button[aria-label="Read"]')
      const editButton = actionsContainer.querySelector('button[aria-label="Edit"]') // This is actually for opening thread
      const snoozeButton = actionsContainer.querySelector('button[aria-label="Snooze"]')
      const deleteButton = actionsContainer.querySelector('button[aria-label="Delete"]')
      
      // Test Read
      await user.click(readButton as HTMLElement)
      expect(onRead).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Open Thread (bound to Edit button in QueueThreadActions)
      await user.click(editButton as HTMLElement)
      expect(onOpenThread).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Snooze
      await user.click(snoozeButton as HTMLElement)
      expect(onSnooze).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Reset mocks
      vi.clearAllMocks()
      
      // Test Delete Action (bound to Delete button in QueueThreadActions)
      await user.click(deleteButton as HTMLElement)
      expect(onActionDelete).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })
    
    it('exercises CrossoverTags links and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      
      renderCard(createMockThread({ 
        id: 1, 
        title: 'Test Thread with Crossovers' 
      }), { 
        onCardClick,
        crossoverGroups: [
          { id: 11, name: 'Rotworld' },
          { id: 12, name: 'Night of the Owls' },
        ]
      })

      // Test CrossoverTags links
      const rotworldLink = screen.getByRole('link', { name: 'Rotworld' })
      const nightOfOwlsLink = screen.getByRole('link', { name: 'Night of the Owls' })
      
      // Test Rotworld link
      await user.click(rotworldLink)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Test Night of the Owls link
      await user.click(nightOfOwlsLink)
      expect(onCardClick).not.toHaveBeenCalled()
    })
    
    it('exercises drag handle and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const onDragStart = vi.fn()
      const onDragEnd = vi.fn()
      const onDragOver = vi.fn()
      const onDrop = vi.fn()
      
      renderCard(createMockThread(), { 
        onCardClick, 
        onDragStart, 
        onDragEnd, 
        onDragOver, 
        onDrop 
      })

      // Test drag handle
      const dragHandle = screen.getByRole('button', { name: /Drag to reorder/i })
      
      await user.click(dragHandle)
      expect(onCardClick).not.toHaveBeenCalled()
      
      // Simulate drag events
      fireEvent.dragStart(dragHandle)
      expect(onDragStart).toHaveBeenCalledTimes(1)
      fireEvent.dragEnd(dragHandle)
      
      const threadCard = screen.getByTestId('queue-thread-item')
      fireEvent.dragOver(threadCard)
      fireEvent.drop(threadCard)
      
      expect(onDragOver).toHaveBeenCalledTimes(1)
      expect(onDrop).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })
    
    it('exercises blocked dependency button and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const onDependencies = vi.fn()
      
      renderCard(createMockThread({ 
        id: 1, 
        title: 'Blocked Test Thread' 
      }), { 
        onCardClick, 
        onDependencies,
        isBlocked: true,
        blockingReasons: ['Blocked by: Prequel Thread']
      })

      // Test blocked dependency button
      const blockedButton = screen.getByRole('button', { name: /View dependencies for Blocked Test Thread/ })
      
      await user.click(blockedButton)
      expect(onDependencies).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })
  })