import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueMappingHealthIndicator from '../components/QueueMappingHealthIndicator'
import QueueThreadCard from '../pages/QueuePage/QueueThreadCard'
import type { ThreadListItem } from '../types'
import type { QueueComicVineMappingHealth } from '../types/queue-mapping'

const { listSpy, searchSeriesSpy } = vi.hoisted(() => ({
  listSpy: vi.fn(),
  searchSeriesSpy: vi.fn(),
}))

// The indicator must render from the persisted Queue projection alone. These
// spies prove the render path below performs no per-card identity fetch and
// no live provider request.
vi.mock('../services/api-issues', () => ({
  issuesApi: { list: listSpy },
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: { searchSeries: searchSeriesSpy },
}))

vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../components/MarqueeTitle', () => ({
  MarqueeTitle: ({ title }: { title: string }) => <span>{title}</span>,
}))

vi.mock('../components/PositionMenu', () => ({
  default: () => <div data-testid="mock-position-menu" />,
}))

function createThread(
  comicvine_mapping: QueueComicVineMappingHealth | null | undefined,
  overrides: Partial<ThreadListItem> = {},
): ThreadListItem {
  return {
    id: 7,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 3,
    queue_position: 1,
    status: 'active',
    last_activity_at: null,
    is_blocked: false,
    blocking_reasons: [],
    total_issues: 12,
    next_unread_issue_number: '10',
    notes: null,
    created_at: '2024-01-01T00:00:00.000Z',
    // SAFETY: the generated transport type predates the #2776 projection;
    // the runtime Queue response carries this field pending regeneration.
    ...(comicvine_mapping === undefined ? {} : { comicvine_mapping }),
    ...overrides,
  } as ThreadListItem
}

function health(
  overrides: Partial<QueueComicVineMappingHealth> = {},
): QueueComicVineMappingHealth {
  return {
    status: 'partial',
    tracked_issue_count: 12,
    confirmed_issue_count: 10,
    needs_mapping_count: 2,
    needs_review_count: 0,
    ...overrides,
  }
}

describe('QueueMappingHealthIndicator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('stays quiet for fully mapped series', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ status: 'fully_mapped', needs_mapping_count: 0 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('queue-mapping-health')).not.toBeInTheDocument()
    expect(screen.queryByTestId('queue-mapping-map-series')).not.toBeInTheDocument()
  })

  it('stays quiet when mapping health is not applicable', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ status: 'not_applicable', tracked_issue_count: 0 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('queue-mapping-health')).not.toBeInTheDocument()
  })

  it('stays quiet when the projection is absent', () => {
    render(
      <QueueMappingHealthIndicator thread={createThread(undefined)} onMapSeries={vi.fn()} />,
    )

    expect(screen.queryByTestId('queue-mapping-health')).not.toBeInTheDocument()
  })

  it('stays quiet for unknown projection shapes instead of inventing status', () => {
    const thread = createThread(undefined)
    ;(thread as unknown as Record<string, unknown>)['comicvine_mapping'] = {
      status: 'mystery',
      tracked_issue_count: 3,
    }
    render(<QueueMappingHealthIndicator thread={thread} onMapSeries={vi.fn()} />)

    expect(screen.queryByTestId('queue-mapping-health')).not.toBeInTheDocument()
  })

  it('shows a concise count for ordinary unmapped issues', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ status: 'unresolved', confirmed_issue_count: 0 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.getByTestId('queue-mapping-health')).toHaveTextContent('2 issues need mapping')
    expect(screen.getByRole('button', { name: 'Map Saga series on ComicVine' })).toBeInTheDocument()
  })

  it('uses singular wording for a single missing issue', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ needs_mapping_count: 1, confirmed_issue_count: 11 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.getByTestId('queue-mapping-health')).toHaveTextContent('1 issue needs mapping')
  })

  it('labels review-needed identities distinctly from ordinary missing mappings', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(
          health({
            status: 'needs_review',
            needs_mapping_count: 0,
            needs_review_count: 1,
            confirmed_issue_count: 11,
          }),
        )}
        onMapSeries={vi.fn()}
      />,
    )

    const indicator = screen.getByTestId('queue-mapping-health')
    expect(indicator).toHaveTextContent('Needs review: 1 issue needs review')
    expect(indicator).not.toHaveTextContent('need mapping')
  })

  it('combines mapping and review counts on partial rows', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ needs_mapping_count: 2, needs_review_count: 1 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.getByTestId('queue-mapping-health')).toHaveTextContent(
      'Needs review: 2 issues need mapping · 1 issue needs review',
    )
  })

  it('carries status in text with an accessible name, not color alone', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ needs_mapping_count: 2 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(
      screen.getByRole('status', {
        name: 'ComicVine mapping status for Saga: 2 issues need mapping',
      }),
    ).toBeInTheDocument()
  })

  it('wraps instead of forcing horizontal escape on narrow cards', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ needs_mapping_count: 2 }))}
        onMapSeries={vi.fn()}
      />,
    )

    expect(screen.getByTestId('queue-mapping-health')).toHaveClass('flex-wrap')
  })

  it('opens the repair flow without navigating to thread details', async () => {
    const user = userEvent.setup()
    const onMapSeries = vi.fn()
    const onCardClick = vi.fn()
    render(
      <MemoryRouter>
        <QueueThreadCard
          thread={createThread(health({ needs_mapping_count: 2 }))}
          index={0}
          isBlocked={false}
          blockingDependencies={[]}
          crossoverGroups={[]}
          crossoverGroupsLoading={false}
          crossoverGroupsError={false}
          isDragOver={false}
          snoozeIcon="😴"
          snoozeLabel="Snooze"
          snoozeDisabled
          onCardClick={onCardClick}
          onDragStart={vi.fn()}
          onDragEnd={vi.fn()}
          onDragOver={vi.fn()}
          onDrop={vi.fn()}
          onRead={vi.fn()}
          onSnooze={vi.fn()}
          onMoveToFront={vi.fn()}
          onMoveToBack={vi.fn()}
          onReposition={vi.fn()}
          onEdit={vi.fn()}
          onDependencies={vi.fn()}
          onDelete={vi.fn()}
          onMapSeries={onMapSeries}
        />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: 'Map Saga series on ComicVine' }))

    expect(onMapSeries).toHaveBeenCalledTimes(1)
    expect(onCardClick).not.toHaveBeenCalled()
  })

  it('renders no mapping chrome on fully mapped cards', () => {
    render(
      <MemoryRouter>
        <QueueThreadCard
          thread={createThread(health({ status: 'fully_mapped', needs_mapping_count: 0 }))}
          index={0}
          isBlocked={false}
          blockingDependencies={[]}
          crossoverGroups={[]}
          crossoverGroupsLoading={false}
          crossoverGroupsError={false}
          isDragOver={false}
          snoozeIcon="😴"
          snoozeLabel="Snooze"
          snoozeDisabled
          onCardClick={vi.fn()}
          onDragStart={vi.fn()}
          onDragEnd={vi.fn()}
          onDragOver={vi.fn()}
          onDrop={vi.fn()}
          onRead={vi.fn()}
          onSnooze={vi.fn()}
          onMoveToFront={vi.fn()}
          onMoveToBack={vi.fn()}
          onReposition={vi.fn()}
          onEdit={vi.fn()}
          onDependencies={vi.fn()}
          onDelete={vi.fn()}
          onMapSeries={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(screen.queryByTestId('queue-mapping-health')).not.toBeInTheDocument()
    expect(screen.queryByTestId('queue-mapping-map-series')).not.toBeInTheDocument()
  })

  it('performs no per-card identity fetch and no live provider request to render', () => {
    render(
      <QueueMappingHealthIndicator
        thread={createThread(health({ needs_mapping_count: 2 }))}
        onMapSeries={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByTestId('queue-mapping-map-series'))

    expect(listSpy).not.toHaveBeenCalled()
    expect(searchSeriesSpy).not.toHaveBeenCalled()
  })
})
