import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoverDetailPage from '../pages/CrossoverDetailPage'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import {
  continuityReadinessApi,
  type ContinuityReadinessResponse,
} from '../services/api-continuity-readiness'
import type { DependencyGroup } from '../services/api-dependency-groups'
import type { Issue, Thread } from '../types'

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    get: vi.fn(),
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

function makeGroup(memberships: DependencyGroup['memberships']): DependencyGroup {
  return {
    id: 7,
    name: 'Annihilation',
    created_at: '2026-08-01T00:00:00Z',
    memberships,
  }
}

const novaThread = makeThread(22, 'Nova: Origin')
const warlockThread = makeThread(101, 'Warlock: Rebirth')
const warlockIssue = makeIssue(11, 101, '3', 'unread')

const populatedGroup = makeGroup([
  { id: 1, thread_id: 22, issue_id: null },
  { id: 2, thread_id: null, issue_id: 11 },
])

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

function mockPopulatedData() {
  mockedGroups.get.mockResolvedValue(populatedGroup)
  mockedThreads.get.mockImplementation(async (id: number) =>
    id === 22 ? novaThread : warlockThread,
  )
  mockedIssues.get.mockResolvedValue(warlockIssue)
  mockedGroups.listForThread.mockImplementation(async (threadId: number) =>
    threadId === 22 ? [{ id: 9, name: 'X of Swords' }] : [],
  )
  mockedGroups.plansForGroup.mockResolvedValue([])
  mockedReadiness.evaluate.mockResolvedValue(readableReadiness)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CrossoverDetailPage', () => {
  it('shows a loading state while the crossover request is pending', async () => {
    let resolveGet: ((group: DependencyGroup) => void) | undefined
    mockedGroups.get.mockImplementation(
      () => new Promise<DependencyGroup>((resolve) => { resolveGet = resolve }),
    )
    mockedGroups.plansForGroup.mockResolvedValue([])
    mockedReadiness.evaluate.mockResolvedValue(readableReadiness)

    renderPage()
    expect(screen.getByText('Loading crossover…')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Back to Crossovers/ }).length).toBeGreaterThan(0)

    resolveGet?.(makeGroup([]))
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
    expect(screen.getByText(/Position 5/)).toBeInTheDocument()
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
    expect(mockedReadiness.evaluate).toHaveBeenCalledWith('crossover', 7)
  })

  it('renders members in authoritative order with read state overlaid', async () => {
    const firstIssue = { ...warlockIssue, id: 11, issue_number: '3', position: 2, status: 'read' as const }
    const secondIssue = { ...warlockIssue, id: 12, issue_number: '4', position: 9, status: 'unread' as const }
    mockedGroups.get.mockResolvedValue(makeGroup([
      { id: 2, thread_id: null, issue_id: 12 },
      { id: 1, thread_id: null, issue_id: 11 },
    ]))
    mockedIssues.get.mockImplementation(async (id: number) => (id === 11 ? firstIssue : secondIssue))
    mockedThreads.get.mockResolvedValue(warlockThread)
    mockedGroups.listForThread.mockResolvedValue([])
    mockedReadiness.evaluate.mockResolvedValue(readableReadiness)

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Unread')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/Issue 4/)).toBeInTheDocument()
    expect(within(rows[1]).getByText('Read')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/Issue 3/)).toBeInTheDocument()
    expect(screen.getByText((_, element) => element?.textContent === '50%')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Continue Reading' })).toHaveAttribute(
      'href',
      '/threads/101',
    )
  })

  it('shows blocked readiness with human-readable blocking reasons per member', async () => {
    const readIssue = { ...warlockIssue, status: 'read' as const }
    mockedGroups.get.mockResolvedValue(makeGroup([{ id: 2, thread_id: null, issue_id: 11 }]))
    mockedIssues.get.mockResolvedValue(readIssue)
    mockedThreads.get.mockResolvedValue(warlockThread)
    mockedGroups.listForThread.mockResolvedValue([])
    mockedReadiness.evaluate.mockResolvedValue(blockedReadiness)

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
    mockedGroups.get.mockResolvedValue(makeGroup([]))
    mockedReadiness.evaluate.mockResolvedValue(readableReadiness)

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
    mockedGroups.get.mockResolvedValue(makeGroup([
      { id: 5, thread_id: null, issue_id: null },
      { id: 6, thread_id: null, issue_id: null },
    ]))
    mockedReadiness.evaluate.mockResolvedValue(readableReadiness)

    renderPage()

    const rows = await screen.findAllByTestId('crossover-member-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Unknown Series')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/Issue \?/)).toBeInTheDocument()
    expect(within(rows[0]).queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View First Series' })).not.toBeInTheDocument()
  })

  it('surfaces load errors and retries successfully', async () => {
    mockedGroups.get
      .mockRejectedValueOnce({ response: { status: 404, data: { detail: 'Crossover not found' } } })
      .mockResolvedValueOnce(populatedGroup)
    mockedThreads.get.mockResolvedValue(novaThread)
    mockedIssues.get.mockResolvedValue(warlockIssue)
    mockedGroups.listForThread.mockResolvedValue([])
    mockedReadiness.evaluate.mockResolvedValue(readableReadiness)

    renderPage()

    expect(await screen.findByText('Error loading crossover')).toBeInTheDocument()
    expect(screen.getByText('Crossover not found')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Annihilation' })).toBeInTheDocument()
    })
    expect(mockedGroups.get).toHaveBeenCalledTimes(2)
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
    mockPopulatedData()
    mockedGroups.plansForGroup.mockResolvedValue([
      { id: 12, name: 'Annihilation Reading Order' },
      { id: 15, name: 'Cosmic Marvel' },
    ])

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Annihilation')).toBeInTheDocument()
    })

    const planLink1 = screen.getByRole('link', { name: 'Reading Plan: Annihilation Reading Order' })
    expect(planLink1).toHaveAttribute('href', '/continuity-plans/12')

    const planLink2 = screen.getByRole('link', { name: 'Reading Plan: Cosmic Marvel' })
    expect(planLink2).toHaveAttribute('href', '/continuity-plans/15')

    expect(mockedGroups.plansForGroup).toHaveBeenCalledWith(7)
  })

  it('omits reading plan links when no plans reference the crossover', async () => {
    mockPopulatedData()
    mockedGroups.plansForGroup.mockResolvedValue([])

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Annihilation')).toBeInTheDocument()
    })

    expect(screen.queryByRole('link', { name: /Reading Plan/ })).not.toBeInTheDocument()
  })
})
