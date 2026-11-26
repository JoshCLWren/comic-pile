import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IdentityInboxPage from '../pages/IdentityInboxPage'
import type { IdentityInboxItem } from '../services/api-identity'

const mockUseIdentityInbox = vi.fn()
const mockUseIdentityInboxSearch = vi.fn()
const mockConfirmIdentity = vi.fn()
type MockMutationResult = {
  mutate: ReturnType<typeof vi.fn>
  mutateAsync: ReturnType<typeof vi.fn>
  isPending: boolean
  isError: boolean
  error: Error | null
  data: unknown
  reset: ReturnType<typeof vi.fn>
}
const mockConfirmMutation: MockMutationResult = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() }
const mockRejectMutation: MockMutationResult = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() }
const mockDeferMutation: MockMutationResult = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() }
const mockSkipMutation: MockMutationResult = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() }

const mockUseConfirmInboxCandidate = vi.fn(() => mockConfirmMutation)
const mockUseRejectInboxCandidate = vi.fn(() => mockRejectMutation)
const mockUseDeferInboxItem = vi.fn(() => mockDeferMutation)
const mockUseSkipInboxItem = vi.fn(() => mockSkipMutation)

vi.mock('../hooks/useIdentityInbox', () => ({
  useIdentityInbox: (offset: number) => mockUseIdentityInbox(offset),
  useIdentityInboxSearch: (query: string, issueId: number, enabled: boolean) =>
    mockUseIdentityInboxSearch(query, issueId, enabled),
  useConfirmInboxCandidate: () => mockUseConfirmInboxCandidate(),
  useRejectInboxCandidate: () => mockUseRejectInboxCandidate(),
  useDeferInboxItem: () => mockUseDeferInboxItem(),
  useSkipInboxItem: () => mockUseSkipInboxItem(),
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: { confirmIdentity: (...args: unknown[]) => mockConfirmIdentity(...args) },
}))

const inboxItem = (overrides: Partial<IdentityInboxItem> = {}): IdentityInboxItem => ({
  mapping_id: 1,
  issue_id: 10,
  thread_id: 100,
  thread_title: 'Mister Miracle',
  issue_number: 'Annual 1',
  status: 'unresolved',
  provider: 'comicvine',
  source_entry_summary: 'Mister Miracle #Annual 1 (DC)',
  why_stopped: 'No validated local candidate',
  candidates: [
    {
      external_identity_id: 501,
      provider: 'comicvine',
      comicvine_id: '4001',
      external_url: 'https://comicvine.gamespot.com/4001',
      metadata_json: { volume: { name: 'Mister Miracle' } },
      status: 'candidate',
      confidence: 0.85,
      evidence_source: 'title_match',
      evidence_json: { evidence: ['title match'] },
      rejection_reason: null,
    },
  ],
  created_at: 1724000000,
  updated_at: 1724001000,
  ...overrides,
})

function mockQueryResult(data: IdentityInboxItem[] = [], total = 0) {
  mockUseIdentityInbox.mockReturnValue({
    data: { items: data, total, offset: 0, limit: 20 },
    isPending: false,
    isError: false,
    error: null,
  })
}

function mockLoadingState() {
  mockUseIdentityInbox.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    error: null,
  })
}

function mockErrorState(message: string) {
  mockUseIdentityInbox.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: true,
    error: new Error(message),
  })
}

function mockSearchResult(overrides: Record<string, unknown> = {}) {
  mockUseIdentityInboxSearch.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockSearchResult()
  mockConfirmIdentity.mockResolvedValue({})
  mockUseConfirmInboxCandidate.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseRejectInboxCandidate.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseDeferInboxItem.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseSkipInboxItem.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
})

describe('IdentityInboxPage', () => {
  const candidateArtCases: Array<{
    source: string
    image: Record<string, string | Record<string, string> | null>
    url: string
  }> = [
    { source: 'direct image URL', image: { image_url: 'https://example.test/direct.jpg' }, url: 'https://example.test/direct.jpg' },
    { source: 'primary image', image: { primary_image: 'https://example.test/primary.jpg' }, url: 'https://example.test/primary.jpg' },
    { source: 'medium image', image: { image: { medium_url: 'https://example.test/medium.jpg' } }, url: 'https://example.test/medium.jpg' },
    { source: 'small image', image: { image: { small_url: 'https://example.test/small.jpg' } }, url: 'https://example.test/small.jpg' },
    { source: 'original image', image: { image: { original_url: 'https://example.test/original.jpg' } }, url: 'https://example.test/original.jpg' },
    { source: 'thumbnail', image: { image: { thumb_url: 'https://example.test/thumb.jpg' } }, url: 'https://example.test/thumb.jpg' },
  ]
  it.each(candidateArtCases)('uses the candidate own $source without resolving any other identity', async ({ image, url }) => {
    const item = inboxItem()
    item.candidates[0].metadata_json = { volume: { name: 'Mister Miracle' }, ...image }
    mockQueryResult([item], 1)
    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    expect(screen.getByRole('img', { name: 'Cover for Mister Miracle' })).toHaveAttribute('src', url)
  })

  it('renders the shared placeholder for a provider candidate with no supplied art', async () => {
    mockQueryResult([inboxItem()], 1)
    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    expect(screen.getByLabelText('No cover for Mister Miracle')).toBeInTheDocument()
  })

  it('shows each unconfirmed provider candidate own cover without changing confirmation actions', async () => {
    const item = inboxItem()
    item.candidates[0].metadata_json = {
      volume: { name: 'Mister Miracle' },
      image: { medium_url: 'https://example.test/comicvine-mister-miracle.jpg' },
      issue_number: 'Annual 1',
    }
    mockQueryResult([item], 1)
    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    expect(screen.getByRole('img', { name: 'Cover for Mister Miracle #Annual 1' })).toHaveAttribute(
      'src', 'https://example.test/comicvine-mister-miracle.jpg',
    )
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeEnabled()
  })

  it('renders loading state while fetching items', () => {
    mockLoadingState()

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('surfaces an error when fetching items fails', () => {
    mockErrorState('network error')

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText(/network error/i)).toBeInTheDocument()
  })

  it('shows an empty state when there are no inbox items', () => {
    mockQueryResult([], 0)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('All clear!')).toBeInTheDocument()
  })

  it('renders inbox items as expandable cards', () => {
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
    expect(screen.getByText('#Annual 1')).toBeInTheDocument()
    expect(screen.getByText('No validated local candidate')).toBeInTheDocument()
  })

  it('expands an item to reveal its action buttons', async () => {
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))

    await waitFor(() => expect(screen.getByText('Confirm')).toBeInTheDocument())
    expect(screen.getByText('Reject')).toBeInTheDocument()
    expect(screen.getByText('Defer')).toBeInTheDocument()
    expect(screen.getByText('Skip')).toBeInTheDocument()
  })

  it('calls the confirm mutation when Confirm is clicked', async () => {
    const confirmMutate = vi.fn()
    mockUseConfirmInboxCandidate.mockReturnValue({ mutate: confirmMutate, mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))
    const confirmButton = await screen.findByText('Confirm')
    await userEvent.click(confirmButton)

    await waitFor(() =>
      expect(confirmMutate).toHaveBeenCalledWith({
        mappingId: 1,
        payload: { external_identity_id: 501 },
      }),
    )
  })

  it('shows a reject form when Reject is clicked without a reason', async () => {
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))
    const rejectButton = await screen.findByText('Reject')
    await userEvent.click(rejectButton)

    expect(screen.getByPlaceholderText('Why is this candidate wrong?')).toBeInTheDocument()
  })

  it('calls the defer mutation when Defer is clicked', async () => {
    const deferMutate = vi.fn()
    mockUseDeferInboxItem.mockReturnValue({ mutate: deferMutate, mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))
    const deferButton = await screen.findByText('Defer')
    await userEvent.click(deferButton)

    await waitFor(() => expect(deferMutate).toHaveBeenCalledWith(1))
  })

  it('calls the skip mutation when Skip is clicked', async () => {
    const skipMutate = vi.fn()
    mockUseSkipInboxItem.mockReturnValue({ mutate: skipMutate, mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))
    const skipButton = await screen.findByText('Skip')
    await userEvent.click(skipButton)

    await waitFor(() => expect(skipMutate).toHaveBeenCalledWith(1))
  })

  it('shows pagination controls when there are multiple pages', () => {
    mockQueryResult(
      Array.from({ length: 20 }, (_, i) => inboxItem({ mapping_id: i })),
      50,
    )

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('50 unresolved items')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('renders the page heading and description', () => {
    mockQueryResult([], 0)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'Identity Inbox' })).toBeInTheDocument()
    expect(screen.getByText(/Resolve unmatched or ambiguous external comic identities/i)).toBeInTheDocument()
  })

  it('uses the useIdentityInbox hook with offset', () => {
    mockQueryResult([], 0)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(mockUseIdentityInbox).toHaveBeenCalledWith(0)
  })

  it('surfaces an action error without discarding the current list', () => {
    mockUseConfirmInboxCandidate.mockReturnValue({
      mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false,
      isError: true, error: new Error('action failed'), data: undefined, reset: vi.fn(),
    })
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText(/action failed/i)).toBeInTheDocument()
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('navigates to the next page via the Next button', async () => {
    mockQueryResult(
      Array.from({ length: 20 }, (_, i) => inboxItem({ mapping_id: i })),
      50,
    )

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('50 unresolved items')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(mockUseIdentityInbox).toHaveBeenLastCalledWith(20))
  })

  it('keeps only one item expanded at a time', async () => {
    const candidate = (
      identityId: number,
      comicvineId: string,
      evidence: string[],
    ) => ({
      external_identity_id: identityId,
      provider: 'comicvine',
      comicvine_id: comicvineId,
      external_url: null,
      metadata_json: {},
      status: 'candidate',
      confidence: 0.8,
      evidence_source: 'title_match',
      evidence_json: { evidence },
      rejection_reason: null,
    })
    const itemA = inboxItem({
      mapping_id: 1,
      thread_title: 'Mister Miracle',
      candidates: [candidate(501, '4001', ['mister miracle title match'])],
    })
    const itemB = inboxItem({
      mapping_id: 2,
      thread_title: 'New Gods',
      candidates: [candidate(601, '4002', ['new gods volume match'])],
    })
    mockQueryResult([itemA, itemB], 2)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await userEvent.click(screen.getByText('Mister Miracle'))
    await waitFor(() =>
      expect(screen.getByText('mister miracle title match')).toBeInTheDocument(),
    )
    expect(screen.queryByText('new gods volume match')).not.toBeInTheDocument()

    await userEvent.click(screen.getByText('New Gods'))

    expect(screen.queryByText('mister miracle title match')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('new gods volume match')).toBeInTheDocument(),
    )
    expect(screen.getAllByText('Confirm')).toHaveLength(1)
  })

  // #5434: the reviewer-driven discovery panel, its explainable results and
  // its partial-series confirmation path are part of the shipped UI, so every
  // branch must be exercised rather than left to the coverage gate.
  it('renders actionable next steps when the inbox item supplies them', async () => {
    mockQueryResult([
      inboxItem({ next_steps: ['Search by a different series name', 'Paste a ComicVine URL'] }),
    ], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))

    expect(screen.getByText('Next steps')).toBeInTheDocument()
    expect(screen.getByText('Paste a ComicVine URL')).toBeInTheDocument()
  })

  it('opens and hides the Find match panel', async () => {
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByLabelText('ComicVine search query')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hide search' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Hide search' }))
    expect(screen.queryByLabelText('ComicVine search query')).not.toBeInTheDocument()
  })

  it('submits a trimmed name or pasted URL to scoped discovery', async () => {
    mockQueryResult([inboxItem()], 1)

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))
    await userEvent.type(
      screen.getByLabelText('ComicVine search query'),
      '  https://comicvine.gamespot.com/volume/4050-42/  ',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    await waitFor(() =>
      expect(mockUseIdentityInboxSearch).toHaveBeenCalledWith(
        'https://comicvine.gamespot.com/volume/4050-42/',
        10,
        true,
      ),
    )
  })

  it('shows a searching state while discovery is pending', async () => {
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({ isPending: true })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText('Searching…')).toBeInTheDocument()
  })

  it('surfaces failed discovery without changing the inbox item', async () => {
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({ isError: true })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText(/Search is unavailable right now/)).toBeInTheDocument()
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('renders explainable scores and evidence for provider results', async () => {
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({
      data: {
        issue_id: 10,
        query: 'Hellboy',
        results: [
          {
            comicvine_issue_id: 900,
            comicvine_volume_id: 42,
            volume_name: 'Hellboy',
            issue_number: '1',
            issue_name: null,
            publisher: 'Dark Horse',
            start_year: 2000,
            site_detail_url: null,
            image_url: null,
            score: 0.87,
            evidence: ['fuzzy title match 87%'],
          },
        ],
        total_available: 1,
        partial_matches: [],
        no_match_reason: null,
      },
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText('87% match')).toBeInTheDocument()
    expect(screen.getByText('fuzzy title match 87%')).toBeInTheDocument()
    expect(screen.getByText(/#1 \(Hellboy\)/)).toBeInTheDocument()
  })

  it('renders sparse provider results without score or evidence', async () => {
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({
      data: {
        issue_id: 10,
        query: 'Hellboy',
        results: [
          {
            comicvine_issue_id: 903,
            comicvine_volume_id: null,
            volume_name: null,
            issue_number: null,
            issue_name: null,
            publisher: null,
            start_year: null,
            site_detail_url: null,
            image_url: null,
            score: null,
            evidence: [],
          },
        ],
        total_available: 1,
        partial_matches: [],
        no_match_reason: null,
      },
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText('#?')).toBeInTheDocument()
    expect(screen.queryByText(/% match/)).not.toBeInTheDocument()
  })

  it('confirms only unambiguous partial matches and lists the rest for review', async () => {
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({
      data: {
        issue_id: 10,
        query: 'B.P.R.D.',
        results: [],
        total_available: 0,
        partial_matches: [
          {
            comicvine_volume_id: 42,
            volume_name: 'B.P.R.D.',
            actionable_reason: 'Volume found; 1 issue matches unambiguously',
            matched: [
              {
                issue_id: 11,
                issue_number: '2',
                comicvine_issue_id: 901,
                mapping_id: 2,
                external_identity_id: 502,
                reason: 'exact label match',
              },
            ],
            unmatched: [
              {
                issue_id: 12,
                issue_number: '3',
                comicvine_issue_id: 0,
                mapping_id: null,
                external_identity_id: null,
                reason: 'not on this volume',
              },
            ],
          },
        ],
        no_match_reason: null,
      },
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText('Volume found; 1 issue matches unambiguously')).toBeInTheDocument()
    expect(screen.getByText('#2 → ComicVine #901')).toBeInTheDocument()
    expect(screen.getByText('#3: not on this volume')).toBeInTheDocument()

    const confirmButtons = screen.getAllByRole('button', { name: 'Confirm' })
    await userEvent.click(confirmButtons[confirmButtons.length - 1])
    await waitFor(() => expect(mockConfirmIdentity).toHaveBeenCalledWith(11, 901))
  })

  it('explains an empty discovery result and offers a default fallback', async () => {
    mockQueryResult([
      inboxItem({ mapping_id: 1 }),
      inboxItem({ mapping_id: 2, issue_id: 11, thread_title: 'Hellboy' }),
    ], 2)
    mockUseIdentityInboxSearch
      .mockReturnValueOnce({
        data: {
          issue_id: 10,
          query: 'Mister Miracle',
          results: [],
          total_available: 0,
          partial_matches: [],
          no_match_reason: 'No volume found for this title',
        },
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      })
      .mockReturnValue({
        data: {
          issue_id: 11,
          query: 'Hellboy',
          results: [],
          total_available: 0,
          partial_matches: [],
          no_match_reason: null,
        },
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))

    expect(screen.getByText(/No volume found for this title/)).toBeInTheDocument()

    await userEvent.click(screen.getByText('Hellboy'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))
    expect(screen.getByText(/No matches found/)).toBeInTheDocument()
  })

  it('surfaces a failed confirmation without changing the issue', async () => {
    mockConfirmIdentity.mockRejectedValue(new Error('confirm failed'))
    mockQueryResult([inboxItem()], 1)
    mockSearchResult({
      data: {
        issue_id: 10,
        query: 'Hellboy',
        results: [],
        total_available: 0,
        partial_matches: [
          {
            comicvine_volume_id: 42,
            volume_name: 'Hellboy',
            actionable_reason: 'Volume found; 1 issue matches unambiguously',
            matched: [
              {
                issue_id: 11,
                issue_number: '2',
                comicvine_issue_id: 901,
                mapping_id: 2,
                external_identity_id: 502,
                reason: 'exact label match',
              },
            ],
            unmatched: [],
          },
        ],
        no_match_reason: null,
      },
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByText('Mister Miracle'))
    await userEvent.click(screen.getByRole('button', { name: 'Find match' }))
    const confirmButtons = screen.getAllByRole('button', { name: 'Confirm' })
    await userEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() =>
      expect(screen.getByText(/Confirmation failed/)).toBeInTheDocument(),
    )
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })
})
