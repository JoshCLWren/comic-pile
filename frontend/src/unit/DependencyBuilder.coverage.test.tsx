import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    const call = toast.showToast.mock.calls[0] as unknown as [string, string, { onClick?: () => void }]
    const action = call[2]?.onClick
    action?.()
    expect(toast.removeToast).toHaveBeenCalled()
  })

  it('covers reading-order tabs, graph loading, note editing, and deletion commit', async () => {
    const withNote = { ...dependency, note: 'Read this first' }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [withNote], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([1])
    api.threadsApi.list.mockResolvedValue({ threads: [thread, { ...thread, id: 2, title: 'Source' }] })
    api.dependenciesApi.deleteDependency.mockResolvedValue({})
    api.dependenciesApi.updateDependency.mockResolvedValue({ ...withNote, note: 'Updated' })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    expect(screen.getByRole('tab', { name: 'Timeline' })).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(screen.getByTestId('mock-flowchart')).toBeInTheDocument())
    screen.getByRole('tab', { name: 'Flowchart' }).focus()
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'Home' })
    expect(screen.getByRole('tab', { name: 'Timeline' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: /edit note/i }))
    const noteInput = screen.getByPlaceholderText('Add a note...')
    await user.clear(noteInput)
    await user.type(noteInput, 'Updated')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.dependenciesApi.updateDependency).toHaveBeenCalledWith(4, 'Updated'))

    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await act(async () => vi.advanceTimersByTime(5000))
    await act(async () => await Promise.resolve())
    expect(api.dependenciesApi.deleteDependency).toHaveBeenCalledWith(4)
    vi.useRealTimers()
  })

  it('validates and completes inline migration for an unmigrated prerequisite', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Unmigrated', total_issues: null }] })
    api.issuesApi.migrateThread.mockResolvedValue({ ...thread, id: 2, title: 'Unmigrated', total_issues: 5 })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Unm')
    await waitFor(() => expect(screen.getByRole('button', { name: /Unmigrated/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Unmigrated/ }))
    await user.click(screen.getByRole('button', { name: 'Migrate Now' }))
    fireEvent.submit(screen.getByRole('button', { name: 'Migrate' }).closest('form')!)
    expect(screen.getByText('Both fields are required for migration.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Last issue read'), '1')
    await user.type(screen.getByLabelText('Total issues'), '5')
    await user.click(screen.getByRole('button', { name: 'Migrate' }))
    await waitFor(() => expect(api.issuesApi.migrateThread).toHaveBeenCalledWith(2, 1, 5))
  })
})
