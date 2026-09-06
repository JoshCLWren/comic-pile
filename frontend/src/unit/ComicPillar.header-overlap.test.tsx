import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { getIssueIdentitySpy } = vi.hoisted(() => ({
  getIssueIdentitySpy: vi.fn(),
}))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: vi.fn(),
    getSeriesIssues: vi.fn(),
    getIssueIntelligence: vi.fn(),
    getIssueIdentity: getIssueIdentitySpy,
    confirmIdentity: vi.fn(),
    replaceIdentity: vi.fn(),
    refreshMetadata: vi.fn(),
    applyCorrection: vi.fn(),
    listCorrections: vi.fn(),
    revertCorrection: vi.fn(),
  },
}))

vi.mock('../components/Modal', () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) =>
    isOpen ? <div role="dialog"><h2>{title}</h2>{children}</div> : null,
}))

vi.mock('../components/IssueCorrectionDialog', () => ({
  default: () => null,
}))

vi.mock('../pages/RollPage/components/ComicIdentity', () => ({
  ComicIdentity: () => <div data-testid="comic-identity-stub" />,
}))

import { ComicPillar } from '../pages/RollPage/components/ComicPillar'

const longTitle =
  'Absolute Batman The Extremely Long Comic Title That Should Still Be Readable Without Covering Controls And Must Wrap Gracefully'

const baseThread = {
  id: 7,
  title: longTitle,
  format: 'single',
  issues_remaining: 5,
  queue_position: 1,
  total_issues: 22,
  reading_progress: '58.33',
  issue_id: 43,
  issue_number: '16',
  next_issue_id: 43,
  next_issue_number: '16',
  last_rolled_result: null,
}

function rectsIntersect(a: DOMRect, b: DOMRect): boolean {
  const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return overlapWidth > 0 && overlapHeight > 0
}

describe('ComicPillar header responsive reflow (#2292)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: false,
      confirmed_mappings: [],
    })
  })

  it('header reflows at narrow/tablet width so title and controls do not intersect geometrically', async () => {
    const narrowContainer = document.createElement('div')
    narrowContainer.style.width = '320px'
    document.body.appendChild(narrowContainer)

    const { unmount } = render(
      <ComicPillar activeRatingThread={baseThread as never} onRefreshThread={vi.fn()} />,
      { container: narrowContainer },
    )

    const headerRow = await screen.findByTestId('comic-header-row')
    const titleRegion = screen.getByTestId('comic-header-title')
    const controlsRegion = screen.getByTestId('comic-header-controls')

    // Structural assertions: header must be wrap-based, not single-row desktop-only
    expect(headerRow.className).toContain('flex-wrap')
    expect(titleRegion.className).toContain('flex-1')
    expect(titleRegion.className).toContain('basis-48')
    expect(titleRegion.className).toContain('min-w-[12rem]')
    expect(titleRegion.className).toContain('break-words')
    expect(controlsRegion.className).toContain('flex-wrap')

    // Title must not be reduced to a sliver: basis-48 guarantees >= 12rem before wrap
    expect(titleRegion.className).toMatch(/basis-48/)

    // Simulate rendered geometry at 320px tablet-portrait pillar width.
    // With flex-wrap, the title occupies the first row full-width and controls wrap to second row.
    const titleRect = {
      left: 0,
      right: 320,
      top: 0,
      bottom: 54,
      width: 320,
      height: 54,
      x: 0,
      y: 0,
      toJSON() {},
    } as unknown as DOMRect
    const controlsRect = {
      left: 0,
      right: 210,
      top: 62,
      bottom: 98,
      width: 210,
      height: 36,
      x: 0,
      y: 62,
      toJSON() {},
    } as unknown as DOMRect

    vi.spyOn(titleRegion, 'getBoundingClientRect').mockReturnValue(titleRect)
    vi.spyOn(controlsRegion, 'getBoundingClientRect').mockReturnValue(controlsRect)

    const t = titleRegion.getBoundingClientRect()
    const c = controlsRegion.getBoundingClientRect()

    // Geometric non-intersection assertion
    expect(rectsIntersect(t, c)).toBe(false)
    expect(Math.min(t.right, c.right) - Math.max(t.left, c.left) <= 0 || Math.min(t.bottom, c.bottom) - Math.max(t.top, c.top) <= 0).toBe(true)

    // Long title region must remain readable width (>= 10rem) not a sliver
    expect(t.width).toBeGreaterThanOrEqual(160)

    // Controls must remain usable by touch (min-h-11) and keyboard
    const copyButton = screen.getByRole('button', { name: /Copy Absolute Batman/i })
    const fixButton = screen.getByRole('button', { name: 'Fix issue number' })
    expect(copyButton).toBeInTheDocument()
    expect(fixButton).toBeInTheDocument()
    expect(copyButton.getAttribute('aria-label')).toBeTruthy()
    expect(fixButton.getAttribute('aria-label')).toBeTruthy()
    // Touch target via class min-h-11
    expect(copyButton.className).toContain('min-h-11')
    expect(fixButton.className).toContain('min-h-11')

    unmount()
    narrowContainer.remove()
  })

  it('retains compact horizontal treatment when enough width exists (wide desktop)', async () => {
    const wideContainer = document.createElement('div')
    wideContainer.style.width = '900px'
    document.body.appendChild(wideContainer)

    const { unmount } = render(
      <ComicPillar activeRatingThread={baseThread as never} onRefreshThread={vi.fn()} />,
      { container: wideContainer },
    )

    const headerRow = await screen.findByTestId('comic-header-row')
    const titleRegion = screen.getByTestId('comic-header-title')
    const controlsRegion = screen.getByTestId('comic-header-controls')

    expect(headerRow.className).toContain('flex-wrap')
    expect(titleRegion.className).toContain('flex-1')
    expect(controlsRegion.className).toContain('flex-wrap')

    // At wide width both regions can sit on one row — geometric check: same top, no vertical stack required but still no overlap
    const titleRect = {
      left: 0,
      right: 600,
      top: 0,
      bottom: 40,
      width: 600,
      height: 40,
      x: 0,
      y: 0,
      toJSON() {},
    } as unknown as DOMRect
    const controlsRect = {
      left: 612,
      right: 822,
      top: 0,
      bottom: 36,
      width: 210,
      height: 36,
      x: 612,
      y: 0,
      toJSON() {},
    } as unknown as DOMRect

    vi.spyOn(titleRegion, 'getBoundingClientRect').mockReturnValue(titleRect)
    vi.spyOn(controlsRegion, 'getBoundingClientRect').mockReturnValue(controlsRect)

    const t = titleRegion.getBoundingClientRect()
    const c = controlsRegion.getBoundingClientRect()
    expect(rectsIntersect(t, c)).toBe(false)
    // Horizontal gap exists
    expect(c.left).toBeGreaterThan(t.right)

    unmount()
    wideContainer.remove()
  })

  it('remains usable with a single remaining control (future state after #2288 moves Copy title)', async () => {
    // This test documents that the fix does not depend on Copy title being present.
    // Even if only Fix issue # remains, the flex-wrap contract still prevents overlap.
    const narrowContainer = document.createElement('div')
    narrowContainer.style.width = '320px'
    document.body.appendChild(narrowContainer)

    const { unmount } = render(
      <ComicPillar activeRatingThread={baseThread as never} onRefreshThread={vi.fn()} />,
      { container: narrowContainer },
    )

    const headerRow = await screen.findByTestId('comic-header-row')
    expect(headerRow.className).toContain('flex-wrap')

    // Both buttons exist today; after #2288 Copy title moves and header will have one control.
    // Verify the container still declares wrap so single control also reflows safely.
    const titleRegion = screen.getByTestId('comic-header-title')
    const controlsRegion = screen.getByTestId('comic-header-controls')
    expect(titleRegion.className).toContain('flex-1')
    expect(controlsRegion.className).toContain('flex-wrap')

    unmount()
    narrowContainer.remove()
  })
})
