import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DependencyBuilder from '../components/DependencyBuilder'
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import { ToastProvider } from '../contexts/ToastProvider'
import type { Issue, IssueListResponse, Thread } from '../types'

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

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
  return {
    ...actual,
    dependenciesApi: {
      listBlockedThreadIds: vi.fn(),
      listThreadDependencies: vi.fn(),
      getIssueDependencies: vi.fn(),
      getBlockingInfo: vi.fn(),
      createDependency: vi.fn(),
      deleteDependency: vi.fn(),
      updateDependency: vi.fn(),
    },
    threadsApi: {
      list: vi.fn(),
      setPending: vi.fn(),
    },
  }
})

const mockedIssuesApi = vi.mocked(issuesApi, { deep: true })
const mockedDependenciesApi = vi.mocked(dependenciesApi, { deep: true })
const mockedThreadsApi = vi.mocked(threadsApi, { deep: true })

function makeThread(overrides: Partial<Thread> & { id: number; title: string }): Thread {
  return {
    format: 'comic',
    status: 'active',
    issues_remaining: 10,
    total_issues: 10,
    queue_position: 1,
    notes: null,
    collection_id: null,
    reading_progress: null,
    next_unread_issue_id: null,
    next_unread_issue_number: '1',
    is_blocked: false,
    blocking_reasons: [],
    ...overrides,
  } as Thread
}

const TARGET_THREAD = makeThread({ id: 1, title: 'Target Thread', queue_position: 1 })
const PREREQ_THREAD = makeThread({
  id: 2,
  title: 'Prereq Thread',
  queue_position: 2,
  issues_remaining: 5,
  total_issues: 5,
})

function makeIssue(overrides: Partial<Issue> & { id: number; thread_id: number }): Issue {
  return {
    issue_number: String(overrides.id),
    status: 'unread',
    read_at: null,
    created_at: '2026-04-22T00:00:00Z',
    ...overrides,
  } as Issue
}

function buildListResponse(
  issues: Issue[],
  nextPageToken: string | null = null
): IssueListResponse {
  return {
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: nextPageToken,
  }
}

function renderBuilder() {
  return render(
    <ToastProvider>
      <DependencyBuilder thread={TARGET_THREAD} isOpen onClose={() => {}} />
    </ToastProvider>
  )
}

async function selectPrerequisiteThread() {
  const user = userEvent.setup()
  const searchInput = screen.getByPlaceholderText(/Type at least 2 characters/i)
  await user.type(searchInput, 'Pre')
  const candidate = await screen.findByRole('button', { name: /Prereq Thread/i })
  await user.click(candidate)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedDependenciesApi.listThreadDependencies.mockResolvedValue({
    blocking: [],
    blocked_by: [],
  })
  mockedDependenciesApi.listBlockedThreadIds.mockResolvedValue([])
  mockedThreadsApi.list.mockResolvedValue({
    threads: [PREREQ_THREAD],
    next_page_token: null,
  })
})

describe('DependencyBuilder issue selection', () => {
  it('fetches source and target issues with status=unread filter', async () => {
    mockedIssuesApi.list.mockResolvedValue(buildListResponse([]))
    renderBuilder()

    await selectPrerequisiteThread()

    await waitFor(() => {
      expect(mockedIssuesApi.list).toHaveBeenCalled()
    })

    for (const call of mockedIssuesApi.list.mock.calls) {
      const params = call[1]
      expect(params).toMatchObject({ status: 'unread', page_size: 100 })
    }
  })

  it('follows pagination tokens until all unread issues are loaded', async () => {
    const prereqPage1 = [
      makeIssue({ id: 201, thread_id: PREREQ_THREAD.id, issue_number: '1' }),
      makeIssue({ id: 202, thread_id: PREREQ_THREAD.id, issue_number: '2' }),
    ]
    const prereqPage2 = [
      makeIssue({ id: 203, thread_id: PREREQ_THREAD.id, issue_number: '3' }),
    ]
    const targetIssues = [
      makeIssue({ id: 101, thread_id: TARGET_THREAD.id, issue_number: '1' }),
    ]

    mockedIssuesApi.list.mockImplementation(
      async (threadId: number, params?: { page_token?: string }) => {
        if (threadId === PREREQ_THREAD.id) {
          return params?.page_token
            ? buildListResponse(prereqPage2)
            : buildListResponse(prereqPage1, 'page-2')
        }
        return buildListResponse(targetIssues)
      }
    )

    renderBuilder()
    await selectPrerequisiteThread()

    const sourceSelect = await screen.findByLabelText(/Prerequisite issue/i)
    await waitFor(() => {
      // 3 unread issues + 1 "Select an issue" placeholder
      expect(sourceSelect.querySelectorAll('option').length).toBe(4)
    })

    const prereqCalls = mockedIssuesApi.list.mock.calls.filter((c) => c[0] === PREREQ_THREAD.id)
    expect(prereqCalls).toHaveLength(2)
    expect(prereqCalls[1][1]).toMatchObject({ page_token: 'page-2' })
  })

  it('does not request read issues and does not render them', async () => {
    const unreadIssue = makeIssue({
      id: 201,
      thread_id: PREREQ_THREAD.id,
      issue_number: '1',
    })

    mockedIssuesApi.list.mockImplementation(async (threadId: number) => {
      if (threadId === PREREQ_THREAD.id) {
        return buildListResponse([unreadIssue])
      }
      return buildListResponse([
        makeIssue({ id: 101, thread_id: TARGET_THREAD.id, issue_number: '1' }),
      ])
    })

    renderBuilder()
    await selectPrerequisiteThread()

    const sourceSelect = await screen.findByLabelText(/Prerequisite issue/i)
    await waitFor(() => {
      expect(sourceSelect.querySelectorAll('option').length).toBeGreaterThan(1)
    })

    const optionLabels = Array.from(sourceSelect.querySelectorAll('option')).map(
      (o) => o.textContent ?? ''
    )
    expect(optionLabels.some((label) => label.includes('#1'))).toBe(true)
    expect(optionLabels.every((label) => !label.includes('✅'))).toBe(true)

    const readCalls = mockedIssuesApi.list.mock.calls.filter((c) => c[1]?.status === 'read')
    expect(readCalls).toHaveLength(0)
  })
})
