import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { ToastProvider } from '../contexts/ToastProvider'
import {
  useCreateThread,
  useDeleteThread,
  useReactivateThread,
  useUpdateThread,
} from '../hooks/useThread'
import {
  useMoveToBack,
  useMoveToFront,
  useMoveToPosition,
  useQueueThreads,
  useShuffleQueue,
} from '../hooks/useQueue'
import { useSession } from '../hooks/useSession'
import { useQueueBlockingInfo } from '../hooks/useQueueBlockingInfo'
import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { threadsApi } from '../services/api-threads'
import { issueDependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { useBugReportRestore } from '../contexts/useBugReportRestore'
import type { IssueListResponse, ThreadListItem } from '../types'

vi.mock('../hooks/useThread', () => ({
  useExcludeThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useCreateThread: vi.fn(),
  useUpdateThread: vi.fn(),
  useDeleteThread: vi.fn(),
  useReactivateThread: vi.fn(),
}))

vi.mock('../hooks/useQueue', () => ({
  useExcludedThreads: vi.fn(() => ({ threads: [], isPending: false, isError: false })),
  useRestoreThread: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })),
  useMoveToFront: vi.fn(),
  useMoveToBack: vi.fn(),
  useMoveToPosition: vi.fn(),
  useQueueThreads: vi.fn(),
  useShuffleQueue: vi.fn(),
}))

vi.mock('../hooks/useSession', () => ({
  useSession: vi.fn(),
}))

vi.mock('../hooks/useSnooze', () => ({
  useSnooze: vi.fn(),
  useUnsnooze: vi.fn(),
}))

vi.mock('../hooks/useQueueBlockingInfo', () => ({
  useQueueBlockingInfo: vi.fn(() => ({})),
}))

vi.mock('../services/api-threads', () => ({
  threadsApi: {
    setPending: vi.fn(),
  },
}))

vi.mock('../services/api-dependencies', () => ({
  dependenciesApi: {
    listBlockedThreadIds: vi.fn().mockResolvedValue([]),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
  issueDependenciesApi: {
    listForThread: vi.fn().mockResolvedValue({ issues: [] }),
  },
}))

// The queue's batched crossover query is a separate service module; without this
// stub the rendered page issues real requests and logs network errors.
vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    listForThreads: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn().mockResolvedValue({ issues: [] }),
    markRead: vi.fn().mockResolvedValue(undefined),
    markUnread: vi.fn().mockResolvedValue(undefined),
    bulkMarkRead: vi.fn().mockResolvedValue(undefined),
    bulkMarkUnread: vi.fn().mockResolvedValue(undefined),
    migrateThread: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: vi.fn(),
}))

// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseQueueThreads = vi.mocked(useQueueThreads) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseCreateThread = vi.mocked(useCreateThread) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseUpdateThread = vi.mocked(useUpdateThread) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseDeleteThread = vi.mocked(useDeleteThread) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseReactivateThread = vi.mocked(useReactivateThread) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseMoveToFront = vi.mocked(useMoveToFront) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseMoveToBack = vi.mocked(useMoveToBack) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseMoveToPosition = vi.mocked(useMoveToPosition) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseShuffleQueue = vi.mocked(useShuffleQueue) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseSession = vi.mocked(useSession) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseBugReportRestore = vi.mocked(useBugReportRestore) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedIssuesApi = vi.mocked(issuesApi) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedListForThread = vi.mocked(issueDependenciesApi).listForThread as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedThreadsApi = vi.mocked(threadsApi) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseSnooze = vi.mocked(useSnooze) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseUnsnooze = vi.mocked(useUnsnooze) as any
// SAFETY: vi.mocked returns strict hook types; cast to any so tests can stub partial returns
const mockedUseQueueBlockingInfo = vi.mocked(useQueueBlockingInfo) as any

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const MIGRATED_THREAD: ThreadListItem = {
  id: 1,
  title: 'Saga',
  format: 'Comic',
  status: 'active',
  queue_position: 1,
  issues_remaining: 5,
  total_issues: 6,
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  last_activity_at: null,
}

const UNMIGRATED_THREAD: ThreadListItem = {
  id: 7,
  title: 'Descender',
  format: 'Comic',
  status: 'active',
  queue_position: 1,
  issues_remaining: 3,
  total_issues: null,
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-03-08T00:00:00Z',
  last_activity_at: null,
}

function renderQueue() {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage />
      </ToastProvider>
    </BrowserRouter>,
  )
}

async function openEditSeries(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getAllByRole('button', { name: /series actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /edit series/i }))
  expect(screen.getByRole('heading', { name: /edit series/i })).toBeInTheDocument()
}

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
  mockedUseQueueThreads.mockReturnValue({
    data: [MIGRATED_THREAD],
    isPending: false,
    isError: false,
    nextPageToken: null,
    loadMore: vi.fn(),
    refetch: vi.fn(),
  })
  mockedUseCreateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseDeleteThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseReactivateThread.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToFront.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToBack.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseMoveToPosition.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseShuffleQueue.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseSession.mockReturnValue({
    data: { snoozed_threads: [], skipped_thread_ids: [], skipped_threads: [] },
    refetch: vi.fn(),
  })
  mockedUseSnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseUnsnooze.mockReturnValue({ mutate: vi.fn(), isPending: false })
  mockedUseBugReportRestore.mockReturnValue({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: vi.fn(),
  })
  mockedUseQueueBlockingInfo.mockReturnValue({})
  mockedListForThread.mockResolvedValue({ issues: [] })
  // SAFETY: full response shape satisfies RollResponse; cast bypasses strict mock typing
  mockedThreadsApi.setPending.mockResolvedValue({} as never)
})

describe('Edit Series loading gate (#3443)', () => {
  it('keeps Save disabled while issues load after a reload plus search, then saves with one click', async () => {
    const issuesRequest = deferred<IssueListResponse>()
    mockedIssuesApi.list.mockReturnValue(issuesRequest.promise)
    const update = vi.fn().mockResolvedValue({})
    mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })

    const user = userEvent.setup()
    renderQueue()

    // Repro shape: search immediately after a fresh /queue load, then edit.
    await user.type(screen.getByPlaceholderText('Search...'), 'Saga')
    await openEditSeries(user)

    // While the issue list request is in flight the Save button is disabled
    // and explains why; the first click cannot be silently dropped.
    const loadingButton = screen.getByRole('button', { name: /loading issues/i })
    expect(loadingButton).toBeDisabled()
    expect(screen.getAllByText(/loading issues/i).length).toBeGreaterThan(0)
    expect(update).not.toHaveBeenCalled()

    await act(async () => {
      issuesRequest.resolve({
        issues: [
          {
            id: 11,
            issue_number: '1',
            status: 'unread',
            thread_id: 1,
            read_at: null,
            created_at: '2026-01-01T00:00:00Z',
          },
          {
            id: 12,
            issue_number: '2',
            status: 'read',
            thread_id: 1,
            read_at: '2026-01-02T00:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
        total_count: 2,
        page_size: 100,
        next_page_token: null,
      })
    })

    const saveButton = await screen.findByRole('button', { name: /save changes/i })
    await waitFor(() => expect(saveButton).toBeEnabled())

    // Exactly one click sends exactly one PUT.
    await user.click(saveButton)
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update).toHaveBeenCalledWith({
      id: 1,
      data: expect.objectContaining({ title: 'Saga', format: 'Comic' }),
    })
  })

  it('enables Save immediately for an unmigrated thread so it can never deadlock', async () => {
    mockedUseQueueThreads.mockReturnValue({
      data: [UNMIGRATED_THREAD],
      isPending: false,
      isError: false,
      nextPageToken: null,
      loadMore: vi.fn(),
      refetch: vi.fn(),
    })
    const update = vi.fn().mockResolvedValue({})
    mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })

    const user = userEvent.setup()
    renderQueue()
    await openEditSeries(user)

    const saveButton = screen.getByRole('button', { name: /save changes/i })
    expect(saveButton).toBeEnabled()
    expect(saveButton).toHaveTextContent('Save Changes')
    expect(mockedIssuesApi.list).not.toHaveBeenCalled()

    await user.click(saveButton)
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  })

  it('shows an error with retry when the issue load fails, then recovers on retry', async () => {
    const failingRequest = deferred<IssueListResponse>()
    mockedIssuesApi.list.mockReturnValueOnce(failingRequest.promise)
    mockedIssuesApi.list.mockReturnValue(
      Promise.resolve({
        issues: [
          {
            id: 11,
            issue_number: '1',
            status: 'unread',
            thread_id: 1,
            read_at: null,
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
        total_count: 1,
        page_size: 100,
        next_page_token: null,
      }),
    )
    const update = vi.fn().mockResolvedValue({})
    mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })

    const user = userEvent.setup()
    renderQueue()
    await openEditSeries(user)

    // While the issue list request is in flight the Save button is disabled
    const loadingButton = screen.getByRole('button', { name: /loading issues/i })
    expect(loadingButton).toBeDisabled()
    expect(update).not.toHaveBeenCalled()

    // Fail the load; the Issues area names the failure and offers recovery
    // instead of going blank, and the dialog is never stuck.
    await act(async () => {
      failingRequest.reject(new Error('load failed'))
    })

    expect(await screen.findByText(/could not load issues/i)).toBeInTheDocument()
    const retryButton = screen.getByRole('button', { name: /retry/i })
    const saveButton = await screen.findByRole('button', { name: /save changes/i })
    await waitFor(() => expect(saveButton).toBeEnabled())

    await user.click(retryButton)
    await waitFor(() => expect(screen.getByTestId('issue-pill-11')).toBeInTheDocument())

    await user.click(saveButton)
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  })

  it('shows an explicit empty state when a migrated thread has no issues', async () => {
    mockedIssuesApi.list.mockResolvedValue({
      issues: [],
      total_count: 0,
      page_size: 100,
      next_page_token: null,
    })
    const update = vi.fn().mockResolvedValue({})
    mockedUseUpdateThread.mockReturnValue({ mutate: update, isPending: false })

    const user = userEvent.setup()
    renderQueue()
    await openEditSeries(user)

    expect(await screen.findByText(/no issues yet/i)).toBeInTheDocument()
    const saveButton = await screen.findByRole('button', { name: /save changes/i })
    await waitFor(() => expect(saveButton).toBeEnabled())

    await user.click(saveButton)
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
  })
})
