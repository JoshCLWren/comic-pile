import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ReadingContextPillar } from '../pages/RollPage/components/ReadingContextPillar'
import {
  READING_CONTEXT_TYPE,
  READING_CONTEXT_TYPE_FLOORS,
  type ReadingContextTypeRole,
} from '../pages/RollPage/readingContextTypography'
import { issuesApi } from '../services/api-issues'
import type { ReaderContextResponse } from '../types'

const navigateSpy = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    getReaderContext: vi.fn(),
  },
}))

vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ContinuityReadinessSummary', () => ({
  ContinuityReadinessSummary: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => <div data-testid="series-progress-stub">2 / 5</div>,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

const getReaderContextMock = issuesApi.getReaderContext as ReturnType<typeof vi.fn>

const activeRatingThread = {
  id: 42,
  title: 'Saga',
  format: 'Comic',
  issues_remaining: 5,
  queue_position: 0,
  total_issues: 10,
  reading_progress: 'in_progress',
  issue_id: 100,
  issue_number: '3',
  next_issue_id: 101,
  next_issue_number: '4',
  last_rolled_result: null,
}

function buildContext(): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: '1-111',
      series_name: 'Ultimate Black Panther',
      average_rating: null,
      ratings_count: 0,
      previous_issue: null,
      recent_ratings: [],
      highest_rating: null,
      lowest_rating: null,
    },
    crossovers: [
      {
        id: 7,
        name: 'Ultimate Universe Reading Order',
        applies_to_current_issue: false,
        next_member: { issue_id: 205, issue_number: '14' },
        average_rating: null,
        ratings_count: 0,
        read_count: 0,
      },
    ],
    local_chain: {
      issues: [
        {
          issue_id: 98,
          issue_number: '3',
          position: 2,
          status: 'read',
          relation: 'previous',
          rating: 3.5,
          crossover_memberships: [{ id: 7, name: 'Ultimate Universe Reading Order' }],
        },
        {
          issue_id: 100,
          issue_number: '5',
          position: 4,
          status: 'unread',
          relation: 'current',
          rating: null,
          crossover_memberships: [],
        },
      ],
      edges: [
        {
          id: 11,
          kind: 'dependency',
          source_issue_id: 98,
          target_issue_id: 100,
          source_thread_id: 42,
          target_thread_id: 42,
          source_label: 'Saga #3',
          target_label: 'Saga #5',
          note: null,
          explanation: 'Blocked by issue #3 in Saga (thread #42)',
        },
      ],
    },
  }
}

/**
 * Issue #1873 acceptance: at a representative 1920px desktop viewport the
 * pillar's decision-relevant text must RESOLVE to readable computed sizes,
 * not merely carry class names. Sizes ship as inline styles sourced from the
 * shared reading-context type scale, so jsdom's computed-style cascade is the
 * source of truth for these assertions.
 */
describe('ReadingContextPillar rendered typography (#1873)', () => {
  function expectComputedFontSize(element: HTMLElement, role: ReadingContextTypeRole) {
    const rendered = window.getComputedStyle(element).fontSize
    expect(rendered, `role "${role}" must resolve exactly`).toBe(
      `${READING_CONTEXT_TYPE[role]}px`,
    )
  }

  function expectReadable(element: HTMLElement, minimumPx: number, description: string) {
    const rendered = parseFloat(window.getComputedStyle(element).fontSize)
    expect(rendered, `${description} must stay readable`).toBeGreaterThanOrEqual(minimumPx)
  }

  it('keeps every role of the shared type scale above its readability floor', () => {
    for (const [role, size] of Object.entries(READING_CONTEXT_TYPE)) {
      const floor = READING_CONTEXT_TYPE_FLOORS[role as ReadingContextTypeRole]
      expect(size, `${role} (${size}px)`).toBeGreaterThanOrEqual(floor)
    }
  })

  it('resolves primary context content to readable sizes at a 1920px desktop viewport', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1920 })
    window.dispatchEvent(new Event('resize'))

    getReaderContextMock.mockResolvedValue(buildContext())
    const { container } = render(
      <ReadingContextPillar
        activeRatingThread={activeRatingThread}
        readingOrders={[]}
        connectedThreads={[]}
        onRefreshThread={vi.fn()}
        rolledResult={7}
        currentDie={20}
      />,
    )

    await screen.findByText('Where you are in Ultimate Black Panther')

    expectComputedFontSize(
      screen.getByText(/Rolled 7 on d20/),
      'statValue',
    )
    expectComputedFontSize(
      screen.getByText('Where you are in Ultimate Black Panther'),
      'sectionHeading',
    )

    const currentIssueButton = screen.getByRole('button', {
      name: /show context for ultimate black panther issue 5/i,
    })
    const currentIssueRow = currentIssueButton.closest('[role="listitem"]') as HTMLElement
    expectComputedFontSize(within(currentIssueRow).getByText('5'), 'primaryValue')

    const ratedIssueButton = screen.getByRole('button', {
      name: /show context for ultimate black panther issue 3/i,
    })
    const ratedIssueRow = ratedIssueButton.closest('[role="listitem"]') as HTMLElement
    expectComputedFontSize(
      within(ratedIssueRow).getByLabelText('Your rating: 3.5 stars'),
      'metaLabel',
    )

    const membershipChip = screen.getByRole('button', {
      name: 'Open Ultimate Universe Reading Order crossover',
    })
    expectComputedFontSize(membershipChip, 'chipLabel')

    const upcomingCrossoverButton = screen.getByRole('button', {
      name: 'Open crossover Ultimate Universe Reading Order, starts at issue 14',
    })
    expectReadable(
      within(upcomingCrossoverButton).getByText('Ultimate Universe Reading Order'),
      READING_CONTEXT_TYPE_FLOORS.primaryValue,
      'upcoming crossover name',
    )
    expectComputedFontSize(
      within(upcomingCrossoverButton).getByText('— starts at #14'),
      'metaLabel',
    )

    const edgeEndpoint = screen.getByRole('button', { name: 'Open thread for Saga #3' })
    expectComputedFontSize(edgeEndpoint, 'primaryValue')

    expectComputedFontSize(
      screen.getByText('Blocked by issue #3 in Saga (thread #42)'),
      'bodyCopy',
    )
    expectComputedFontSize(
      screen.getByText("Being part of a crossover doesn't block reading by itself."),
      'bodyCopy',
    )

    const allText = container.querySelectorAll<HTMLElement>('*')
    for (const element of allText) {
      if (element.textContent?.trim() === '') continue
      // jsdom computes only explicitly-set sizes; inherited sizes resolve in
      // real browsers to the 16px root default, so unstyled nodes are safe.
      const rendered = window.getComputedStyle(element).fontSize
      if (rendered === '') continue
      expectReadable(element, READING_CONTEXT_TYPE_FLOORS.statLabel, element.tagName)
    }
  })
})
