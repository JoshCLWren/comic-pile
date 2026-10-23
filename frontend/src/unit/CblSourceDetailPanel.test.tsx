import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CblSourceDetailPanel } from '../components/CblSourceDetailPanel'
import type { CBLSourceEntryDetail, CBLSourceListDetail } from '../services/api-cbl-sources'

const mocks = vi.hoisted(() => ({
  detail: vi.fn(),
}))

vi.mock('../services/api-cbl-sources', () => ({
  cblSourcesApi: {
    detail: mocks.detail,
  },
}))

const PAGE_SIZE = 200
const TOTAL_POSITIONS = 2210

function entryAt(position: number): CBLSourceEntryDetail {
  return {
    position,
    series_name: 'Ultimate Spider-Man',
    issue_number: String(position),
    volume_year: 2000,
    publication_year: 2000,
    comicvine_issue_id: `4000-${position}`,
    comicvine_volume_id: '4000-vol-1',
  }
}

function pageAt(offset: number): CBLSourceListDetail {
  const count = Math.min(PAGE_SIZE, TOTAL_POSITIONS - offset)
  return {
    id: 7,
    name: 'Ultimate Reading Order',
    source_path: 'Marvel/Ultimate.cbl',
    source_repository: 'JoshCLWren/CBL-ReadingLists',
    source_ref: 'JoshCLWren/CBL-ReadingLists:Marvel/Ultimate.cbl',
    declared_issue_count: TOTAL_POSITIONS,
    content_hash: 'hash-1',
    revision_sha: 'abcdef1234567890',
    entries_total: TOTAL_POSITIONS,
    entries_offset: offset,
    entries_limit: PAGE_SIZE,
    entries: Array.from({ length: count }, (_, index) => entryAt(offset + index + 1)),
  }
}

function renderPanel(state?: unknown) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const initialEntry = state
    ? { pathname: '/cbl-sources', search: '?list=7', state }
    : '/cbl-sources?list=7'
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <CblSourceDetailPanel listId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('CblSourceDetailPanel', () => {
  it('pages beyond 2,000 positions with bounded 200-position requests', async () => {
    const user = userEvent.setup()
    mocks.detail.mockImplementation(
      (_listId: number, params: { offset: number; limit: number }) =>
        Promise.resolve(pageAt(params.offset)),
    )

    renderPanel()
    await screen.findByTestId('cbl-source-detail')

    expect(mocks.detail).toHaveBeenCalledTimes(1)
    expect(mocks.detail).toHaveBeenNthCalledWith(1, 7, { offset: 0, limit: PAGE_SIZE })
    expect(screen.getByRole('button', { name: /Show more positions/ })).toHaveTextContent(
      `200 of ${TOTAL_POSITIONS}`,
    )

    // Eleven pages of at most 200 positions each crosses the 2,000-position
    // boundary without ever asking the API for an unbounded page.
    for (let offset = PAGE_SIZE; offset <= 2000; offset += PAGE_SIZE) {
      await user.click(screen.getByRole('button', { name: /Show more positions/ }))
      await waitFor(() => {
        expect(mocks.detail).toHaveBeenLastCalledWith(7, { offset, limit: PAGE_SIZE })
      })
    }

    expect(mocks.detail).toHaveBeenCalledTimes(11)
    expect(
      mocks.detail.mock.calls.every(([, params]) => params.limit === PAGE_SIZE),
    ).toBe(true)
    expect(screen.getByRole('button', { name: /Show more positions/ })).toHaveTextContent(
      `2200 of ${TOTAL_POSITIONS}`,
    )
  })

  it('returns to the surface recorded in router state', async () => {
    mocks.detail.mockResolvedValue(pageAt(0))
    renderPanel({ from: '/thread/3', label: 'Series' })

    const back = await screen.findByRole('link', { name: 'Back to Series' })
    expect(back).toHaveAttribute('href', '/thread/3')
  })

  it('retries after a failed source load', async () => {
    const user = userEvent.setup()
    mocks.detail
      .mockRejectedValueOnce(new Error('source unavailable'))
      .mockResolvedValueOnce(pageAt(0))
    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load this CBL source.')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByTestId('cbl-source-detail')).toHaveTextContent(
      'Ultimate Reading Order',
    )
  })

  it('omits optional provenance and hides paging for a complete short source', async () => {
    mocks.detail.mockResolvedValue({
      ...pageAt(0),
      name: '',
      source_path: '',
      source_repository: '',
      revision_sha: '',
      entries_total: 1,
      entries: [
        {
          position: 1,
          series_name: 'Minimal Series',
          issue_number: '1',
          volume_year: null,
          publication_year: null,
          comicvine_issue_id: '4000-minimal',
          comicvine_volume_id: null,
        },
      ],
    })
    renderPanel()

    const detail = await screen.findByTestId('cbl-source-detail')
    expect(detail.querySelector('h2')).toHaveTextContent('CBL source')
    expect(detail).toHaveTextContent('Shared CBL source')
    expect(detail).not.toHaveTextContent('revision')
    expect(detail).not.toHaveTextContent('vol ')
    expect(detail).not.toHaveTextContent('Show more positions')
  })

  it('falls back to Reading Plans when router state is absent', async () => {
    mocks.detail.mockResolvedValue(pageAt(0))
    renderPanel()

    const back = await screen.findByRole('link', { name: 'Back to Reading Plans' })
    expect(back).toHaveAttribute('href', '/continuity-plans')
  })
})
