/**
 * Roll provenance on the rating result card (issue #3126).
 *
 * The reported defect: after rolling, the result card showed the picked series
 * but never which die face won or where that series sat in the queue, forcing
 * the reader to count the face-mapping list by hand. These cases pin the
 * result-card surface that closes that loop.
 */
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RatingThread } from '../pages/RollPage/types'

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: {
    searchSeries: vi.fn(),
    getSeriesIssues: vi.fn(),
    getIssueIntelligence: vi.fn().mockResolvedValue(null),
    getIssueIdentity: vi.fn().mockResolvedValue({
      has_confirmed_identity: false,
      comicvine_issue_id: null,
      confirmed_mappings: [],
    }),
    confirmIdentity: vi.fn(),
    replaceIdentity: vi.fn(),
    refreshMetadata: vi.fn(),
    applyCorrection: vi.fn(),
    listCorrections: vi.fn(),
    revertCorrection: vi.fn(),
  },
}))

vi.mock('../pages/RollPage/components/ComicIdentity', () => ({
  ComicIdentity: () => <div data-testid="comic-identity-stub" />,
}))

import { ComicPillar } from '../pages/RollPage/components/ComicPillar'

function rolledThread(overrides: Partial<RatingThread> = {}): RatingThread {
  return {
    id: 7,
    title: 'Stormwatch Vol. 1',
    format: 'single',
    issues_remaining: 5,
    queue_position: 5,
    total_issues: 12,
    reading_progress: '58.33',
    issue_id: 77,
    issue_number: '43',
    next_issue_id: 77,
    next_issue_number: '43',
    last_rolled_result: 14,
    ...overrides,
  }
}

function renderResultCard(thread: RatingThread | null, currentDie?: number) {
  return render(
    <ComicPillar activeRatingThread={thread} currentDie={currentDie} onRefreshThread={vi.fn()} />,
  )
}

describe('Roll result provenance on the result card (#3126)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('names the winning face and the queue position of the picked series', async () => {
    renderResultCard(rolledThread(), 20)

    const result = await screen.findByTestId('comic-roll-result')
    expect(result.textContent).toBe('Rolled 14 of d20 · #5 in queue')

    // The provenance belongs to this card: it reads before the title it explains.
    const title = screen.getByTestId('comic-header-title')
    expect(
      result.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('drops the queue segment when the payload carries no position', async () => {
    renderResultCard(rolledThread({ queue_position: 0 }), 6)

    const result = await screen.findByTestId('comic-roll-result')
    expect(result.textContent).toBe('Rolled 14 of d6')
    expect(result.textContent).not.toContain('queue')
  })

  it('stays silent when the card was not produced by a roll', async () => {
    renderResultCard(rolledThread({ last_rolled_result: null }), 6)

    expect(screen.queryByTestId('comic-roll-result')).toBeNull()
  })

  it('stays silent when the die size for the roll is unknown', async () => {
    renderResultCard(rolledThread(), undefined)

    expect(screen.queryByTestId('comic-roll-result')).toBeNull()
  })

  it('stays silent when no thread is active', async () => {
    renderResultCard(null, 6)

    expect(screen.queryByTestId('comic-roll-result')).toBeNull()
  })
})
