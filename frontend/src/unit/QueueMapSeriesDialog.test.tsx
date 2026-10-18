import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import type { ComicVineSeriesResult, ComicVineSeriesSearchResponse } from '../services/api-comicvine'
import { seriesMappingApi } from '../services/api-series-mapping'
import type {
  SeriesMappingCommitResponse,
  SeriesMappingPreviewResponse,
  SeriesMappingPreviewRow,
} from '../services/api-series-mapping'
import { comicVineApi } from '../services/api-comicvine'
import { issuesApi } from '../services/api-issues'
import type { IssueListResponse } from '../services/api-issues'

const { searchSeriesSpy } = vi.hoisted(() => ({ searchSeriesSpy: vi.fn() }))
const { listIssuesSpy } = vi.hoisted(() => ({ listIssuesSpy: vi.fn() }))
const { previewSpy, commitSpy } = vi.hoisted(() => ({ previewSpy: vi.fn(), commitSpy: vi.fn() }))
const { invalidateQueueSpy, invalidateIntelligenceManySpy } = vi.hoisted(() => ({
  invalidateQueueSpy: vi.fn(),
  invalidateIntelligenceManySpy: vi.fn(),
}))

vi.mock('../services/api-comicvine', () => ({
  comicVineApi: { searchSeries: searchSeriesSpy },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { list: listIssuesSpy },
}))

vi.mock('../services/api-series-mapping', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-series-mapping')>()
  return {
    ...actual,
    seriesMappingApi: { preview: previewSpy, commit: commitSpy },
  }
})

vi.mock('../query/cacheEffects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../query/cacheEffects')>()
  return {
    ...actual,
    invalidateAfterQueueMutation: invalidateQueueSpy,
    invalidateComicVineIssueIntelligenceMany: invalidateIntelligenceManySpy,
  }
})

vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean
    title: string
    children: ReactNode
  }) => (isOpen ? (
    <div role="dialog">
      <h2>{title}</h2>
      {children}
    </div>
  ) : null),
}))

import QueueMapSeriesDialog from '../components/QueueMapSeriesDialog'

const mockedSearchSeries = vi.mocked(comicVineApi.searchSeries)
const mockedListIssues = vi.mocked(issuesApi.list)
const mockedPreview = vi.mocked(seriesMappingApi.preview)
const mockedCommit = vi.mocked(seriesMappingApi.commit)

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const VOLUME: ComicVineSeriesResult = {
  comicvine_volume_id: 20764,
  name: 'Saga',
  publisher: 'Image',
  start_year: 2012,
  issue_count: 54,
  site_detail_url: null,
  image_url: null,
}

function previewRow(overrides: Partial<SeriesMappingPreviewRow>): SeriesMappingPreviewRow {
  return {
    row_id: 'issue:2',
    issue_id: 2,
    issue_number: '2',
    title: 'Chapter Two',
    classification: 'safe_exact_match',
    thread_id: 7,
    thread_title: 'Saga',
    current_mapping_status: null,
    proposed_mapping: true,
    default_selected: true,
    reason: null,
    ...overrides,
  }
}

function previewResponse(
  rows: SeriesMappingPreviewRow[],
  overrides: Partial<SeriesMappingPreviewResponse> = {},
): SeriesMappingPreviewResponse {
  return {
    preview_token: 'preview-tok',
    scope: {
      status: 'available',
      scope_key: 'scope-key',
      origin_issue_id: 1,
      series_label: 'Saga',
      basis: 'evidence',
    },
    provider_series: null,
    counts: {
      already_confirmed: 0,
      safe_exact_match: 1,
      needs_review_ambiguous: 1,
      needs_review_conflict: 0,
      unresolved: 0,
      excluded_special: 0,
    },
    rows,
    issued_at: 1700000000,
    expires_at: null,
    ...overrides,
  }
}

const COMMIT_SUCCESS: SeriesMappingCommitResponse = {
  idempotency_key: 'queue-mapping-7-1-1700000000',
  confirmed_issue_ids: [2],
  already_confirmed_issue_ids: [],
  needs_review_issue_ids: [3],
  hydration_queued_issue_ids: [2],
  series_mapping: {
    provider: 'comicvine',
    external_id: '20764',
    status: 'confirmed',
    evidence_source: 'user_series_confirmation',
  },
}

const VOLUME_2: ComicVineSeriesResult = {
  comicvine_volume_id: 31111,
  name: 'Saga (Book Two)',
  publisher: 'Image',
  start_year: 2019,
  issue_count: 18,
  site_detail_url: null,
  image_url: null,
}

function searchResponse(
  results: ComicVineSeriesResult[],
  overrides: Partial<ComicVineSeriesSearchResponse> = {},
): ComicVineSeriesSearchResponse {
  return {
    query: 'Saga',
    results,
    total_available: results.length,
    offset: 0,
    limit: 10,
    has_more: false,
    next_offset: null,
    ...overrides,
  }
}

function issueListResponse(): IssueListResponse {
  return {
    issues: [
      {
        id: 1,
        thread_id: 7,
        issue_number: '1',
        status: 'unread',
        read_at: null,
        created_at: '2024-01-01T00:00:00.000Z',
      },
    ],
    total_count: 1,
    page_size: 100,
    next_page_token: null,
  }
}

function renderDialog(onMapped = vi.fn(), onClose = vi.fn()) {
  return {
    onMapped,
    onClose,
    ...render(
      <QueueMapSeriesDialog
        isOpen
        threadId={7}
        threadTitle="Saga"
        onClose={onClose}
        onMapped={onMapped}
      />,
      { wrapper: createWrapper() },
    ),
  }
}

  beforeEach(() => {
  // reset (not clear) so unconsumed one-time implementations queued by any
  // earlier failed test cannot leak into the next test's mocked responses.
  vi.resetAllMocks()
  mockedSearchSeries.mockResolvedValue(searchResponse([VOLUME]))
  mockedListIssues.mockResolvedValue(issueListResponse())
  mockedPreview.mockResolvedValue(
    previewResponse([
      previewRow({}),
      previewRow({
        row_id: 'issue:3',
        issue_id: 3,
        issue_number: '3',
        title: 'Chapter Three',
        classification: 'needs_review_ambiguous',
        proposed_mapping: false,
        default_selected: false,
      }),
      previewRow({
        row_id: 'provider:99',
        issue_id: 99,
        issue_number: '99',
        title: 'Not owned',
        classification: 'unresolved',
        thread_id: null,
        thread_title: null,
        proposed_mapping: false,
        default_selected: false,
      }),
    ]),
  )
  mockedCommit.mockResolvedValue(COMMIT_SUCCESS)
})

describe('QueueMapSeriesDialog', () => {
  it('searches on open and shows the mapping preview after a volume is selected', async () => {
    const user = userEvent.setup()
    renderDialog()

    const result = await screen.findByTestId('queue-map-series-result')
    expect(mockedSearchSeries).toHaveBeenCalledWith('Saga', 10, 0)
    expect(result).toHaveTextContent('Saga')

    await user.click(result)

    const preview = await screen.findByTestId('queue-map-series-preview')
    expect(preview).toBeInTheDocument()
    expect(mockedPreview).toHaveBeenCalledWith({
      origin_issue_id: 1,
      provider: 'comicvine',
      provider_series_external_id: '20764',
      scope_mode: 'queue_thread_bootstrap',
    })
    expect(screen.getByTestId('queue-map-series-approve')).toHaveTextContent('Map 1 issue')
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-provider-inventory')).toHaveTextContent(
      '1 other issue is in this volume but not in your library',
    )
  })

  it('bootstraps a completely unmapped thread with every owned issue selectable', async () => {
    const user = userEvent.setup()
    const ownedRows = [1, 2, 3, 4, 5].map((number) =>
      previewRow({
        row_id: `issue:${number}`,
        issue_id: number,
        issue_number: String(number),
        title: `Chapter ${number}`,
      }),
    )
    mockedPreview.mockResolvedValue(previewResponse(ownedRows))
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await screen.findByTestId('queue-map-series-preview')

    expect(mockedPreview).toHaveBeenCalledWith(
      expect.objectContaining({ scope_mode: 'queue_thread_bootstrap' }),
    )
    // The reported bug: the approval button read "Map 0 issues" for a matching miniseries.
    expect(screen.getByTestId('queue-map-series-approve')).toHaveTextContent('Map 5 issues')
    expect(screen.queryByTestId('queue-map-series-provider-inventory')).not.toBeInTheDocument()
  })

  it('commits only safe exact rows and refreshes the Queue without a reload', async () => {
    const user = userEvent.setup()
    const { onMapped } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    await waitFor(() => expect(mockedCommit).toHaveBeenCalledTimes(1))
    expect(mockedCommit).toHaveBeenCalledWith({
      preview_token: 'preview-tok',
      idempotency_key: 'queue-mapping-7-1-1700000000',
      approved_row_ids: ['issue:2'],
    })
    expect(await screen.findByRole('status')).toHaveTextContent('1 issue mapped to Saga')
    expect(onMapped).toHaveBeenCalledWith([2])
    expect(invalidateQueueSpy).toHaveBeenCalledTimes(1)
    expect(invalidateIntelligenceManySpy).toHaveBeenCalledWith(expect.anything(), [2])
  })

  it('cancels without committing when the reader dismisses the preview', async () => {
    const user = userEvent.setup()
    const { onClose } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await screen.findByTestId('queue-map-series-preview')
    await user.click(screen.getByTestId('queue-map-series-dismiss'))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mockedCommit).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('reports a provider search failure without closing the dialog', async () => {
    const user = userEvent.setup()
    mockedSearchSeries.mockRejectedValueOnce(new Error('boom'))
    const { onClose } = renderDialog()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to search ComicVine. Please try again.',
    )
    expect(onClose).not.toHaveBeenCalled()

    mockedSearchSeries.mockResolvedValue(searchResponse([VOLUME]))
    await user.type(screen.getByTestId('queue-map-series-search-input'), '!')
    expect((await screen.findAllByTestId('queue-map-series-result')).length).toBeGreaterThan(0)
  })

  it('reports a preview failure with a way out and no mutation', async () => {
    const user = userEvent.setup()
    mockedPreview.mockRejectedValueOnce(new Error('preview down'))
    const { onClose } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    expect(await screen.findByText('The mapping plan could not be loaded. Nothing was changed.')).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-retry')).toHaveTextContent('Try again')
    await user.click(screen.getByTestId('queue-map-series-dismiss'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mockedCommit).not.toHaveBeenCalled()
  })

  it('lets the reader retry the same volume after a preview failure', async () => {
    const user = userEvent.setup()
    // The first attempt fails (e.g. a transient provider outage); the retry must
    // re-request the same volume and render its plan instead of forcing a different one.
    mockedPreview.mockRejectedValueOnce(new Error('preview down'))
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await screen.findByText('The mapping plan could not be loaded. Nothing was changed.')

    await user.click(screen.getByTestId('queue-map-series-retry'))

    expect(await screen.findByTestId('queue-map-series-preview')).toBeInTheDocument()
    expect(await screen.findByTestId('queue-map-series-approve')).toHaveTextContent('Map 1 issue')
    expect(mockedPreview).toHaveBeenCalledTimes(2)
    expect(mockedPreview).toHaveBeenLastCalledWith({
      origin_issue_id: 1,
      provider: 'comicvine',
      provider_series_external_id: '20764',
      scope_mode: 'queue_thread_bootstrap',
    })
    expect(mockedCommit).not.toHaveBeenCalled()
  })

  it('reports review-needed rows without making them approvable', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    const rows = await screen.findAllByTestId('queue-map-series-row')
    const reviewRow = rows.find((row) => row.dataset.classification === 'needs_review_ambiguous')
    expect(reviewRow).toBeDefined()
    expect(reviewRow!.querySelector('input[type="checkbox"]')).toBeNull()
    expect(reviewRow!).toHaveTextContent('Needs review')
  })

  it('reports an unavailable scope as a normal outcome with a way out', async () => {
    const user = userEvent.setup()
    mockedPreview.mockResolvedValueOnce(
      previewResponse([], {
        preview_token: null,
        scope: {
          status: 'unavailable',
          scope_key: null,
          origin_issue_id: 1,
          series_label: null,
          basis: 'insufficient_non_thread_evidence',
        },
        counts: {
          already_confirmed: 0,
          safe_exact_match: 0,
          needs_review_ambiguous: 0,
          needs_review_conflict: 0,
          unresolved: 0,
          excluded_special: 0,
        },
        rows: [],
      }),
    )
    const { onClose } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    expect(await screen.findByText(/could not establish a safe mapping scope/)).toBeInTheDocument()
    await user.click(screen.getByTestId('queue-map-series-dismiss'))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(mockedCommit).not.toHaveBeenCalled()
  })

  it('explains when the series has no tracked issues to map', async () => {
    mockedListIssues.mockResolvedValue({
      issues: [],
      total_count: 0,
      page_size: 100,
      next_page_token: null,
    })
    renderDialog()

    expect(await screen.findByText('This series has no tracked issues to map.')).toBeInTheDocument()
  })

  it('does not search when the thread title has no usable text', async () => {
    render(
      <QueueMapSeriesDialog
        isOpen
        threadId={7}
        threadTitle=""
        onClose={vi.fn()}
        onMapped={vi.fn()}
      />,
      { wrapper: createWrapper() },
    )

    expect(mockedSearchSeries).not.toHaveBeenCalled()
    expect(screen.getByTestId('queue-map-series-search-input')).toHaveValue('')
  })

  it('shows a searching indicator and ignores a stale response that resolves later', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: ComicVineSeriesSearchResponse) => void
    mockedSearchSeries
      .mockImplementationOnce(
        () =>
          new Promise<ComicVineSeriesSearchResponse>((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockResolvedValueOnce(searchResponse([VOLUME]))
    renderDialog()

    expect(await screen.findByLabelText('Searching')).toBeInTheDocument()

    await user.type(screen.getByTestId('queue-map-series-search-input'), '!')
    await waitFor(() => expect(mockedSearchSeries).toHaveBeenCalledTimes(2))
    expect(await screen.findAllByTestId('queue-map-series-result')).toHaveLength(1)

    resolveFirst(
      searchResponse([
        VOLUME,
        { ...VOLUME_2, comicvine_volume_id: 99999, name: 'Stale Volume' },
      ]),
    )
    await waitFor(() => expect(mockedSearchSeries).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('Stale Volume')).not.toBeInTheDocument()
    expect(await screen.findAllByTestId('queue-map-series-result')).toHaveLength(1)
  })

  it('loads more results and deduplicates volumes already listed', async () => {
    const user = userEvent.setup()
    mockedSearchSeries.mockResolvedValueOnce(
      searchResponse([VOLUME], { has_more: true, next_offset: 10 }),
    )
    mockedSearchSeries.mockResolvedValueOnce(
      searchResponse([VOLUME, VOLUME_2], { offset: 10, has_more: false, next_offset: null }),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-back'))
    await screen.findByTestId('queue-map-series-result')

    await user.click(screen.getByTestId('queue-map-series-load-more'))

    expect(mockedSearchSeries).toHaveBeenLastCalledWith('Saga', 10, 10)
    expect(await screen.findAllByTestId('queue-map-series-result')).toHaveLength(2)
    expect(screen.getByText('Saga (Book Two)')).toBeInTheDocument()
    expect(screen.queryByTestId('queue-map-series-load-more')).not.toBeInTheDocument()
  })

  it('disables the load more button while a search is in flight', async () => {
    const user = userEvent.setup()
    mockedSearchSeries.mockResolvedValueOnce(
      searchResponse([VOLUME], { has_more: true, next_offset: 10 }),
    )
    let resolveSecond!: (value: ComicVineSeriesSearchResponse) => void
    mockedSearchSeries.mockImplementationOnce(
      () =>
        new Promise<ComicVineSeriesSearchResponse>((resolve) => {
          resolveSecond = resolve
        }),
    )
    renderDialog()

    await screen.findByTestId('queue-map-series-result')

    await user.type(screen.getByTestId('queue-map-series-search-input'), '!')
    await waitFor(() => expect(mockedSearchSeries).toHaveBeenCalledTimes(2))

    const loadMore = screen.getByTestId('queue-map-series-load-more')
    expect(loadMore).toHaveTextContent('Loading...')
    expect(loadMore).toBeDisabled()
    fireEvent.click(loadMore)
    expect(mockedSearchSeries).toHaveBeenCalledTimes(2)

    resolveSecond(searchResponse([VOLUME_2], { has_more: false, next_offset: null }))
    expect(await screen.findByText('Saga (Book Two)')).toBeInTheDocument()
    expect(screen.queryByTestId('queue-map-series-load-more')).not.toBeInTheDocument()
  })

  it('clears the results when the search text is emptied', async () => {
    const user = userEvent.setup()
    renderDialog()

    await screen.findByTestId('queue-map-series-result')
    await user.clear(screen.getByTestId('queue-map-series-search-input'))

    expect(screen.queryByTestId('queue-map-series-result')).not.toBeInTheDocument()
    expect(screen.queryByText('No volumes matched that search.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('queue-map-series-load-more')).not.toBeInTheDocument()
  })

  it('shows an empty-results message when no volumes match', async () => {
    mockedSearchSeries.mockResolvedValueOnce(searchResponse([]))
    renderDialog()

    expect(await screen.findByText('No volumes matched that search.')).toBeInTheDocument()
    expect(screen.queryByTestId('queue-map-series-result')).not.toBeInTheDocument()
  })

  it('returns to search and re-previews when choosing a different volume', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await screen.findByTestId('queue-map-series-preview')

    await user.click(screen.getByTestId('queue-map-series-back'))
    expect(screen.getByTestId('queue-map-series-search-input')).toBeInTheDocument()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await screen.findByTestId('queue-map-series-preview')

    expect(mockedPreview).toHaveBeenCalledTimes(2)
  })

  it('unchecks and rechecks safe rows, updating the approval count', async () => {
    const user = userEvent.setup()
    mockedPreview.mockResolvedValueOnce(
      previewResponse([
        previewRow({}),
        previewRow({
          row_id: 'issue:3',
          issue_id: 3,
          issue_number: '3',
          title: 'Chapter Three',
        }),
      ]),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    const approve = await screen.findByTestId('queue-map-series-approve')
    expect(approve).toHaveTextContent('Map 2 issues')

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(2)

    await user.click(checkboxes[0])
    expect(screen.getByTestId('queue-map-series-approve')).toHaveTextContent('Map 1 issue')
    expect(screen.getByTestId('queue-map-series-approve')).not.toBeDisabled()

    await user.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByTestId('queue-map-series-approve')).toBeDisabled()

    await user.click(screen.getAllByRole('checkbox')[0])
    await user.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByTestId('queue-map-series-approve')).toHaveTextContent('Map 2 issues')
  })

  it('labels rows without an issue number as Unnumbered and omits missing titles', async () => {
    const user = userEvent.setup()
    mockedPreview.mockResolvedValueOnce(
      previewResponse([
        previewRow({ issue_number: '', title: null }),
      ]),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    const row = await screen.findByTestId('queue-map-series-row')
    expect(row).toHaveTextContent('Unnumbered')
    expect(row).not.toHaveTextContent('Chapter Two')
  })

  it('omits meta text when the volume has no publisher, year, or issue count', async () => {
    mockedSearchSeries.mockResolvedValueOnce(
      searchResponse([{ ...VOLUME, publisher: null, start_year: null, issue_count: null }]),
    )
    renderDialog()

    const result = await screen.findByRole('button', { name: 'Saga' })
    expect(result).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Image/ })).not.toBeInTheDocument()
  })

  it('disables volume selection when the origin issue fails to load', async () => {
    mockedListIssues.mockRejectedValueOnce(new Error('origin down'))
    renderDialog()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This series could not be loaded for mapping. Please try again.',
    )
    expect(screen.getByTestId('queue-map-series-result')).toBeDisabled()
  })

  it('reports a generic commit failure without refreshing the Queue', async () => {
    const user = userEvent.setup()
    mockedCommit.mockRejectedValueOnce(new Error('commit failed'))
    const { onMapped } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not map the series. Nothing was changed.',
    )
    expect(onMapped).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('re-reads the plan when the commit reports a stale preview', async () => {
    const user = userEvent.setup()
    mockedCommit.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'preview_expired' } },
    })
    const { onMapped } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    await waitFor(() => expect(mockedPreview).toHaveBeenCalledTimes(2))
    expect(onMapped).not.toHaveBeenCalled()
    expect(invalidateQueueSpy).not.toHaveBeenCalled()
  })

  it('uses plural wording when multiple issues map and some still need review', async () => {
    const user = userEvent.setup()
    mockedCommit.mockResolvedValueOnce({
      ...COMMIT_SUCCESS,
      confirmed_issue_ids: [2, 3],
      needs_review_issue_ids: [4, 5],
      hydration_queued_issue_ids: [2, 3],
    })
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    expect(await screen.findByRole('status')).toHaveTextContent('2 issues mapped to Saga')
    expect(screen.getByRole('status')).toHaveTextContent('2 still need review.')
    expect(screen.getByTestId('queue-map-series-dismiss')).toHaveTextContent('Done')
    expect(screen.queryByTestId('queue-map-series-approve')).not.toBeInTheDocument()
  })

  it('does not mention review when nothing is left for review', async () => {
    const user = userEvent.setup()
    mockedCommit.mockResolvedValueOnce({
      ...COMMIT_SUCCESS,
      needs_review_issue_ids: [],
      hydration_queued_issue_ids: [2],
    })
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    expect(await screen.findByRole('status')).toHaveTextContent('1 issue mapped to Saga')
    expect(screen.queryByText(/still need/)).not.toBeInTheDocument()
  })

  it('explains when the volume has no exact matches for owned issues', async () => {
    const user = userEvent.setup()
    mockedPreview.mockResolvedValueOnce(
      previewResponse([
        previewRow({
          row_id: 'issue:3',
          issue_id: 3,
          issue_number: '3',
          title: 'Chapter Three',
          classification: 'needs_review_ambiguous',
          proposed_mapping: false,
          default_selected: false,
        }),
      ]),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    expect(await screen.findByText(/No exact matches for your issues in this volume/)).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-approve')).toBeDisabled()
  })

  it('shows a pending state while the commit is in flight', async () => {
    const user = userEvent.setup()
    let resolveCommit!: (value: SeriesMappingCommitResponse) => void
    mockedCommit.mockImplementationOnce(
      () =>
        new Promise<SeriesMappingCommitResponse>((resolve) => {
          resolveCommit = resolve
        }),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))
    await user.click(await screen.findByTestId('queue-map-series-approve'))

    expect(await screen.findByRole('button', { name: 'Mapping...' })).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-dismiss')).toBeDisabled()

    resolveCommit(COMMIT_SUCCESS)
    expect(await screen.findByRole('status')).toHaveTextContent('1 issue mapped to Saga')
  })

  it('counts provider inventory in plural when several rows are not owned', async () => {
    const user = userEvent.setup()
    mockedPreview.mockResolvedValueOnce(
      previewResponse([
        previewRow({}),
        previewRow({
          row_id: 'provider:99',
          issue_id: 99,
          issue_number: '99',
          title: 'Not owned',
          classification: 'unresolved',
          thread_id: null,
          thread_title: null,
          proposed_mapping: false,
          default_selected: false,
        }),
        previewRow({
          row_id: 'provider:100',
          issue_id: 100,
          issue_number: '100',
          title: 'Also not owned',
          classification: 'unresolved',
          thread_id: null,
          thread_title: null,
          proposed_mapping: false,
          default_selected: false,
        }),
      ]),
    )
    renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    expect(await screen.findByTestId('queue-map-series-provider-inventory')).toHaveTextContent(
      '2 other issues are in this volume but not in your library',
    )
  })
})
