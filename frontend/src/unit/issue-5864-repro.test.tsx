import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
} from '../pages/QueuePage/IssueToggleList.api'
import type { IssueEditPreviewResponse } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

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
const mockedDependenciesApi = { listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>() }
const ISSUES: Issue[] = [
  { id: 1, thread_id: 99, issue_number: '3', status: 'read', read_at: 'now', created_at: 'now' },
  { id: 2, thread_id: 99, issue_number: '4', status: 'unread', read_at: null, created_at: 'now' },
]
const listResponse: IssueListResponse = { issues: ISSUES, total_count: 2, page_size: 100, next_page_token: null }
const previewResponse: IssueEditPreviewResponse = {
  thread_id: 99,
  thread_title: 'Detective Comics',
  requested_strategy: 'safe_default',
  default_outcome: {
    strategy: 'safe_default',
    can_commit: true,
    preserves_existing_relative_order: true,
    before: ISSUES.map((i, x) => ({ issue_id: i.id, issue_number: i.issue_number, position: x + 1, is_new: false, series_title: 'Detective Comics', source_lists: [], is_read: false, has_rating: false, is_mapped: false, frontier_label: null, effect: '', is_duplicate: false })),
    after: [ISSUES[0]].map((i, x) => ({ issue_id: i.id, issue_number: i.issue_number, position: x + 1, is_new: false, series_title: 'Detective Comics', source_lists: [], is_read: false, has_rating: false, is_mapped: false, frontier_label: null, effect: '', is_duplicate: false })),
    added_issue_numbers: [],
    graph: { status: 'ok', cycles: [] },
    conflict_message: null,
  },
  numeric_resort_outcome: null,
  expected_issue_ids: [1],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(listResponse)
  mockedIssuesApi.previewDelete.mockResolvedValue(previewResponse)
  mockedIssuesApi.delete.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
})

describe('issue #5864 reproduction', () => {
  it('reports a pending mutation when a staged delete is confirmed', async () => {
    const onPending = vi.fn()
    render(
      <IssueToggleList
        threadId={99}
        deferred
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedDependenciesApi}
        onPendingMutationsChange={onPending}
      />,
    )
    await screen.findByTestId('issue-pill-2')
    fireEvent.click(screen.getByTestId('issue-delete-2'))
    await screen.findByTestId('delete-issue-dialog')
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))
    await screen.findByTestId('edit-series-structure-preview-modal')
    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    expect(onPending).toHaveBeenLastCalledWith(true)
  })
})
