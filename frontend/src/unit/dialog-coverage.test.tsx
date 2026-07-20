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
