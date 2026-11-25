import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DuplicateReconciliationPage from '../pages/DuplicateReconciliationPage'
import { issueDuplicateReconciliationApi } from '../services/api-issue-duplicate-reconciliation'
import { cast } from '../utils/cast'
import type {
  DuplicateCandidateGroup,
  DuplicateIssueEvidence,
  ReconcileApplyResponse,
  ReconcilePreviewResponse,
  ReconcileUndoResponse,
} from '../types'

vi.mock('../services/api-issue-duplicate-reconciliation', async () => {
  const actual = await vi.importActual<typeof import('../services/api-issue-duplicate-reconciliation')>(
    '../services/api-issue-duplicate-reconciliation',
  )
  return {
    ...actual,
    issueDuplicateReconciliationApi: {
      ...actual.issueDuplicateReconciliationApi,
      detect: vi.fn(),
      preview: vi.fn(),
      apply: vi.fn(),
      undo: vi.fn(),
    },
  }
})

const mockDetect = cast<ReturnType<typeof vi.fn>>(issueDuplicateReconciliationApi.detect)
const mockPreview = cast<ReturnType<typeof vi.fn>>(issueDuplicateReconciliationApi.preview)
const mockApply = cast<ReturnType<typeof vi.fn>>(issueDuplicateReconciliationApi.apply)
const mockUndo = cast<ReturnType<typeof vi.fn>>(issueDuplicateReconciliationApi.undo)

function evidence(overrides: Partial<DuplicateIssueEvidence> = {}): DuplicateIssueEvidence {
  return {
    issue_id: 10,
    thread_id: 1,
    thread_title: 'B.P.R.D. Return of the Master',
    issue_number: '4',
    status: 'read',
    read_at: '2026-11-05T06:03:08Z',
    created_at: '2026-01-01T00:00:00Z',
    merged_into_issue_id: null,
    comicvine_issue_id: '364132',
    comicvine_volume_id: 51622,
    comicvine_issue_number: '101',
    comicvine_story_number: '4',
    rating_events: [],
    read_events: [],
    list_memberships: [],
    is_synthetic_placeholder_read: false,
    ...overrides,
  }
}

function group(overrides: Partial<DuplicateCandidateGroup> = {}): DuplicateCandidateGroup {
  return {
    group_key: 'g1',
    confidence: 'high',
    reason: 'Same Comic Vine identity',
    evidence: [
      evidence({ issue_id: 10, issue_number: '4' }),
      evidence({
        issue_id: 20,
        issue_number: '101',
        status: 'read',
        read_at: '2026-11-05T05:02:02Z',
        created_at: '2026-11-05T05:11:33Z',
        is_synthetic_placeholder_read: true,
        read_events: [{ event_id: 1, timestamp: '2026-11-05T05:02:02Z', issue_number: '101' }],
      }),
    ],
    suggested_canonical_issue_id: 10,
    suggested_duplicate_issue_ids: [20],
    ...overrides,
  }
}

function previewResponse(overrides: Partial<ReconcilePreviewResponse> = {}): ReconcilePreviewResponse {
  return {
    canonical_issue_id: 10,
    duplicate_issue_ids: [20],
    canonical: evidence({ issue_id: 10 }),
    duplicates: [evidence({ issue_id: 20, is_synthetic_placeholder_read: true })],
    actions: [
      {
        kind: 'move_mapping',
        description: 'Move mapping',
        safe: true,
        requires_decision: false,
        decision_key: null,
      },
      {
        kind: 'suppress_synthetic_read_events',
        description: 'Suppress synthetic reads',
        safe: true,
        requires_decision: true,
        decision_key: 'suppress:20',
      },
    ],
    warnings: ['synthetic placeholder detected'],
    can_apply: true,
    preview_token: 'token-1',
    ...overrides,
  }
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DuplicateReconciliationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DuplicateReconciliationPage', () => {
  it('shows loading state', () => {
    mockDetect.mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('shows empty state', async () => {
    mockDetect.mockResolvedValue({ groups: [] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('No duplicate groups detected.')).toBeInTheDocument()
    })
  })

  it('shows error state', async () => {
    mockDetect.mockRejectedValue(new Error('boom'))
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Failed to load detections.')).toBeInTheDocument()
    })
  })

  it('shows preview error', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockRejectedValue(new Error('preview boom'))
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByText('preview boom')).toBeInTheDocument()
    })
  })


  it('applies reconciliation with null undo id', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    mockApply.mockResolvedValue({
      canonical_issue_id: 10,
      merged_issue_ids: [20],
      moved_event_ids: [],
      moved_mapping_ids: [],
      moved_list_entry_ids: [],
      suppressed_duplicate_issue_ids: [],
      undo_snapshot_id: null,
      warnings: [],
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply reconciliation' })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    await waitFor(() => {
      expect(screen.getByText('Reconciled. Undo ID: n/a')).toBeInTheDocument()
    })
  })

  it('shows apply error', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    mockApply.mockRejectedValue(new Error('apply boom'))
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply reconciliation' })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    await waitFor(() => {
      expect(screen.getByText('apply boom')).toBeInTheDocument()
    })
  })

  it('shows undo error', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    mockApply.mockResolvedValue({
      canonical_issue_id: 10,
      merged_issue_ids: [20],
      moved_event_ids: [],
      moved_mapping_ids: [],
      moved_list_entry_ids: [],
      suppressed_duplicate_issue_ids: [],
      undo_snapshot_id: 7,
      warnings: [],
    })
    mockUndo.mockRejectedValue(new Error('undo boom'))
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply reconciliation' })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Undo #7' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Undo #7' }))
    await waitFor(() => {
      expect(screen.getByText('undo boom')).toBeInTheDocument()
    })
  })

  it('selects canonical via button', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: /Canonical: #101 \(20\)/ }))
    expect(screen.getByText('Preview resolution')).toBeInTheDocument()
  })

  it('renders null evidence fields and related label', async () => {
    const user = userEvent.setup()
    const relatedGroup = group({
      evidence: [
        evidence({ issue_id: 10, read_at: null, comicvine_issue_id: null }),
        evidence({ issue_id: 20, issue_number: '101' }),
        evidence({ issue_id: 30, issue_number: '102' }),
      ],
    })
    mockDetect.mockResolvedValue({ groups: [relatedGroup] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    expect(screen.getByText('Related')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders a detected group and selects it', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    expect(screen.getByText('Resolve duplicate')).toBeInTheDocument()
    expect(screen.getByText(/Invalid synthetic placeholder read/)).toBeInTheDocument()
    expect(screen.getByText('Preview resolution')).toBeInTheDocument()
  })

  it('refreshes detections', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(mockDetect).toHaveBeenCalledTimes(2)
  })

  it('previews reconciliation and cancels', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByText('move_mapping')).toBeInTheDocument()
    })
    expect(screen.getByText('synthetic placeholder detected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('move_mapping')).not.toBeInTheDocument()
  })

  it('toggles duplicate membership', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    const checkboxes = screen.getAllByRole('checkbox')
    const enabledCheckbox = checkboxes.find((cb) => !cb.hasAttribute('disabled'))!
    await user.click(enabledCheckbox)
    await user.click(enabledCheckbox)
    expect(enabledCheckbox).toBeInTheDocument()
  })

  it('applies reconciliation and undoes it', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    const applyResult: ReconcileApplyResponse = {
      canonical_issue_id: 10,
      merged_issue_ids: [20],
      moved_event_ids: [1],
      moved_mapping_ids: [2],
      moved_list_entry_ids: [3],
      suppressed_duplicate_issue_ids: [20],
      undo_snapshot_id: 42,
      warnings: [],
    }
    mockApply.mockResolvedValue(applyResult)
    const undoResult: ReconcileUndoResponse = {
      reconciliation_id: 42,
      undone: true,
      warnings: [],
    }
    mockUndo.mockResolvedValue(undoResult)

    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply reconciliation' })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: 'Apply reconciliation' }))
    await waitFor(() => {
      expect(screen.getByText('Reconciled. Undo ID: 42')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: 'Undo #42' }))
    await waitFor(() => {
      expect(screen.getByText('Undid reconciliation 42')).toBeInTheDocument()
    })
  })

  it('changes a decision and re-previews', async () => {
    const user = userEvent.setup()
    mockDetect.mockResolvedValue({ groups: [group()] })
    mockPreview.mockResolvedValue(previewResponse())
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Same Comic Vine identity'))
    await user.click(screen.getByRole('button', { name: 'Preview resolution' }))
    await waitFor(() => {
      expect(screen.getByText('Confirm merge despite warning')).toBeInTheDocument()
    })
    await user.click(screen.getByLabelText('Confirm merge despite warning'))
    expect(mockPreview).toHaveBeenCalled()
  })

  it('shows merged-into badge for merged evidence', async () => {
    mockDetect.mockResolvedValue({
      groups: [
        group({
          evidence: [
            evidence({ issue_id: 10, merged_into_issue_id: 99 }),
            evidence({ issue_id: 20, merged_into_issue_id: null }),
          ],
        }),
      ],
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('Same Comic Vine identity')).toBeInTheDocument()
    })
    await userEvent.setup().click(screen.getByText('Same Comic Vine identity'))
    await waitFor(() => {
      expect(screen.getByText('Merged into issue 99')).toBeInTheDocument()
    })
  })
})
