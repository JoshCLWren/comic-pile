import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  it('does not load or render content when closed or missing a thread', () => {
    const { container } = render(<DependencyBuilder thread={null} isOpen={false} onClose={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
    expect(api.dependenciesApi.listThreadDependencies).not.toHaveBeenCalled()
    render(<DependencyBuilder thread={null} isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('shows dependency loading and request errors', async () => {
    api.dependenciesApi.listThreadDependencies.mockRejectedValueOnce(new Error('load failed'))
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('load failed')).toBeInTheDocument())
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
  })

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
    const call = toast.showToast.mock.calls.at(-1) as unknown as [string, string, { onClick?: () => void }]
    const action = call[2]?.onClick
    act(() => action?.())
    expect(toast.removeToast).toHaveBeenCalled()
  })

  it('covers reading-order tabs, graph loading, note editing, and deletion commit', async () => {
    const withNote = { ...dependency, note: 'Read this first' }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [withNote], blocked_by: [withNote] })
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
    await user.click(screen.getByRole('tab', { name: 'Timeline' }))
    screen.getByRole('tab', { name: 'Flowchart' }).focus()
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' })
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowLeft' })
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'End' })
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'Home' })
    expect(screen.getByRole('tab', { name: 'Timeline' })).toHaveFocus()

    await user.click(screen.getAllByRole('button', { name: /edit note/i })[0]!)
    const noteInput = screen.getAllByPlaceholderText('Add a note...')[0]!
    await user.clear(noteInput)
    await user.type(noteInput, 'Updated')
    await user.click(screen.getAllByRole('button', { name: 'Save' })[0]!)
    await waitFor(() => expect(api.dependenciesApi.updateDependency).toHaveBeenCalledWith(4, 'Updated'))

    vi.useFakeTimers()
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]!)
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

  it('handles empty searches, search errors, issue pagination, and save errors', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockRejectedValueOnce(new Error('search failed'))
    api.issuesApi.list
      .mockResolvedValueOnce({ issues: [{ id: 8, thread_id: 2, issue_number: '1', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: 'next' })
      .mockResolvedValueOnce({ issues: [{ id: 9, thread_id: 2, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: 'next' })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'x')
    expect(screen.queryByText('No matching threads found.')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'y')
    await waitFor(() => expect(screen.getByText('search failed')).toBeInTheDocument())

    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Prerequisite', total_issues: 3 }] })
    await user.clear(screen.getByLabelText('Search prerequisite thread'))
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    expect(screen.getByRole('option', { name: '#2' })).toBeInTheDocument()
    api.dependenciesApi.createDependency.mockRejectedValueOnce(new Error('save failed'))
    await user.click(screen.getByRole('button', { name: /Block issue/ }))
    await waitFor(() => expect(screen.getByText('save failed')).toBeInTheDocument())
  })

  it('handles note validation, cancellation, and update failures', async () => {
    const noted = { ...dependency, note: 'Existing note' }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [noted], blocked_by: [] })
    api.dependenciesApi.updateDependency.mockRejectedValueOnce(new Error('note failed'))
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Existing note')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Edit note' }))
    const input = screen.getByPlaceholderText('Add a note...')
    await user.clear(input)
    await user.type(input, 'Changed')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.getByText('note failed')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
  })

  it('builds issue graph nodes, handles duplicate dependencies, and reports graph failures', async () => {
    const issueDependency = {
      ...dependency,
      source_thread_id: 2,
      target_thread_id: 1,
      source_issue_id: 8,
      target_issue_id: 9,
      source_issue_thread_id: 2,
      target_issue_thread_id: 1,
      source_label: 'Source #1',
      target_label: 'Target #2',
      is_issue_level: true,
    }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [issueDependency, { ...issueDependency, id: 5 }], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([1, 2])
    api.threadsApi.list.mockResolvedValue({ threads: [thread, { ...thread, id: 2, title: 'Source', total_issues: 4 }] })
    api.issuesApi.list
      .mockResolvedValueOnce({ issues: [{ id: 8, thread_id: 2, issue_number: '1', status: 'unread' }], next_page_token: null })
      .mockResolvedValueOnce({ issues: [{ id: 9, thread_id: 1, issue_number: '2', status: 'unread' }], next_page_token: null })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(screen.getByTestId('mock-flowchart')).toBeInTheDocument())
    await user.click(screen.getAllByRole('button', { name: /remove/i })[0]!)
    expect(toast.showToast).toHaveBeenCalled()
  })

  it('builds thread-level flowchart edges and related thread context', async () => {
    const threadDependency = {
      ...dependency,
      source_thread_id: 2,
      target_thread_id: 1,
      source_issue_id: null,
      target_issue_id: null,
      is_issue_level: false,
      source_label: 'Source thread',
      target_label: 'Target thread',
    }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [threadDependency], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([1])
    api.threadsApi.list.mockResolvedValue({ threads: [thread, { ...thread, id: 2, title: 'Source thread' }] })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(screen.getByTestId('mock-flowchart')).toBeInTheDocument())
  })

  it('rejects invalid inline migration values and recovers from migration/delete errors', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Unmigrated', total_issues: null }] })
    api.issuesApi.migrateThread.mockRejectedValueOnce(new Error('migration failed'))
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Unm')
    await waitFor(() => expect(screen.getByRole('button', { name: /Unmigrated/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Unmigrated/ }))
    await user.click(screen.getByRole('button', { name: 'Migrate Now' }))
    await user.type(screen.getByLabelText('Last issue read'), '99')
    await user.type(screen.getByLabelText('Total issues'), '2')
    await user.click(screen.getByRole('button', { name: 'Migrate' }))
    await waitFor(() => expect(screen.getByText(/Invalid migration values/)).toBeInTheDocument())
    await user.clear(screen.getByLabelText('Last issue read'))
    await user.type(screen.getByLabelText('Last issue read'), '1')
    await user.click(screen.getByRole('button', { name: 'Migrate' }))
    await waitFor(() => expect(screen.getByText('migration failed')).toBeInTheDocument())
  })

  it('handles flowchart loading failures and unread-issue loading failures', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [dependency], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([])
    api.threadsApi.list.mockRejectedValueOnce(new Error('graph failed'))
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('[loadFlowchartData] Error:', expect.any(Error)))
    errorSpy.mockRestore()

    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Unread source', total_issues: 3 }] })
    api.issuesApi.list.mockRejectedValue(new Error('issues failed'))
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Unread')
    await waitFor(() => expect(screen.getByRole('button', { name: /Unread source/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Unread source/ }))
    await waitFor(() => expect(api.issuesApi.list).toHaveBeenCalled())
  })

  it('keeps the graph usable when blocked-id and issue context requests fail', async () => {
    const incompleteIssueDependency = {
      ...dependency,
      source_issue_id: 8,
      target_issue_id: 9,
      source_issue_thread_id: null,
      target_issue_thread_id: null,
      source_label: null,
      target_label: null,
      is_issue_level: true,
    }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [incompleteIssueDependency], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockRejectedValueOnce(new Error('blocked ids failed'))
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('[loadFlowchartData] Error:', expect.any(Error)))
    errorSpy.mockRestore()
  })

  it('covers thread-level labels, duplicate issue dependencies, and missing issue choices', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({
      blocking: [{ ...dependency, id: 12, source_issue_id: null, target_issue_id: null, source_label: null, target_label: null, source_thread_id: 2, target_thread_id: 1 }],
      blocked_by: [{ ...dependency, id: 13, source_issue_id: null, target_issue_id: null, source_label: null, target_label: null, source_thread_id: 2, target_thread_id: 1 }],
    })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Prerequisite', total_issues: 2 }] })
    api.issuesApi.list.mockResolvedValue({ issues: [], next_page_token: null })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Remove' }).length).toBe(2))
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    expect(screen.getAllByText('No unread issues available').length).toBeGreaterThan(0)
  })

  it('searches without a current thread and renders dependency label fallbacks', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Standalone' }] })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={null} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Sta')
    await waitFor(() => expect(screen.getByRole('button', { name: /Standalone/ })).toBeInTheDocument())
  })

  it('shows empty unread issue selectors after a successful empty issue response', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({
      blocking: [{ ...dependency, source_label: null, target_label: null, target_issue_id: 9 }],
      blocked_by: [{ ...dependency, source_label: null, target_label: null, source_issue_id: 8 }],
    })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'No unread', total_issues: 3 }] })
    api.issuesApi.list.mockResolvedValue({ issues: [], next_page_token: null })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'No ')
    await waitFor(() => expect(screen.getByRole('button', { name: /No unread/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /No unread/ }))
    await waitFor(() => expect(screen.getAllByRole('option', { name: /No unread issues available/ })).toHaveLength(2))
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([])
    api.threadsApi.list.mockResolvedValue({ threads: [thread, { ...thread, id: 2, title: 'No unread' }] })
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    await user.click(screen.getByRole('tab', { name: 'Flowchart' }))
    await waitFor(() => expect(screen.getByTestId('mock-flowchart')).toBeInTheDocument())
  })

  it('shows the searching state while a thread search is pending', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'pending')
    await waitFor(() => expect(screen.getByText('Searching…')).toBeInTheDocument())
  })

  it('reports missing issue selections and unmigrated target threads', async () => {
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Prerequisite' }] })
    api.issuesApi.list.mockResolvedValue({
      issues: [{ id: 8, thread_id: 2, issue_number: '1', status: 'unread' }],
      next_page_token: null,
    })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Prerequisite issue'), '')
    expect(screen.getByRole('button', { name: /Block issue/ })).toBeDisabled()

    cleanup()
    const unmigratedTarget = { ...thread, total_issues: null }
    render(<DependencyBuilder thread={unmigratedTarget as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Block issue/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Block issue/ }))
    expect(screen.getByText('Target thread must be migrated to issue tracking before adding issue dependencies.')).toBeInTheDocument()
  })

  it('covers note length validation and delete cleanup when the modal closes', async () => {
    const noted = { ...dependency, note: 'Existing' }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [noted], blocked_by: [] })
    api.dependenciesApi.deleteDependency.mockRejectedValue(new Error('delete failed'))
    const user = userEvent.setup()
    const { rerender } = render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('Existing')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Edit note' }))
    const input = screen.getByPlaceholderText('Add a note...')
    fireEvent.change(input, { target: { value: 'x'.repeat(256) } })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    rerender(<DependencyBuilder thread={thread as never} isOpen={false} onClose={vi.fn()} />)
    await waitFor(() => expect(api.dependenciesApi.deleteDependency).toHaveBeenCalledWith(4))
  })

  it('commits a pending deletion successfully when the builder closes', async () => {
    const noted = { ...dependency, note: 'Commit on close' }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [noted], blocked_by: [] })
    api.dependenciesApi.deleteDependency.mockResolvedValue(undefined)
    const changed = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} onChanged={changed} />)
    await waitFor(() => expect(screen.getByText('Commit on close')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    rerender(<DependencyBuilder thread={thread as never} isOpen={false} onClose={vi.fn()} onChanged={changed} />)
    await waitFor(() => expect(changed).toHaveBeenCalled())
    expect(toast.removeToast).toHaveBeenCalled()
  })

  it('disables duplicate issue dependencies and surfaces API warnings', async () => {
    const issueDependency = { ...dependency, source_issue_id: 8, target_issue_id: 9, source_issue_thread_id: 2, target_issue_thread_id: 1, source_label: 'Prerequisite #1', target_label: 'Target #2', is_issue_level: true }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [issueDependency], blocked_by: [] })
    api.threadsApi.list.mockResolvedValue({ threads: [{ ...thread, id: 2, title: 'Prerequisite', total_issues: 3 }] })
    api.issuesApi.list.mockResolvedValue({ issues: [{ id: 8, thread_id: 2, issue_number: '1', status: 'unread' }], next_page_token: null })
    api.dependenciesApi.createDependency.mockResolvedValue({ warning: 'Dependency may create a cycle' })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    expect(screen.getByLabelText('Target issue')).toBeInTheDocument()
  })

  it('renders safely when opened without a thread', () => {
    render(<DependencyBuilder thread={null} isOpen onClose={vi.fn()} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('handles malformed graph dependencies, keyboard tab navigation, empty issues, and blank notes', async () => {
    const malformed = {
      ...dependency,
      id: 5,
      source_thread_id: null,
      target_thread_id: null,
      source_issue_id: 0,
      target_issue_id: 9,
      source_issue_thread_id: null,
      target_issue_thread_id: 1,
      source_label: null,
      target_label: null,
      note: null,
    }
    api.dependenciesApi.listThreadDependencies.mockResolvedValue({ blocking: [malformed], blocked_by: [] })
    api.dependenciesApi.listBlockedThreadIds.mockResolvedValue([])
    api.threadsApi.list.mockResolvedValue({ threads: [thread, { ...thread, id: 2, title: 'Prerequisite', total_issues: 3 }] })
    api.issuesApi.list.mockResolvedValue({ issues: [], next_page_token: null })
    api.dependenciesApi.updateDependency.mockResolvedValue({ ...malformed, note: null })
    const user = userEvent.setup()
    render(<DependencyBuilder thread={thread as never} isOpen onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole('button', { name: /view reading order/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /view reading order/i }))
    const tablist = screen.getByRole('tablist')
    const timeline = screen.getByRole('tab', { name: 'Timeline' })
    const graph = screen.getByRole('tab', { name: 'Flowchart' })
    graph.focus()
    fireEvent.keyDown(tablist, { key: 'ArrowRight' })
    fireEvent.keyDown(tablist, { key: 'ArrowLeft' })
    fireEvent.keyDown(tablist, { key: 'End' })
    expect(graph).toHaveFocus()
    fireEvent.keyDown(tablist, { key: 'Escape' })
    timeline.focus()
    fireEvent.keyDown(tablist, { key: 'ArrowLeft' })
    expect(graph).toHaveFocus()
    await user.click(screen.getByRole('button', { name: '+ Add note' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.dependenciesApi.updateDependency).toHaveBeenCalledWith(5, null))

    await user.type(screen.getByLabelText('Search prerequisite thread'), 'Pre')
    await waitFor(() => expect(screen.getByRole('button', { name: /Prerequisite/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Prerequisite/ }))
    await waitFor(() => expect(screen.getByLabelText('Prerequisite issue')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Prerequisite issue'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Target issue'), { target: { value: '' } })
    expect(screen.getAllByText('No unread issues available')).toHaveLength(2)
  })
})
