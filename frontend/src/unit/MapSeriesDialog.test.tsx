import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ComponentProps, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapSeriesDialog from '../pages/QueuePage/MapSeriesDialog'

const { threadsGetMock, issuesListMock } = vi.hoisted(() => ({
  threadsGetMock: vi.fn(),
  issuesListMock: vi.fn(),
}))

vi.mock('../services/api-threads', () => ({
  threadsApi: { get: threadsGetMock },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: issuesListMock },
}))

vi.mock('../components/ComicVineSearchDialog', () => ({
  default: ({
    issueId,
    threadTitle,
    issueNumber,
    onClose,
    onConfirmed,
  }: {
    issueId: number | null
    threadTitle: string
    issueNumber: string | null
    onClose: () => void
    onConfirmed: () => void
  }) => (
    <div
      data-testid="mock-comicvine-search"
      data-issue-id={issueId ?? ''}
      data-issue-number={issueNumber ?? ''}
      data-thread-title={threadTitle}
    >
      <button type="button" data-testid="mock-search-close" onClick={onClose}>
        Close search
      </button>
      <button type="button" data-testid="mock-search-confirm" onClick={onConfirmed}>
        Confirm mapping
      </button>
    </div>
  ),
}))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function renderDialog(overrides: Partial<ComponentProps<typeof MapSeriesDialog>> = {}) {
  const props = {
    isOpen: true,
    threadId: 9,
    threadTitle: 'Saga',
    onClose: vi.fn(),
    onMapped: vi.fn(),
    ...overrides,
  }
  render(<MapSeriesDialog {...props} />, { wrapper })
  return props
}

function threadDetail(overrides = {}) {
  return {
    id: 9,
    title: 'Saga',
    next_unread_issue_id: 77,
    next_unread_issue_number: '12',
    ...overrides,
  }
}

function issuePage(issues: Array<{ id: number; issue_number: string }>) {
  return {
    issues: issues.map((issue) => ({
      thread_id: 9,
      status: 'unread',
      read_at: null,
      created_at: '2024-01-01T00:00:00.000Z',
      ...issue,
    })),
    total_count: issues.length,
    page_size: 1,
    next_page_token: null,
  }
}

describe('MapSeriesDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when closed without fetching issues', () => {
    const { container } = render(
      <MapSeriesDialog
        isOpen={false}
        threadId={9}
        threadTitle="Saga"
        onClose={vi.fn()}
        onMapped={vi.fn()}
      />,
      { wrapper },
    )

    expect(container).toBeEmptyDOMElement()
    expect(threadsGetMock).not.toHaveBeenCalled()
    expect(issuesListMock).not.toHaveBeenCalled()
  })

  it('anchors the repair on the next unread issue, never the thread id', async () => {
    threadsGetMock.mockResolvedValue(threadDetail())

    renderDialog()

    const search = await screen.findByTestId('mock-comicvine-search')
    expect(search).toHaveAttribute('data-issue-id', '77')
    expect(search).toHaveAttribute('data-issue-number', '12')
    expect(search).toHaveAttribute('data-thread-title', 'Saga')
    expect(issuesListMock).not.toHaveBeenCalled()
  })

  it('falls back to the first tracked issue when nothing is unread', async () => {
    threadsGetMock.mockResolvedValue(
      threadDetail({ next_unread_issue_id: null, next_unread_issue_number: null }),
    )
    issuesListMock.mockResolvedValue(issuePage([{ id: 5, issue_number: '1' }]))

    renderDialog()

    const search = await screen.findByTestId('mock-comicvine-search')
    expect(search).toHaveAttribute('data-issue-id', '5')
    expect(search).toHaveAttribute('data-issue-number', '1')
    expect(issuesListMock).toHaveBeenCalledWith(9, { page_size: 1 })
  })

  it('explains when the thread tracks no issues instead of opening the search', async () => {
    threadsGetMock.mockResolvedValue(
      threadDetail({ next_unread_issue_id: null, next_unread_issue_number: null }),
    )
    issuesListMock.mockResolvedValue(issuePage([]))

    const props = renderDialog()

    expect(await screen.findByTestId('map-series-empty')).toHaveTextContent(
      'has no tracked issues to map yet',
    )
    expect(screen.queryByTestId('mock-comicvine-search')).not.toBeInTheDocument()
    expect(props.onMapped).not.toHaveBeenCalled()
  })

  it('reports anchor load failures without changing mappings', async () => {
    threadsGetMock.mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()

    renderDialog()

    expect(await screen.findByTestId('map-series-error')).toHaveTextContent(
      'No mappings were changed',
    )
    expect(screen.queryByTestId('mock-comicvine-search')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(threadsGetMock).toHaveBeenCalledTimes(2))
  })

  it('refreshes queue health after a confirmed mapping', async () => {
    threadsGetMock.mockResolvedValue(threadDetail())
    const user = userEvent.setup()

    const props = renderDialog()
    await screen.findByTestId('mock-comicvine-search')

    await user.click(screen.getByTestId('mock-search-confirm'))

    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(props.onMapped).toHaveBeenCalledTimes(1)
  })

  it('canceling the search closes without refreshing queue health', async () => {
    threadsGetMock.mockResolvedValue(threadDetail())
    const user = userEvent.setup()

    const props = renderDialog()
    await screen.findByTestId('mock-comicvine-search')

    await user.click(screen.getByTestId('mock-search-close'))

    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(props.onMapped).not.toHaveBeenCalled()
  })
})
