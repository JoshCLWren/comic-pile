import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueThreadCard from '../pages/QueuePage/QueueThreadCard'
import type { BlockingDependency, ThreadListItem } from '../types'
import type { components } from '../generated/openapi'
type ComicVineMappingHealth = components['schemas']['ComicVineMappingHealth']

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
    onDelete,
    onSnooze,
    snoozeLabel,
    snoozeDisabled,
  }: {
    onDependencies: () => void
    onMoveToFront: () => void
    onMoveToBack: () => void
    onEdit: () => void
    onDelete: () => void
    onSnooze?: (thread: ThreadListItem) => void
    snoozeLabel?: string
    snoozeDisabled?: boolean
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
      {snoozeLabel && (
        <button
          type="button"
          data-testid="mock-position-snooze"
          // SAFETY: the card forwards the thread to onSnooze without reading its fields
          onClick={onSnooze ? () => onSnooze({} as ThreadListItem) : undefined}
          disabled={snoozeDisabled}
        >
          {snoozeLabel}
        </button>
      )}
      <button type="button" data-testid="mock-position-dependencies" onClick={onDependencies}>
        Dependencies
      </button>
      <button type="button" data-testid="mock-position-delete" onClick={onDelete}>
        Delete
      </button>
    </div>
  ),
}))

vi.mock('../components/QueueMapSeriesDialog', () => ({
  default: ({
    isOpen,
    threadTitle,
    onClose,
    onMapped,
  }: {
    isOpen: boolean
    threadTitle: string
    onClose: () => void
    onMapped: (ids: number[]) => void
  }) =>
    isOpen ? (
      <div data-testid="mock-map-series-dialog">
        <span data-testid="mock-map-series-thread">{threadTitle}</span>
        <button type="button" data-testid="mock-map-series-close" onClick={onClose}>
          Close
        </button>
        <button type="button" data-testid="mock-map-series-done" onClick={() => onMapped([7])}>
          Done
        </button>
      </div>
    ) : null,
}))

function createMockThread(overrides: Partial<ThreadListItem> = {}): ThreadListItem {
  return {
    id: 1,
    title: 'Test Thread',
    format: 'Comic',
    issues_remaining: 5,
    total_issues: 10,
    next_unread_issue_number: null,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    notes: null,
    last_activity_at: null,
    created_at: '2024-01-01T00:00:00.000Z',
    comicvine_mapping: null,
    ...overrides,
  }
}

function renderCard(thread: ThreadListItem, overrides: Partial<Parameters<typeof QueueThreadCard>[0]> = {}) {
  const defaults = {
    thread,
    index: 0,
    isBlocked: false,
    // SAFETY: this fixture declares no blocking dependencies
    blockingDependencies: [] as BlockingDependency[],
    // SAFETY: empty literal satisfies the DependencyGroupSummary subset this card renders.
    crossoverGroups: [] as { id: number; name: string }[],
    crossoverGroupsLoading: false,
    crossoverGroupsError: false,
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
    onSnooze: vi.fn(),
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
      blockingDependencies: [],
    })

    const blockedButton = screen.getByRole('button', { name: /View dependencies for Test Thread/ })
    expect(blockedButton).toBeInTheDocument()
  })

  it('names the blocking dependency and links to the blocker thread', () => {
    const blocker: BlockingDependency = {
      thread_id: 42,
      thread_title: 'Prequel Thread',
      issue_number: '3',
      label: 'Needs Prequel Thread: #3',
    }
    renderCard(createMockThread(), {
      isBlocked: true,
      blockingDependencies: [
        blocker,
        { ...blocker, thread_id: 43, thread_title: 'Other Blocker', label: 'Needs Other Blocker: #1' },
      ],
    })

    const blockerLink = screen.getByRole('link', { name: 'Open Prequel Thread' })
    expect(blockerLink).toHaveAttribute('href', '/thread/42')
    expect(blockerLink).toHaveTextContent('Needs Prequel Thread: #3')
    expect(screen.getByRole('link', { name: 'Open Other Blocker' })).toHaveTextContent('Needs Other Blocker: #1')
  })

  it('does not render blocked explanation when thread is not blocked', () => {
    const thread = createMockThread()
    renderCard(thread)

    expect(screen.queryByRole('button', { name: /View dependencies for/ })).not.toBeInTheDocument()
  })

  it('renders canonical blockers and their editors instead of legacy dependency copy', () => {
    renderCard(createMockThread(), {
      isBlocked: true,
      readingBoundary: {
        thread_id: 1,
        state: 'blocked',
        summary: 'Saga #6 is waiting on 1 live requirement.',
        blockers: [
          {
            kind: 'hold',
            origin: 'reading_list',
            reason: 'Hold in Ultimate: waiting on One Year In #1',
            waiting_on: [
              {
                issue_id: 9,
                thread_id: 2,
                thread_title: 'One Year In',
                issue_number: '1',
                label: 'One Year In #1',
                volume_label: 'One Year In (2025)',
              },
            ],
            editor: { kind: 'reading_list', list_id: 4, label: 'Ultimate' },
          },
        ],
      },
    })

    expect(screen.getByTestId('canonical-reading-boundary')).toBeInTheDocument()
    expect(screen.getByText('Saga #6 is waiting on 1 live requirement.')).toBeInTheDocument()
    expect(screen.getByText('Hold in Ultimate: waiting on One Year In #1')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open One Year In issue #1' })).toHaveAttribute(
      'href',
      '/thread/2?issue=9#issue-9',
    )
    expect(screen.getByRole('link', { name: 'Edit Ultimate' })).toHaveAttribute('href', '/reading-lists/4')
    // The legacy fallback only exists for deployments without canonical data.
    expect(screen.queryByTestId('eligibility-explanation')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /View dependencies for/ })).not.toBeInTheDocument()
  })

  it('keeps the legacy blocker explanation when canonical boundaries are unavailable', () => {
    renderCard(createMockThread({ blocking_reasons: ['Waiting on Prequel Thread #3'] }), {
      isBlocked: true,
      blockingDependencies: [
        { thread_id: 42, thread_title: 'Prequel Thread', issue_number: '3', label: 'Needs Prequel Thread: #3' },
      ],
      readingBoundary: {
        thread_id: 1,
        state: 'unavailable',
        summary: 'Option E is not active for Test Thread.',
      },
    })

    expect(screen.queryByTestId('canonical-reading-boundary')).not.toBeInTheDocument()
    expect(screen.getByTestId('eligibility-explanation')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Prequel Thread' })).toHaveAttribute('href', '/thread/42')
    expect(screen.getByText('Waiting on Prequel Thread #3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View dependencies for Test Thread' })).toBeInTheDocument()
  })

  it('expands historical associations without opening Thread Detail', async () => {
    const user = userEvent.setup()
    const onCardClick = vi.fn()
    renderCard(createMockThread(), {
      onCardClick,
      readingBoundary: {
        thread_id: 1,
        state: 'available',
        summary: 'Saga #6 is available next.',
        historical: [
          {
            kind: 'legacy_dependency',
            label: 'Prequel → Saga',
            detail: 'Historical association; not an active reading requirement.',
            editor: { kind: 'prerequisite', thread_id: 1, label: 'Saga prerequisites' },
          },
        ],
      },
    })

    await user.click(screen.getByText('Historical associations — not active blockers'))

    expect(onCardClick).not.toHaveBeenCalled()
  })

  it('shows historical-only associations without inventing a blocked state', () => {
    renderCard(createMockThread(), {
      isBlocked: false,
      readingBoundary: {
        thread_id: 1,
        state: 'available',
        summary: 'Saga #6 is available next.',
        historical: [
          {
            kind: 'converted_prerequisite',
            label: 'Prequel → Saga',
            detail: 'Converted generated association; not an active reading requirement.',
          },
        ],
      },
    })

    expect(screen.getByText('Saga #6 is available next.')).toBeInTheDocument()
    expect(screen.queryByText(/Read & Rate unlocks/i)).not.toBeInTheDocument()
    expect(screen.getByText('Historical associations — not active blockers')).toBeInTheDocument()
  })

  it('distinguishes blocked Queue cards with continuity styling instead of danger-red', () => {
    const { unmount } = renderCard(createMockThread())
    const unblocked = screen.getByTestId('queue-thread-item')
    expect(unblocked.className).not.toMatch(/bg-red-500/)
    expect(unblocked.className).not.toMatch(/theme-danger/)
    expect(unblocked.className).not.toMatch(/theme-continuity-accent/)
    expect(screen.queryByLabelText('Blocked series')).not.toBeInTheDocument()
    expect(screen.queryByTestId('queue-thread-blocked-detail')).not.toBeInTheDocument()
    unmount()

    renderCard(createMockThread(), {
      isBlocked: true,
      blockingDependencies: [],
    })
    const blocked = screen.getByTestId('queue-thread-item')
    expect(blocked.className).not.toMatch(/bg-red-500/)
    expect(blocked.className).not.toMatch(/theme-danger/)
    expect(screen.getByLabelText('Blocked series')).toHaveClass('text-[var(--theme-continuity-accent)]')

    const detail = screen.getByTestId('queue-thread-blocked-detail')
    expect(detail.className).toMatch(/theme-continuity-accent/)
    expect(detail.className).not.toMatch(/bg-red-500/)
    expect(detail.className).not.toMatch(/text-red-/)
    expect(detail.className).not.toMatch(/theme-danger/)
  })

  it('communicates available vs disabled actions on blocked rows only', () => {
    renderCard(createMockThread(), {
      isBlocked: true,
      readDisabled: true,
      readDisabledReason: 'Blocked by a prerequisite',
      snoozeDisabled: true,
      snoozeLabel: 'Snooze',
      snoozeIcon: '😴',
      blockingDependencies: [
        { thread_id: 42, thread_title: 'Prequel Thread', issue_number: '3', label: 'Needs Prequel Thread: #3' },
      ],
    })

    const detail = screen.getByTestId('queue-thread-blocked-detail')
    expect(detail).toHaveTextContent(
      'Read & Rate unlocks once the active reading requirements are satisfied.',
    )

    const actionsGroup = screen.getByRole('group', { name: 'Actions for Test Thread' })
    const readButton = within(actionsGroup).getByRole('button', { name: 'Read & Rate' })
    expect(readButton).toBeDisabled()

    expect(screen.getByRole('link', { name: 'Open Prequel Thread' })).toHaveAttribute(
      'href',
      '/thread/42',
    )
  })

  it('includes Snooze in blocked-row guidance when snooze is available', () => {
    renderCard(createMockThread(), {
      isBlocked: true,
      readDisabled: true,
      readDisabledReason: 'Blocked by a prerequisite',
      snoozeDisabled: false,
      snoozeLabel: 'Snooze',
      snoozeIcon: '😴',
      blockingDependencies: [
        { thread_id: 42, thread_title: 'Prequel Thread', issue_number: '3', label: 'Needs Prequel Thread: #3' },
      ],
    })

    const detail = screen.getByTestId('queue-thread-blocked-detail')
    expect(detail).toHaveTextContent(
      'Read & Rate unlocks once the active reading requirements are satisfied.',
    )
  })

  it('does not show blocked-row action guidance on unblocked rows', () => {
    renderCard(createMockThread(), {
      isBlocked: false,
      readDisabled: false,
      snoozeDisabled: false,
      snoozeLabel: 'Snooze',
      snoozeIcon: '😴',
    })

    expect(screen.queryByTestId('queue-thread-blocked-detail')).not.toBeInTheDocument()
    expect(screen.queryByText(/Read & Rate unlocks/i)).not.toBeInTheDocument()

    const actionsGroup = screen.getByRole('group', { name: 'Actions for Test Thread' })
    expect(within(actionsGroup).getByRole('button', { name: 'Read & Rate' })).not.toBeDisabled()
  })

  it('keeps crossover load errors out of dependency continuity styling', () => {
    renderCard(createMockThread(), {
      crossoverGroups: [],
      crossoverGroupsError: true,
    })

    expect(screen.getByText('Crossovers unavailable')).toHaveClass('text-red-300/80')
  })

  it('still disables Read & Rate when the thread is blocked', () => {
    renderCard(createMockThread(), {
      isBlocked: true,
      readDisabled: true,
      readDisabledReason: 'Blocked by a prerequisite',
    })

    expect(screen.getByRole('button', { name: 'Read & Rate' })).toBeDisabled()
  })

  it('composes hover with the drag-over tint instead of overriding it on the shared row', () => {
    renderCard(createMockThread(), { isDragOver: true })

    const card = screen.getByTestId('queue-thread-item')
    expect(card.className).toMatch(/hover:bg-white\/\[0\.04\]/)
    expect(card.className).not.toMatch(/bg-amber-500\/10/)

    const tint = screen.getByTestId('queue-thread-drag-over')
    expect(tint).toHaveClass('bg-amber-500/10')
    expect(tint).toHaveClass('pointer-events-none', 'absolute', 'inset-0')
  })

  it('does not render the drag-over tint when the row is not a drop target', () => {
    renderCard(createMockThread(), { isDragOver: false })

    expect(screen.queryByTestId('queue-thread-drag-over')).not.toBeInTheDocument()
  })

  it('keeps the drag-over tint while a blocked row still carries its continuity cues', () => {
    renderCard(createMockThread(), {
      isDragOver: true,
      isBlocked: true,
      blockingDependencies: [],
    })

    expect(screen.getByTestId('queue-thread-drag-over')).toHaveClass('bg-amber-500/10')
    expect(screen.getByLabelText('Blocked series')).toHaveClass('text-[var(--theme-continuity-accent)]')
    expect(screen.getByTestId('queue-thread-blocked-detail').className).toMatch(/theme-continuity-accent/)
  })

  it('renders thread title', () => {
    const thread = createMockThread({ title: 'Amazing Spider-Man' })
    renderCard(thread)
    expect(screen.getByTestId('mock-marquee')).toHaveTextContent('Amazing Spider-Man')
  })

  it('keeps the title button from collapsing and switches layout on container width, not viewport md', () => {
    const thread = createMockThread({ title: 'Very Long Thread Title That Would Previously Collapse' })
    const { unmount } = renderCard(thread)

    const titleButton = screen.getByRole('button', { name: `Open ${thread.title}` })
    expect(titleButton).toHaveClass('min-w-24', 'flex-1')

    // The row must decide stacked vs horizontal from the actual list container
    // width (@2xl container query), not the raw viewport `md` breakpoint that
    // ignores the width already consumed by the desktop sidebar (#2284).
    const card = screen.getByTestId('queue-thread-item')
    expect(card).toHaveClass('flex-col')
    expect(card).not.toHaveClass('md:flex-row')
    expect(card).toHaveClass('@2xl:flex-row')

    unmount()
  })

  it('renders format label', () => {
    const thread = createMockThread({ format: 'Trade Paperback' })
    renderCard(thread)
    expect(screen.getByText('Trade Paperback')).toBeInTheDocument()
  })

  it('renders series metadata for a fully mapped series with year, volume, and publisher', () => {
    const thread = createMockThread({
      title: 'Uncanny X-Men',
      series_metadata: {
        year: 2013,
        volume: 'Vol. 3',
        publisher: 'Marvel',
      },
    })
    renderCard(thread)

    expect(screen.getByText('2013')).toBeInTheDocument()
    expect(screen.getByText('Vol. 3')).toBeInTheDocument()
    expect(screen.getByText('Marvel')).toBeInTheDocument()
  })

  it('renders series metadata for a partially mapped series with only year and publisher', () => {
    const thread = createMockThread({
      title: 'Some Series',
      series_metadata: {
        year: 2020,
        volume: null,
        publisher: 'DC Comics',
      },
    })
    renderCard(thread)

    expect(screen.getByText('2020')).toBeInTheDocument()
    expect(screen.getByText('DC Comics')).toBeInTheDocument()
    expect(screen.queryByText('Vol.')).not.toBeInTheDocument()
  })

  it('renders series metadata for a mapped series with only volume', () => {
    const thread = createMockThread({
      title: 'Some Series',
      series_metadata: {
        year: null,
        volume: 'Vol. 1',
        publisher: null,
      },
    })
    renderCard(thread)

    expect(screen.getByText('Vol. 1')).toBeInTheDocument()
    expect(screen.queryByText('2020')).not.toBeInTheDocument()
    expect(screen.queryByText('DC Comics')).not.toBeInTheDocument()
  })

  it('renders "Unmapped series" fallback when series_metadata is null', () => {
    const thread = createMockThread({
      title: 'Unknown Series',
      series_metadata: null,
    })
    renderCard(thread)

    expect(screen.getByTestId('series-unmapped')).toHaveTextContent('Unmapped series')
  })

  it('renders "No confirmed metadata" when series_metadata exists but all fields are null', () => {
    const thread = createMockThread({
      title: 'Mapped But No Metadata',
      series_metadata: {
        year: null,
        volume: null,
        publisher: null,
      },
    })
    renderCard(thread)

    expect(screen.getByText('No confirmed metadata')).toBeInTheDocument()
  })

  it('renders singular "1 issue remaining" for a single remaining issue', () => {
    const thread = createMockThread({ issues_remaining: 1 })
    renderCard(thread)
    expect(screen.getByText('1 issue remaining')).toBeInTheDocument()
  })

  it('renders issues remaining count', () => {
    const thread = createMockThread({ issues_remaining: 7 })
    renderCard(thread)
    expect(screen.getByText('7 issues remaining')).toBeInTheDocument()
  })

  it('hides "Up next" for blocked threads even when a next unread issue exists', () => {
    const thread = createMockThread({
      total_issues: 10,
      issues_remaining: 3,
      next_unread_issue_number: '5',
      is_blocked: true,
    })
    renderCard(thread, { isBlocked: true, blockingDependencies: [{ thread_id: 2, thread_title: 'Prerequisite', issue_number: '4', label: 'Blocked by a prerequisite' }] })
    expect(screen.queryByText(/Up next/)).not.toBeInTheDocument()
    expect(screen.getByText('3 issues remaining')).toBeInTheDocument()
  })

  it('renders singular "1 issue remaining" in the "Up next" line when only one issue remains', () => {
    const thread = createMockThread({
      total_issues: 10,
      issues_remaining: 1,
      next_unread_issue_number: '5',
    })
    renderCard(thread)
    expect(screen.getByText('Up next: #5 · 1 issue remaining')).toBeInTheDocument()
  })

  it('renders next unread issue number when migrated and available', () => {
    const thread = createMockThread({
      issues_remaining: 3,
      next_unread_issue_number: '5',
    })
    renderCard(thread)
    expect(screen.getByText('Up next: #5 · 3 issues remaining')).toBeInTheDocument()
  })

  it('renders notes when present', () => {
    const thread = createMockThread({ notes: 'This is a note' })
    renderCard(thread)
    expect(screen.getByText('This is a note')).toBeInTheDocument()
  })

  it('wrap-breaks long imported URLs in notes so they cannot bleed across cards', () => {
    const thread = createMockThread({
      notes:
        'Imported: https://www.leagueofcomicgeeks.com/issue/14276/annihilation-protocol-the-gathering-storm-annual-special-edition-collectors-variant',
    })
    renderCard(thread)

    const notes = screen.getByText(/Imported: https:\/\/www\.leagueofcomicgeeks\.com/)
    expect(notes).toHaveClass('[overflow-wrap:anywhere]', 'break-words')
  })

  it('exposes the full thread title via native tooltip on the title button', () => {
    const thread = createMockThread({ title: 'Free Comic Book Day 2025: Amazing Spider-Man' })
    renderCard(thread)

    expect(screen.getByRole('button', { name: `Open ${thread.title}` })).toHaveAttribute(
      'title',
      thread.title,
    )
  })

  it('renders multiple crossover memberships supplied by the Queue batch loader', () => {
    renderCard(createMockThread(), {
      crossoverGroups: [
        { id: 11, name: 'Rotworld' },
        { id: 12, name: 'Night of the Owls' },
      ],
    })

    expect(screen.getByRole('link', { name: 'Rotworld' })).toHaveAttribute('href', '/continuity-plans/events?group=11')
    expect(screen.getByRole('link', { name: 'Night of the Owls' })).toHaveAttribute('href', '/continuity-plans/events?group=12')
  })

  it('renders exactly the memberships the parent resolved for this card', () => {
    renderCard(createMockThread({ id: 27 }), {
      crossoverGroups: [{ id: 31, name: 'Blackest Night' }],
    })

    expect(screen.getByRole('link', { name: 'Blackest Night' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Rotworld' })).not.toBeInTheDocument()
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
    // SAFETY: every callback name is paired with a vi.fn of the same arity
    const callbacks = Object.fromEntries([
      'onCardClick', 'onDragStart', 'onDragEnd', 'onDragOver', 'onDrop', 'onDependencies',
      'onMoveToFront', 'onMoveToBack', 'onReposition', 'onEdit', 'onDelete',
    ].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>
    renderCard(createMockThread({ total_issues: null, issues_remaining: 0, notes: null }), {
      isBlocked: true,
      blockingDependencies: [],
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

      renderCard(createMockThread(), {
        onCardClick,
        onRead,
        snoozeLabel: 'Snooze',
        snoozeIcon: '😴',
      })

      const actionsContainer = screen.getByRole('group', { name: /Actions for Test Thread/i })

      const readButton = actionsContainer.querySelector('button[aria-label="Read & Rate"]')

      // SAFETY: the queried node is the element the component rendered under test
      await user.click(readButton as HTMLElement)
      expect(onRead).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })

    it('exercises PositionMenu descendants (Edit, Snooze, Delete) and confirms onCardClick is not invoked', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const onEdit = vi.fn()
      const onSnooze = vi.fn()
      const onDelete = vi.fn()

      renderCard(createMockThread(), {
        onCardClick,
        onEdit,
        onSnooze,
        onDelete,
        snoozeLabel: 'Snooze',
        snoozeIcon: '😴',
      })

      const editBtn = screen.getByTestId('mock-position-edit')
      const snoozeBtn = screen.getByTestId('mock-position-snooze')
      const deleteBtn = screen.getByTestId('mock-position-delete')

      await user.click(editBtn)
      expect(onEdit).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()

      vi.clearAllMocks()

      await user.click(snoozeBtn)
      expect(onSnooze).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()

      vi.clearAllMocks()

      await user.click(deleteBtn)
      expect(onDelete).toHaveBeenCalledTimes(1)
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
        blockingDependencies: []
      })

      // Test blocked dependency button
      const blockedButton = screen.getByRole('button', { name: /View dependencies for Blocked Test Thread/ })
      
      await user.click(blockedButton)
      expect(onDependencies).toHaveBeenCalledTimes(1)
      expect(onCardClick).not.toHaveBeenCalled()
    })

    it('renders snooze button in PositionMenu with aria-disabled when not the pending thread', () => {
      renderCard(createMockThread(), {
        snoozeDisabled: true,
        snoozeLabel: 'Snooze',
        snoozeIcon: '😴',
      })

      const snoozeButton = screen.getByTestId('mock-position-snooze')
      expect(snoozeButton).toBeDisabled()
    })

    it('renders snooze button in PositionMenu without aria-disabled when enabled', () => {
      renderCard(createMockThread(), {
        snoozeDisabled: false,
        snoozeLabel: 'Snooze',
        snoozeIcon: '😴',
      })

      const snoozeButton = screen.getByTestId('mock-position-snooze')
      expect(snoozeButton).not.toBeDisabled()
    })

    it('opens the Map series repair dialog from an unresolved mapping indicator', async () => {
      const user = userEvent.setup()
      const onCardClick = vi.fn()
      const threadWithMapping: ThreadListItem = {
        ...createMockThread(),
        comicvine_mapping: {
          status: 'unresolved',
          tracked_issue_count: 4,
          metadata_missing_count: 0,
          confirmed_issue_count: 0,
          needs_mapping_count: 4,
          needs_review_count: 0,
        },
      }
      renderCard(threadWithMapping, { onCardClick })

      expect(screen.getByText('4 issues need mapping')).toBeInTheDocument()
      expect(screen.queryByTestId('mock-map-series-dialog')).not.toBeInTheDocument()

      await user.click(screen.getByTestId('queue-map-series-btn'))

      expect(screen.getByTestId('mock-map-series-dialog')).toBeInTheDocument()
      expect(screen.getByTestId('mock-map-series-thread')).toHaveTextContent('Test Thread')
      expect(onCardClick).not.toHaveBeenCalled()

      await user.click(screen.getByTestId('mock-map-series-done'))

      expect(screen.queryByTestId('mock-map-series-dialog')).not.toBeInTheDocument()
    })

    it('stays quiet without a Map series action for fully mapped series', () => {
      const threadWithMapping: ThreadListItem = {
        ...createMockThread(),
        comicvine_mapping: {
          status: 'fully_mapped',
          tracked_issue_count: 5,
          metadata_missing_count: 0,
          confirmed_issue_count: 5,
          needs_mapping_count: 0,
          needs_review_count: 0,
        },
      }
      renderCard(threadWithMapping)

      expect(screen.queryByTestId('queue-map-series-btn')).not.toBeInTheDocument()
      expect(screen.queryByTestId('mock-map-series-dialog')).not.toBeInTheDocument()
    })

  it('renders the thread tags on the Queue row so tags are scannable before rolling (#3425)', () => {
    const thread = createMockThread({
      title: 'Spider-Man',
      tags: [
        {
          id: 4,
          name: 'Physical',
          normalized_name: 'physical',
          scope: 'global',
          owner_user_id: null,
          color: '#3B82F6',
          created_at: '2024-01-01T00:00:00.000Z',
          updated_at: '2024-01-01T00:00:00.000Z',
        },
      ],
    })
    renderCard(thread)

    const group = screen.getByRole('region', { name: 'Tags for Spider-Man' })
    expect(within(group).getByText('Physical')).toBeInTheDocument()
  })

  it('renders no tag group on an untagged Queue row', () => {
    renderCard(createMockThread({ title: 'Untagged Saga' }))

    expect(
      screen.queryByRole('region', { name: 'Tags for Untagged Saga' }),
    ).not.toBeInTheDocument()
  })

    it('distinguishes review-needed indicator from an ordinary unmapped pill', () => {
      const threadWithMapping: ThreadListItem = {
        ...createMockThread(),
        comicvine_mapping: {
          status: 'needs_review',
          tracked_issue_count: 3,
          metadata_missing_count: 0,
          confirmed_issue_count: 1,
          needs_mapping_count: 0,
          needs_review_count: 2,
        },
      }
      renderCard(threadWithMapping)

      expect(screen.getByText('2 issues need review')).toBeInTheDocument()
      expect(screen.queryByText(/need mapping/)).toBeNull()
      expect(screen.getByTestId('queue-map-series-btn')).toBeInTheDocument()
    })
  })