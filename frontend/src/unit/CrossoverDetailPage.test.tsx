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
import { continuityReadinessApi } from '../services/api-continuity-readiness'
import type { ContinuityReadinessResponse } from '../services/api-continuity-readiness'
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
  threadsApi: {
    get: vi.fn(),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    get: vi.fn(),
  },
}))

vi.mock('../services/api-continuity-readiness', () => ({
  continuityReadinessApi: {
    evaluate: vi.fn(),
  },
}))

const mockedGroups = vi.mocked(dependencyGroupsApi)
const mockedThreads = vi.mocked(threadsApi)
const mockedIssues = vi.mocked(issuesApi)
const mockedReadiness = vi.mocked(continuityReadinessApi)

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
  } = {},
): DependencyGroupDetailMember {
  const thread = opts.thread ?? null
  const issue = opts.issue ?? null
  return {
    membership: {
      id,
      thread_id: thread?.id ?? null,
      issue_id: issue?.id ?? null,
      sequence_order: id,
      series_title: thread?.title ?? null,
      issue_number: issue?.issue_number ?? null,
    },
    thread,
    issue,
    other_crossovers: opts.otherCrossovers ?? [],
  }
}

function makeDetail(
  members: DependencyGroupDetailMember[],
  opts: {
    readiness?: ContinuityReadinessResponse | null
    linkedPlans?: DependencyGroupSummary[]
  } = {},
): DependencyGroupDetail {
  return {
    id: 7,
    name: 'Annihilation',
    created_at: '2026-08-01T00:00:00Z',
    memberships: members,
    readiness: opts.readiness ?? null,
    linked_plans: opts.linkedPlans ?? [],
  }
}

const novaThread = makeThread(22, 'Nova: Origin')
const warlockThread = makeThread(101, 'Warlock: Rebirth')
const warlockIssue = makeIssue(11, 101, '3', 'unread')

const populatedMembers = [
  makeDetailMember(1, { thread: novaThread, otherCrossovers: ['X of Swords'] }),
  makeDetailMember(2, { issue: warlockIssue, thread: warlockThread }),
]

const readableReadiness: ContinuityReadinessResponse = {
  node_type: 'crossover',
  node_id: 7,
  is_readable: true,
  evaluated_issue_id: 55,
  blockers: [],
}

const blockedReadiness: ContinuityReadinessResponse = {
  node_type: 'crossover',
  node_id: 7,
  is_readable: false,
  evaluated_issue_id: null,
  blockers: [
    {
      rule_id: 3,
      source_type: 'issue',
      source_id: 11,
      source_label: 'Warlock: Rebirth #3',
      satisfaction_type: 'after',
      satisfied: false,
      causing_issue_ids: [88],
      causing_member_issue_ids: [11],
      unread_issue_details: [
        { issue_id: 88, label: 'Nova #12' },
        { issue_id: 89, label: 'Gamora #2' },
      ],
      note: 'Finish the prologue before this issue.',
    },
  ],
}

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

function mockPopulatedData(opts: { readiness?: ContinuityReadinessResponse | null } = {}) {
  mockedGroups.getDetail.mockResolvedValue(
    makeDetail(populatedMembers, { readiness: opts.readiness ?? readableReadiness }),
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
    expect(screen.getAllByRole('link', { name: /Back to Crossovers/ }).length).toBeGreaterThan(0)

    resolveGet?.(makeDetail([]))
    expect(await screen.findByText('No members in this crossover yet.')).toBeInTheDocument()
  })

  it('renders human-readable member labels with progress and multi-crossover membership', async () => {
    mockPopulatedData()

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    expect(screen.getByText(/2 members/)).toBeInTheDocument()
    expect(screen.getByText('Members')).toBeInTheDocument()
    expect(screen.getByText('Nova: Origin')).toBeInTheDocument()
    expect(screen.getAllByText('Warlock: Rebirth').length).toBe(2)
    expect(screen.queryByText(/^Thread 22$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Issue 11$/)).not.toBeInTheDocument()
    expect(screen.getByText(/Also in: X of Swords/)).toBeInTheDocument()
    expect(screen.getByText('Issues Tracked')).toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.textContent === '0%')).toBeInTheDocument()
    expect(screen.getByText('Next Up')).toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.textContent === '1.')).toBeInTheDocument()
    expect(screen.queryByText(/Position 5/)).not.toBeInTheDocument()
    expect(screen.getAllByText('Readable').length).toBeGreaterThan(0)
    expect(screen.getByText('This crossover is ready to read.'))
    expect(screen.getByText('Evaluated issue: 55')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue Reading' })).toHaveAttribute(
      'href',
      '/threads/101',
    )
    expect(screen.getByRole('link', { name: 'View First Series' })).toHaveAttribute(
      'href',
      '/threads/22',
    )
  })

  it('loads the whole crossover with a single bounded request (no per-member waterfall)', async () => {
    mockPopulatedData()

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    expect(mockedGroups.getDetail).toHaveBeenCalledTimes(1)
    expect(mockedGroups.getDetail).toHaveBeenCalledWith(7)
    expect(mockedGroups.get).not.toHaveBeenCalled()
    expect(mockedGroups.listForThread).not.toHaveBeenCalled()
    expect(mockedGroups.plansForGroup).not.toHaveBeenCalled()
    expect(mockedThreads.get).not.toHaveBeenCalled()
    expect(mockedIssues.get).not.toHaveBeenCalled()
    expect(mockedReadiness.evaluate).not.toHaveBeenCalled()
  })

  it('renders members in authoritative order with read state overlaid', async () => {
    const firstIssue = { ...warlockIssue, id: 11, issue_number: '3', position: 9, status: 'read' as const }
    const secondIssue = { ...warlockIssue, id: 12, issue_number: '4', position: 2, status: 'unread' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        makeDetailMember(2, { issue: secondIssue, thread: warlockThread }),
        makeDetailMember(1, { issue: firstIssue, thread: warlockThread }),
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
    expect(screen.getByRole('link', { name: 'Continue Reading' })).toHaveAttribute(
      'href',
      '/threads/101',
    )
  })

  it('shows blocked readiness with human-readable blocking reasons per member', async () => {
    const readIssue = { ...warlockIssue, status: 'read' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([makeDetailMember(2, { issue: readIssue, thread: warlockThread })], {
        readiness: blockedReadiness,
      }),
    )

    renderPage()

    expect(await screen.findByText('1 continuity rule blocking.')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Show blocking details'))
    expect(screen.getByText('Warlock: Rebirth #3')).toBeInTheDocument()
    expect(screen.getByText('(after)')).toBeInTheDocument()
    expect(screen.getByText('Unread: Nova #12 (Issue 88)')).toBeInTheDocument()
    expect(screen.getByText('Finish the prologue before this issue.')).toBeInTheDocument()

    const blockedRow = screen.getByTestId('crossover-member-row')
    fireEvent.click(within(blockedRow).getByText('Blocking reasons'))
    expect(within(blockedRow).getByText(/Warlock: Rebirth #3 \(after\)/)).toBeInTheDocument()
    expect(within(blockedRow).getByText(/— Nova #12, Gamora #2/)).toBeInTheDocument()
    expect(within(blockedRow).getByText('Blocked')).toBeInTheDocument()
    expect(screen.queryByText('Next Up')).not.toBeInTheDocument()
  })

  it('renders the no-members state without next-up or member actions', async () => {
    mockedGroups.getDetail.mockResolvedValue(makeDetail([]))

    renderPage()

    expect(await screen.findByText('No members in this crossover yet.')).toBeInTheDocument()
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText((_, element) => element?.textContent === '0%')).toBeInTheDocument()
    expect(screen.queryByText('Next Up')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View First Series' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
    expect(mockedThreads.get).not.toHaveBeenCalled()
    expect(mockedIssues.get).not.toHaveBeenCalled()
  })

  it('falls back to Unknown Series for a membership without thread or issue metadata', async () => {
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        makeDetailMember(5, { thread: null, issue: null }),
        makeDetailMember(6, { thread: null, issue: null }),
      ]),
    )

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Unknown Series')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/Issue \?/)).toBeInTheDocument()
    expect(within(rows[0]).queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View First Series' })).not.toBeInTheDocument()
  })

  it('surfaces load errors and retries successfully', async () => {
    mockedGroups.getDetail
      .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Crossover not found' } } })
      .mockResolvedValueOnce(
        makeDetail(populatedMembers, { readiness: readableReadiness }),
      )

    renderPage()

    expect(await screen.findByText('Error loading crossover')).toBeInTheDocument()
    expect(screen.getByText('Crossover not found')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    })
    expect(mockedGroups.getDetail).toHaveBeenCalledTimes(2)
  })

  it('navigates back through history when the Back action is used', async () => {
    mockPopulatedData()
    const historyBack = vi.spyOn(window.history, 'back').mockImplementation(() => {})

    renderPage()
    fireEvent.click(await screen.findByRole('link', { name: 'Back' }))

    expect(historyBack).toHaveBeenCalled()
    historyBack.mockRestore()
  })

  it('shows linked reading plans and navigates to the plan page', async () => {
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail(populatedMembers, {
        readiness: readableReadiness,
        linkedPlans: [
          { id: 12, name: 'Annihilation Reading Order' },
          { id: 15, name: 'Cosmic Marvel' },
        ],
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Annihilation')).toBeInTheDocument()
    })

    const planLink1 = screen.getByRole('link', { name: 'Reading Plan: Annihilation Reading Order' })
    expect(planLink1).toHaveAttribute('href', '/continuity-plans/12')

    const planLink2 = screen.getByRole('link', { name: 'Reading Plan: Cosmic Marvel' })
    expect(planLink2).toHaveAttribute('href', '/continuity-plans/15')

    expect(mockedGroups.plansForGroup).not.toHaveBeenCalled()
  })

  it('omits reading plan links when no plans reference the crossover', async () => {
    mockPopulatedData()

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Annihilation')).toBeInTheDocument()
    })

    expect(screen.queryByRole('link', { name: /Reading Plan/ })).not.toBeInTheDocument()
  })

  it('renders unordered members last with fallback position marker', async () => {
    const orderedIssue = { ...warlockIssue, id: 11, issue_number: '3', position: 9, status: 'read' as const }
    const unorderedIssue = { ...warlockIssue, id: 99, issue_number: '½', position: 1, status: 'unread' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        {
          membership: {
            id: 20,
            thread_id: null,
            issue_id: 99,
            sequence_order: null,
            series_title: warlockThread.title,
            issue_number: '½',
          },
          thread: warlockThread,
          issue: unorderedIssue,
          other_crossovers: [],
        },
        makeDetailMember(1, { issue: orderedIssue, thread: warlockThread }),
      ]),
    )

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    // Ordered entry (position 1) must sort first; unordered last with fallback marker
    expect(within(rows[0]).getByText(/Issue 3/)).toBeInTheDocument()
    expect(within(rows[1]).getByText(/Issue ½/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('—.')).toBeInTheDocument()
  })

  it('applies id tie-breaker when sequence_order values are equal', async () => {
    const issueA = { ...warlockIssue, id: 50, issue_number: '5', status: 'unread' as const }
    const issueB = { ...warlockIssue, id: 51, issue_number: '6', status: 'unread' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        {
          membership: { id: 10, thread_id: null, issue_id: 51, sequence_order: 1, series_title: warlockThread.title, issue_number: '6' },
          thread: warlockThread,
          issue: issueB,
          other_crossovers: [],
        },
        {
          membership: { id: 5, thread_id: null, issue_id: 50, sequence_order: 1, series_title: warlockThread.title, issue_number: '5' },
          thread: warlockThread,
          issue: issueA,
          other_crossovers: [],
        },
      ]),
    )

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    // Lower membership id must sort first when sequence_order ties
    expect(within(rows[0]).getByText(/Issue 5/)).toBeInTheDocument()
    expect(within(rows[1]).getByText(/Issue 6/)).toBeInTheDocument()
  })

  it('renders the unresolved Continue Reading fallback when no member has a thread', async () => {
    const unresolvedA = { ...warlockIssue, id: 31, issue_number: '3', status: 'read' as const }
    const unresolvedB = { ...warlockIssue, id: 32, issue_number: '4', status: 'unread' as const }
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        {
          membership: {
            id: 70,
            thread_id: null,
            issue_id: 31,
            sequence_order: 1,
            series_title: null,
            issue_number: '3',
          },
          thread: null,
          issue: unresolvedA,
          other_crossovers: [],
        },
        {
          membership: {
            id: 71,
            thread_id: null,
            issue_id: 32,
            sequence_order: 2,
            series_title: null,
            issue_number: '4',
          },
          thread: null,
          issue: unresolvedB,
          other_crossovers: [],
        },
      ]),
    )

    renderPage()

    expect(await screen.findByText('No readable issue')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Continue Reading' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View First Series' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
  })

  it('renders the unresolved Next Up fallback when next unread has no thread', async () => {
    mockedGroups.getDetail.mockResolvedValue(
      makeDetail([
        {
          membership: {
            id: 80,
            thread_id: null,
            issue_id: 41,
            sequence_order: 1,
            series_title: null,
            issue_number: '1',
          },
          thread: null,
          issue: { ...warlockIssue, id: 41, issue_number: '1', status: 'unread' as const },
          other_crossovers: [],
        },
      ]),
    )

    renderPage()

    expect(await screen.findByText('Next Up')).toBeInTheDocument()
    expect(screen.getByText('Unresolved')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Read Now' })).not.toBeInTheDocument()
    expect(screen.getByText('No readable issue')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Continue Reading' })).not.toBeInTheDocument()
  })
})
