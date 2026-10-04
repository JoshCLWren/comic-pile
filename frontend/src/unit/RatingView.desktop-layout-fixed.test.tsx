import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RatingView } from '../pages/RollPage/components/RatingView'
import {
  ROLL_WORKSPACE_MAX_WIDTH,
  ROLL_WORKSPACE_TRACKS,
} from '../pages/RollPage/workspaceLayout'
import { hasNoGridColsArbitraryComma } from '../../eslint-rules/grid-cols-comma-guard'
import { ToastProvider } from '../contexts/ToastProvider'
import type { RatingViewData } from '../pages/RollPage/useRatingView'
import type { RatingThread } from '../pages/RollPage/types'
import type { ReaderContextResponse } from '../types'

vi.mock('../components/LazyDice3D', () => ({ default: () => <div data-testid="dice" /> }))
vi.mock('../components/Tooltip', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../components/IssueCorrectionDialog', () => ({ default: () => null }))
vi.mock('../components/ContinuityCorrectionDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ReadingOrderGroups', () => ({
  ReadingOrderGroups: () => null,
}))
vi.mock('../pages/RollPage/components/ComicVineIssueCard', () => ({
  ComicVineIssueCard: () => null,
}))
vi.mock('../pages/RollPage/components/ReadingRouteExplanation', () => ({
  ReadingRouteExplanation: () => null,
}))

interface HoistedComicVineModule {
  comicvineState: {
    metadata: unknown
  }
}

const { comicvineState } = vi.hoisted((): HoistedComicVineModule => ({
  comicvineState: { metadata: null },
}))
vi.mock('../hooks/useComicVineIssueIntelligence', () => ({
  useComicVineIssueIntelligence: () => ({
    metadata: comicvineState.metadata,
    isLoading: false,
    refetch: vi.fn(),
  }),
}))

function makeRatingViewData(overrides: Partial<RatingViewData> = {}): RatingViewData {
  return {
    activeRatingThread: {
      id: 1,
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 5,
      total_issues: 10,
      issue_number: '3',
      next_issue_number: '4',
      reading_progress: 'in_progress',
      queue_position: 0,
      issue_id: 100,
      next_issue_id: 101,
    },
    currentDie: 6,
    rolledResult: 3,
    rating: 3.0,
    predictedDie: 8,
    errorMessage: '',
    rateIsPending: false,
    snoozeIsPending: false,
    dismissIsPending: false,
    skipIsPending: false,
    onUpdateRating: vi.fn(),
    onSubmitRating: vi.fn(),
    onSnooze: vi.fn(),
    onSkip: undefined,
    onCancel: vi.fn(),
    onRefreshThread: vi.fn(),
    readerContext: null,
    isReaderContextLoading: false,
    readerContextError: null,
    ratingViewTopRef: null,
    issuesRemaining: 5,
    readingContextRequested: false,
    readingBoundariesRequested: false,
    readingOrdersIsLoading: false,
    readingOrdersError: null,
    connectedThreadsIsLoading: false,
    connectedThreadsError: null,
    ...overrides,
  }
}

function ratingView(overrides: Partial<RatingViewData> = {}) {
  return (
    <MemoryRouter>
      <ToastProvider>
        <RatingView data={makeRatingViewData(overrides)} />
      </ToastProvider>
    </MemoryRouter>
  )
}

function richReaderContext(): ReaderContextResponse {
  return {
    issue_id: 100,
    series: {
      identity_source: 'comicvine',
      canonical_series_id: 'series-1',
      series_name: 'Saga',
      average_rating: 4.2,
      ratings_count: 12,
      previous_issue: { issue_id: 99, issue_number: '2', rating: 4.0 },
      recent_ratings: [{ issue_id: 99, issue_number: '2', rating: 4.0 }],
      highest_rating: 5.0,
      lowest_rating: 2.0,
    },
    crossovers: [
      {
        id: 500,
        name: 'StoryArc 1',
        applies_to_current_issue: true,
        membership_kind: 'issue',
        next_member: null,
        average_rating: 4.0,
        ratings_count: 3,
        read_count: 2,
      },
    ],
    local_chain: {
      issues: [
        { issue_id: 99, issue_number: '2', position: 1, status: 'read', relation: 'previous', rating: 4.0, crossover_memberships: [] },
        { issue_id: 100, issue_number: '3', position: 2, status: 'unread', relation: 'current', rating: null, crossover_memberships: [{ id: 500, name: 'StoryArc 1' }] },
        { issue_id: 101, issue_number: '4', position: 3, status: 'unread', relation: 'next', rating: null, crossover_memberships: [] },
      ],
      edges: [
        {
          id: 1,
          kind: 'dependency',
          source_issue_id: 99,
          target_issue_id: 100,
          source_thread_id: null,
          target_thread_id: null,
          source_label: '#2',
          target_label: '#3',
          source_status: 'read',
          target_status: 'unread',
          note: null,
          explanation: 'Finish the previous issue first.',
        },
      ],
    },
  }
}

function gridChildren(container: HTMLElement) {
  const grid = container.querySelector('[data-testid="rating-pillars-grid"]')
  return { grid, cells: Array.from(grid!.querySelectorAll<HTMLElement>(':scope > div')) }
}

describe('RatingView desktop layout respects state instead of reserving fixed coordinates (#2711 revises #1943) - GEOMETRY-BASED', () => {
  it('packs regions without fixed coordinates and reserves no middle column', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    const { grid, cells } = gridChildren(container)
    expect(grid).not.toBeNull()
    
    // ✅ PROVE ACTUAL GEOMETRY (instead of class names):
    
    // 1. Prove the container is actually a grid
    const gridStyle = window.getComputedStyle(grid!)
    expect(gridStyle.display).toBe('grid')
    expect(gridStyle.alignItems).toBe('start')
    
    // 2. Prove the grid has the correct max-width and centering
    expect(gridStyle.maxWidth).toBe('1024px') // lg:max-w-4xl = 1024px
    expect(gridStyle.marginLeft).toBe('auto')
    expect(gridStyle.marginRight).toBe('auto')
    
    // 3. Prove the grid has the correct template columns (actual geometry)
    expect(gridStyle.gridTemplateColumns).toBe('minmax(0,24rem) minmax(18rem,24rem)')
    expect(hasNoGridColsArbitraryComma(grid!.className)).toBe(true)
    expect(gridStyle.gridTemplateColumns).not.toBe('repeat(auto-fit')
    
    // 4. Prove the workspace geometry is consistent
    const gridRect = grid!.getBoundingClientRect()
    expect(gridRect.width).toBeLessThanOrEqual(1024) // Respect max-w-4xl
    
    // 5. Prove only Comic and decision regions exist (2 cells)
    expect(cells.length).toBe(2)
    
    expect(cells[0].dataset.testid).toBe('rating-region-comic')
    expect(cells[1].dataset.testid).toBe('rating-region-decision')
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()

    // 6. Prove no fixed grid coordinates are used
    for (const cell of cells) {
      const cellStyle = window.getComputedStyle(cell)
      expect(cellStyle.gridColumnStart).toBe('auto')
      expect(cellStyle.gridColumnEnd).toBe('auto')
      expect(cellStyle.gridRowStart).toBe('auto')
      expect(cellStyle.gridRowEnd).toBe('auto')
      expect(cellStyle.gridColumnSpan).toBe('auto')
      expect(cellStyle.gridRowSpan).toBe('auto')
      expect(cellStyle.gridTemplateColumns).toBe('')
    }
  })

  it('gives every region a min-w-0 wrapper so content packs without overflow', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    const comicRegion = container.querySelector('[data-testid="rating-region-comic"]')
    const decisionRegion = container.querySelector('[data-testid="rating-region-decision"]')
    
    expect(comicRegion).not.toBeNull()
    expect(decisionRegion).not.toBeNull()
    
    // ✅ Prove min-w-0 actually works (content can shrink):
    const comicStyle = window.getComputedStyle(comicRegion!)
    const decisionStyle = window.getComputedStyle(decisionRegion!)
    
    expect(comicStyle.minWidth).toBe('0px')
    expect(decisionStyle.minWidth).toBe('0px')
    
    // ✅ Prove content is properly contained within regions
    const comicRect = comicRegion!.getBoundingClientRect()
    const decisionRect = decisionRegion!.getBoundingClientRect()
    
    expect(comicRect.width).toBeGreaterThan(0)
    expect(decisionRect.width).toBeGreaterThan(0)
    
    // ✅ Prove regions have different widths (24rem vs 18rem)
    expect(comicRect.width).toBeGreaterThan(decisionRect.width)
  })

  it('stacks the decision card and context disclosure in the decision region', () => {
    const { container } = render(ratingView({ readerContext: richReaderContext() }))
    const decisionRegion = container.querySelector<HTMLElement>('[data-testid="rating-region-decision"]')
    const decisionCard = container.querySelector<HTMLElement>('[data-testid="decision-card"]')
    const contextDisclosure = container.querySelector<HTMLElement>('[data-testid="context-disclosure"]')
    const actions = container.querySelector<HTMLElement>('[data-testid="rating-actions"]')
    
    expect(decisionRegion).not.toBeNull()
    expect(decisionCard).not.toBeNull()
    expect(contextDisclosure).not.toBeNull()
    expect(actions).not.toBeNull()
    
    // ✅ Prove elements are stacked vertically in decision region:
    const decisionRect = decisionRegion!.getBoundingClientRect()
    const cardRect = decisionCard!.getBoundingClientRect()
    const disclosureRect = contextDisclosure!.getBoundingClientRect()
    const actionsRect = actions!.getBoundingClientRect()
    
    // Card is above disclosure
    expect(cardRect.bottom).toBeLessThanOrEqual(disclosureRect.top)
    
    // Disclosure is above actions
    expect(disclosureRect.bottom).toBeLessThanOrEqual(actionsRect.top)
    
    // All elements are within the decision region
    expect(cardRect.left).toBeGreaterThanOrEqual(decisionRect.left)
    expect(cardRect.right).toBeLessThanOrEqual(decisionRect.right)
    expect(disclosureRect.left).toBeGreaterThanOrEqual(decisionRect.left)
    expect(disclosureRect.right).toBeLessThanOrEqual(decisionRect.right)
    expect(actionsRect.left).toBeGreaterThanOrEqual(decisionRect.left)
    expect(actionsRect.right).toBeLessThanOrEqual(decisionRect.right)
    
    // ✅ Prove decision card doesn't span full width
    const cardStyle = window.getComputedStyle(decisionCard!)
    expect(cardStyle.gridColumnSpan).toBe('1')
  })

  it('caps a heavy cover to a viewport-relative budget so actions stay above the fold', () => {
    comicvineState.metadata = {
      comicvine_issue_id: '12345',
      comicvine_url: null,
      series_name: 'Saga',
      series_id: 1,
      issue_number: '3',
      name: 'The Pretending Town',
      description: null,
      image_url: 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=',
      cover_date: '2020-01-01',
      store_date: null,
      creators: [],
      story_arcs: [],
    }
    const { container } = render(ratingView())
    const comicRegion = container.querySelector('[data-testid="rating-region-comic"]')
    const cover = container.querySelector('[data-testid="comic-cover"]')
    const decisionRegion = container.querySelector('[data-testid="rating-region-decision"]')
    const actions = container.querySelector('[data-testid="rating-actions"]')
    
    expect(comicRegion).not.toBeNull()
    expect(cover).not.toBeNull()
    expect(decisionRegion).not.toBeNull()
    expect(actions).not.toBeNull()
    
    // ✅ Prove aspect ratio and height caps are applied:
    const aspectRatioAttr = cover!.getAttribute('data-cover-aspect-ratio')
    const heightCapAttr = cover!.getAttribute('data-cover-height-cap-vh')
    const widthCapAttr = cover!.getAttribute('data-cover-width-cap-vh')
    
    const aspectRatio = Number(aspectRatioAttr)
    const heightCap = Number(heightCapAttr)
    const widthCap = Number(widthCapAttr)
    
    expect(Number.isFinite(aspectRatio)).toBe(true)
    expect(aspectRatio).toBeGreaterThan(0)
    expect(heightCap).toBe(45)
    expect(Number.isFinite(widthCap)).toBe(true)
    expect(widthCap).toBeGreaterThan(0)
    expect(widthCap).toBeCloseTo(heightCap * aspectRatio)
    
    // ✅ Prove cover respects aspect ratio constraints
    const coverRect = cover!.getBoundingClientRect()
    const actualAspectRatio = coverRect.width / coverRect.height
    expect(actualAspectRatio).toBeCloseTo(aspectRatio, 1)
    
    // ✅ Prove cover respects height cap
    const coverStyle = window.getComputedStyle(cover!)
    const maxHeight = parseFloat(coverStyle.maxHeight)
    expect(maxHeight).toBeGreaterThan(0)
    expect(maxHeight).toBeLessThanOrEqual(window.innerHeight * 0.45) // 45vh
    
    // ✅ Prove actions remain visible (above fold)
    const actionsRect = actions!.getBoundingClientRect()
    const viewportHeight = window.innerHeight
    expect(actionsRect.top).toBeLessThanOrEqual(viewportHeight * 0.8) // Above 80% of viewport
    
    // ✅ Prove no max-h- classes are used (flexible sizing)
    expect(cover!.className).not.toContain('max-h-')
  })
})

describe('RatingView reading-context affordances retired (#2711)', () => {
  it('contains no Why this?, Reading Context or Reading Boundaries affordance', () => {
    render(ratingView())
    expect(screen.queryByText('Why this?')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-context-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('reading-boundaries-button')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Context')).not.toBeInTheDocument()
    expect(screen.queryByText('Reading Boundaries')).not.toBeInTheDocument()
    expect(screen.queryByTestId('rating-region-reading-optional')).not.toBeInTheDocument()
  })
})

afterEach(() => {
  comicvineState.metadata = null
})