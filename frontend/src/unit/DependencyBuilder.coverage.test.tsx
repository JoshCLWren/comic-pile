import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  dependenciesApi: { listThreadDependencies: vi.fn(), listBlockedThreadIds: vi.fn(), createDependency: vi.fn(), deleteDependency: vi.fn(), updateDependency: vi.fn() },
  threadsApi: { list: vi.fn() },
  issuesApi: { list: vi.fn(), migrateThread: vi.fn() },
}))
const toast = vi.hoisted(() => ({ showToast: vi.fn(() => 'toast'), removeToast: vi.fn() }))
vi.mock('../services/api', () => api)
vi.mock('../services/api-issues', () => ({ issuesApi: api.issuesApi }))
vi.mock('../contexts/useToast', () => ({ useToast: () => toast }))
vi.mock('../components/DependencyFlowchart', () => ({ default: () => <div data-testid="mock-flowchart" /> }))
vi.mock('../components/ReadingOrderTimeline', () => ({ default: () => <div data-testid="mock-timeline" /> }))
import DependencyBuilder from '../components/DependencyBuilder'

const thread = { id: 1, title: 'Target', format: 'Comic', issues_remaining: 1, total_issues: 3, next_unread_issue_id: null, reading_progress: null, queue_position: 1, status: 'active', is_blocked: false, blocking_reasons: [], collection_id: null, created_at: 'now' }
const dependency = { id: 4, source_thread_id: 2, target_thread_id: 1, source_issue_id: null, target_issue_id: null, source_label: 'Source', target_label: 'Target', created_at: 'now' }

describe('DependencyBuilder', () => {
  it('searches, selects, loads issues, creates dependencies, and opens views', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Prerequisite', total_issues: 2 }] })
    api.issuesApi.list.mockResolvedValue({ issues: [{ id: 8, thread_id: 2, issue_number: '1', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: null })
    api.dependenciesApi.createDependency.mockResolvedValue({})
    const user = userEvent.setup(); const changed = vi.fn()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} onChanged={changed} />)
    await waitFor(() => expect(screen.getByText('No prerequisites yet.')).toBeInTheDocument())
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument(), { timeout: 1000 })
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Block issue/ }))
    await waitFor(() => expect(api.dependenciesApi.createDependency).toHaveBeenCalled())
    expect(changed).toHaveBeenCalled()
  })

  it('renders existing dependency rows and undo deletion', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [dependency], blocked_by: [dependency] })
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getAllByText('Source').length).toBeGreaterThan(0))
    const remove = screen.getAllByRole('button', { name: 'Remove' })[0]
    fireEvent.click(remove)
    await waitFor(() => expect(toast.showToast).toHaveBeenCalled())
    const action = toast.showToast.mock.calls[0]?.[2]?.onClick as (() => void) | undefined
    action?.()
    expect(toast.removeToast).toHaveBeenCalled()
  })
})
