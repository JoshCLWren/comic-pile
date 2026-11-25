import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DuplicateReconciliationPage from '../pages/DuplicateReconciliationPage'
import { issueDuplicateReconciliationApi } from '../services/api-issue-duplicate-reconciliation'
import type {
  DuplicateCandidateGroup,
  DuplicateDetectionResponse,
  DuplicateIssueEvidence,
  ReconcileApplyResponse,
  ReconcilePreviewResponse,
  ReconcileUndoResponse,
} from '../types'

vi.mock('../services/api-issue-duplicate-reconciliation', () => ({
  issueDuplicateReconciliationApi: {
    detect: vi.fn(),
    preview: vi.fn(),
    apply: vi.fn(),
    undo: vi.fn(),
  },
}))

const detect = vi.mocked(issueDuplicateReconciliationApi.detect)
const preview = vi.mocked(issueDuplicateReconciliationApi.preview)
const apply = vi.mocked(issueDuplicateReconciliationApi.apply)
const undo = vi.mocked(issueDuplicateReconciliationApi.undo)

function evidence(overrides: Partial<DuplicateIssueEvidence> = {}): DuplicateIssueEvidence {
  return {
    issue_id: 10,
    thread_id: 100,
    thread_title: 'Mister Miracle',
    issue_number: '1',
    status: 'read',
    read_at: '2026-01-02T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    merged_into_issue_id: null,
    comicvine_issue_id: '4001',
    comicvine_volume_id: 900,
    comicvine_issue_number: '1',
    comicvine_story_number: null,
    rating_events: [{ event_id: 5, rating: 5, timestamp: '2026-01-02T00:00:00Z' }],
    read_events: [{ event_id: 6, timestamp: '2026-01-02T00:00:00Z', issue_number: '1' }],
    list_memberships: [{ list_id: 7, list_name: 'Owned', position: 1, entry_id: 8 }],
    is_synthetic_placeholder_read: false,
    ...overrides,
  }
}

function group(overrides: Partial<DuplicateCandidateGroup> = {}): DuplicateCandidateGroup {
  return {
    group_key: 'cv-volume-900:4001',
    confidence: 'high',
    reason: 'Verified provider identity',
    evidence: [evidence(), evidence({ issue_id: 11, issue_number: 'Annual 1' })],
    suggested_canonical_issue_id: 10,
    suggested_duplicate_issue_ids: [11],
    ...overrides,
  }
}

function detections(groups: DuplicateCandidateGroup[]): DuplicateDetectionResponse {
  return { groups }
}

function previewResponse(
  overrides: Partial<ReconcilePreviewResponse> = {},
): ReconcilePreviewResponse {
  return {
    canonical_issue_id: 10,
    duplicate_issue_ids: [11],
    canonical: evidence(),
    duplicates: [evidence({ issue_id: 11 })],
    actions: [
      {
        kind: 'link_provider_mapping',
        description: 'Link the verified provider mapping',
        safe: true,
        requires_decision: false,
        decision_key: null,
      },
      {
        kind: 'move_rating',
        description: 'Move a conflicting genuine rating',
        safe: false,
        requires_decision: true,
        decision_key: 'rating_conflict',
      },
    ],
    warnings: ['Artificial suppression timestamp excluded'],
    can_apply: true,
    preview_token: 'token-1',
    ...overrides,
  }
}

function applyResponse(overrides: Partial<ReconcileApplyResponse> = {}): ReconcileApplyResponse {
  return {
    canonical_issue_id: 10,
    merged_issue_ids: [11],
    moved_event_ids: [5],
    moved_mapping_ids: [6],
    moved_list_entry_ids: [7],
    suppressed_duplicate_issue_ids: [11],
    undo_snapshot_id: 55,
    warnings: [],
    ...overrides,
  }
}

function undoResponse(overrides: Partial<ReconcileUndoResponse> = {}): ReconcileUndoResponse {
  return { reconciliation_id: 55, undone: true, warnings: [], ...overrides }
}

async function renderWithGroup(candidateGroup = group()) {
  detect.mockResolvedValue(detections([candidateGroup]))
  render(<DuplicateReconciliationPage />)
  await screen.findByText(candidateGroup.reason)
  await userEvent.click(screen.getByText(candidateGroup.reason))
}

beforeEach(() => {
  vi.clearAllMocks()
  detect.mockResolvedValue(detections([]))
  preview.mockResolvedValue(previewResponse())
  apply.mockResolvedValue(applyResponse())
  undo.mockResolvedValue(undoResponse())
})

describe('DuplicateReconciliationPage', () => {
  it('shows a loading state while detections are pending', () => {
    detect.mockReturnValue(new Promise(() => undefined))

    render(<DuplicateReconciliationPage />)

    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('reports a detection load failure', async () => {
    detect.mockRejectedValue(new Error('detections unavailable'))

    render(<DuplicateReconciliationPage />)

    expect(await screen.findByText('Failed to load detections.')).toBeInTheDocument()
  })

  it('shows an empty state when no duplicate group is detected', async () => {
    render(<DuplicateReconciliationPage />)

    expect(await screen.findByText('No duplicate groups detected.')).toBeInTheDocument()
    expect(screen.getByText('Select a detected group to preview reconciliation.')).toBeInTheDocument()
  })

  it('refetches detections when Refresh is clicked', async () => {
    render(<DuplicateReconciliationPage />)
    await screen.findByText('No duplicate groups detected.')

    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    await waitFor(() => expect(detect).toHaveBeenCalledTimes(2))
  })

  it('shows identity, volume, ratings, read events and memberships with labels', async () => {
    await renderWithGroup(
      group({
        evidence: [
          evidence({ is_synthetic_placeholder_read: true, read_at: '2026-01-01T00:00:00Z' }),
          evidence({ issue_id: 11, merged_into_issue_id: 10, comicvine_issue_id: null }),
        ],
      }),
    )

    expect(screen.getByText('Mister Miracle #1')).toBeInTheDocument()
    expect(screen.getByText('4001')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.getAllByText(/^Canonical$/)).toHaveLength(1)
    expect(screen.getAllByText(/^Duplicate$/)).toHaveLength(1)
    expect(screen.getAllByText(/^Related$/)).toHaveLength(0)
    expect(screen.getByText('Invalid synthetic placeholder read (read_at before created_at)')).toBeInTheDocument()
    expect(screen.getByText('Merged into issue 10')).toBeInTheDocument()
    expect(screen.getAllByText('Ratings:')).toHaveLength(2)
    expect(screen.getAllByText('Read events:')).toHaveLength(2)
    expect(screen.getAllByText('List memberships:')).toHaveLength(2)
  })

  it('lets the reader change the canonical issue and toggle duplicate selection', async () => {
    await renderWithGroup()

    await userEvent.click(screen.getByRole('button', { name: 'Canonical: #Annual 1 (11)' }))
    expect(screen.getByRole('checkbox', { name: 'Duplicate: #1 (10)' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Duplicate: #Annual 1 (11)' })).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Duplicate: #1 (10)' }))
    expect(screen.getByRole('checkbox', { name: 'Duplicate: #1 (10)' })).not.toBeChecked()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Duplicate: #Annual 1 (11)' }))
    expect(screen.getByRole('checkbox', { name: 'Duplicate: #Annual 1 (11)' })).toBeChecked()
  })

  it('previews canonical, aliases, actions, warnings and Queue/Roll changes', async () => {
    await renderWithGroup()

    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))

    expect(await screen.findByText('Artificial suppression timestamp excluded')).toBeInTheDocument()
    expect(screen.getByText('Link the verified provider mapping')).toBeInTheDocument()
    expect(screen.getByText('Move a conflicting genuine rating')).toBeInTheDocument()
    expect(preview).toHaveBeenCalledWith({
      canonical_issue_id: 10,
      duplicate_issue_ids: [11],
      decisions: {},
    })
  })

  it('re-previews with the reader decision and applies the token, then undoes it', async () => {
    await renderWithGroup()
    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await screen.findByText('Move a conflicting genuine rating')

    await userEvent.click(screen.getByRole('checkbox', { name: 'Confirm merge despite warning' }))

    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
    expect(preview).toHaveBeenLastCalledWith({
      canonical_issue_id: 10,
      duplicate_issue_ids: [11],
      decisions: { rating_conflict: 'merge' },
    })

    await userEvent.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    expect(await screen.findByText('Reconciled. Undo ID: 55')).toBeInTheDocument()
    expect(apply).toHaveBeenCalledWith({
      canonical_issue_id: 10,
      duplicate_issue_ids: [11],
      decisions: { rating_conflict: 'merge' },
      preview_token: 'token-1',
    })

    await userEvent.click(screen.getByRole('button', { name: 'Undo #55' }))
    expect(await screen.findByText('Undid reconciliation 55')).toBeInTheDocument()
    expect(undo).toHaveBeenCalledWith({ reconciliation_id: 55 })
  })

  it('keeps a distinct option when the preview is not applicable', async () => {
    await renderWithGroup()
    preview.mockResolvedValue(previewResponse({ can_apply: false }))

    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))

    expect(await screen.findByRole('button', { name: 'Apply reconciliation' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Artificial suppression timestamp excluded')).not.toBeInTheDocument()
  })

  it('surfaces preview, apply and undo failures without losing the decision surface', async () => {
    await renderWithGroup()
    preview.mockRejectedValueOnce(new Error('preview failed'))

    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))
    expect(await screen.findByText('preview failed')).toBeInTheDocument()

    preview.mockResolvedValue(previewResponse())
    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await screen.findByText('Move a conflicting genuine rating')
    apply.mockRejectedValueOnce(new Error('apply failed'))

    await userEvent.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    expect(await screen.findByText('apply failed')).toBeInTheDocument()
    expect(screen.getByText('Move a conflicting genuine rating')).toBeInTheDocument()

    apply.mockResolvedValue(applyResponse({ undo_snapshot_id: 77 }))
    await userEvent.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    expect(await screen.findByRole('button', { name: 'Undo #77' })).toBeInTheDocument()

    undo.mockRejectedValueOnce(new Error('undo failed'))
    await userEvent.click(screen.getByRole('button', { name: 'Undo #77' }))
    expect(await screen.findByText('undo failed')).toBeInTheDocument()
  })

  it('handles non-Error rejections and an apply without an undo snapshot', async () => {
    await renderWithGroup()
    preview.mockRejectedValueOnce('preview offline')

    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))
    expect(await screen.findByText('Preview failed')).toBeInTheDocument()

    preview.mockResolvedValue(previewResponse())
    apply.mockResolvedValueOnce(applyResponse({ undo_snapshot_id: null }))
    await userEvent.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await screen.findByText('Move a conflicting genuine rating')
    await userEvent.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    expect(await screen.findByText('Reconciled. Undo ID: n/a')).toBeInTheDocument()
  })
})
