import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { beginRouteRestore } from '../scroll/scrollCoordinator'
import { issueCardsApi, type IssueCard, type IssueReadRateResponse } from '../services/issueCardsApi'
import { getReadingListProgressIndex } from '../utils/readingListProgress'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
  searchIssues: vi.fn(),
  apply: vi.fn(),
  exportXml: vi.fn(),
}))

vi.mock('../services/api-custom-cbl', async () => {
  const actual = await vi.importActual<typeof import('../services/api-custom-cbl')>('../services/api-custom-cbl')
  return { ...actual, customCBLApi: mocks }
})

const fetchCards = vi.spyOn(issueCardsApi, 'fetchCards')
const patchIssue = vi.spyOn(issueCardsApi, 'patchIssue')

function detectiveEntries() {
  return [
    {
      id: 1, position: 0, issue_id: 9001, thread_id: 55,
      series_name: 'Detective Comics', issue_number: '3', status: 'read',
      skipped: false, is_checkpoint: false, gate: 'none' as const,
    },
    {
      id: 2, position: 1, issue_id: 9002, thread_id: 55,
      series_name: 'Detective Comics', issue_number: '4', status: 'read',
      skipped: false, is_checkpoint: false, gate: 'none' as const,
    },
  ]
}

function detectiveCard(issueId: number, status: string): IssueCard {
  return {
    issue_id: issueId, thread_id: 55, thread_title: 'Detective Comics',
    issue_number: issueId === 9001 ? '3' : '4', status, rating: null,
    mapping_state: 'unmapped', has_confirmed_identity: false, cover_image_url: null,
  }
}

function directReceipt(issueId: number, status: 'read' | 'unread'): IssueReadRateResponse {
  return {
    issue: detectiveCard(issueId, status),
    thread: {
      thread_id: 55, status: 'active', issues_remaining: status === 'read' ? 0 : 1,
      next_unread_issue_id: status === 'unread' ? issueId : null,
    },
    read_event_created: true, rating_event_created: false, replayed: false,
  }
}

function entriesWithProgress(firstUnread: number, skippedPositions: number[] = []) {
  return Array.from({ length: 466 }, (_, position) => ({
    id: position + 1,
    issue_id: 50000 + position,
    position,
    thread_id: position + 10,
    series_name: position === 83 ? 'B.P.R.D.: Casualties' : 'Reading Order Comic',
    issue_number: position === 83 ? '1' : String(position + 1),
    status: position < firstUnread ? 'read' : 'unread',
    skipped: skippedPositions.includes(position),
    is_checkpoint: false,
    gate: 'none',
  }))
}

function renderEditor(entries: ReturnType<typeof entriesWithProgress>) {
  mocks.get.mockResolvedValue({
    id: 2,
    user_id: 1,
    name: 'Mignolaverse — Julix Comics (Unread)',
    description: '',
    mode: 'strict',
    issue_count: entries.length,
    entries,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30000 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CustomCBLBuilder initialListId={2} /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Reading List editing progress', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    mocks.list.mockResolvedValue([{ id: 2, name: 'Mignolaverse', issue_count: 466, mode: 'strict' }])
  })

  it('opens a 466-entry Julix list at the first unread issue rather than position one', async () => {
    renderEditor(entriesWithProgress(83))
    const next = await screen.findByText('B.P.R.D.: Casualties #1')
    const card = next.closest('[data-testid="reading-list-entry"]')!
    expect(card).toHaveAttribute('aria-current', 'step')
    expect(card).toHaveTextContent('Up next')
    expect(screen.getByText('466 matching issues · Page 3 of 16')).toBeInTheDocument()
    expect(screen.queryByText('Reading Order Comic #1')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to next unread · #84' })).toBeVisible()
    await waitFor(() => expect(card).toHaveFocus())

    fireEvent.click(screen.getAllByRole('button', { name: 'Next 30' })[0])
    expect(screen.queryByText('B.P.R.D.: Casualties #1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Go to next unread · #84' }))
    expect(screen.getByText('B.P.R.D.: Casualties #1')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('B.P.R.D.: Casualties #1').closest('[data-testid="reading-list-entry"]')).toHaveFocus())
  })

  it('uses the next non-skipped unread issue and does not mistake read items for the frontier', async () => {
    renderEditor(entriesWithProgress(83, [83]))
    await screen.findByText('Reading Order Comic #85')
    expect(screen.getByRole('button', { name: 'Go to next unread · #85' })).toBeVisible()
    expect(screen.getByText('Reading Order Comic #85').closest('[aria-current]')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('B.P.R.D.: Casualties #1').closest('[aria-current]')).toBeNull()
  })

  it('opens near the end without an unread badge when everything has been read', async () => {
    const entries = entriesWithProgress(466)
    expect(getReadingListProgressIndex(entries)).toBe(465)
    renderEditor(entries)
    await screen.findByText('Reading Order Comic #466')
    expect(screen.getByText('466 matching issues · Page 16 of 16')).toBeInTheDocument()
    expect(screen.queryByText('Up next')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Go to next unread/ })).not.toBeInTheDocument()
  })

  it('defers the open reveal until route scroll restoration settles (#4248)', async () => {
    const original = Element.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, writable: true, value: scrollIntoView })
    const endRestore = beginRouteRestore()
    try {
      renderEditor(entriesWithProgress(83))
      const next = await screen.findByText('B.P.R.D.: Casualties #1')
      const card = next.closest('[data-testid="reading-list-entry"]')!
      expect(card).toHaveAttribute('aria-current', 'step')
      // While route restoration is settling, the semantic reveal must not race it.
      expect(scrollIntoView).not.toHaveBeenCalled()
      endRestore()
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'center' }))
    } finally {
      endRestore()
      Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, writable: true, value: original })
    }
  })

  it('returns the first unread unskipped index or the final entry', () => {
    expect(getReadingListProgressIndex([])).toBe(0)
    expect(getReadingListProgressIndex([
      { status: 'read', skipped: false },
      { status: 'unread', skipped: true },
      { status: 'unread', skipped: false },
    ])).toBe(2)
    expect(getReadingListProgressIndex([
      { status: 'read', skipped: false },
      { status: 'read', skipped: false },
    ])).toBe(1)
  })

  it('reconciles the Current position banner immediately after a direct read/unread (#5865)', async () => {
    const user = userEvent.setup()
    const entries = detectiveEntries()
    mocks.get.mockResolvedValue({
      id: 2, user_id: 1, name: 'Detective Comics', description: '', mode: 'strict',
      issue_count: entries.length, entries,
      created_at: '2026-11-26T00:00:00Z', updated_at: '2026-11-26T00:00:00Z',
    })
    const statuses = new Map(entries.map((entry) => [entry.issue_id, entry.status]))
    fetchCards.mockImplementation(async (ids) => ids.map((id) => detectiveCard(id, statuses.get(id) ?? 'read')))
    patchIssue.mockImplementation(async (id, input) => {
      const status = input.status === 'unread' ? 'unread' : 'read'
      statuses.set(id, status)
      return directReceipt(id, status)
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30000 } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter><CustomCBLBuilder initialListId={2} /></MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('Current position: all issues in this list are read or skipped.')).toBeVisible()
    const entry = (await screen.findByText('Detective Comics #3')).closest('[data-testid="reading-list-entry"]') as HTMLElement
    const card = within(entry).getByTestId('comic-issue-card')

    await user.click(within(card).getByRole('button', { name: 'Mark unread' }))
    expect(await screen.findByText(
      'Current position: next unread is #1 · Detective Comics #3 (unread).',
    )).toBeVisible()
    expect(entry).toHaveAttribute('aria-current', 'step')

    await user.click(within(card).getByRole('button', { name: 'Read now' }))
    await user.click(within(card).getByRole('button', { name: 'Mark read & save' }))
    expect(await screen.findByText('Current position: all issues in this list are read or skipped.')).toBeVisible()
    expect(patchIssue).toHaveBeenCalledWith(9001, expect.objectContaining({ status: 'unread' }))
    expect(patchIssue).toHaveBeenCalledWith(9001, expect.objectContaining({ status: 'read' }))
  })
})
