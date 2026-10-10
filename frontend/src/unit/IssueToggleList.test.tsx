import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import type {
  IssueToggleListApi,
  IssueToggleListDependenciesApi,
  IssueToggleListHandle,
} from '../pages/QueuePage/IssueToggleList'
import type { Issue, IssueListResponse } from '../types'
import { cast } from '../utils/cast'

// Injectable fakes passed through the real `issuesApi`/`dependenciesApi` props —
// no module mocking of the API services.
const mockedIssuesApi = {
  list: vi.fn<IssueToggleListApi['list']>(),
  create: vi.fn<IssueToggleListApi['create']>(),
  markRead: vi.fn<IssueToggleListApi['markRead']>(),
  markUnread: vi.fn<IssueToggleListApi['markUnread']>(),
  delete: vi.fn<IssueToggleListApi['delete']>(),
  reorder: vi.fn<IssueToggleListApi['reorder']>(),
}

const mockedIssueDependenciesApi = {
  listForThread: vi.fn<IssueToggleListDependenciesApi['listForThread']>(),
}

const BASE_ISSUES: Issue[] = [
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
  {
    id: 3,
    thread_id: 99,
    issue_number: '3',
    status: 'read',
    read_at: '2026-03-08T00:00:00Z',
    created_at: '2026-03-08T00:00:00Z',
  },
]

function buildListResponse(
  issues: Issue[] = BASE_ISSUES,
  nextPageToken: string | null = null
): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: nextPageToken,
  }
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void

  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, resolve, reject }
}

function createDataTransfer(): DataTransfer {
  // SAFETY: DataTransfer is a browser DOM interface; the mock satisfies the full contract via the cast below
  return {
    dropEffect: 'move',
    effectAllowed: 'move',
    files: cast<FileList>([]),
    items: cast<DataTransferItemList>([]),
    types: [],
    clearData: vi.fn(),
    getData: vi.fn(),
    setData: vi.fn(),
    setDragImage: vi.fn(),
  } as DataTransfer
}

function getIssueOrder(): Array<string | null> {
  return screen.getAllByTestId(/issue-pill-/).map((pill) => pill.getAttribute('data-issue-number'))
}

async function renderIssueToggleList() {
  render(
    <IssueToggleList
      threadId={99}
      issuesApi={mockedIssuesApi}
      dependenciesApi={mockedIssueDependenciesApi}
    />,
  )
  await waitFor(() => {
    expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('confirm', vi.fn())

  mockedIssuesApi.list.mockResolvedValue(buildListResponse())
  mockedIssuesApi.create.mockResolvedValue(buildListResponse([]))
  mockedIssuesApi.markRead.mockResolvedValue()
  mockedIssuesApi.markUnread.mockResolvedValue()
  mockedIssuesApi.reorder.mockResolvedValue()
  mockedIssuesApi.delete.mockResolvedValue()
  mockedIssueDependenciesApi.listForThread.mockResolvedValue({
    thread_id: 99,
    issues: [],
  })
})
describe('IssueToggleList', () => {
  it('uses the timeout focus fallback when animation frames are unavailable', async () => {
    const original = window.requestAnimationFrame
    Object.defineProperty(window, 'requestAnimationFrame', { configurable: true, value: undefined })
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(screen.getByTestId('issue-move-down-1')).toHaveFocus()
    Object.defineProperty(window, 'requestAnimationFrame', { configurable: true, value: original })
  })

  it('keeps boundary move controls in place and ignores an empty add request', async () => {
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-move-up-1'))
    fireEvent.click(screen.getByTestId('issue-move-down-3'))
    fireEvent.keyDown(screen.getByTestId('issue-add-input'), { key: 'Enter' })
    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
  })

  it('surfaces add-issue failures submitted with Enter', async () => {
    mockedIssuesApi.create.mockRejectedValueOnce(new Error('add failed'))
    await renderIssueToggleList()
    const input = screen.getByTestId('issue-add-input')
    fireEvent.change(input, { target: { value: '4-5' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByText('add failed')).toBeInTheDocument())
  })
  it('loads all issue pages before rendering the full list', async () => {
    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse(BASE_ISSUES.slice(0, 2), 'page-2'))
      .mockResolvedValueOnce(buildListResponse(BASE_ISSUES.slice(2)))

    await renderIssueToggleList()

    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(1, 99, { page_size: 100 })
    expect(mockedIssuesApi.list).toHaveBeenNthCalledWith(2, 99, {
      page_size: 100,
      page_token: 'page-2',
    })
    expect(getIssueOrder()).toEqual(['1', '2', '3'])
  })

  it('optimistically reorders issues and persists the new order', async () => {
    const reorderRequest = createDeferred<void>()
    mockedIssuesApi.reorder.mockReturnValueOnce(reorderRequest.promise)

    await renderIssueToggleList()

    fireEvent.dragStart(screen.getByTestId('issue-toggle-1'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.dragOver(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.drop(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })

    expect(getIssueOrder()).toEqual(['2', '3', '1'])
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [2, 3, 1])

    await act(async () => {
      reorderRequest.resolve()
      await reorderRequest.promise
    })
  })

  it('reverts the optimistic reorder when the API call fails', async () => {
    const reorderRequest = createDeferred<void>()
    mockedIssuesApi.reorder.mockReturnValueOnce(reorderRequest.promise)

    await renderIssueToggleList()

    fireEvent.dragStart(screen.getByTestId('issue-toggle-1'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.dragOver(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.drop(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })

    expect(getIssueOrder()).toEqual(['2', '3', '1'])

    await act(async () => {
      reorderRequest.reject(new Error('Issue reorder failed'))

      try {
        await reorderRequest.promise
      } catch {
        // The component surfaces the error inline; the rejected promise is expected here.
      }
    })

    await waitFor(() => {
      expect(getIssueOrder()).toEqual(['1', '2', '3'])
    })
    expect(screen.getByText('Issue reorder failed')).toBeInTheDocument()
  })

  it('inserts the dragged issue after the drop target regardless of drag direction', async () => {
    const reorderRequest = createDeferred<void>()
    mockedIssuesApi.reorder.mockReturnValueOnce(reorderRequest.promise)

    await renderIssueToggleList()

    fireEvent.dragStart(screen.getByTestId('issue-toggle-3'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.dragOver(screen.getByTestId('issue-pill-1'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.drop(screen.getByTestId('issue-pill-1'), {
      dataTransfer: createDataTransfer(),
    })

    expect(getIssueOrder()).toEqual(['1', '3', '2'])
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [1, 3, 2])

    await act(async () => {
      reorderRequest.resolve()
      await reorderRequest.promise
    })
  })

  it('keeps later optimistic mutations when an earlier queued mutation fails', async () => {
    const canonicalIssuesAfterFailure: Issue[] = [
      ...BASE_ISSUES,
      {
        id: 4,
        thread_id: 99,
        issue_number: '4',
        status: 'unread',
        read_at: null,
        created_at: '2026-03-08T00:00:00Z',
      },
    ]

    const reorderRequest = createDeferred<void>()
    const deleteRequest = createDeferred<void>()
    mockedIssuesApi.reorder.mockReturnValueOnce(reorderRequest.promise)
    mockedIssuesApi.delete.mockReturnValueOnce(deleteRequest.promise)
    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse())
      .mockResolvedValueOnce(buildListResponse(canonicalIssuesAfterFailure))

    await renderIssueToggleList()

    fireEvent.dragStart(screen.getByTestId('issue-toggle-1'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.dragOver(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })
    fireEvent.drop(screen.getByTestId('issue-pill-3'), {
      dataTransfer: createDataTransfer(),
    })

    expect(getIssueOrder()).toEqual(['2', '3', '1'])

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()

    // Confirm the delete through the in-app dialog. The dialog closes on
    // confirmation so it can never trap focus over the list it edits.
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))
    expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
    expect(getIssueOrder()).toEqual(['3', '1'])

    await act(async () => {
      reorderRequest.reject(new Error('Issue reorder failed'))

      try {
        await reorderRequest.promise
      } catch {
        // The component surfaces the error inline; the rejected promise is expected here.
      }
    })

    await waitFor(() => {
      expect(getIssueOrder()).toEqual(['1', '3', '4'])
    })
    expect(screen.getByText('Issue reorder failed')).toBeInTheDocument()
    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2)

    await act(async () => {
      deleteRequest.resolve()
      await deleteRequest.promise
    })

    await waitFor(() => {
      expect(getIssueOrder()).toEqual(['1', '3', '4'])
    })
  })

  it('reorders issues with move controls for keyboard and touch users', async () => {
    const reorderRequest = createDeferred<void>()
    mockedIssuesApi.reorder.mockReturnValueOnce(reorderRequest.promise)

    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    expect(getIssueOrder()).toEqual(['2', '1', '3'])
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [2, 1, 3])
    expect(screen.getByText('Moved issue #1 down.')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByTestId('issue-move-down-1')).toHaveFocus()
    })

    await act(async () => {
      reorderRequest.resolve()
      await reorderRequest.promise
    })
  })

  it('deletes an issue after confirmation and updates the pills optimistically', async () => {
    const deleteRequest = createDeferred<void>()
    mockedIssuesApi.delete.mockReturnValueOnce(deleteRequest.promise)

    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))

    // The delete dialog should now be open
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Delete Issue' })).toBeInTheDocument()
    expect(
      screen.getByText(/Are you sure you want to delete issue #2\?/),
    ).toBeInTheDocument()

    // Click the Delete button in the dialog
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    // Confirming closes the dialog instead of holding a focus trap open while
    // the delete settles (#3269), and the optimistic removal is immediate.
    expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
    expect(mockedIssuesApi.delete).toHaveBeenCalledWith(2)
    expect(getIssueOrder()).toEqual(['1', '3'])

    await act(async () => {
      deleteRequest.resolve()
      await deleteRequest.promise
    })
  })

  it('does not delete an issue when confirmation is cancelled', async () => {
    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))

    // The delete dialog should now be open
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Delete Issue' })).toBeInTheDocument()
    expect(
      screen.getByText(/Are you sure you want to delete issue #2\?/),
    ).toBeInTheDocument()

    // Click the Cancel button in the dialog
    fireEvent.click(screen.getByText('Cancel'))

    expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
    expect(getIssueOrder()).toEqual(['1', '2', '3'])
  })

  it('restores the issue and reports the failure inline when a confirmed delete fails', async () => {
    mockedIssuesApi.delete.mockRejectedValueOnce(new Error('delete failed'))
    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    await waitFor(() => expect(screen.getByText('delete failed')).toBeInTheDocument())
    expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
    // The failed issue comes back so the reader can retry from the list.
    await waitFor(() => expect(getIssueOrder()).toEqual(['1', '2', '3']))
  })

  it('closes the confirmation dialog on Escape without deleting', async () => {
    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })

    await waitFor(() =>
      expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
    )
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
    expect(getIssueOrder()).toEqual(['1', '2', '3'])
  })

  describe('collapsible issue list', () => {
    it('shows all issues when total issues <= 5', async () => {
      const smallIssueList: Issue[] = [
        {
          id: 1,
          thread_id: 99,
          issue_number: '1',
          status: 'read',
          read_at: '2026-03-08T00:00:00Z',
          created_at: '2026-03-08T00:00:00Z',
        },
        {
          id: 2,
          thread_id: 99,
          issue_number: '2',
          status: 'read',
          read_at: '2026-03-08T00:00:00Z',
          created_at: '2026-03-08T00:00:00Z',
        },
        {
          id: 3,
          thread_id: 99,
          issue_number: '3',
          status: 'unread',
          read_at: null,
          created_at: '2026-03-08T00:00:00Z',
        },
      ]
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(smallIssueList))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
      })

      expect(screen.queryByRole('button', { name: /Show all/i })).not.toBeInTheDocument()
      expect(getIssueOrder()).toEqual(['1', '2', '3'])
    })

    it('shows only issues around next unread by default when total issues > 5', async () => {
      const largeIssueList: Issue[] = Array.from({ length: 10 }, (_, i) => ({
        id: i + 1,
        thread_id: 99,
        issue_number: String(i + 1),
        status: i < 4 ? 'read' : 'unread',
        read_at: i < 4 ? '2026-03-08T00:00:00Z' : null,
        created_at: '2026-03-08T00:00:00Z',
      }))
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(largeIssueList))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-2')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: 'Show all 10' })).toBeInTheDocument()
      expect(screen.getByText(/Showing \d+ of 10 issues around your current position/)).toBeInTheDocument()

      const visibleIssues = getIssueOrder()
      expect(visibleIssues.length).toBeLessThan(10)
      expect(visibleIssues).toContain('5')
    })

    it('expands to show all issues when toggle button is clicked', async () => {
      const largeIssueList: Issue[] = Array.from({ length: 10 }, (_, i) => ({
        id: i + 1,
        thread_id: 99,
        issue_number: String(i + 1),
        status: i < 4 ? 'read' : 'unread',
        read_at: i < 4 ? '2026-03-08T00:00:00Z' : null,
        created_at: '2026-03-08T00:00:00Z',
      }))
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(largeIssueList))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-2')).toBeInTheDocument()
      })

      const showAllButton = screen.getByRole('button', { name: 'Show all 10' })
      fireEvent.click(showAllButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
      })

      expect(getIssueOrder()).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'])
    })

    it('collapses back to show fewer issues when toggle button is clicked again', async () => {
      const largeIssueList: Issue[] = Array.from({ length: 10 }, (_, i) => ({
        id: i + 1,
        thread_id: 99,
        issue_number: String(i + 1),
        status: i < 4 ? 'read' : 'unread',
        read_at: i < 4 ? '2026-03-08T00:00:00Z' : null,
        created_at: '2026-03-08T00:00:00Z',
      }))
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(largeIssueList))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-2')).toBeInTheDocument()
      })

      const showAllButton = screen.getByRole('button', { name: 'Show all 10' })
      fireEvent.click(showAllButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
      })

      const showFewerButton = screen.getByRole('button', { name: 'Show fewer' })
      fireEvent.click(showFewerButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Show all 10' })).toBeInTheDocument()
      })

      const visibleIssues = getIssueOrder()
      expect(visibleIssues.length).toBeLessThan(10)
    })

    it('shows last 3 issues when all issues are read', async () => {
      const allReadIssueList: Issue[] = Array.from({ length: 10 }, (_, i) => ({
        id: i + 1,
        thread_id: 99,
        issue_number: String(i + 1),
        status: 'read',
        read_at: '2026-03-08T00:00:00Z',
        created_at: '2026-03-08T00:00:00Z',
      }))
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(allReadIssueList))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-8')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: 'Show all 10' })).toBeInTheDocument()

      const visibleIssues = getIssueOrder()
      expect(visibleIssues).toEqual(['8', '9', '10'])
    })

    it('shows exactly 3 before + next unread + 3 after for large issue lists', async () => {
      const twentyIssues: Issue[] = Array.from({ length: 20 }, (_, i) => ({
        id: i + 1,
        thread_id: 99,
        issue_number: String(i + 1),
        status: i < 10 ? 'read' : 'unread',
        read_at: i < 10 ? '2026-03-08T00:00:00Z' : null,
        created_at: '2026-03-08T00:00:00Z',
      }))
      mockedIssuesApi.list.mockResolvedValue(buildListResponse(twentyIssues))

      render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-8')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: 'Show all 20' })).toBeInTheDocument()

      const visibleIssues = getIssueOrder()
      expect(visibleIssues.length).toBe(7)
      expect(visibleIssues).toEqual(['8', '9', '10', '11', '12', '13', '14'])
    })

  it('auto-expands when moving issue outside visible window', async () => {
    const twentyIssues: Issue[] = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1,
      thread_id: 99,
      issue_number: String(i + 1),
      status: i < 10 ? 'read' : 'unread',
      read_at: i < 10 ? '2026-03-08T00:00:00Z' : null,
      created_at: '2026-03-08T00:00:00Z',
    }))
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(twentyIssues))

    render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)

    await waitFor(() => {
      expect(screen.getByTestId('issue-pill-8')).toBeInTheDocument()
    })

    const showAllButton = screen.queryByRole('button', { name: 'Show all 20' })
    expect(showAllButton).toBeInTheDocument()

    // Move issue 14 (last visible) down - it should go outside the visible window
    // and trigger auto-expand
    const moveDownButton = screen.getByTestId('issue-move-down-14')
    fireEvent.click(moveDownButton)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
    })

    const allVisibleIssues = getIssueOrder()
    expect(allVisibleIssues.length).toBe(20)
  })

  it('shows dependency details and closes the dependency modal', async () => {
    mockedIssueDependenciesApi.listForThread.mockResolvedValue({
      thread_id: 99,
      issues: [
        {
          issue_id: 1,
          incoming: [
            {
              dependency_id: 10,
              source_issue_id: 2,
              source_thread_id: 20,
              source_thread_title: 'Before',
              source_issue_number: '2',
            },
          ],
          outgoing: [
            {
              dependency_id: 11,
              source_issue_id: 3,
              source_thread_id: 30,
              source_thread_title: 'After',
              source_issue_number: '3',
            },
          ],
        },
      ],
    })
    await renderIssueToggleList()
    fireEvent.click(screen.getByRole('button', { name: 'View dependencies for issue #1' }))
    expect(screen.getByText('Dependencies for Issue #1')).toBeInTheDocument()
    expect(screen.getByText(/Before #2/)).toBeInTheDocument()
    expect(screen.getByText(/After #3/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Close modal'))
    expect(screen.queryByText('Dependencies for Issue #1')).not.toBeInTheDocument()
  })

  it('handles empty and failed issue additions, including Enter submission', async () => {
    await renderIssueToggleList()
    const input = screen.getByTestId('issue-add-input')
    expect(screen.getByTestId('issue-add-button')).toBeDisabled()
    mockedIssuesApi.create.mockRejectedValueOnce(new Error('add failed'))
    fireEvent.change(input, { target: { value: '4-5' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(screen.getByText('add failed')).toBeInTheDocument())
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '4-5')
  })

  it('recovers after toggle and delete mutation failures', async () => {
    mockedIssuesApi.markRead.mockRejectedValueOnce(new Error('toggle failed'))
    mockedIssuesApi.list.mockResolvedValueOnce(buildListResponse()).mockResolvedValue(buildListResponse())
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-toggle-1'))
    await waitFor(() => expect(screen.getByText('toggle failed')).toBeInTheDocument())
    // A confirmed delete reports failures through the same inline action error
    // channel, since the confirmation dialog closes on confirm.
    mockedIssuesApi.delete.mockRejectedValueOnce(new Error('delete failed'))
    fireEvent.click(screen.getByTestId('issue-delete-2'))
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))
    await waitFor(() => expect(screen.getByText('delete failed')).toBeInTheDocument())
    expect(screen.queryByTestId('delete-issue-dialog')).not.toBeInTheDocument()
  })

  it('handles dependency fetch errors, no-op moves, and successful additions', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockedIssueDependenciesApi.listForThread.mockRejectedValue(new Error('dependency lookup failed'))
    mockedIssuesApi.create.mockResolvedValue(buildListResponse(BASE_ISSUES))
    await renderIssueToggleList()
    await waitFor(() => expect(errorSpy).toHaveBeenCalled())
    fireEvent.click(screen.getByTestId('issue-move-up-1'))
    fireEvent.click(screen.getByTestId('issue-move-down-3'))
    fireEvent.dragStart(screen.getByTestId('issue-toggle-1'), { dataTransfer: createDataTransfer() })
    fireEvent.drop(screen.getByTestId('issue-pill-1'), { dataTransfer: createDataTransfer() })
    fireEvent.change(screen.getByTestId('issue-add-input'), { target: { value: '4' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    await waitFor(() => expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '4'))
    errorSpy.mockRestore()
  })

  it('toggles both read states and tolerates an initial issue-load failure', async () => {
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-toggle-1'))
    await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(1))
    fireEvent.click(screen.getByTestId('issue-toggle-3'))
    await waitFor(() => expect(mockedIssuesApi.markUnread).toHaveBeenCalledWith(3))

    cleanup()
    mockedIssuesApi.list.mockRejectedValueOnce(new Error('initial load failed'))
    render(<IssueToggleList
        threadId={99}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />)
    await waitFor(() => expect(screen.queryByText('Loading issues…')).not.toBeInTheDocument())
  })

  it('uses the timeout focus fallback after rerendering', async () => {
    const originalRaf = window.requestAnimationFrame
    Object.defineProperty(window, 'requestAnimationFrame', { configurable: true, value: undefined })
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-move-down-1'))
    await waitFor(() => expect(screen.getByTestId('issue-move-down-1')).toHaveFocus())
    Object.defineProperty(window, 'requestAnimationFrame', { configurable: true, value: originalRaf })
  })

  it('calls onIssueChanged after a successful delete', async () => {
    const onIssueChanged = vi.fn()
    render(
      <IssueToggleList
        threadId={99}
        onIssueChanged={onIssueChanged}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('confirm-delete-issue'))

    await waitFor(() => expect(mockedIssuesApi.delete).toHaveBeenCalledWith(2))
    await waitFor(() => expect(onIssueChanged).toHaveBeenCalled())
  })

  it('calls onIssueChanged after a successful toggle', async () => {
    const onIssueChanged = vi.fn()
    render(
      <IssueToggleList
        threadId={99}
        onIssueChanged={onIssueChanged}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('issue-toggle-1'))

    await waitFor(() => expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(1))
    await waitFor(() => expect(onIssueChanged).toHaveBeenCalled())
  })

  it('does not call onIssueChanged when delete is cancelled', async () => {
    const onIssueChanged = vi.fn()
    render(
      <IssueToggleList
        threadId={99}
        onIssueChanged={onIssueChanged}
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('issue-delete-2'))
    expect(screen.getByTestId('delete-issue-dialog')).toBeInTheDocument()

    // Click the Cancel button in the dialog
    fireEvent.click(screen.getByText('Cancel'))

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(onIssueChanged).not.toHaveBeenCalled()
    expect(mockedIssuesApi.delete).not.toHaveBeenCalled()
  })
})

describe('IssueToggleList reorder mode (#2950)', () => {
  const NON_ASCENDING_ISSUES: Issue[] = [
    {
      id: 7,
      thread_id: 99,
      issue_number: '3',
      status: 'read',
      read_at: '2026-03-08T00:00:00Z',
      created_at: '2026-03-08T00:00:00Z',
    },
    {
      id: 8,
      thread_id: 99,
      issue_number: '1',
      status: 'unread',
      read_at: null,
      created_at: '2026-03-08T00:00:00Z',
    },
    {
      id: 9,
      thread_id: 99,
      issue_number: '2',
      status: 'unread',
      read_at: null,
      created_at: '2026-03-08T00:00:00Z',
    },
  ]

  function getReorderOrder(): Array<string | null> {
    return screen
      .getAllByTestId(/issue-reorder-row-/)
      .map((row) => row.getAttribute('data-issue-number'))
  }

  async function enterReorderMode() {
    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))
  }

  it('exposes an explicit, touch-reachable reorder control outside the drag affordance', async () => {
    await renderIssueToggleList()

    const toggle = screen.getByTestId('issue-reorder-toggle')
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveAccessibleName('Reorder issues')

    fireEvent.click(toggle)

    expect(screen.getByTestId('issue-reorder-toggle')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('issue-reorder-list')).toBeInTheDocument()
    expect(getReorderOrder()).toEqual(['1', '2', '3'])

    // The pill view is replaced, so the compact desktop-only arrow buttons
    // cannot be the only reorder path.
    expect(screen.queryByTestId('issue-pill-1')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Move issue #1 up')).toHaveAttribute(
      'data-move-control',
      'up-1',
    )
    expect(screen.getByLabelText('Move issue #1 down')).toHaveAttribute(
      'data-move-control',
      'down-1',
    )
  })

  it('shows the whole series in reorder mode even when the pill list is windowed', async () => {
    // Nine issues push the pill list into its collapsed visibility window.
    const manyIssues: Issue[] = Array.from({ length: 9 }, (_unused, index) => ({
      id: index + 1,
      thread_id: 99,
      issue_number: String(index + 1),
      status: 'unread' as const,
      read_at: null,
      created_at: '2026-03-08T00:00:00Z',
    }))
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(manyIssues))

    await renderIssueToggleList()

    expect(screen.getByText(/around your current position/i)).toBeInTheDocument()
    expect(screen.queryByTestId('issue-pill-9')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))

    expect(getReorderOrder()).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9'])
    expect(screen.queryByText(/around your current position/i)).not.toBeInTheDocument()
  })

  it('persists the visible order through the existing reorder contract', async () => {
    await enterReorderMode()

    fireEvent.click(screen.getByTestId('issue-move-down-1'))

    expect(getReorderOrder()).toEqual(['2', '1', '3'])
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [2, 1, 3])
    expect(screen.getByText('Moved issue #1 down.')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByTestId('issue-move-down-1')).toHaveFocus()
    })
  })

  it('disables the boundary move controls without dropping them from the list', async () => {
    await enterReorderMode()

    expect(screen.getByTestId('issue-move-up-1')).toBeDisabled()
    expect(screen.getByTestId('issue-move-down-3')).toBeDisabled()
    expect(screen.getByTestId('issue-move-down-1')).not.toBeDisabled()
    expect(screen.getByTestId('issue-move-up-3')).not.toBeDisabled()

    fireEvent.click(screen.getByTestId('issue-move-up-1'))
    fireEvent.click(screen.getByTestId('issue-move-down-3'))

    expect(mockedIssuesApi.reorder).not.toHaveBeenCalled()
    expect(getReorderOrder()).toEqual(['1', '2', '3'])
  })

  it('keeps a deliberately non-numeric order instead of re-sorting it back', async () => {
    mockedIssuesApi.list.mockResolvedValue(buildListResponse(NON_ASCENDING_ISSUES))

    await renderIssueToggleList()
    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))

    expect(getReorderOrder()).toEqual(['3', '1', '2'])

    fireEvent.click(screen.getByTestId('issue-move-down-7'))

    expect(getReorderOrder()).toEqual(['1', '3', '2'])
    expect(mockedIssuesApi.reorder).toHaveBeenCalledWith(99, [8, 7, 9])
  })

  it('returns to the pill view when reordering is finished', async () => {
    await enterReorderMode()

    fireEvent.click(screen.getByTestId('issue-reorder-toggle'))

    expect(screen.queryByTestId('issue-reorder-list')).not.toBeInTheDocument()
    expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
    expect(screen.getByTestId('issue-reorder-toggle')).toHaveAccessibleName('Reorder issues')
  })
})

describe('IssueToggleList deferred mode (#3267)', () => {
  async function renderDeferred() {
    const ref = createRef<IssueToggleListHandle>()
    render(
      <IssueToggleList
        ref={ref}
        threadId={99}
        deferred
        issuesApi={mockedIssuesApi}
        dependenciesApi={mockedIssueDependenciesApi}
      />,
    )
    await waitFor(() => {
      expect(screen.getAllByTestId(/issue-pill-/).length).toBeGreaterThan(0)
    })
    return ref
  }

  it('queues Add without calling the API until flush', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')
    fireEvent.change(input, { target: { value: '4-5' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    // No API call yet — the create is queued as a draft.
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    // Pending create is visible in the UI.
    expect(screen.getByTestId('pending-creates')).toHaveTextContent('4-5')
    expect(ref.current?.hasPendingMutations()).toBe(true)

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.create).toHaveBeenCalledWith(99, '4-5')
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('discards queued mutations on unmount without flushing', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')
    fireEvent.change(input, { target: { value: '4-5' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    expect(ref.current?.hasPendingMutations()).toBe(true)

    // Unmount without flushing (dialog X/close).
    cleanup()
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
  })

  it('queues toggle and delete without flushing in deferred mode', async () => {
    const ref = await renderDeferred()
    fireEvent.click(screen.getByTestId('issue-toggle-1'))
    expect(mockedIssuesApi.markRead).not.toHaveBeenCalled()
    expect(mockedIssuesApi.markUnread).not.toHaveBeenCalled()

    await act(async () => {
      await ref.current?.flush()
    })
    expect(mockedIssuesApi.markRead).toHaveBeenCalledWith(1)
  })

  it('queues multiple creates and flushes all of them', async () => {
    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    // Add first issue range
    fireEvent.change(input, { target: { value: '7' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    expect(screen.getByTestId('pending-creates')).toHaveTextContent('7')

    // Add second issue range
    fireEvent.change(input, { target: { value: 'Annual 2' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    expect(screen.getByTestId('pending-creates')).toHaveTextContent('Annual 2')

    // Add third issue range
    fireEvent.change(input, { target: { value: '10-12' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    expect(screen.getByTestId('pending-creates')).toHaveTextContent('10-12')

    // Verify all three are queued
    expect(mockedIssuesApi.create).not.toHaveBeenCalled()
    expect(ref.current?.hasPendingMutations()).toBe(true)

    // Flush all
    await act(async () => {
      await ref.current?.flush()
    })

    // Verify all three create calls were made
    expect(mockedIssuesApi.create).toHaveBeenCalledTimes(3)
    expect(mockedIssuesApi.create).toHaveBeenNthCalledWith(1, 99, '7')
    expect(mockedIssuesApi.create).toHaveBeenNthCalledWith(2, 99, 'Annual 2')
    expect(mockedIssuesApi.create).toHaveBeenNthCalledWith(3, 99, '10-12')
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('handles server errors for subsequent creates in a batch', async () => {
    // Simulate server accepting first create but rejecting subsequent ones
    mockedIssuesApi.create
      .mockResolvedValueOnce(buildListResponse([{ id: 10, thread_id: 99, issue_number: '7', status: 'unread', read_at: null, created_at: '2026-03-08T00:00:00Z' }]))
      .mockRejectedValueOnce(new Error('Issue number already exists'))
      .mockRejectedValueOnce(new Error('Issue number already exists'))

    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')

    fireEvent.change(input, { target: { value: '7' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    fireEvent.change(input, { target: { value: 'Annual 2' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))
    fireEvent.change(input, { target: { value: '10-12' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    await act(async () => {
      await ref.current?.flush()
    })

    // All three create calls should be attempted
    expect(mockedIssuesApi.create).toHaveBeenCalledTimes(3)
    // Error should be surfaced for the failed ones
    expect(screen.getByText('Issue number already exists')).toBeInTheDocument()
    expect(ref.current?.hasPendingMutations()).toBe(false)
  })

  it('re-reads server order after a create so the base list is not appended blindly', async () => {
    // The server inserts an ordinary numeric issue at its natural position
    // rather than appending it, so a mid-series create must not be assumed to
    // land at the end of the list.
    mockedIssuesApi.create.mockResolvedValue(
      buildListResponse([
        {
          id: 4,
          thread_id: 99,
          issue_number: '2',
          status: 'unread',
          read_at: null,
          created_at: '2026-03-08T00:00:00Z',
        },
      ]),
    )
    mockedIssuesApi.list
      .mockResolvedValueOnce(buildListResponse())
      .mockResolvedValue(
        buildListResponse([
          {
            id: 2,
            thread_id: 99,
            issue_number: '2',
            status: 'unread',
            read_at: null,
            created_at: '2026-03-08T00:00:00Z',
          },
          {
            id: 4,
            thread_id: 99,
            issue_number: '2b',
            status: 'unread',
            read_at: null,
            created_at: '2026-03-08T00:00:00Z',
          },
          {
            id: 1,
            thread_id: 99,
            issue_number: '1',
            status: 'unread',
            read_at: null,
            created_at: '2026-03-08T00:00:00Z',
          },
          {
            id: 3,
            thread_id: 99,
            issue_number: '3',
            status: 'read',
            read_at: null,
            created_at: '2026-03-08T00:00:00Z',
          },
        ]),
      )

    const ref = await renderDeferred()
    const input = screen.getByTestId('issue-add-input')
    fireEvent.change(input, { target: { value: '2b' } })
    fireEvent.click(screen.getByTestId('issue-add-button'))

    await act(async () => {
      await ref.current?.flush()
    })

    // The re-read happened rather than trusting the create response position.
    expect(mockedIssuesApi.list).toHaveBeenCalledTimes(2)
    // Server order wins: #2b sits after #2, not at the end of the list.
    expect(getIssueOrder()).toEqual(['2', '2b', '1', '3'])
  })
})
})
