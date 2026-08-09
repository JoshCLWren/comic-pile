import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CrossoversPage from '../pages/CrossoversPage'
import { threadsApi } from '../services/api'
import { dependencyGroupsApi } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'

vi.mock('../services/api', () => ({
  threadsApi: {
    get: vi.fn(),
  },
}))

vi.mock('../services/api-issues', () => ({
  issuesApi: {
    list: vi.fn(),
  },
}))

vi.mock('../services/api-dependency-groups', () => ({
  dependencyGroupsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    delete: vi.fn(),
    addIssueRange: vi.fn(),
  },
}))

const groupsApi = vi.mocked(dependencyGroupsApi)
const threadApi = vi.mocked(threadsApi)
const issueApi = vi.mocked(issuesApi)

const crossover = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}
const secondCrossover = {
  id: 8,
  name: 'Secret Wars',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [],
}
const thread = {
  id: 22,
  title: 'Nova',
  format: 'single issues',
  issues_remaining: 3,
  total_issues: 3,
  queue_position: 4,
  status: 'active',
  is_blocked: false,
  blocking_reasons: [],
  created_at: '2026-08-01T00:00:00Z',
}
const issues = [
  {
    id: 31,
    thread_id: 22,
    issue_number: '2',
    position: 3,
    status: 'read' as const,
    read_at: '2026-08-02T00:00:00Z',
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 32,
    thread_id: 22,
    issue_number: 'Annual 1',
    position: 4,
    status: 'unread' as const,
    read_at: null,
    created_at: '2026-08-01T00:00:00Z',
  },
  {
    id: 33,
    thread_id: 22,
    issue_number: '½',
    position: 5,
    status: 'unread' as const,
    read_at: null,
    created_at: '2026-08-01T00:00:00Z',
  },
]

function openRangeForm(name = /Annihilation.*0 members/) {
  fireEvent.click(screen.getByRole('button', { name }))
}

async function loadIssues() {
  fireEvent.change(screen.getByLabelText('Thread ID'), { target: { value: '22' } })
  fireEvent.click(screen.getByRole('button', { name: 'Choose issues' }))
  await screen.findByText(/Issues from Nova/)
}

function selectRange(firstIssueId: string, lastIssueId: string) {
  fireEvent.change(screen.getByLabelText('First issue'), { target: { value: firstIssueId } })
  fireEvent.change(screen.getByLabelText('Last issue'), { target: { value: lastIssueId } })
}

beforeEach(() => {
  vi.clearAllMocks()
  groupsApi.list.mockResolvedValue([crossover])
  threadApi.get.mockResolvedValue(thread)
  issueApi.list.mockResolvedValue({
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
  })
})

describe('CrossoversPage issue ranges', () => {
  it('uses shared issue selectors and never exposes issue positions', async () => {
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()

    expect(screen.queryByLabelText('Start position')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('End position')).not.toBeInTheDocument()
    expect(screen.getByLabelText('First issue')).toHaveTextContent('#2')
    expect(screen.getByLabelText('First issue')).toHaveTextContent('#Annual 1')
    expect(screen.getByLabelText('First issue')).toHaveTextContent('#½')
  })

  it('translates selected issue labels to canonical positions when saving', async () => {
    groupsApi.addIssueRange.mockResolvedValue({
      thread_id: 22,
      start_position: 3,
      end_position: 5,
      added_issue_ids: [31, 33],
      already_present_issue_ids: [32],
    })
    groupsApi.get.mockResolvedValue({
      ...crossover,
      memberships: [
        { id: 1, issue_id: 31, thread_id: null },
        { id: 2, issue_id: 32, thread_id: null },
        { id: 3, issue_id: 33, thread_id: null },
      ],
    })

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()
    selectRange('31', '33')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    expect(await screen.findByRole('status')).toHaveTextContent('2 added, 1 already present.')
    expect(groupsApi.addIssueRange).toHaveBeenCalledWith(7, 22, 3, 5)
    expect(groupsApi.get).toHaveBeenCalledWith(7)
    expect(screen.getByText('3 issue memberships and 0 thread memberships.')).toBeInTheDocument()
    expect(screen.getByLabelText('Thread ID')).toHaveValue('')
    expect(screen.queryByLabelText('First issue')).not.toBeInTheDocument()
  })

  it('shows reversed-range validation using comic issue labels', async () => {
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()
    selectRange('33', '31')

    expect(screen.getByRole('alert')).toHaveTextContent(
      '#½ comes after #2 in Nova. Choose a later ending issue.',
    )
    expect(screen.getByRole('button', { name: 'Add range' })).toBeDisabled()
    expect(groupsApi.addIssueRange).not.toHaveBeenCalled()
  })

  it('loads every issue page so later specials remain selectable', async () => {
    issueApi.list
      .mockResolvedValueOnce({
        issues: issues.slice(0, 2),
        total_count: 3,
        page_size: 2,
        next_page_token: 'next-page',
      })
      .mockResolvedValueOnce({
        issues: issues.slice(2),
        total_count: 3,
        page_size: 2,
        next_page_token: null,
      })

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()

    expect(issueApi.list).toHaveBeenNthCalledWith(1, 22, { page_size: 100 })
    expect(issueApi.list).toHaveBeenNthCalledWith(2, 22, {
      page_size: 100,
      page_token: 'next-page',
    })
    expect(screen.getByLabelText('Last issue')).toHaveTextContent('#½')
  })

  it('clears range state when expanding another crossover', async () => {
    groupsApi.list.mockResolvedValue([crossover, secondCrossover])
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')

    openRangeForm()
    await loadIssues()
    selectRange('31', '33')
    openRangeForm(/Secret Wars.*0 members/)

    expect(screen.getByLabelText('Thread ID')).toHaveValue('')
    expect(screen.queryByLabelText('First issue')).not.toBeInTheDocument()
    expect(screen.getByRole('form', { name: 'Add issue range to Secret Wars' })).toBeInTheDocument()
  })

  it('reports issue-loading failures without exposing position inputs', async () => {
    issueApi.list.mockRejectedValue(new Error('Issues unavailable'))
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()

    fireEvent.change(screen.getByLabelText('Thread ID'), { target: { value: '22' } })
    fireEvent.click(screen.getByRole('button', { name: 'Choose issues' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Issues unavailable')
    expect(screen.queryByLabelText('Start position')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add range' })).toBeDisabled()
  })

  it('keeps controls locked while a range save is pending', async () => {
    groupsApi.addIssueRange.mockImplementation(() => new Promise(() => undefined))
    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()
    selectRange('31', '33')
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    expect(screen.getByRole('button', { name: 'Adding…' })).toBeDisabled()
    expect(screen.getByLabelText('Thread ID')).toBeDisabled()
    expect(screen.getByLabelText('First issue')).toBeDisabled()
  })

  it('clears expanded range state when deleting the expanded crossover', async () => {
    groupsApi.delete.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<CrossoversPage />)
    await screen.findByText('Annihilation')
    openRangeForm()
    await loadIssues()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(groupsApi.delete).toHaveBeenCalledWith(7))
    expect(screen.queryByText('Annihilation')).not.toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Add issue range to Annihilation' })).not.toBeInTheDocument()
  })
})
