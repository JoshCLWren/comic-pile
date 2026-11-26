import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList'
import type { IssueEditPreviewResponse } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

/** #4654 closure coverage: alias offers, stale-version token, post-commit Undo. */
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
const mockedUndo = vi.fn<(sessionId: number, snapshotId: number) => Promise<void>>()

const ISSUES: Issue[] = [
  {
    id: 1,
    thread_id: 99,
    issue_number: '1',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
  {
    id: 2,
    thread_id: 99,
    issue_number: '2',
    status: 'unread',
    read_at: null,
    created_at: '2026-03-08T00:00:00Z',
  },
]

function listResponse(undo = false): IssueListResponse {
  return {
    issues: ISSUES,
    total_count: ISSUES.length,
    page_size: 100,
    next_page_token: null,
    ...(undo ? { undo_session_id: 7, undo_snapshot_id: 42 } : {}),
  }
}

function previewResponse(withAlias: boolean): IssueEditPreviewResponse {
  return {
    thread_id: 99,
    thread_title: 'Test series',
    requested_strategy: 'safe_default',
    expected_issue_ids: [1, 2],
    alias_offers: withAlias
      ? [
          {
            requested_issue_number: '101',
            existing_issue_id: 55,
            existing_issue_number: '101',
            series_title: 'Other series',
            evidence: 'confirmed external identity mapping',
          },
        ]
      : [],
    default_outcome: {
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
        { issue_id: null, issue_number: '102', position: 3, is_new: true },
      ],
      added_issue_numbers: ['102'],
      graph: { status: 'ok', cycles: [] },
      conflict_message: null,
    },
    numeric_resort_outcome: null,
  }
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
    target: { value: '101-102' },
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
  mockedIssuesApi.previewCreate.mockImplementation(async () => previewResponse(false))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
  mockedUndo.mockResolvedValue()
})

describe('IssueToggleList #4654 alias and Undo contract', () => {
  it('requires explicit alias acceptance and re-previews before confirming', async () => {
    mockedIssuesApi.previewCreate
      .mockResolvedValueOnce(previewResponse(true))
      .mockResolvedValueOnce(previewResponse(false))
    const ref = await renderDeferred()
    await openPreview()

    expect(screen.getByTestId('preview-alias-offers')).toBeInTheDocument()
    expect(screen.getByTestId('preview-alias-offer')).toHaveTextContent('Other series')
    const confirm = screen.getByTestId('confirm-preview-add') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)

    fireEvent.click(screen.getByTestId('accept-alias'))
    await waitFor(() => {
      expect(mockedIssuesApi.previewCreate).toHaveBeenLastCalledWith(99, '101-102', {
        accepted_alias_numbers: ['101'],
      })
    })
    await waitFor(() => {
      expect((screen.getByTestId('confirm-preview-add') as HTMLButtonElement).disabled).toBe(false)
    })
    fireEvent.click(screen.getByTestId('confirm-preview-add'))
    await ref.current!.flush()

    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '101-102', {
      expected_issue_ids: [1, 2],
      accepted_alias_numbers: ['101'],
      strategy: 'safe_default',
    })
  })

  it('sends the previewed issue IDs so a stale version is rejected server-side', async () => {
    const ref = await renderDeferred()
    await openPreview()
    fireEvent.click(screen.getByTestId('confirm-preview-add'))
    await ref.current!.flush()

    expect(mockedIssuesApi.create).toHaveBeenCalledWith(
      99,
      '101-102',
      expect.objectContaining({ expected_issue_ids: [1, 2] }),
    )
  })

  it('offers a post-commit Undo that restores the pre-edit snapshot', async () => {
    mockedIssuesApi.create.mockResolvedValueOnce(listResponse(true))
    const ref = await renderDeferred()
    await openPreview()
    fireEvent.click(screen.getByTestId('confirm-preview-add'))
    await ref.current!.flush()

    const undoBar = await screen.findByTestId('edit-series-undo-bar')
    expect(undoBar).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('undo-edit-add'))

    await waitFor(() => {
      expect(mockedUndo).toHaveBeenCalledWith(7, 42)
    })
    await waitFor(() => {
      expect(screen.queryByTestId('edit-series-undo-bar')).not.toBeInTheDocument()
    })
    expect(mockedIssuesApi.list).toHaveBeenCalled()
  })
})
