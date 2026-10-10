import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import type { ComicVineSeriesResult } from '../services/api-comicvine'
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
    evidence_source: 'preview',
  },
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
  vi.clearAllMocks()
  mockedSearchSeries.mockResolvedValue({
    query: 'Saga',
    results: [VOLUME],
    total_available: 1,
    offset: 0,
    limit: 10,
    has_more: false,
    next_offset: null,
  })
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
    })
    expect(screen.getByTestId('queue-map-series-approve')).toHaveTextContent('Map 1 issue')
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByTestId('queue-map-series-provider-inventory')).toHaveTextContent(
      '1 other issue is in this volume but not in your library',
    )
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

    mockedSearchSeries.mockResolvedValue({
      query: 'Saga',
      results: [VOLUME],
      total_available: 1,
      offset: 0,
      limit: 10,
      has_more: false,
      next_offset: null,
    })
    await user.type(screen.getByTestId('queue-map-series-search-input'), '!')
    expect(await screen.findByTestId('queue-map-series-result')).toBeInTheDocument()
  })

  it('reports a preview failure with a way out and no mutation', async () => {
    const user = userEvent.setup()
    mockedPreview.mockRejectedValueOnce(new Error('preview down'))
    const { onClose } = renderDialog()

    await user.click(await screen.findByTestId('queue-map-series-result'))

    expect(await screen.findByText('The mapping plan could not be loaded. Nothing was changed.')).toBeInTheDocument()
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
})
