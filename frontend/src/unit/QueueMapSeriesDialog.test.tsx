import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QueueMapSeriesDialog from '../components/QueueMapSeriesDialog'
import type { SeriesMappingPreviewScope } from '../services/api-series-mapping'
import type { ThreadListItem } from '../types'

const { searchSeriesSpy, listIssuesSpy, invalidateQueueSpy, previewMock, commitMutateMock, commitMock } =
  vi.hoisted(() => ({
    searchSeriesSpy: vi.fn(),
    listIssuesSpy: vi.fn(),
    invalidateQueueSpy: vi.fn(),
    previewMock: vi.fn(),
    commitMutateMock: vi.fn(),
    commitMock: vi.fn(),
  }))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: { searchSeries: searchSeriesSpy },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: listIssuesSpy },
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMutation: invalidateQueueSpy,
}))

vi.mock('../hooks/useSiblingSeriesMapping', () => ({
  useSiblingSeriesMappingPreview: previewMock,
  useCommitSeriesMapping: commitMock,
}))

vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
    size,
    'data-testid': testId,
  }: {
    isOpen: boolean
    title: string
    children: ReactNode
    size?: string
    'data-testid'?: string
  }) =>
    isOpen ? (
      <div role="dialog" data-modal-size={size} data-testid={testId}>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
}))

const mockSeries = {
  comicvine_volume_id: 20764,
  name: 'Saga',
  publisher: 'Image',
  start_year: 2012,
  issue_count: 60,
  site_detail_url: null,
  image_url: null,
}

function createThread(): ThreadListItem {
  const thread: ThreadListItem = {
    id: 10,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 2,
    queue_position: 1,
    status: 'active',
    last_activity_at: null,
    is_blocked: false,
    blocking_reasons: [],
    total_issues: 12,
    next_unread_issue_number: '11',
    notes: null,
    created_at: '2024-01-01T00:00:00.000Z',
  }
  return thread
}

function ownedIssues() {
  return {
    issues: [
      {
        id: 101,
        thread_id: 10,
        issue_number: '10',
        status: 'read',
        read_at: '2024-01-02T00:00:00.000Z',
        created_at: '2024-01-01T00:00:00.000Z',
      },
      {
        id: 102,
        thread_id: 10,
        issue_number: '11',
        status: 'unread',
        read_at: null,
        created_at: '2024-01-01T00:00:00.000Z',
      },
    ],
    total_count: 2,
    page_size: 50,
    next_page_token: null,
  }
}

function availablePreview() {
  return {
    data: {
      preview_token: 'preview-tok',
      scope: {
        status: 'available' as const,
        scope_key: 'scope-1',
        origin_issue_id: 102,
        series_label: 'Saga',
        basis: 'confirmed_volume',
      },
      provider_series: null,
      counts: {
        already_confirmed: 1,
        safe_exact_match: 1,
        needs_review_ambiguous: 1,
        needs_review_conflict: 0,
        unresolved: 0,
        excluded_special: 0,
      },
      rows: [
        {
          row_id: 'issue:101',
          issue_id: 101,
          issue_number: '10',
          title: 'Saga #10',
          classification: 'already_confirmed',
          thread_id: 10,
          thread_title: 'Saga',
          current_mapping_status: null,
          proposed_mapping: false,
          default_selected: false,
          reason: null,
        },
        {
          row_id: 'issue:102',
          issue_id: 102,
          issue_number: '11',
          title: 'Saga #11',
          classification: 'safe_exact_match',
          thread_id: 10,
          thread_title: 'Saga',
          current_mapping_status: null,
          proposed_mapping: true,
          default_selected: true,
          reason: null,
        },
        {
          row_id: 'issue:103',
          issue_id: 103,
          issue_number: '12',
          title: 'Saga #12',
          classification: 'needs_review_ambiguous',
          thread_id: 10,
          thread_title: 'Saga',
          current_mapping_status: null,
          proposed_mapping: false,
          default_selected: false,
          reason: 'two_candidates',
        },
        {
          row_id: 'provider:999',
          issue_id: 0,
          issue_number: '13',
          title: null,
          classification: 'unresolved',
          thread_id: null,
          thread_title: null,
          current_mapping_status: null,
          proposed_mapping: false,
          default_selected: false,
          reason: null,
        },
      ],
      issued_at: 1,
      expires_at: null,
    },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }
}

function renderDialog(onClose: () => void = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return {
    onClose,
    ...render(
      <QueryClientProvider client={client}>
        <QueueMapSeriesDialog thread={createThread()} onClose={onClose} />
      </QueryClientProvider>,
    ),
  }
}

describe('QueueMapSeriesDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchSeriesSpy.mockResolvedValue({
      query: 'Saga',
      results: [mockSeries],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    listIssuesSpy.mockResolvedValue(ownedIssues())
    previewMock.mockReturnValue({
      data: null,
      isPending: false,
      isError: false,
      isSuccess: false,
      error: null,
      refetch: vi.fn(),
    })
    commitMock.mockReturnValue({
      mutate: commitMutateMock,
      isPending: false,
      isError: false,
      isSuccess: false,
      data: null,
      error: null,
      reset: vi.fn(),
    })
  })

  it('auto-searches the thread title without any provider call before open', async () => {
    renderDialog()

    await waitFor(() =>
      expect(searchSeriesSpy).toHaveBeenCalledWith('Saga', 10, 0),
    )
    expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument()
    // The shared Modal primitive owns the dialog surface, which keeps the
    // mobile bottom-sheet presentation instead of a bespoke overlay.
    expect(screen.getByTestId('queue-map-series-dialog')).toHaveAttribute(
      'data-modal-size',
      'large',
    )
  })

  it('anchors the preview on the next unread issue of the exact thread', async () => {
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() =>
      expect(previewMock).toHaveBeenCalledWith(102, 'comicvine', '20764', true),
    )
    expect(listIssuesSpy).toHaveBeenCalledWith(10, { page_size: 50 })
  })

  it('commits only safe exact rows and refreshes the Queue without a reload', async () => {
    previewMock.mockReturnValue({ ...availablePreview(), isSuccess: true })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-preview')).toBeInTheDocument())
    // Ambiguous rows are reported but never preselected for bulk approval.
    expect(screen.getByTestId('queue-map-series-preview')).toHaveTextContent('Needs review')
    expect(
      screen.getByRole('button', { name: 'Map 1 issue' }),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Map 1 issue' }))

    expect(commitMutateMock).toHaveBeenCalledTimes(1)
    const [request, handlers] = commitMutateMock.mock.calls[0]
    expect(request.preview_token).toBe('preview-tok')
    // The commit surface only ever receives a non-empty key namespaced
    // to this repair flow; retries reuse it until another volume is picked.
    expect(request.idempotency_key).toMatch(/^queue-map-series-/)
    expect(request.idempotency_key.length).toBeGreaterThan(0)
    // Only the safe exact row is approved; the ambiguous and provider
    // inventory rows never reach the commit surface.
    expect(request.approved_row_ids).toEqual(['issue:102'])

    await handlers.onSuccess({
      confirmed_issue_ids: [102],
      already_confirmed_issue_ids: [101],
      needs_review_issue_ids: [103],
      hydration_queued_issue_ids: [102],
    })
    expect(invalidateQueueSpy).toHaveBeenCalledTimes(1)
  })

  it('reports leftovers after a successful commit and closes on Done', async () => {
    previewMock.mockReturnValue({ ...availablePreview(), isSuccess: true })
    commitMock.mockReturnValue({
      mutate: commitMutateMock,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: {
        confirmed_issue_ids: [102],
        already_confirmed_issue_ids: [101],
        needs_review_issue_ids: [103],
        hydration_queued_issue_ids: [102],
        series_mapping: {
          provider: 'comicvine',
          external_id: '20764',
          status: 'confirmed',
          evidence_source: 'user_series_confirmation',
        },
      },
      error: null,
      reset: vi.fn(),
    })
    const onClose = vi.fn()
    renderDialog(onClose)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-result')).toBeInTheDocument())
    expect(screen.getByTestId('queue-map-series-result')).toHaveTextContent('1 issue mapped to Saga')
    expect(screen.getByTestId('queue-map-series-result')).toHaveTextContent(
      '1 still needs review and is available for issue-level correction',
    )

    fireEvent.click(screen.getByTestId('queue-map-series-done'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('lets the reader deselect every safe row so nothing can be approved', async () => {
    previewMock.mockReturnValue({ ...availablePreview(), isSuccess: true })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-preview')).toBeInTheDocument())
    const checkbox = screen.getByRole('checkbox')
    fireEvent.click(checkbox)

    expect(screen.getByTestId('queue-map-series-approve')).toBeDisabled()
    fireEvent.click(screen.getByTestId('queue-map-series-approve'))
    expect(commitMutateMock).not.toHaveBeenCalled()
  })

  it('renders series and rows without optional metadata', async () => {
    searchSeriesSpy.mockResolvedValue({
      query: 'Saga',
      results: [
        {
          comicvine_volume_id: 20764,
          name: 'Saga',
          publisher: null,
          start_year: null,
          issue_count: null,
          site_detail_url: null,
          image_url: null,
        },
      ],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    const preview = availablePreview()
    preview.data.rows = preview.data.rows.map((row) => ({ ...row, issue_number: '' }))
    previewMock.mockReturnValue({ ...preview, isSuccess: true })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-preview')).toBeInTheDocument())
    expect(screen.getAllByText('Unnumbered').length).toBeGreaterThan(0)
  })

  it('cancels from the series step without mutating anything', async () => {
    const onClose = vi.fn()
    renderDialog(onClose)

    await waitFor(() => expect(searchSeriesSpy).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('queue-map-series-cancel'))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(commitMutateMock).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('cancels from the preview step without touching Queue state', async () => {
    previewMock.mockReturnValue({ ...availablePreview(), isSuccess: true })
    const onClose = vi.fn()
    renderDialog(onClose)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-preview')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('queue-map-series-cancel'))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(commitMutateMock).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('keeps provider failures inside the dialog with a retry and no mutation', async () => {
    const refetch = vi.fn()
    previewMock.mockReturnValue({
      data: null,
      isPending: false,
      isError: true,
      isSuccess: false,
      error: { response: { data: { detail: 'provider_unavailable' } } },
      refetch,
    })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() => expect(screen.getByTestId('queue-map-series-preview-error')).toBeInTheDocument())
    expect(screen.getByTestId('queue-map-series-preview-error')).toHaveTextContent('provider_unavailable')
    expect(screen.queryByTestId('queue-map-series-approve')).not.toBeInTheDocument()
    expect(commitMutateMock).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('queue-map-series-retry'))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it('offers no commit when the scope cannot be safely established', async () => {
    const base = availablePreview()
    const unavailableScope: SeriesMappingPreviewScope = {
      status: 'unavailable',
      scope_key: null,
      origin_issue_id: 102,
      series_label: null,
      basis: 'insufficient_non_thread_evidence',
    }
    const unavailable = {
      ...base,
      data: {
        ...base.data,
        scope: unavailableScope,
      },
    }
    previewMock.mockReturnValue({ ...unavailable, isSuccess: true })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() =>
      expect(screen.getByTestId('queue-map-series-unavailable')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('queue-map-series-approve')).not.toBeInTheDocument()
    expect(commitMutateMock).not.toHaveBeenCalled()
  })

  it('explains threads without issue tracking instead of offering a mapping', async () => {
    listIssuesSpy.mockResolvedValue({
      issues: [],
      total_count: 0,
      page_size: 50,
      next_page_token: null,
    })
    renderDialog()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Saga' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Saga' }))

    await waitFor(() =>
      expect(screen.getByText(/does not use issue tracking/)).toBeInTheDocument(),
    )
    expect(previewMock).toHaveBeenCalledWith(null, 'comicvine', '20764', false)
    expect(commitMutateMock).not.toHaveBeenCalled()
  })
})
