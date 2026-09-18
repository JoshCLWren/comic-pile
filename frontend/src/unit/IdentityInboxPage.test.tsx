import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IdentityInboxPage from '../pages/IdentityInboxPage'
import type { IdentityInboxItem } from '../services/api'

const mockUseIdentityInbox = vi.fn()
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
  useConfirmInboxCandidate: () => mockUseConfirmInboxCandidate(),
  useRejectInboxCandidate: () => mockUseRejectInboxCandidate(),
  useDeferInboxItem: () => mockUseDeferInboxItem(),
  useSkipInboxItem: () => mockUseSkipInboxItem(),
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

beforeEach(() => {
  vi.clearAllMocks()
  mockUseConfirmInboxCandidate.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseRejectInboxCandidate.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseDeferInboxItem.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
  mockUseSkipInboxItem.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, isError: false, error: null, data: undefined, reset: vi.fn() })
})

describe('IdentityInboxPage', () => {
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
})
