/**
 * Roll header metadata hierarchy (#3011).
 *
 * Guards the polish defects reported on the Roll rating view:
 * - metadata separators render only between visible items and stay glued to
 *   the item they follow, so a wrap cannot strand a bare separator;
 * - the publication date is rendered once, not repeated per region;
 * - the story title reads as a subtitle of the main issue title instead of
 *   floating under the cover.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComicVineIssueIntelligence } from '../services/api-comicvine'
import type { RatingThread } from '../pages/RollPage/types'

const { getIssueIntelligenceSpy, getIssueIdentitySpy } = vi.hoisted(() => ({
  getIssueIntelligenceSpy: vi.fn(),
  getIssueIdentitySpy: vi.fn().mockResolvedValue({
    has_confirmed_identity: true,
    comicvine_issue_id: '36956',
    confirmed_mappings: [],
    candidate_mappings: [],
    has_unresolved: false,
  }),
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: vi.fn().mockResolvedValue({ query: '', results: [], total_available: 0 }),
    getSeriesIssues: vi.fn().mockResolvedValue({ comicvine_volume_id: 42, series_name: '', issues: [] }),
    getIssueIntelligence: getIssueIntelligenceSpy,
    getIssueIdentity: getIssueIdentitySpy,
    confirmIdentity: vi.fn().mockResolvedValue({}),
    replaceIdentity: vi.fn().mockResolvedValue({}),
    refreshMetadata: vi.fn(),
    applyCorrection: vi.fn(),
    listCorrections: vi.fn().mockResolvedValue([]),
    revertCorrection: vi.fn(),
  },
}))

vi.mock('../pages/RollPage/components/ComicIdentity', () => ({
  ComicIdentity: () => <div data-testid="comic-identity-stub" />,
}))

import { ComicPillar } from '../pages/RollPage/components/ComicPillar'

const STORE_DATE = '1993-06-15'

const linkedThread: RatingThread = {
  id: 7,
  title: 'Stormwatch Vol. 1',
  format: 'single',
  issues_remaining: 5,
  queue_position: 1,
  total_issues: 12,
  reading_progress: '58.33',
  issue_id: 77,
  issue_number: '43',
  next_issue_id: 77,
  next_issue_number: '43',
  last_rolled_result: null,
}

function intelligenceMetadata(
  overrides: Partial<ComicVineIssueIntelligence> = {},
): ComicVineIssueIntelligence {
  return {
    comicvine_issue_id: '36956',
    comicvine_url: null,
    series_name: 'Stormwatch',
    series_id: 42,
    issue_number: '43',
    name: 'The Dark Side',
    description: null,
    image_url: null,
    cover_date: null,
    store_date: STORE_DATE,
    creators: [],
    story_arcs: [],
    ...overrides,
  }
}

function renderPillar(thread: RatingThread = linkedThread) {
  return render(<ComicPillar activeRatingThread={thread} onRefreshThread={vi.fn()} />)
}

function separatorTexts(progressLine: HTMLElement): string[] {
  return Array.from(progressLine.querySelectorAll('[aria-hidden="true"]')).map(
    (node) => node.textContent ?? '',
  )
}

describe('Roll header metadata hierarchy (#3011)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('separates only the visible metadata items and glues each separator to its item', async () => {
    getIssueIntelligenceSpy.mockResolvedValue(intelligenceMetadata())

    renderPillar()

    const progressLine = await screen.findByTestId('comic-progress-line')
    await waitFor(() => expect(progressLine.textContent).toContain('58% complete'))

    // Only the three progress facts are shown; separators sit strictly between
    // them, never before the first or after the last item.
    expect(progressLine.textContent).toBe('Issue 43 of 12\u00a0· 58% complete\u00a0· 5 left')
    expect(separatorTexts(progressLine)).toEqual(['\u00a0· ', '\u00a0· '])

    // A non-breaking space binds the separator to the item it follows, so a
    // wrapped line can never open with a dangling separator.
    for (const separator of Array.from(progressLine.querySelectorAll('[aria-hidden="true"]'))) {
      expect(separator.textContent?.startsWith('\u00a0')).toBe(true)
      expect(separator.parentElement?.firstChild).toBe(separator)
    }

    // Every item is atomic, so wrapping can only happen between items.
    for (const item of Array.from(progressLine.querySelectorAll('span'))) {
      if (!item.hasAttribute('aria-hidden')) {
        expect(item).toHaveClass('whitespace-nowrap')
      }
    }
  })

  it('drops the issue item and its separator when the running total is unknown', async () => {
    getIssueIntelligenceSpy.mockResolvedValue(intelligenceMetadata())

    renderPillar({ ...linkedThread, total_issues: null })

    const progressLine = await screen.findByTestId('comic-progress-line')
    await waitFor(() =>
      expect(getIssueIntelligenceSpy).toHaveBeenCalled(),
    )

    expect(progressLine.textContent).toBe('0% complete\u00a0· 5 left')
    expect(separatorTexts(progressLine)).toEqual(['\u00a0· '])
    expect(progressLine.textContent?.startsWith('\u00a0')).toBe(false)
  })

  it('renders the publication date once, never in the header metadata line', async () => {
    getIssueIntelligenceSpy.mockResolvedValue(intelligenceMetadata())

    renderPillar()

    const progressLine = await screen.findByTestId('comic-progress-line')
    await waitFor(() => expect(progressLine.textContent).toContain('58% complete'))

    const year = STORE_DATE.slice(0, 4)
    expect(progressLine.textContent).not.toContain(year)
    expect(document.body.textContent).not.toContain(year)
  })

  it('presents the story title as a subtitle of the main issue title', async () => {
    getIssueIntelligenceSpy.mockResolvedValue(intelligenceMetadata())

    renderPillar()

    const storyTitle = await screen.findByTestId('comic-story-title')
    expect(storyTitle.textContent).toBe('The Dark Side')

    const mainTitle = screen.getByTestId('comic-header-title')
    const progressLine = screen.getByTestId('comic-progress-line')

    // Subordinate to the main title, and inside the same title block.
    expect(storyTitle.className).toContain('text-sm')
    expect(mainTitle.className).toContain('text-xl')
    expect(
      mainTitle.compareDocumentPosition(storyTitle) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(
      storyTitle.compareDocumentPosition(progressLine) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('omits the story title when ComicVine has no issue name', async () => {
    getIssueIntelligenceSpy.mockResolvedValue(intelligenceMetadata({ name: null }))

    renderPillar()

    await screen.findByTestId('comic-header-title')
    await waitFor(() =>
      expect(getIssueIntelligenceSpy).toHaveBeenCalled(),
    )
    expect(screen.queryByTestId('comic-story-title')).toBeNull()
  })
})
