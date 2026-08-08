import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

const issues = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), move: vi.fn(), markRead: vi.fn(), markUnread: vi.fn() }))
vi.mock('../services/api-issues', () => ({ issuesApi: issues }))
vi.mock('../components/Modal', () => ({ default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: ReactNode }) => isOpen ? <div role="dialog"><h2>{title}</h2>{children}</div> : null }))
import BugReportModal from '../components/BugReportModal'
import IssueCorrectionDialog from '../components/IssueCorrectionDialog'

describe('bug report and issue correction dialogs', () => {
  it('validates, submits, cancels, and reports bug submission errors', async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockRejectedValue(new Error('failed')); const onClose = vi.fn()
    render(<BugReportModal isOpen onClose={onClose} onSubmit={onSubmit} diagnosticData={{ browser: 'x' } as never} />)
    expect(screen.getByText(/Browser info/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Submit Report' })).toBeDisabled()
    await user.type(screen.getByLabelText('Title'), ' Bug '); await user.type(screen.getByLabelText('Description'), ' Details ')
    await user.click(screen.getByRole('button', { name: 'Submit Report' }))
    await waitFor(() => expect(screen.getByText('failed')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('submits from the description action key while preserving Shift+Enter for newlines', async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<BugReportModal isOpen onClose={vi.fn()} onSubmit={onSubmit} diagnosticData={null} />)

    await user.type(screen.getByLabelText('Title'), ' Mobile submit ')
    const description = screen.getByLabelText('Description')
    await user.type(description, ' Use the keyboard action ')
    expect(description).toHaveAttribute('enterkeyhint', 'send')

    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(description).toHaveValue(' Use the keyboard action \n')

    fireEvent.keyDown(description, { key: 'Enter' })
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('bug', 'Mobile submit', 'Use the keyboard action'))
  })

  it('switches to feature request copy and submits the selected type', async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<BugReportModal isOpen onClose={vi.fn()} onSubmit={onSubmit} diagnosticData={null} />)

    expect(screen.getByRole('radio', { name: 'Bug report' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Feature request' })).not.toBeChecked()
    await user.click(screen.getByRole('radio', { name: 'Feature request' }))
    expect(screen.getByRole('radio', { name: 'Feature request' })).toBeChecked()
    expect(screen.getByRole('heading', { name: 'Request a Feature' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Briefly describe the feature')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('What would you like ComicPile to do, and how would it help?')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Title'), ' Reading timer ')
    await user.type(screen.getByLabelText('Description'), ' Track time per issue. ')
    await user.click(screen.getByRole('button', { name: 'Submit Request' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('feature', 'Reading timer', 'Track time per issue.'))
  })

  it('loads issues and submits an existing issue correction', async () => {
    issues.list.mockResolvedValue({ issues: [{ id: 1, thread_id: 2, issue_number: '1', status: 'unread', read_at: null, created_at: 'now' }], next_page_token: null })
    const onSuccess = vi.fn(); const onClose = vi.fn(); const user = userEvent.setup()
    render(<IssueCorrectionDialog isOpen threadId={2} currentIssueNumber="1" totalIssues={3} threadTitle="Saga" onClose={onClose} onSuccess={onSuccess} />)
    await waitFor(() => expect(screen.getByRole('textbox', { name: /What issue/ })).toHaveValue('1'))
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('creates a missing issue and handles keyboard and close paths', async () => {
    issues.list.mockResolvedValue({ issues: [], next_page_token: null })
    issues.create.mockResolvedValue({ issues: [{ id: 9, thread_id: 2, issue_number: '5', status: 'unread', read_at: null, created_at: 'now' }] })
    const onSuccess = vi.fn(); const onClose = vi.fn(); const user = userEvent.setup()
    render(<IssueCorrectionDialog isOpen threadId={2} currentIssueNumber={null} totalIssues={10} threadTitle="Saga" onClose={onClose} onSuccess={onSuccess} />)
    await waitFor(() => expect(screen.getByText(/What issue/)).toBeInTheDocument())
    const input = screen.getByRole('textbox', { name: /What issue/ })
    await user.clear(input); await user.type(input, '5'); fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(issues.create).toHaveBeenCalled())
    fireEvent.keyDown(document, { key: 'Escape' }); expect(onClose).toHaveBeenCalled()
  })
})
