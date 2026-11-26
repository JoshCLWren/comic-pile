import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

/** A4: delete and reorder must preview exact before/after rows before queueing. */
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
const mockedUndo = vi.fn<() => Promise<void>>()

const ISSUES: Issue[] = [129, 140, 130].map((number, index) => ({
  id: index + 1,
  thread_id: 99,
  issue_number: String(number),
  status: 'unread',
  read_at: null,
  created_at: '2026-03-08T00:00:00Z',
}))

const listResponse: IssueListResponse = {
  issues: ISSUES,
  total_count: ISSUES.length,
  page_size: 100,
  next_page_token: null,
}

function structureResponse(
  beforeNumbers: string[],
  afterNumbers: string[],
  overrides: Partial<IssueEditPreviewResponse['default_outcome']> = {},
): IssueEditPreviewResponse {
  const rows = (numbers: string[]) => numbers.map((issueNumber, index) => ({
    issue_id: ISSUES.find((issue) => issue.issue_number === issueNumber)?.id ?? null,
    issue_number: issueNumber,
    position: index + 1,
    is_new: false,
    series_title: 'Synthetic nonnumeric series',
    source_lists: ['Julix reading order'],
    is_read: false,
    has_rating: false,
    is_mapped: false,
    frontier_label: index === 0 ? 'current unread (Queue/Roll frontier)' : null,
    effect: `kept #${issueNumber} at position ${index + 1}`,
    is_duplicate: false,
  }))
  return {
    thread_id: 99,
    thread_title: 'Synthetic nonnumeric series',
    requested_strategy: 'safe_default',
    default_outcome: {
      strategy: 'safe_default',
      can_commit: true,
      preserves_existing_relative_order: true,
      before: rows(beforeNumbers),
      after: rows(afterNumbers),
      added_issue_numbers: [],
      graph: { status: 'ok', cycles: [] },
      conflict_message: null,
      ...overrides,
    },
    numeric_resort_outcome: null,
    expected_issue_ids: [1, 2, 3],
  }
}

async function renderList(deferred = true) {
  const ref = createRef<IssueToggleListHandle>()
  render(
    <IssueToggleList
      ref={ref}
      threadId={99}
      deferred={deferred}
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

async function openDeletePreview() {
  fireEvent.click(screen.getByTestId('issue-delete-2'))
  await screen.findByTestId('delete-issue-dialog')
  fireEvent.click(screen.getByTestId('confirm-delete-issue'))
  await screen.findByTestId('edit-series-structure-preview-modal')
}

async function openReorderPreview() {
  fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
  fireEvent.click(screen.getByTestId('issue-move-down-1'))
  await screen.findByTestId('edit-series-structure-preview-modal')
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(listResponse)
  mockedIssuesApi.create.mockResolvedValue(listResponse)
  mockedIssuesApi.previewCreate.mockResolvedValue(structureResponse(['129'], ['129', '101']))
  mockedIssuesApi.previewDelete.mockResolvedValue(
    structureResponse(
      ['129', '140', '130'],
      ['129', '130'],
    ),
  )
  mockedIssuesApi.previewReorder.mockResolvedValue(
    structureResponse(
      ['129', '140', '130'],
      ['140', '129', '130'],
      { preserves_existing_relative_order: false },
    ),
  )
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
  mockedUndo.mockResolvedValue(undefined)
})

describe('IssueToggleList #4654 delete/reorder structure preview', () => {
  it('shows human-readable before/after rows and only queues a confirmed delete', async () => {
    const ref = await renderList()
    await openDeletePreview()

    const modal = screen.getByTestId('edit-series-structure-preview-modal')
    expect(modal).toHaveTextContent('Removing an issue from Synthetic nonnumeric series')
    expect(screen.getByTestId('structure-preview-before-after')).toHaveTextContent('#140')
    expect(modal).toHaveTextContent('List: Julix reading order')
    expect(modal).toHaveTextContent('current unread (Queue/Roll frontier)')
    expect(mockedIssuesApi.previewDelete).toHaveBeenCalledWith(99, 2)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
    expect(ref.current?.hasPendingMutations()).toBe(false)

    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.delete).toHaveBeenCalledWith(2)
  })

  it('cancelling a delete preview leaves the draft untouched', async () => {
    const ref = await renderList()
    await openDeletePreview()
    fireEvent.click(screen.getByTestId('cancel-structure-preview'))

    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
  })

  it('previews the projected reorder and queues it only on confirmation', async () => {
    const ref = await renderList()
    await openReorderPreview()

    const modal = screen.getByTestId('edit-series-structure-preview-modal')
    expect(modal).toHaveTextContent('Reordering issues in Synthetic nonnumeric series')
    expect(mockedIssuesApi.previewReorder).toHaveBeenCalledWith(99, [2, 1, 3])
    expect(screen.queryByTestId('issue-action-error')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)

    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    expect(ref.current?.hasPendingMutations()).toBe(true)
    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [2, 1, 3])
  })

  it('shows concrete conflicts and refuses to confirm a cyclic projection', async () => {
    await renderList()
    mockedIssuesApi.previewReorder.mockResolvedValueOnce(
      structureResponse(['129', '140', '130'], ['140', '129', '130'], {
        can_commit: false,
        conflict_message: 'Reading-graph cycle: #140 -> #129',
        graph: {
          status: 'cycle',
          cycles: [{
            message: 'Reading-graph cycle: #140 -> #129',
            edges: [{
              source: { issue_id: 2, issue_number: '140', series_title: 'Synthetic nonnumeric series' },
              target: { issue_id: 1, issue_number: '129', series_title: 'Synthetic nonnumeric series' },
              origin: 'constraint',
            }],
          }],
        },
      }),
    )
    await openReorderPreview()

    expect(screen.getByTestId('structure-preview-conflict')).toHaveTextContent('Reading-graph cycle: #140 -> #129')
    expect(screen.getByTestId('structure-preview-cycle-path')).toHaveTextContent('Synthetic nonnumeric series #140 -> Synthetic nonnumeric series #129')
    expect(screen.getByTestId('confirm-structure-preview')).toBeDisabled()
  })

  it('a failed preview reports the reason and does not queue the edit', async () => {
    const ref = await renderList()
    mockedIssuesApi.previewDelete.mockRejectedValueOnce(new Error('preview exploded'))
    fireEvent.click(screen.getByTestId('issue-delete-1'))
    await screen.findByTestId('delete-issue-dialog')
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    await waitFor(() => {
      expect(screen.getByTestId('issue-action-error')).toHaveTextContent('preview exploded')
    })
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
  })

  it('keeps the immediate-mode direct path when no Save boundary exists', async () => {
    await renderList(false)
    fireEvent.click(screen.getByTestId('issue-delete-1'))
    await screen.findByTestId('delete-issue-dialog')
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    await waitFor(() => expect(mockedIssuesApi.delete).toHaveBeenCalledWith(1))
    expect(mockedIssuesApi.previewDelete).not.toHaveBeenCalled()
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
  })

  it('falls back to the direct path when a preview seam is not injected', async () => {
    const ref = createRef<IssueToggleListHandle>()
    render(
      <IssueToggleList
        ref={ref}
        threadId={99}
        deferred
        issuesApi={{
          list: mockedIssuesApi.list,
          create: mockedIssuesApi.create,
          previewCreate: mockedIssuesApi.previewCreate,
          markRead: mockedIssuesApi.markRead,
          markUnread: mockedIssuesApi.markUnread,
          delete: mockedIssuesApi.delete,
          reorder: mockedIssuesApi.reorder,
        }}
        dependenciesApi={mockedDependenciesApi}
      />,
    )
    await waitFor(() => {
      expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
    })
    fireEvent.click(screen.getByTestId('issue-delete-1'))
    await screen.findByTestId('delete-issue-dialog')
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
  })
})
