import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import { issuesApi } from '../services/api-issues'
import type { Issue, IssueListResponse } from '../types'

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    move: vi.fn(),
    reorder: vi.fn(),
    delete: vi.fn(),
    migrateThread: vi.fn(),
  },
}))

const mockedIssuesApi = vi.mocked(issuesApi, { deep: true })

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
  return {
    dropEffect: 'move',
    effectAllowed: 'move',
    files: [] as unknown as FileList,
    items: [] as unknown as DataTransferItemList,
    types: [],
    clearData: vi.fn(),
    getData: vi.fn(),
    setData: vi.fn(),
    setDragImage: vi.fn(),
  } as unknown as DataTransfer
}

function getIssueOrder(): Array<string | null> {
  return screen.getAllByTestId(/issue-pill-/).map((pill) => pill.getAttribute('data-issue-number'))
}

async function renderIssueToggleList() {
  render(<IssueToggleList threadId={99} />)
  await waitFor(() => {
    expect(screen.getByTestId('issue-pill-1')).toBeInTheDocument()
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
})

describe('IssueToggleList', () => {
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
    const confirmMock = vi.mocked(window.confirm)
    confirmMock.mockReturnValue(true)
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
    const confirmMock = vi.mocked(window.confirm)
    confirmMock.mockReturnValue(true)

    const deleteRequest = createDeferred<void>()
    mockedIssuesApi.delete.mockReturnValueOnce(deleteRequest.promise)

    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))

    expect(confirmMock).toHaveBeenCalledWith('Delete issue #2?')
    expect(mockedIssuesApi.delete).toHaveBeenCalledWith(2)
    expect(getIssueOrder()).toEqual(['1', '3'])

    await act(async () => {
      deleteRequest.resolve()
      await deleteRequest.promise
    })
  })

  it('does not delete an issue when confirmation is cancelled', async () => {
    const confirmMock = vi.mocked(window.confirm)
    confirmMock.mockReturnValue(false)

    await renderIssueToggleList()

    fireEvent.click(screen.getByTestId('issue-delete-2'))

    expect(confirmMock).toHaveBeenCalledWith('Delete issue #2?')
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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

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

      render(<IssueToggleList threadId={99} />)

      await waitFor(() => {
        expect(screen.getByTestId('issue-pill-8')).toBeInTheDocument()
      })

      const showAllButton = screen.queryByRole('button', { name: 'Show all 20' })
      expect(showAllButton).toBeInTheDocument()

      const moveDownButton = screen.getByTestId('issue-move-down-8')
      fireEvent.click(moveDownButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
      })

      const allVisibleIssues = getIssueOrder()
      expect(allVisibleIssues.length).toBe(20)
    })
  })
})
