import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import IdentityInboxPage from '../pages/IdentityInboxPage'

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()
const mockGetAccessToken = vi.fn(() => 'test-token')

vi.mock('../services/api', () => {
  return {
    default: {
      get: (...args: Parameters<typeof mockGet>) => mockGet(...args),
      post: (...args: Parameters<typeof mockPost>) => mockPost(...args),
      put: vi.fn(),
      delete: vi.fn(),
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    },
    setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) =>
      mockSetAccessToken(...args),
    clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) =>
      mockClearAccessToken(...args),
    getAccessToken: () => mockGetAccessToken(),
  }
})

const inboxItem = (overrides = {}) => ({
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

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockSetAccessToken.mockReset()
  mockClearAccessToken.mockReset()
  window.localStorage.clear()
})

describe('IdentityInboxPage', () => {
  it('renders loading state while fetching items', async () => {
    let resolve: (value: { items: typeof inboxItem[]; total: number; offset: number; limit: number }) => void
    mockGet.mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r
        }),
    )

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('Loading...')).toBeInTheDocument()
    resolve!({ items: [], total: 0, offset: 0, limit: 20 })
    await waitFor(() => expect(screen.getByText('All clear!')).toBeInTheDocument())
  })

  it('surfaces an error when fetching items fails', async () => {
    mockGet.mockRejectedValueOnce(new Error('network error'))

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument())
  })

  it('shows an empty state when there are no inbox items', async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('All clear!')).toBeInTheDocument())
  })

  it('renders inbox items as expandable cards', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    expect(screen.getByText('#Annual 1')).toBeInTheDocument()
    expect(screen.getByText('No validated local candidate')).toBeInTheDocument()
    // Candidates section is only visible when expanded
  })

  it('expands an item to reveal its action buttons', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))

    await waitFor(() => expect(screen.getByText('Confirm')).toBeInTheDocument())
    expect(screen.getByText('Reject')).toBeInTheDocument()
    expect(screen.getByText('Defer')).toBeInTheDocument()
    expect(screen.getByText('Skip')).toBeInTheDocument()
  })

  it('calls the confirm endpoint and refreshes the list', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })
    mockPost.mockResolvedValueOnce({})
    mockGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))
    const confirmButton = await screen.findByText('Confirm')
    await userEvent.click(confirmButton)

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/v1/identity-inbox/1/confirm', {
        external_identity_id: 501,
      }),
    )
  })

  it('shows a reject form when Reject is clicked without a reason', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))
    const rejectButton = await screen.findByText('Reject')
    await userEvent.click(rejectButton)

    expect(screen.getByPlaceholderText('Why is this candidate wrong?')).toBeInTheDocument()
  })

  it('calls the defer endpoint when Defer is clicked', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })
    mockPost.mockResolvedValueOnce({})
    mockGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))
    const deferButton = await screen.findByText('Defer')
    await userEvent.click(deferButton)

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/v1/identity-inbox/1/defer', undefined),
    )
  })

  it('calls the skip endpoint when Skip is clicked', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })
    mockPost.mockResolvedValueOnce({})
    mockGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))
    const skipButton = await screen.findByText('Skip')
    await userEvent.click(skipButton)

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith('/v1/identity-inbox/1/skip', undefined),
    )
  })

  it('shows pagination controls when there are multiple pages', async () => {
    mockGet.mockResolvedValueOnce({
      items: Array.from({ length: 20 }, (_, i) => inboxItem({ mapping_id: i })),
      total: 50,
      offset: 0,
      limit: 20,
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('50 unresolved items')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('renders the page heading and description', async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Identity Inbox' })).toBeInTheDocument()
    expect(screen.getByText(/Resolve unmatched or ambiguous external comic identities/i)).toBeInTheDocument()
  })

  it('surfaces an action error without discarding the current list', async () => {
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })
    mockPost.mockRejectedValueOnce(new Error('action failed'))
    mockGet.mockResolvedValueOnce({ items: [inboxItem()], total: 1, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Mister Miracle'))
    const confirmButton = await screen.findByText('Confirm')
    await userEvent.click(confirmButton)

    await waitFor(() => expect(screen.getByText(/action failed/i)).toBeInTheDocument())
    expect(screen.getByText('Mister Miracle')).toBeInTheDocument()
  })

  it('navigates to the next page via the Next button', async () => {
    mockGet.mockResolvedValueOnce({
      items: Array.from({ length: 20 }, (_, i) => inboxItem({ mapping_id: i })),
      total: 50,
      offset: 0,
      limit: 20,
    })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('50 unresolved items')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() =>
      expect(mockGet).toHaveBeenLastCalledWith('/v1/identity-inbox', {
        params: { offset: 20, limit: 20 },
      }),
    )
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
    mockGet.mockResolvedValueOnce({ items: [itemA, itemB], total: 2, offset: 0, limit: 20 })

    render(
      <MemoryRouter initialEntries={['/identity-inbox']}>
        <Routes>
          <Route path="/identity-inbox" element={<IdentityInboxPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Mister Miracle')).toBeInTheDocument())
    expect(
      screen
        .getAllByRole('button')
        .filter((button) => button.textContent?.includes('Mister Miracle')),
    ).toHaveLength(1)
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