import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { RatingThread } from '../pages/RollPage/types'

const { confirmIdentitySpy, replaceIdentitySpy, searchSeriesSpy, getSeriesIssuesSpy, getIssueIdentitySpy } =
  vi.hoisted(() => ({
    // SAFETY: mock payload supplies only the fields this test asserts
    confirmIdentitySpy: vi.fn().mockResolvedValue({} as never),
    // SAFETY: mock payload supplies only the fields this test asserts
    replaceIdentitySpy: vi.fn().mockResolvedValue({} as never),
    searchSeriesSpy: vi.fn(),
    getSeriesIssuesSpy: vi.fn(),
    getIssueIdentitySpy: vi.fn(),
  }))

vi.mock('../services/api', () => ({
  comicVineApi: {
    searchSeries: searchSeriesSpy,
    getSeriesIssues: getSeriesIssuesSpy,
    getIssueIntelligence: vi.fn().mockResolvedValue(null),
    getIssueIdentity: getIssueIdentitySpy,
    confirmIdentity: confirmIdentitySpy,
    replaceIdentity: replaceIdentitySpy,
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
  default: ({
    isOpen,
    threadTitle,
  }: {
    isOpen: boolean
    threadTitle: string
  }) => (isOpen ? <div role="dialog"><h2>Fix Issue Number</h2>{threadTitle}</div> : null),
}))

vi.mock('../pages/RollPage/components/ComicIdentity', () => ({
  ComicIdentity: () => <div data-testid="comic-identity-stub" />,
}))

import { ComicPillar } from '../pages/RollPage/components/ComicPillar'

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

const unlinkedThread: RatingThread = { ...linkedThread, id: 0 }

const mockSeries = {
  comicvine_volume_id: 42,
  name: 'Stormwatch',
  publisher: 'WildStorm',
  start_year: 1993,
  issue_count: 12,
  site_detail_url: null,
  image_url: null,
}

const mockIssue = {
  comicvine_issue_id: 36956,
  issue_number: '1',
  name: 'The Dark Side',
  cover_date: '1993-01-01',
  store_date: null,
  image_url: null,
  site_detail_url: null,
}

function renderPillar(thread: RatingThread = linkedThread) {
  return render(
    <ComicPillar activeRatingThread={thread} onRefreshThread={vi.fn()} />,
  )
}

async function openCorrections(): Promise<HTMLElement> {
  const trigger = await screen.findByRole('button', { name: 'Comic corrections' })
  fireEvent.click(trigger)
  return screen.findByRole('menu')
}

describe('Roll correction controls move behind a quiet overflow menu (#3008)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({ query: '', results: [mockSeries], total_available: 1 })
    getSeriesIssuesSpy.mockResolvedValue({
      comicvine_volume_id: 42,
      series_name: 'Stormwatch',
      issues: [mockIssue],
    })
  })

  it('no longer renders the correction actions as buttons under the comic title', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const controls = await screen.findByTestId('comic-header-controls')
    await waitFor(() => expect(controls.textContent).toContain('Linked'))

    // Nothing correction-shaped is exposed as a standalone button any more.
    expect(within(controls).queryByRole('button', { name: 'Fix issue number' })).toBeNull()
    expect(within(controls).queryByRole('button', { name: 'Wrong series?' })).toBeNull()
    expect(within(controls).queryByRole('button', { name: 'Find ComicVine match' })).toBeNull()
    expect(within(controls).queryByRole('menuitem')).toBeNull()

    // Exactly one quiet trigger remains, and it is a menu button.
    const triggers = within(controls).getAllByRole('button')
    expect(triggers).toHaveLength(1)
    expect(triggers[0]).toHaveAttribute('aria-haspopup', 'menu')
    expect(triggers[0]).toHaveAttribute('aria-label', 'Comic corrections')
    expect(triggers[0].textContent).toContain('⋯')
  })

  it('keeps the correction region visually quieter than the title hierarchy', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const title = await screen.findByTestId('comic-header-title')
    const controls = screen.getByTestId('comic-header-controls')
    const status = await screen.findByTestId('comic-mapping-status')
    const trigger = within(controls).getByRole('button', { name: 'Comic corrections' })

    // The title keeps the page-level treatment...
    expect(title.className).toContain('text-xl')
    expect(title.className).toContain('font-black')

    // ...while correction affordances stay at metadata scale, ride a semantic
    // theme role instead of a raw palette color, and never carry a
    // primary-action fill that would compete with Mark read & save.
    expect(status.className).toContain('text-[10px]')
    expect(status.className).toContain('uppercase')
    expect(status.className).toContain('var(--theme-comic-accent)')
    expect(status.className).not.toMatch(/green-|amber-|stone-\d/)
    expect(status.className).not.toContain('bg-[var(--theme-comic-accent)]')
    expect(trigger.className).toContain('var(--theme-text-dim)')
    expect(trigger.className).not.toContain('bg-[var(--theme-comic-accent)]')

    // The old amber "Find ComicVine match" fill is gone; nothing in the region
    // paints a solid action surface.
    expect(controls.className).not.toContain('bg-amber-500')
  })

  it('keeps mapping status discoverable without opening an edit flow', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const status = await screen.findByTestId('comic-mapping-status')
    expect(status).toHaveAttribute('data-mapping-status', 'linked')
    expect(status).toHaveTextContent('Linked')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('reports an unconfirmed mapping as a readable status instead of a loud button', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: false,
      comicvine_issue_id: null,
      confirmed_mappings: [],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const status = await screen.findByTestId('comic-mapping-status')
    expect(status).toHaveAttribute('data-mapping-status', 'unlinked')
    expect(status).toHaveTextContent('Not linked')
    expect(screen.queryByRole('button', { name: 'Find ComicVine match' })).toBeNull()
  })

  it('retains every correction action inside the overflow menu', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const menu = await openCorrections()
    expect(within(menu).getByRole('menuitem', { name: 'Fix issue number' })).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: 'Wrong series?' })).toBeInTheDocument()
    // A confirmed mapping does not also offer the first-time match action.
    expect(within(menu).queryByRole('menuitem', { name: 'Find ComicVine match' })).toBeNull()
  })

  it('offers the first-time match action in the menu when no mapping is confirmed', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: false,
      comicvine_issue_id: null,
      confirmed_mappings: [],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const menu = await openCorrections()
    expect(within(menu).getByRole('menuitem', { name: 'Find ComicVine match' })).toBeInTheDocument()
    expect(within(menu).queryByRole('menuitem', { name: 'Wrong series?' })).toBeNull()
  })

  it('still opens the Fix Issue Number dialog from the overflow menu', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const menu = await openCorrections()
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Fix issue number' }))

    expect(await screen.findByRole('dialog')).toHaveTextContent('Fix Issue Number')
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('marks Fix issue # unavailable instead of hiding it when there is no thread to correct', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar(unlinkedThread)

    const menu = await openCorrections()
    const fixItem = within(menu).getByRole('menuitem', { name: 'Fix issue number' })
    expect(fixItem).toHaveAttribute('aria-disabled', 'true')

    fireEvent.click(fixItem)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('preserves keyboard and screen-reader access to the collapsed menu', async () => {
    const user = userEvent.setup()
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const trigger = await screen.findByRole('button', { name: 'Comic corrections' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    // ArrowDown opens and moves focus into the menu (menu-button pattern).
    trigger.focus()
    await user.keyboard('{ArrowDown}')
    const menu = await screen.findByRole('menu')
    expect(menu).toHaveAttribute('aria-label', 'Comic corrections')
    expect(trigger).toHaveAttribute('aria-expanded', 'true')

    const items = within(menu).getAllByRole('menuitem')
    expect(document.activeElement).toBe(items[0])

    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(items[1])
    await user.keyboard('{ArrowUp}')
    expect(document.activeElement).toBe(items[0])

    // Escape closes and returns focus to the trigger.
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    // Enter re-opens from the keyboard and lands on the first item.
    await user.keyboard('{Enter}')
    await screen.findByRole('menu')
    expect(document.activeElement).toBe(screen.getByRole('menuitem', { name: 'Fix issue number' }))
  })

  it('returns focus to the trigger after a menu action opens a dialog', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    const trigger = await screen.findByRole('button', { name: 'Comic corrections' })
    const menu = await openCorrections()
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'Wrong series?' }))

    await screen.findByRole('dialog')
    expect(document.activeElement).toBe(trigger)
  })

  it('closes the overflow menu on an outside pointer press', async () => {
    getIssueIdentitySpy.mockResolvedValue({
      has_confirmed_identity: true,
      comicvine_issue_id: null,
      confirmed_mappings: [{ comicvine_id: 36956 }],
      candidate_mappings: [],
      has_unresolved: false,
    })

    renderPillar()

    await openCorrections()
    fireEvent.mouseDown(screen.getByTestId('comic-header-row'))
    expect(screen.queryByRole('menu')).toBeNull()
  })
})