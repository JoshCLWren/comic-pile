import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoverDetailPage from '../pages/CrossoverDetailPage'
import {
  dependencyGroupsApi,
  type DependencyGroupDetail,
  type DependencyGroupDetailMember,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import type { Issue, Thread } from '../types'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    get: vi.fn(),
    getDetail: vi.fn(),
    listForThread: vi.fn(),
    plansForGroup: vi.fn(),
  },
}))

vi.mock('../services/api', () => ({
  threadsApi: { get: vi.fn() },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: { get: vi.fn() },
}))

const mockedGroups = vi.mocked(dependencyGroupsApi)
const mockedThreads = vi.mocked(threadsApi)
const mockedIssues = vi.mocked(issuesApi)

function makeThread(id: number, title: string): Thread {
  return {
    id,
    title,
    format: 'single issues',
    issues_remaining: 1,
    total_issues: 6,
    next_unread_issue_id: null,
    next_unread_issue_number: null,
    queue_position: 1,
    status: 'active',
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2026-08-01T00:00:00Z',
  }
}

function makeIssue(id: number, threadId: number, issueNumber: string, status: Issue['status']): Issue {
  return {
    id,
    thread_id: threadId,
    issue_number: issueNumber,
    position: 5,
    status,
    read_at: status === 'read' ? '2026-08-02T00:00:00Z' : null,
    created_at: '2026-08-01T00:00:00Z',
  }
}

function makeDetailMember(
  id: number,
  opts: {
    thread?: Thread | null
    issue?: Issue | null
    otherCrossovers?: string[]
    sequence_order?: number | null
  } = {},
): DependencyGroupDetailMember {
  const thread = opts.thread ?? null
  const issue = opts.issue ?? null
  return {
    membership: {
      id,
      thread_id: thread?.id ?? null,
      issue_id: issue?.id ?? null,
      series_title: thread?.title ?? null,
      issue_number: issue?.issue_number ?? null,
      sequence_order: opts.sequence_order ?? null,
    },
    thread,
    issue,
    other_crossovers: opts.otherCrossovers ?? [],
  }
}

function makeDetail(
  members: DependencyGroupDetailMember[],
  opts: { linkedPlans?: DependencyGroupSummary[] } = {},
): DependencyGroupDetail {
  return {
    id: 7,
    name: 'Annihilation',
    created_at: '2026-08-01T00:00:00Z',
    memberships: members,
    linked_plans: opts.linkedPlans ?? [],
  }
}

const novaThread = makeThread(22, 'Nova: Origin')
const warlockThread = makeThread(101, 'Warlock: Rebirth')
const warlockIssue = makeIssue(11, 101, '3', 'unread')
const populatedMembers = [
  makeDetailMember(1, { thread: novaThread, otherCrossovers: ['X of Swords'], sequence_order: 1 }),
  makeDetailMember(2, { issue: warlockIssue, thread: warlockThread, sequence_order: 2 }),
]

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/crossovers/7']}>
      <Routes>
        <Route path="/crossovers/:group" element={<CrossoverDetailPage />} />
        <Route path="/threads/:id" element={<div>Thread page</div>} />
        <Route path="/continuity-plans/:id" element={<div>Plan page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CrossoverDetailPage', () => {
  it('shows a loading state while the crossover request is pending', async () => {
    let resolveGet: ((detail: DependencyGroupDetail) => void) | undefined
    mockedGroups.getDetail.mockImplementation(
      () => new Promise<DependencyGroupDetail>((resolve) => { resolveGet = resolve }),
    )

    renderPage()
    expect(screen.getByText('Loading crossover…')).toBeInTheDocument()
    resolveGet?.(makeDetail([]))
    expect(await screen.findByText('No members in this crossover yet.')).toBeInTheDocument()
  })

  it('renders factual project data without a readiness verdict', async () => {
    mockedGroups.getDetail.mockResolvedValue(makeDetail(populatedMembers))

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    expect(screen.getByText(/2 members/)).toBeInTheDocument()
    expect(screen.getByText('Nova: Origin')).toBeInTheDocument()
    expect(screen.getAllByText('Warlock: Rebirth').length).toBe(2)
    expect(screen.getByText(/Also in: X of Swords/)).toBeInTheDocument()
    expect(screen.getByText('Issues Tracked')).toBeInTheDocument()
    expect(screen.getByText('Next Up')).toBeInTheDocument()
    expect(screen.getByText(/Position 2/)).toBeInTheDocument()
    expect(screen.queryByText(/Readable/)).not.toBeInTheDocument()
    expect(screen.queryByText(/continuity rule blocking/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/readiness/i)).not.toBeInTheDocument()
  })

  it('loads the whole crossover with one detail request and no secondary evaluation call', async () => {
    mockedGroups.getDetail.mockResolvedValue(makeDetail(populatedMembers))

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    expect(mockedGroups.getDetail).toHaveBeenCalledTimes(1)
    expect(mockedGroups.getDetail).toHaveBeenCalledWith(7)
    expect(mockedGroups.get).not.toHaveBeenCalled()
    expect(mockedGroups.listForThread).not.toHaveBeenCalled()
    expect(mockedGroups.plansForGroup).not.toHaveBeenCalled()
    expect(mockedThreads.get).not.toHaveBeenCalled()
    expect(mockedIssues.get).not.toHaveBeenCalled()
  })

  it('sorts provenance ordering and marks read entries', async () => {
    const firstIssue = { ...warlockIssue, id: 11, issue_number: '3', position: 2, status: 'read' as const }
    const secondIssue = { ...warlockIssue, id: 12, issue_number: '4', position: 9, status: 'unread' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        makeDetailMember(2, { issue: secondIssue, thread: warlockThread, sequence_order: 5 }),
        makeDetailMember(1, { issue: firstIssue, thread: warlockThread, sequence_order: 1 }),
      ]),
    )

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Read')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/Issue 3/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('Unread')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/Issue 4/)).toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.textContent === '50%')).toBeInTheDocument()
  })

  it('keeps linked Reading Plans available', async () => {
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail(populatedMembers, {
        linkedPlans: [
          { id: 12, name: 'Annihilation Reading Order' },
          { id: 15, name: 'Cosmic Marvel' },
        ],
      }),
    )

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Reading Plan: Annihilation Reading Order' })).toHaveAttribute(
      'href',
      '/continuity-plans/12',
    )
    expect(screen.getByRole('link', { name: 'Reading Plan: Cosmic Marvel' })).toHaveAttribute(
      'href',
      '/continuity-plans/15',
    )
  })

  it('surfaces load errors and retries successfully', async () => {
    mockedGroups.getDetail
      .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Crossover not found' } } })
      .mockResolvedValueOnce(makeDetail(populatedMembers))

    renderPage()

    expect(await screen.findByText('Error loading crossover')).toBeInTheDocument()
    expect(screen.getByText('Crossover not found')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Annihilation' })).toBeInTheDocument())
    expect(mockedGroups.getDetail).toHaveBeenCalledTimes(2)
  })

  it('renders the no-members state without next-up or member actions', async () => {
    mockedGroups.getDetail.mockResolvedValue(makeDetail([]))

    renderPage()

    expect(await screen.findByText('No members in this crossover yet.')).toBeInTheDocument()
    expect(screen.queryByText('Next Up')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View First Series' })).not.toBeInTheDocument()
  })
})
