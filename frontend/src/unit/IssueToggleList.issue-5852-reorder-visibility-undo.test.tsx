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

/**
 * #5852 regression: in Edit Series, Move down used to have no visible effect,
 * showed no order-effect preview, and offered no Undo before or after Save.
 * The editor must show the pending order immediately, keep the server-side
 * before/after confirmation, and offer a real Undo for the committed reorder.
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

function previewResponse(beforeNumbers: string[], afterNumbers: string[]): IssueEditPreviewResponse {
  const rows = (numbers: string[]) => numbers.map((issueNumber, index) => ({
    issue_id: ISSUES.find((issue) => issue.issue_number === issueNumber)?.id ?? null,
    issue_number: issueNumber,
    position: index + 1,
    is_new: false,
    series_title: 'Synthetic nonnumeric series',
    source_lists: ['Authored order'],
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
      preserves_existing_relative_order: false,
      before: rows(beforeNumbers),
      after: rows(afterNumbers),
      added_issue_numbers: [],
      graph: { status: 'ok', cycles: [] },
      conflict_message: null,
    },
    numeric_resort_outcome: null,
    expected_issue_ids: [1, 2, 3],
  }
}

function reorderRowNumbers(): string[] {
  const rows = screen.queryAllByTestId(/issue-reorder-row-/)
  return rows.map((row) => row.getAttribute('data-issue-number') ?? '')
}

async function renderList() {
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
  fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
  return ref
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedIssuesApi.list.mockResolvedValue(listResponse)
  mockedIssuesApi.create.mockResolvedValue(listResponse)
  mockedIssuesApi.previewCreate.mockResolvedValue(previewResponse(['129'], ['129', '101']))
  mockedIssuesApi.previewDelete.mockResolvedValue(previewResponse(['129', '140', '130'], ['129', '130']))
  mockedIssuesApi.previewReorder.mockResolvedValue(
    previewResponse(['129', '140', '130'], ['140', '129', '130']),
  )
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedDependenciesApi.listForThread.mockResolvedValue({ thread_id: 99, issues: [] })
  mockedUndo.mockResolvedValue(undefined)
})

describe('IssueToggleList #5852 visible reorder, preview and Undo', () => {
  it('shows the new order immediately and a pending preview before the server confirms', async () => {
    let resolvePreview: ((value: IssueEditPreviewResponse) => void) | undefined
    mockedIssuesApi.previewReorder.mockReturnValue(new Promise((resolve) => {
      resolvePreview = resolve
    }))

    const ref = await renderList()
    expect(reorderRowNumbers()).toEqual(['129', '140', '130'])

    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    // No waiting on the preview RPC: the click itself is visible.
    expect(reorderRowNumbers()).toEqual(['140', '129', '130'])
    expect(screen.getByTestId('pending-reorder-preview')).toHaveTextContent('Pending order change')
    expect(screen.getByTestId('pending-reorder-effect-1')).toHaveTextContent('#129: 1 → 2')
    expect(screen.getByTestId('undo-pending-reorder')).toBeInTheDocument()
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)

    act(() => resolvePreview?.(previewResponse(['129', '140', '130'], ['140', '129', '130'])))
    const modal = await screen.findByTestId('edit-series-structure-preview-modal')
    expect(modal).toHaveTextContent('Reordering issues in Synthetic nonnumeric series')
    expect(screen.getByTestId('structure-preview-before-after')).toHaveTextContent('List: Authored order')
  })

  it('Undo before save restores the saved order and queues nothing', async () => {
    const ref = await renderList()
    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await screen.findByTestId('edit-series-structure-preview-modal')

    fireEvent.click(screen.getByTestId('undo-pending-reorder'))

    expect(reorderRowNumbers()).toEqual(['129', '140', '130'])
    expect(screen.queryByTestId('pending-reorder-preview')).not.toBeInTheDocument()
    expect(screen.queryByTestId('edit-series-structure-preview-modal')).not.toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })

  it('composes successive moves and offers a real Undo after Save', async () => {
    mockedIssuesApi.previewReorder.mockImplementation(async (_threadId, issueIds) =>
      previewResponse(
        ['129', '140', '130'],
        [issueIds[1], issueIds[0], issueIds[2]]
          .map((id) => ISSUES.find((issue) => issue.id === id)?.issue_number ?? ''),
      ))

    const ref = await renderList()
    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await screen.findByTestId('edit-series-structure-preview-modal')
    fireEvent.click(screen.getByTestId('confirm-structure-preview'))

    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await screen.findByTestId('edit-series-structure-preview-modal')
    expect(reorderRowNumbers()).toEqual(['140', '130', '129'])

    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    await act(async () => {
      await ref.current?.flush()
    })

    expect(mockedIssuesApi.reorder).toHaveBeenLastCalledWith(99, [2, 3, 1])
    expect(ref.current?.hasUndoPoint()).toBe(true)
    await screen.findByTestId('edit-series-undo-bar')
    fireEvent.click(screen.getByTestId('undo-edit-add'))

    await waitFor(() => expect(mockedIssuesApi.reorder).toHaveBeenLastCalledWith(99, [1, 2, 3]))
    expect(screen.queryByTestId('edit-series-undo-bar')).not.toBeInTheDocument()
    expect(ref.current?.hasUndoPoint()).toBe(false)
  })

  it('two Move down clicks on issue #129 advance it two positions (QA repro)', async () => {
    const ref = await renderList()

    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await screen.findByTestId('edit-series-structure-preview-modal')
    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    expect(reorderRowNumbers()).toEqual(['140', '129', '130'])

    // After the first move is queued, the second click uses the updated list.
    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await screen.findByTestId('edit-series-structure-preview-modal')
    fireEvent.click(screen.getByTestId('confirm-structure-preview'))
    expect(reorderRowNumbers()).toEqual(['140', '130', '129'])

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.reorder).toHaveBeenLastCalledWith(99, [2, 3, 1])

    await screen.findByTestId('edit-series-undo-bar')
    fireEvent.click(screen.getByTestId('undo-edit-add'))
    await waitFor(() => expect(mockedIssuesApi.reorder).toHaveBeenLastCalledWith(99, [1, 2, 3]))
    expect(ref.current?.hasUndoPoint()).toBe(false)
  })

  it('a failed reorder preview is retryable and never commits the draft', async () => {
    const ref = await renderList()
    mockedIssuesApi.previewReorder.mockRejectedValueOnce(new Error('preview exploded'))
    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    const errorModal = await screen.findByTestId('edit-series-structure-preview-error-modal')
    expect(errorModal).toHaveTextContent('preview exploded')
    expect(reorderRowNumbers()).toEqual(['140', '129', '130'])
    expect(ref.current?.hasPendingMutations()).toBe(false)

    fireEvent.click(screen.getByTestId('retry-structure-preview'))
    const preview = await screen.findByTestId('edit-series-structure-preview-modal')
    expect(preview).toBeInTheDocument()
    expect(screen.queryByTestId('edit-series-structure-preview-error-modal')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('cancel-structure-preview'))
    expect(reorderRowNumbers()).toEqual(['129', '140', '130'])
    expect(ref.current?.hasPendingMutations()).toBe(false)
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
  })

  it('keeps the direct reorder path when no preview seam is injected', async () => {
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
    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    expect(ref.current?.hasPendingMutations()).toBe(true)
    expect(screen.queryByTestId('pending-reorder-preview')).not.toBeInTheDocument()
    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [2, 1, 3])
  })
})
