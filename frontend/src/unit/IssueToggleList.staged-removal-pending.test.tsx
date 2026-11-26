import { fireEvent, render, screen } from '@testing-library/react'
import { act, createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList.api'
import type { IssueEditPreviewResponse } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

/**
 * Regression coverage for #5864 / MQA-QUEUE-008: confirming a staged issue
 * removal must mark the Edit Series draft dirty immediately. Since #4654 the
 * delete mutation is enqueued only after a second (structure-preview)
 * confirmation, so the parent's queued-mutation signal alone leaves a window
 * where closing silently discards a removal the reader believes is staged.
 */

const mockedIssuesApi = {
  list: vi.fn<IssueToggleListApi['list']>(),
  create: vi.fn<IssueToggleListApi['create']>(),
  previewCreate: vi.fn<IssueToggleListApi['previewCreate']>(),
  previewDelete: vi.fn<NonNullable<IssueToggleListApi['previewDelete']>>(),
  previewReorder: vi.fn<NonNullable<IssueToggleListApi['previewReorder']>>(),
  markRead: vi.fn<IssueToggleListApi['markRead']>(),
  markUnread: vi.fn<IssueToggleListApi['markUnread']>(),
  delete: vi.fn<IssueToggleListApi['delete']>(),
  reorder: vi.fn<IssueToggleListApi['reorder']>(),
}
const mockedDependenciesApi = {
  listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>(),
}

const ISSUES: Issue[] = [
  { id: 1, thread_id: 99, issue_number: '3', status: 'read', read_at: 'now', created_at: 'now' },
  { id: 2, thread_id: 99, issue_number: '4', status: 'unread', read_at: null, created_at: 'now' },
]
const listResponse: IssueListResponse = {
  issues: ISSUES, total_count: ISSUES.length, page_size: 100, next_page_token: null,
}
const previewResponse: IssueEditPreviewResponse = {
  thread_id: 99,
  thread_title: 'Detective Comics',
  requested_strategy: 'safe_default',
  default_outcome: {
    strategy: 'safe_default',
    can_commit: true,
    preserves_existing_relative_order: true,
    before: ISSUES.map((issue, index) => ({
      issue_id: issue.id, issue_number: issue.issue_number, position: index + 1, is_new: false,
      series_title: 'Detective Comics', source_lists: [], is_read: false, has_rating: false,
      is_mapped: false, frontier_label: null, effect: '', is_duplicate: false,
    })),
    after: [ISSUES[0]].map((issue, index) => ({
      issue_id: issue.id, issue_number: issue.issue_number, position: index + 1, is_new: false,
      series_title: 'Detective Comics', source_lists: [], is_read: false, has_rating: false,
      is_mapped: false, frontier_label: null, effect: '', is_duplicate: false,
    })),
    added_issue_numbers: [],
    graph: { status: 'ok', cycles: [] },
    conflict_message: null,
  },
  numeric_resort_outcome: null,
  expected_issue_ids: [1],
}

async function renderList(onPendingMutationsChange: (pending: boolean) => void) {
  const ref = createRef<IssueToggleListHandle>()
  render(
    <IssueToggleList
      ref={ref}
      threadId={99}
      deferred
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedDependenciesApi}
      onPendingMutationsChange={onPendingMutationsChange}
    />,
  )
  await screen.findByTestId('issue-pill-2')
  return ref
}

async function confirmRemovalDialog() {
  fireEvent.click(screen.getByTestId('issue-delete-2'))
  await screen.findByTestId('delete-issue-dialog')
  fireEvent.click(screen.getByTestId('confirm-delete-issue'))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(listResponse)
  mockedIssuesApi.previewDelete.mockResolvedValue(previewResponse)
  mockedIssuesApi.delete.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
})

describe('IssueToggleList staged removal dirtiness (#5864)', () => {
  it('marks the draft dirty as soon as the removal dialog is confirmed, before the preview resolves', async () => {
    // Hold the preview open: this is the window where #5864 closed silently.
    let resolvePreview: (response: IssueEditPreviewResponse) => void = () => undefined
    mockedIssuesApi.previewDelete.mockImplementation(
      () => new Promise<IssueEditPreviewResponse>((resolve) => { resolvePreview = resolve }),
    )
    const onPending = vi.fn()
    const ref = await renderList(onPending)

    await confirmRemovalDialog()
    expect(onPending).toHaveBeenLastCalledWith(true)
    // The mutation itself is still only staged, not queued or sent.
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()

    await act(async () => { resolvePreview(previewResponse) })
    expect(await screen.findByTestId('edit-series-structure-preview-modal')).toBeInTheDocument()
    expect(onPending).toHaveBeenLastCalledWith(true)
  })

  it('keeps the draft dirty when the structure preview fails', async () => {
    mockedIssuesApi.previewDelete.mockRejectedValueOnce(new Error('Not Found'))
    const onPending = vi.fn()
    const ref = await renderList(onPending)

    await confirmRemovalDialog()
    expect(await screen.findByTestId('edit-series-structure-preview-error-modal')).toBeInTheDocument()
    expect(onPending).toHaveBeenLastCalledWith(true)
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('keeps the draft dirty and queues the mutation after preview confirmation', async () => {
    const onPending = vi.fn()
    const ref = await renderList(onPending)

    await confirmRemovalDialog()
    await screen.findByTestId('edit-series-structure-preview-modal')
    fireEvent.click(screen.getByTestId('confirm-structure-preview'))

    expect(onPending).toHaveBeenLastCalledWith(true)
    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
  })

  it('does not mark the draft dirty when the removal dialog is cancelled', async () => {
    const onPending = vi.fn()
    await renderList(onPending)

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    await screen.findByTestId('delete-issue-dialog')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onPending).not.toHaveBeenCalledWith(true)
    expect(mockedIssuesApi.previewDelete).not.toHaveBeenCalled()
  })

  it('marks the draft dirty as soon as a reorder is staged, before preview confirmation', async () => {
    mockedIssuesApi.previewReorder.mockImplementation(
      () => new Promise<IssueEditPreviewResponse>(() => undefined),
    )
    const onPending = vi.fn()
    const ref = await renderList(onPending)

    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    expect(screen.getByTestId('pending-reorder-preview')).toBeInTheDocument()
    expect(onPending).toHaveBeenLastCalledWith(true)
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })
})
