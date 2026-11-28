import { forwardRef, useImperativeHandle } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../contexts/ToastProvider'
import { useUpdateThread } from '../hooks/useThread'
import { queryClient } from '../query/queryClient'
import ThreadDetailView from '../pages/ThreadDetailView'
import type { IssueToggleListHandle } from '../pages/QueuePage/IssueToggleList'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { tagsApi } from '../services/api-tags'
import { threadsApi } from '../services/api-threads'

/**
 * #5952: after Save Changes completes, Edit Series must not ask to discard a
 * saved draft. For a migrated thread the issue count is server-derived, so a
 * completed issue toggle changes `thread.issues_remaining` on refetch while
 * the draft still holds the count captured when the dialog opened. The dialog
 * stays mounted when Save left an Undo point, which is when the stale count
 * used to make a clean, saved draft look dirty.
 *
 * The issue list child is mocked only to expose an Undo point and to signal a
 * persisted toggle; the API layer and the real page dialog are exercised.
 */

const routeParams = { id: '1' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => routeParams }
})

vi.mock('../hooks/useThread', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})

vi.mock('../services/api-threads', () => ({ threadsApi: { get: vi.fn(), update: vi.fn() } }))

vi.mock('../services/api-dependencies', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-dependencies')>()
  return {
    ...actual,
    dependenciesApi: {
      getIssueDependencies: vi.fn().mockResolvedValue({ incoming: [], outgoing: [] }),
      getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    },
  }
})

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
    create: vi.fn(),
    previewCreate: vi.fn(),
    markRead: vi.fn(),
    markUnread: vi.fn(),
    delete: vi.fn(),
    reorder: vi.fn(),
  },
}))

vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      list: vi.fn().mockResolvedValue({ tags: [] }),
      effectiveForIssue: vi.fn().mockResolvedValue({
        target_type: 'Issue', target_id: 0, direct_tags: [], effective_tags: [],
      }),
      effectiveForThread: vi.fn().mockResolvedValue({
        target_type: 'Thread', target_id: 1, direct_tags: [], effective_tags: [],
      }),
      effectiveForPlan: vi.fn().mockResolvedValue({
        target_type: 'ContinuityPlan', target_id: 0, direct_tags: [], effective_tags: [],
      }),
      threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    },
  }
})

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: forwardRef<IssueToggleListHandle, { onIssueChanged?: () => void }>(
    function MockIssueToggleList(props, ref) {
      useImperativeHandle(ref, () => ({
        flush: async () => undefined,
        hasPendingMutations: () => false,
        // Save keeps the dialog mounted while its Undo bar is live (#4654).
        hasUndoPoint: () => true,
      }))
      return (
        <button
          type="button"
          data-testid="mock-toggle-issue"
          onClick={() => props.onIssueChanged?.()}
        >
          Toggle issue #2
        </button>
      )
    },
  ),
}))

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mutateMock = vi.fn()

// SAFETY: fixtures supply only the fields this page reads. A tracked series
// starts at 5 remaining; a persisted toggle moves the server value to 4.
const OPEN_THREAD = {
  id: 1,
  title: 'Saga',
  format: 'Comics',
  issues_remaining: 5,
  queue_position: 1,
  status: 'active',
  total_issues: 10,
  next_unread_issue_number: '6',
  notes: 'original note',
}
const SAVED_THREAD = { ...OPEN_THREAD, issues_remaining: 4, next_unread_issue_number: '7' }

let serverThread: typeof OPEN_THREAD

beforeEach(() => {
  queryClient.clear()
  routeParams.id = '1'
  serverThread = OPEN_THREAD
  mutateMock.mockReset()
  mutateMock.mockResolvedValue(SAVED_THREAD)
  mockedUseUpdateThread.mockReturnValue({ mutate: mutateMock, isPending: false } as never)
  mockedThreadsApiGet.mockReset()
  mockedThreadsApiGet.mockImplementation(async () => serverThread as never)
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 1, thread_id: 1, issue_number: '6', status: 'unread', read_at: null, created_at: 'now' }],
    next_page_token: null,
    total_count: 1,
    page_size: 100,
  })
  vi.mocked(dependenciesApi.getConnectedThreads).mockResolvedValue({ thread_id: 1, connected_threads: [] })
  vi.mocked(tagsApi.threadIssuesEffective).mockResolvedValue({ thread_id: 1, issues: [] })
})

function renderPage() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ThreadDetailView />
      </ToastProvider>
    </MemoryRouter>,
  )
}

async function openEditDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(await screen.findByLabelText('Notes')).toBeVisible()
}

describe('Thread detail Edit Series saved-draft dirty check (#5952)', () => {
  it('does not prompt to discard after a completed save when a toggle changed the server issue count', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    await openEditDialog(user)
    // The toggle persisted server-side; the live thread refetches the new
    // count while the draft still holds the count captured on open.
    serverThread = SAVED_THREAD
    await user.click(screen.getByTestId('mock-toggle-issue'))
    await waitFor(() => {
      expect(screen.getByText((_content, element) =>
        element?.tagName === 'P' && element.textContent === '6 of 10 issues read')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Save Changes' }))
    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1))
    // Undo point keeps the dialog open after Save; only the Undo bar remains.
    expect(screen.getByRole('dialog', { name: 'Edit Series' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    expect(screen.queryByRole('dialog', { name: 'Discard changes?' })).not.toBeInTheDocument()
  })

  it('still prompts for a genuinely unsaved draft after a migrated thread save', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())

    await openEditDialog(user)
    await user.type(screen.getByDisplayValue('Saga'), ' renamed')

    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    const prompt = screen.getByRole('dialog', { name: 'Discard changes?' })
    expect(prompt).toBeInTheDocument()
    expect(mutateMock).not.toHaveBeenCalled()

    await user.click(within(prompt).getByRole('button', { name: 'Keep editing' }))
    expect(screen.getByRole('dialog', { name: 'Edit Series' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('Saga renamed')).toBeInTheDocument()
  })
})
