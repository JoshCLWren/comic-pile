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
    addMember: vi.fn(),
    addIssueRange: vi.fn(),
    removeMember: vi.fn(),
  },
}))

const api = vi.mocked(dependencyGroupsApi)
const threadApi = vi.mocked(threadsApi)
const issueApi = vi.mocked(issuesApi)

const crossover = {
  id: 7,
  name: 'Annihilation',
  created_at: '2026-08-06T00:00:00Z',
  memberships: [
    { id: 1, issue_id: 31, thread_id: null },
    { id: 2, issue_id: null, thread_id: 22 },
  ],
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

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue([crossover])
  threadApi.get.mockResolvedValue(thread)
  issueApi.list.mockResolvedValue({
    issues,
    total_count: issues.length,
    page_size: 100,
    next_page_token: null,
  })
})

describe('CrossoversPage membership editing', () => {
  it('shows individual issue and thread memberships', async () => {
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    expect(screen.getByText('Issue 31')).toBeInTheDocument()
    expect(screen.getByText('Thread 22')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Annihilation members' })).toBeInTheDocument()
  })

  it('adds a whole thread membership and updates the visible group', async () => {
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44 })
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '44' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByText('Thread 44')).toBeInTheDocument()
    expect(api.addMember).toHaveBeenCalledWith(7, { thread_id: 44 })
    expect(screen.getByRole('status')).toHaveTextContent('Thread added to crossover.')
    expect(screen.getByLabelText('Whole thread ID')).toHaveValue('')
  })

  it('preserves unrelated crossovers while adding and removing memberships', async () => {
    const unrelated = {
      id: 8,
      name: 'Secret Invasion',
      created_at: '2026-08-06T00:00:00Z',
      memberships: [{ id: 8, issue_id: 80, thread_id: null }],
    }
    api.list.mockResolvedValue([crossover, unrelated])
    api.addMember.mockResolvedValue({ id: 3, issue_id: null, thread_id: 44 })
    api.removeMember.mockResolvedValue(undefined)
    render(<CrossoversPage />)

    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))
    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '44' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))
    expect(await screen.findByText('Thread 44')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))
    await waitFor(() => expect(screen.queryByText('Issue 31')).not.toBeInTheDocument())

    expect(screen.getByRole('button', { name: /Secret Invasion.*1 member/ })).toBeInTheDocument()
  })

  it('keeps a successful range add committed when the membership refresh fails', async () => {
    api.addIssueRange.mockResolvedValue({
      thread_id: 22,
      start_position: 3,
      end_position: 5,
      added_issue_ids: [31],
      already_present_issue_ids: [],
    })
    api.get.mockRejectedValue(new Error('Refresh unavailable'))
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Thread ID'), { target: { value: '22' } })
    fireEvent.click(screen.getByRole('button', { name: 'Choose issues' }))
    await screen.findByText(/Issues from Nova/)
    fireEvent.change(screen.getByLabelText('First issue'), { target: { value: '31' } })
    fireEvent.change(screen.getByLabelText('Last issue'), { target: { value: '33' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add range' }))

    await waitFor(() => expect(api.addIssueRange).toHaveBeenCalledTimes(1))
    const status = await screen.findByRole('status', undefined, { timeout: 5000 })
    expect(status).toHaveTextContent('1 added, 0 already present.')
    expect(status).toHaveTextContent('latest memberships could not be refreshed: Refresh unavailable')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Thread ID')).toHaveValue('')
    expect(screen.queryByLabelText('First issue')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Last issue')).not.toBeInTheDocument()
    expect(api.addIssueRange).toHaveBeenCalledWith(7, 22, 3, 5)
  })

  it('keeps the whole-thread form usable when adding a membership fails', async () => {
    api.addMember.mockRejectedValue(new Error('Thread lookup unavailable'))
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '44' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Thread lookup unavailable')
    expect(screen.getByLabelText('Whole thread ID')).toHaveValue('44')
    expect(screen.getByRole('button', { name: 'Add thread' })).toBeEnabled()
  })

  it('rejects invalid whole-thread IDs before calling the API', async () => {
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid thread ID.')

    fireEvent.change(screen.getByLabelText('Whole thread ID'), { target: { value: '1.5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add thread' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid thread ID.')
    expect(api.addMember).not.toHaveBeenCalled()
  })

  it('removes a membership without changing the crossover itself', async () => {
    api.removeMember.mockResolvedValue(undefined)
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))

    await waitFor(() => expect(screen.queryByText('Issue 31')).not.toBeInTheDocument())
    expect(api.removeMember).toHaveBeenCalledWith(7, 1)
    expect(screen.getByText('Annihilation')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Comic removed from crossover.')
  })

  it('ignores another membership removal while one is pending', async () => {
    let resolveRemoval: (() => void) | undefined
    api.removeMember.mockImplementation(() => new Promise<void>((resolve) => {
      resolveRemoval = resolve
    }))
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove thread 22 from Annihilation' }))

    expect(api.removeMember).toHaveBeenCalledTimes(1)
    resolveRemoval?.()
    await waitFor(() => expect(screen.queryByText('Issue 31')).not.toBeInTheDocument())
    expect(screen.getByText('Thread 22')).toBeInTheDocument()
  })

  it('keeps membership visible when removal fails', async () => {
    api.removeMember.mockRejectedValue(new Error('Removal unavailable'))
    render(<CrossoversPage />)
    fireEvent.click(await screen.findByRole('button', { name: /Annihilation.*2 members/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Remove issue 31 from Annihilation' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Removal unavailable')
    expect(screen.getByText('Issue 31')).toBeInTheDocument()
  })
})
