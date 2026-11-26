import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import ThreadDetailView from '../pages/ThreadDetailView'
import { ToastProvider } from '../contexts/ToastProvider'
import { useUpdateThread } from '../hooks/useThread'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api-dependencies'
import { issuesApi } from '../services/api-issues'
import { undoApi } from '../services/api-undo'
import { tagsApi } from '../services/api-tags'

const routeParams = { id: '1' }

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useParams: () => routeParams }
})
vi.mock('../hooks/useThread', async () => {
  const actual = await vi.importActual<typeof import('../hooks/useThread')>('../hooks/useThread')
  return { ...actual, useUpdateThread: vi.fn() }
})
vi.mock('../services/api-threads', () => ({ threadsApi: { get: vi.fn() } }))
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
    list: vi.fn(), create: vi.fn(), previewCreate: vi.fn(), previewDelete: vi.fn(),
    previewReorder: vi.fn(), markRead: vi.fn(), markUnread: vi.fn(), delete: vi.fn(), reorder: vi.fn(),
  },
}))
vi.mock('../services/api-undo', () => ({ undoApi: { undo: vi.fn().mockResolvedValue(undefined) } }))
vi.mock('../services/api-tags', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-tags')>()
  return {
    ...actual,
    tagsApi: {
      list: vi.fn().mockResolvedValue({ tags: [] }),
      effectiveForIssue: vi.fn().mockResolvedValue({ target_type: 'Issue', target_id: 0, direct_tags: [], effective_tags: [] }),
      effectiveForThread: vi.fn().mockResolvedValue({ target_type: 'Thread', target_id: 1, direct_tags: [], effective_tags: [] }),
      effectiveForPlan: vi.fn().mockResolvedValue({ target_type: 'ContinuityPlan', target_id: 0, direct_tags: [], effective_tags: [] }),
      threadIssuesEffective: vi.fn().mockResolvedValue({ thread_id: 1, issues: [] }),
    },
  }
})

const mockedUseUpdateThread = vi.mocked(useUpdateThread)
const mockedThreadsApiGet = vi.mocked(threadsApi.get)
const mockedIssuesApiList = vi.mocked(issuesApi.list)
const mockedPreviewDelete = vi.mocked(issuesApi.previewDelete)

beforeEach(() => {
  routeParams.id = '1'
  mockedUseUpdateThread.mockReturnValue({ mutate: vi.fn().mockResolvedValue({}), isPending: false } as never)
  mockedThreadsApiGet.mockReset()
  mockedThreadsApiGet.mockResolvedValue({
    id: 1, title: 'Saga', format: 'Comics', issues_remaining: 5, queue_position: 1,
    status: 'active', total_issues: 10, next_unread_issue_number: '3', notes: null,
  } as never)
  mockedIssuesApiList.mockReset()
  mockedIssuesApiList.mockResolvedValue({
    issues: [{ id: 1, thread_id: 1, issue_number: '4', status: 'unread', read_at: null, created_at: 'now' }],
    next_page_token: null, total_count: 1, page_size: 100,
  })
  mockedPreviewDelete.mockReset()
  mockedPreviewDelete.mockResolvedValue({
    thread_id: 1, thread_title: 'Saga', requested_strategy: 'safe_default',
    default_outcome: { strategy: 'safe_default', can_commit: true, preserves_existing_relative_order: true, before: [], after: [], added_issue_numbers: [], graph: { status: 'ok', cycles: [] }, conflict_message: null },
    numeric_resort_outcome: null,
  } as never)
})

function renderPage() {
  return render(<MemoryRouter><ToastProvider><ThreadDetailView /></ToastProvider></MemoryRouter>)
}

it('#5864: closing Edit after a staged issue removal asks before discarding', async () => {
  const user = userEvent.setup()
  renderPage()
  await waitFor(() => expect(screen.getByText('Saga')).toBeInTheDocument())
  await user.click(screen.getByRole('button', { name: 'Edit' }))
  expect(await screen.findByLabelText('Notes')).toBeVisible()
  await user.click(await screen.findByTestId('issue-delete-1'))
  await screen.findByTestId('delete-issue-dialog')
  await user.click(screen.getByTestId('confirm-delete-issue'))
  await screen.findByTestId('edit-series-structure-preview-modal')
  await user.click(screen.getByTestId('confirm-structure-preview'))
  await user.click(screen.getByRole('button', { name: 'Close modal' }))
  const prompt = await screen.findByRole('dialog', { name: 'Discard changes?' })
  expect(prompt).toBeInTheDocument()
})
