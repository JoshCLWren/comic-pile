import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueToggleList } from '../pages/QueuePage'
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

function buildListResponse(issues: Issue[] = BASE_ISSUES): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
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
})
