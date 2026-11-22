import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
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
})
