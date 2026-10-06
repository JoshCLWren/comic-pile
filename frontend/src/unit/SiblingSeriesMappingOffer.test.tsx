import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const { useSiblingSeriesMappingPreviewMock, useCommitSeriesMappingMock } = vi.hoisted(() => ({
  useSiblingSeriesMappingPreviewMock: vi.fn(),
  useCommitSeriesMappingMock: vi.fn(),
}))

vi.mock('../hooks/useSiblingSeriesMapping', () => ({
  useSiblingSeriesMappingPreview: useSiblingSeriesMappingPreviewMock,
  useCommitSeriesMapping: useCommitSeriesMappingMock,
}))

import SiblingSeriesMappingOffer from '../components/SiblingSeriesMappingOffer'

const defaultPreview = {
  data: {
    preview_token: 'tok',
    scope: { status: 'available' as const, scope_key: 'k', origin_issue_id: 1, series_label: 'Saga', basis: 'b' },
    provider_series: null,
    counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
    rows: [
      {
        row_id: 'issue:1',
        issue_id: 1,
        issue_number: '1',
        title: 'Saga #1',
        classification: 'already_confirmed',
        thread_id: 10,
        thread_title: 'Saga',
        current_mapping_status: null,
        proposed_mapping: false,
        default_selected: false,
        reason: null,
      },
      {
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
      },
    ],
    issued_at: 1,
    expires_at: null,
  },
  isPending: false,
  isError: false,
  refetch: vi.fn(),
  reset: vi.fn(),
}

const defaultCommit = {
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  isSuccess: false,
  data: null as { confirmed_issue_ids: number[] } | null,
  error: null as unknown,
  reset: vi.fn(),
}

const defaultProps = (overrides = {}) => ({
  originIssueId: 1,
  provider: 'comicvine',
  providerSeriesExternalId: '20764',
  seriesLabel: 'Saga (2012)',
  onMapped: vi.fn(),
  onDismiss: vi.fn(),
  ...overrides,
})

function renderOffer(overrides = {}) {
  const props = defaultProps(overrides)
  useSiblingSeriesMappingPreviewMock.mockReturnValue(defaultPreview)
  useCommitSeriesMappingMock.mockReturnValue(defaultCommit)
  render(<SiblingSeriesMappingOffer {...props} />)
  return { props, previewMock: useSiblingSeriesMappingPreviewMock, commitMock: useCommitSeriesMappingMock }
}

beforeEach(() => {
  vi.clearAllMocks()
  useSiblingSeriesMappingPreviewMock.mockReturnValue(defaultPreview)
  useCommitSeriesMappingMock.mockReturnValue(defaultCommit)
})

describe('SiblingSeriesMappingOffer loading', () => {
  it('renders a loading state while the preview is pending', () => {
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      isPending: true,
      data: undefined,
    })
    renderOffer()

    expect(screen.getByTestId('sibling-mapping-offer')).toHaveTextContent('Checking the rest of')
    expect(screen.getByText('Saga (2012)')).toBeInTheDocument()
  })
})

describe('SiblingSeriesMappingOffer error', () => {
  it('renders an error state when the preview fails', () => {
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      isError: true,
      data: undefined,
    })
    renderOffer()

    expect(screen.getByRole('alert')).toHaveTextContent('Saga (2012) was matched, but the remaining issues in the series could not be checked.')
    expect(screen.getByTestId('sibling-mapping-dismiss')).toHaveTextContent('Done')
  })
})

describe('SiblingSeriesMappingOffer empty', () => {
  it('renders a no-match message when no approvable rows exist', () => {
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      data: {
        ...defaultPreview.data,
        rows: [
          {
            row_id: 'issue:1',
            issue_id: 1,
            issue_number: '1',
            title: 'Saga #1',
            classification: 'already_confirmed',
            thread_id: 10,
            thread_title: 'Saga',
            current_mapping_status: null,
            proposed_mapping: false,
            default_selected: false,
            reason: null,
          },
        ],
      },
    })
    renderOffer()

    expect(screen.getByText(/is linked for this issue/)).toBeInTheDocument()
    expect(screen.getByTestId('sibling-mapping-dismiss')).toHaveTextContent('Done')
  })
})

describe('SiblingSeriesMappingOffer success', () => {
  it('shows a success message after a successful commit', () => {
    useCommitSeriesMappingMock.mockReturnValue({
      ...defaultCommit,
      isSuccess: true,
      data: { confirmed_issue_ids: [2], already_confirmed_issue_ids: [], needs_review_issue_ids: [], hydration_queued_issue_ids: [], series_mapping: { provider: 'comicvine', external_id: '20764', status: 'confirmed', evidence_source: 'user_confirmed' } },
    })
    renderOffer()

    expect(screen.getByText('1 sibling issue mapped to Saga (2012).')).toBeInTheDocument()
    expect(screen.getByTestId('sibling-mapping-approve')).toHaveTextContent('Mapped')
  })
})

describe('SiblingSeriesMappingOffer commit error', () => {
  it('shows a generic error when the commit fails', () => {
    useCommitSeriesMappingMock.mockReturnValue({
      ...defaultCommit,
      isError: true,
      error: new Error('Server error'),
    })
    renderOffer()

    expect(screen.getByRole('alert')).toHaveTextContent('Could not map the sibling issues. Nothing else was changed.')
  })

  it('re-reads the preview when the commit fails with a stale preview', async () => {
    const refetch = vi.fn()
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      refetch,
    })
    useCommitSeriesMappingMock.mockReturnValue({
      ...defaultCommit,
      isError: true,
      error: { response: { data: { detail: 'preview_expired' } } },
    })
    renderOffer()

    expect(screen.getByRole('alert')).toHaveTextContent('That preview is out of date. Reviewing the series again.')
  })
})

describe('SiblingSeriesMappingOffer interactions', () => {
  it('toggles row selection and enables the approve button when rows are selected', () => {
    renderOffer()

    const approveButton = screen.getByTestId('sibling-mapping-approve')
    expect(approveButton).toHaveTextContent('Map 1 issue')
    expect(approveButton).not.toBeDisabled()

    const checkbox = screen.getByRole('checkbox', { name: /#2/ })
    fireEvent.click(checkbox)

    expect(approveButton).toHaveTextContent('Map 0 issues')
    expect(approveButton).toBeDisabled()
  })

  it('calls commit with the selected row ids when the reader approves', () => {
    const mutate = vi.fn()
    useCommitSeriesMappingMock.mockReturnValue({
      ...defaultCommit,
      mutate,
    })
    renderOffer()

    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(mutate).toHaveBeenCalledWith({
      preview_token: 'tok',
      idempotency_key: 'sibling-mapping-1-1',
      approved_row_ids: ['issue:2'],
    })
  })

  it('calls onDismiss when the reader declines', () => {
    const onDismiss = vi.fn()
    renderOffer({ onDismiss })

    fireEvent.click(screen.getByTestId('sibling-mapping-dismiss'))

    expect(onDismiss).toHaveBeenCalled()
  })
})

describe('SiblingSeriesMappingOffer provider inventory', () => {
  it('shows provider inventory count for non-owned rows', () => {
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      data: {
        preview_token: 'tok',
        scope: { status: 'available' as const, scope_key: 'k', origin_issue_id: 1, series_label: 'Saga', basis: 'b' },
        provider_series: null,
        counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
        rows: [
          {
            row_id: 'roster:1',
            issue_id: 99,
            issue_number: '1',
            title: 'Saga #1',
            classification: 'safe_exact_match',
            thread_id: null,
            thread_title: null,
            current_mapping_status: null,
            proposed_mapping: true,
            default_selected: false,
            reason: null,
          },
          {
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
          },
        ],
        issued_at: 1,
        expires_at: null,
      },
    })
    renderOffer()

    expect(screen.getByTestId('sibling-mapping-provider-inventory')).toHaveTextContent('1 other issue is in this volume but not in your library.')
  })
})

describe('SiblingSeriesMappingOffer no preview token', () => {
  it('does not call commit when the preview token is missing', () => {
    const mutate = vi.fn()
    useCommitSeriesMappingMock.mockReturnValue({
      ...defaultCommit,
      mutate,
    })
    useSiblingSeriesMappingPreviewMock.mockReturnValue({
      ...defaultPreview,
      data: {
        preview_token: null,
        scope: { status: 'unavailable' as const, scope_key: null, origin_issue_id: 1, series_label: null, basis: null },
        provider_series: null,
        counts: { already_confirmed: 0, safe_exact_match: 0, needs_review_ambiguous: 0, needs_review_conflict: 0, unresolved: 0, excluded_special: 0 },
        rows: [
          {
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
          },
        ],
        issued_at: 0,
        expires_at: null,
      },
    })
    renderOffer()

    fireEvent.click(screen.getByTestId('sibling-mapping-approve'))

    expect(mutate).not.toHaveBeenCalled()
  })
})
