import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList'
import type { IssueEditPreviewOutcome, IssueEditPreviewResponse } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

/** #4654 branch coverage: projected cycles, alias de-selection and Undo failure. */
const mockedIssuesApi = {
  list: vi.fn<IssueToggleListApi['list']>(),
  create: vi.fn<IssueToggleListApi['create']>(),
  previewCreate: vi.fn<IssueToggleListApi['previewCreate']>(),
  markRead: vi.fn<IssueToggleListApi['markRead']>(),
  markUnread: vi.fn<IssueToggleListApi['markUnread']>(),
  delete: vi.fn<IssueToggleListApi['delete']>(),
  reorder: vi.fn<IssueToggleListApi['reorder']>(),
}
const mockedDependenciesApi = {
  listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>(),
}
const mockedUndo = vi.fn<
  (sessionId: string | number, snapshotId: string | number) => Promise<void>
>()

const ISSUES: Issue[] = [
  {
    id: 1,
    thread_id: 99,
    issue_number: '129',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
  {
    id: 2,
    thread_id: 99,
    issue_number: '140',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
]

function listResponse(withUndo = false): IssueListResponse {
  const response: IssueListResponse = {
    issues: ISSUES,
    total_count: ISSUES.length,
    page_size: 100,
    next_page_token: null,
  }
  if (withUndo) {
    response.undo_session_id = 7
    response.undo_snapshot_id = 42
  }
  return response
}

function baseOutcome(): IssueEditPreviewOutcome {
  return {
    strategy: 'safe_default',
    can_commit: true,
    preserves_existing_relative_order: true,
    before: ISSUES.map((issue, index) => ({
      issue_id: issue.id,
      issue_number: issue.issue_number,
      position: index + 1,
      is_new: false,
    })),
    after: [
      ...ISSUES.map((issue, index) => ({
        issue_id: issue.id,
        issue_number: issue.issue_number,
        position: index + 1,
        is_new: false,
      })),
      { issue_id: null, issue_number: '101', position: 3, is_new: true },
    ],
    added_issue_numbers: ['101'],
    graph: { status: 'ok', cycles: [] },
    conflict_message: null,
  }
}

function previewResponse(
  defaultOutcome: IssueEditPreviewOutcome,
  numericOutcome: IssueEditPreviewOutcome | null,
  withAlias = false,
): IssueEditPreviewResponse {
  const response: IssueEditPreviewResponse = {
    thread_id: 99,
    thread_title: 'Synthetic nonnumeric series',
    requested_strategy: 'safe_default',
    default_outcome: defaultOutcome,
    numeric_resort_outcome: numericOutcome,
    expected_issue_ids: [1, 2],
  }
  if (withAlias) {
    response.alias_offers = [{
      requested_issue_number: '101',
      existing_issue_id: 55,
      existing_issue_number: '101',
      series_title: 'Other series',
      evidence: 'confirmed external identity mapping',
    }]
  }
  return response
}

async function renderDeferred() {
  const ref = createRef<IssueToggleListHandle>()
  render(
    <IssueToggleList
      ref={ref}
      threadId={99}
      deferred
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedDependenciesApi}
      undoApi={{ undo: mockedUndo }}
    />,
  )
  await waitFor(() => {
    expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
  })
  return ref
}

async function openPreview() {
  fireEvent.change(screen.getByTestId('issue-add-input'), {
    target: { value: '101' },
  })
  fireEvent.click(screen.getByTestId('issue-add-button'))
  await waitFor(() => {
    expect(screen.getByTestId('edit-series-preview-modal')).toBeInTheDocument()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(listResponse())
  mockedIssuesApi.create.mockResolvedValue(listResponse())
  mockedIssuesApi.previewCreate.mockImplementation(async () => previewResponse(baseOutcome(), null))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
  mockedUndo.mockResolvedValue(undefined)
})

describe('IssueToggleList #4654 preview, alias and Undo branch coverage', () => {
  it('shows a projected numeric-resort cycle and its own Before/After rows before saving', async () => {
    const safe = baseOutcome()
    const numeric = baseOutcome()
    numeric.strategy = 'numeric_resort'
    numeric.can_commit = false
    numeric.conflict_message = null
    numeric.preserves_existing_relative_order = false
    numeric.after = [{
      issue_id: null,
      issue_number: '101',
      position: 1,
      is_new: true,
      effect: 'Numeric resort re-seats #101 ahead of authored order',
    }]
    numeric.graph = {
      status: 'cycle',
      cycles: [{
        message: 'Source constraint cycle',
        edges: [{
          source: { issue_id: 1, issue_number: '129', series_title: 'Synthetic series' },
          target: { issue_id: 2, issue_number: '140', series_title: 'Other series' },
          origin: 'reading_list',
        }],
      }],
    }
    mockedIssuesApi.previewCreate.mockResolvedValueOnce(previewResponse(safe, numeric))
    const ref = await renderDeferred()
    await openPreview()

    fireEvent.click(screen.getByRole('radio', { name: /Numeric resort/ }))

    expect(screen.getByTestId('confirm-preview-add')).toBeDisabled()
    expect(screen.getByTestId('numeric-resort-cycle')).toHaveTextContent(
      'This change would create a reading-graph cycle.',
    )
    expect(screen.getByTestId('numeric-resort-cycle-path')).toHaveTextContent(
      'Synthetic series #129 -> Other series #140',
    )
    expect(screen.getByText('Numeric resort re-seats #101 ahead of authored order')).toBeInTheDocument()
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('un-accepting an alias re-previews with no aliases and re-disables Add', async () => {
    mockedIssuesApi.previewCreate.mockImplementation(async () => previewResponse(baseOutcome(), null, true))
    await renderDeferred()
    await openPreview()

    expect(screen.getByTestId('confirm-preview-add')).toBeDisabled()
    fireEvent.click(screen.getByTestId('accept-alias'))
    await waitFor(() => {
      expect(screen.getByTestId('confirm-preview-add')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('accept-alias'))
    await waitFor(() => {
      expect(mockedIssuesApi.previewCreate).toHaveBeenLastCalledWith(99, '101', {
        accepted_alias_numbers: [],
      })
    })
    expect(screen.getByTestId('confirm-preview-add')).toBeDisabled()
  })

  it('keeps the Undo affordance and reports the error when an Undo fails', async () => {
    mockedIssuesApi.create.mockResolvedValueOnce(listResponse(true))
    mockedUndo.mockRejectedValueOnce(new Error('undo failed'))
    const ref = await renderDeferred()
    await openPreview()
    fireEvent.click(screen.getByTestId('confirm-preview-add'))
    await ref.current!.flush()

    const undoBar = await screen.findByTestId('edit-series-undo-bar')
    fireEvent.click(screen.getByTestId('undo-edit-add'))

    await waitFor(() => {
      expect(screen.getByTestId('issue-action-error')).toHaveTextContent('undo failed')
    })
    expect(undoBar).toBeInTheDocument()
    expect(mockedUndo).toHaveBeenCalledWith(7, 42)
  })

  it('explains a safe-default conflict even when the server sends no message', async () => {
    const safe = baseOutcome()
    safe.can_commit = false
    safe.conflict_message = null
    safe.graph = { status: 'cycle', cycles: [] }
    mockedIssuesApi.previewCreate.mockResolvedValueOnce(previewResponse(safe, null))
    await renderDeferred()
    await openPreview()

    expect(screen.getByTestId('confirm-preview-add')).toBeDisabled()
    expect(screen.getByText('This change would create a reading-graph cycle.')).toBeInTheDocument()
    expect(screen.queryByTestId('safe-default-cycle-path')).not.toBeInTheDocument()
  })
})
