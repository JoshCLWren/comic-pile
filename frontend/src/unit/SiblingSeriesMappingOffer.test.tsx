import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import type {
  SeriesMappingCommitResponse,
  SeriesMappingPreviewResponse,
  SeriesMappingPreviewRow,
} from '../services/api-series-mapping'

const { useSiblingSeriesMappingPreviewMock, useCommitSeriesMappingMock } = vi.hoisted(() => ({
  useSiblingSeriesMappingPreviewMock: vi.fn(),
  useCommitSeriesMappingMock: vi.fn(),
}))

vi.mock('../hooks/useSiblingSeriesMapping', () => ({
  useSiblingSeriesMappingPreview: useSiblingSeriesMappingPreviewMock,
  useCommitSeriesMapping: useCommitSeriesMappingMock,
}))

import SiblingSeriesMappingOffer from '../components/SiblingSeriesMappingOffer'

function previewRow(overrides: Partial<SeriesMappingPreviewRow>): SeriesMappingPreviewRow {
  return {
    row_id: 'issue:2',
    issue_id: 2,
    issue_number: '2',
    title: 'Saga #2',
    classification: 'safe_exact_match',
    thread_id: 10,
    thread_title: 'Saga',
    current_mapping_status: null,
    proposed_mapping: true,
    default_selected: true,
    reason: null,
    ...overrides,
  }
}

const ORIGIN_ROW = previewRow({
  row_id: 'issue:1',
  issue_id: 1,
  issue_number: '1',
  title: 'Saga #1',
  classification: 'already_confirmed',
  proposed_mapping: false,
  default_selected: false,
})

const SIBLING_ROW = previewRow({})

function previewResponse(
  rows: SeriesMappingPreviewRow[],
  overrides: Partial<SeriesMappingPreviewResponse> = {},
): SeriesMappingPreviewResponse {
  return {
    preview_token: 'tok',
    scope: {
      status: 'available',
      scope_key: 'k',
      origin_issue_id: 1,
      series_label: 'Saga',
      basis: 'b',
    },
    provider_series: null,
    counts: {
      already_confirmed: 0,
      safe_exact_match: 0,
      needs_review_ambiguous: 0,
      needs_review_conflict: 0,
      unresolved: 0,
      excluded_special: 0,
    },
    rows,
    issued_at: 1,
    expires_at: null,
    ...overrides,
  }
}

const COMMIT_SUCCESS: SeriesMappingCommitResponse = {
  idempotency_key: 'sibling-mapping-1-1',
  confirmed_issue_ids: [2],
  already_confirmed_issue_ids: [],
  needs_review_issue_ids: [],
  hydration_queued_issue_ids: [],
  series_mapping: {
    provider: 'comicvine',
    external_id: '20764',
    status: 'confirmed',
    evidence_source: 'user_confirmed',
  },
}

function mockPreview(data: SeriesMappingPreviewResponse | undefined, overrides = {}) {
  useSiblingSeriesMappingPreviewMock.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  })
}

function mockCommit(overrides = {}) {
  useCommitSeriesMappingMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    data: null,
    error: null,
    reset: vi.fn(),
    ...overrides,
  })
}

function renderOffer(overrides: Partial<ComponentProps<typeof SiblingSeriesMappingOffer>> = {}) {
  render(
    <SiblingSeriesMappingOffer
      originIssueId={1}
      provider="comicvine"
      providerSeriesExternalId="20764"
      seriesLabel="Saga (2012)"
      onMapped={vi.fn()}
      onDismiss={vi.fn()}
      {...overrides}
    />,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockPreview(previewResponse([ORIGIN_ROW, SIBLING_ROW]))
  mockCommit()
})

describe('SiblingSeriesMappingOffer loading', () => {
  it('renders a loading state while the preview is pending', () => {
    mockPreview(undefined, { isPending: true })

    renderOffer()

    expect(screen.getByTestId('sibling-mapping-offer')).toHaveTextContent('Checking the rest of')
    expect(screen.getByText('Saga (2012)')).toBeInTheDocument()
    expect(screen.queryByTestId('sibling-mapping-approve')).not.toBeInTheDocument()
  })
})

describe('SiblingSeriesMappingOffer error', () => {
  it('renders an error state when the preview fails', () => {
    mockPreview(undefined, { isError: true })

    renderOffer()

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Saga (2012) was matched, but the remaining issues in the series could not be checked.',
    )
    expect(screen.getByTestId('sibling-mapping-dismiss')).toHaveTextContent('Done')
  })

  it('leaves the reader a way out when the preview fails', () => {
    mockPreview(undefined, { isError: true })
    const onDismiss = vi.fn()

    renderOffer({ onDismiss })
    fireEvent.click(screen.getByTestId('sibling-mapping-dismiss'))

    expect(onDismiss).toHaveBeenCalled()
  })
})

describe('SiblingSeriesMappingOffer empty', () => {
  it('renders a no-match message when no approvable rows exist', () => {
    mockPreview(previewResponse([ORIGIN_ROW]))

    renderOffer()

    expect(screen.getByText(/is linked for this issue/)).toBeInTheDocument()
    expect(screen.getByTestId('sibling-mapping-dismiss')).toHaveTextContent('Done')
    expect(screen.queryByTestId('sibling-mapping-approve')).not.toBeInTheDocument()
  })
})

describe('SiblingSeriesMappingOffer success', () => {
  it('shows a success message after a successful commit', () => {
    mockCommit({ isSuccess: true, data: COMMIT_SUCCESS })

    renderOffer()

    expect(screen.getByText('1 sibling issue mapped to Saga (2012).')).toBeInTheDocument()
    expect(screen.getByTestId('sibling-mapping-approve')).toHaveTextContent('Mapped')
  })

  it('reports every confirmed sibling when several issues map at once', () => {
    mockCommit({
      isSuccess: true,
      data: { ...COMMIT_SUCCESS, confirmed_issue_ids: [2, 3] },
    })

    renderOffer()

    expect(screen.getByText('2 sibling issues mapped to Saga (2012).')).toBeInTheDocument()
  })

  it('reports the confirmed issue ids to the caller', () => {
    const mutate = vi.fn()
    mockCommit({ mutate })
    const onMapped = vi.fn()

    renderOffer({ onMapped })
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    const [, handlers] = mutate.mock.calls[0]
    handlers.onSuccess(COMMIT_SUCCESS)

    expect(onMapped).toHaveBeenCalledWith([2])
  })
})

describe('SiblingSeriesMappingOffer commit error', () => {
  it('shows a generic error when the commit fails', () => {
    mockCommit({ isError: true, error: new Error('Server error') })

    renderOffer()

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not map the sibling issues. Nothing else was changed.',
    )
  })

  it('re-reads the preview when the commit fails with a stale preview', () => {
    const refetch = vi.fn()
    const reset = vi.fn()
    const mutate = vi.fn()
    const staleError = { response: { data: { detail: 'preview_expired' } } }
    mockPreview(previewResponse([ORIGIN_ROW, SIBLING_ROW]), { refetch })
    mockCommit({ mutate, isError: true, error: staleError, reset })

    renderOffer()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'That preview is out of date. Reviewing the series again.',
    )

    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))
    const [, handlers] = mutate.mock.calls[0]
    handlers.onError(staleError)

    expect(reset).toHaveBeenCalled()
    expect(refetch).toHaveBeenCalled()
  })

  it('does not re-read the preview for a non-stale commit failure', () => {
    const refetch = vi.fn()
    const reset = vi.fn()
    const mutate = vi.fn()
    mockPreview(previewResponse([ORIGIN_ROW, SIBLING_ROW]), { refetch })
    mockCommit({ mutate, isError: true, error: new Error('boom'), reset })

    renderOffer()
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))
    const [, handlers] = mutate.mock.calls[0]
    handlers.onError(new Error('boom'))

    expect(reset).not.toHaveBeenCalled()
    expect(refetch).not.toHaveBeenCalled()
  })
})

describe('SiblingSeriesMappingOffer interactions', () => {
  it('reports progress and blocks a second approval while the commit is in flight', () => {
    mockCommit({ isPending: true })

    renderOffer()

    expect(screen.getByTestId('sibling-mapping-approve')).toHaveTextContent('Mapping...')
    expect(screen.getByTestId('sibling-mapping-approve')).toBeDisabled()
    expect(screen.getByTestId('sibling-mapping-dismiss')).toBeDisabled()
  })

  it('toggles row selection and disables approval when nothing stays selected', () => {
    renderOffer()

    const approveButton = screen.getByTestId('sibling-mapping-approve')
    expect(approveButton).toHaveTextContent('Map 1 issue')
    expect(approveButton).not.toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: /#2/ }))

    expect(approveButton).toHaveTextContent('Map 0 issues')
    expect(approveButton).toBeDisabled()
  })

  it('restores a row the reader re-checks after unchecking it', () => {
    renderOffer()

    const checkbox = screen.getByRole('checkbox', { name: /#2/ })
    fireEvent.click(checkbox)
    fireEvent.click(checkbox)

    expect(screen.getByTestId('sibling-mapping-approve')).toHaveTextContent('Map 1 issue')
  })

  it('calls commit with the selected row ids when the reader approves', () => {
    const mutate = vi.fn()
    mockCommit({ mutate })

    renderOffer()
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(mutate).toHaveBeenCalledWith(
      {
        preview_token: 'tok',
        idempotency_key: 'sibling-mapping-1-1',
        approved_row_ids: ['issue:2'],
      },
      expect.any(Object),
    )
  })

  it('never approves the origin issue that licensed the sibling scope', () => {
    const mutate = vi.fn()
    mockPreview(
      previewResponse([
        previewRow({ row_id: 'issue:1', issue_id: 1, issue_number: '1' }),
        SIBLING_ROW,
      ]),
    )
    mockCommit({ mutate })

    renderOffer()
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(mutate.mock.calls[0][0].approved_row_ids).toEqual(['issue:2'])
  })

  it('labels a row with no number rather than showing a bare hash', () => {
    mockPreview(previewResponse([previewRow({ issue_number: '', title: null })]))

    renderOffer()

    expect(screen.getByText('Unnumbered')).toBeInTheDocument()
    expect(screen.queryByText(/Saga #2/)).not.toBeInTheDocument()
  })

  it('lists an owned row the preview did not mark approvable without a checkbox', () => {
    mockPreview(
      previewResponse([
        previewRow({
          row_id: 'issue:3',
          issue_id: 3,
          issue_number: '3',
          classification: 'needs_review_conflict',
          default_selected: false,
        }),
        SIBLING_ROW,
      ]),
    )

    renderOffer()

    expect(screen.getAllByRole('checkbox')).toHaveLength(1)
    expect(screen.getByText('Conflict')).toBeInTheDocument()
  })

  it('calls onDismiss when the reader declines', () => {
    const onDismiss = vi.fn()

    renderOffer({ onDismiss })
    fireEvent.click(screen.getByTestId('sibling-mapping-dismiss'))

    expect(onDismiss).toHaveBeenCalled()
  })
})

describe('SiblingSeriesMappingOffer provider inventory', () => {
  it('summarizes provider inventory for rows the reader does not own', () => {
    mockPreview(
      previewResponse([
        previewRow({ row_id: 'roster:1', issue_id: 99, thread_id: null, thread_title: null }),
        SIBLING_ROW,
      ]),
    )

    renderOffer()

    expect(screen.getByTestId('sibling-mapping-provider-inventory')).toHaveTextContent(
      '1 other issue is in this volume but not in your library.',
    )
  })

  it('pluralizes the provider inventory summary', () => {
    mockPreview(
      previewResponse([
        previewRow({ row_id: 'roster:1', issue_id: 98, thread_id: null, thread_title: null }),
        previewRow({ row_id: 'roster:2', issue_id: 99, thread_id: null, thread_title: null }),
        SIBLING_ROW,
      ]),
    )

    renderOffer()

    expect(screen.getByTestId('sibling-mapping-provider-inventory')).toHaveTextContent(
      '2 other issues are in this volume but not in your library.',
    )
  })
})

describe('SiblingSeriesMappingOffer no preview token', () => {
  it('does not call commit when the preview token is missing', () => {
    const mutate = vi.fn()
    mockCommit({ mutate })
    mockPreview(previewResponse([SIBLING_ROW], { preview_token: null, issued_at: 0 }))

    renderOffer()
    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(mutate).not.toHaveBeenCalled()
  })
})
