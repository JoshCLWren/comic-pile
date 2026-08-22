import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MarqueeTitle } from '../components/MarqueeTitle'
import IssueCorrectionDialog from '../components/IssueCorrectionDialog'
import MigrationDialog from '../components/MigrationDialog'

const issuesApi = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), move: vi.fn(), markRead: vi.fn(), markUnread: vi.fn() }))
vi.mock('../services/api-issues', () => ({ issuesApi }))
const migration = vi.hoisted(() => ({ migrateThread: vi.fn() }))
vi.mock('../services/api', () => ({ migrationApi: migration }))

describe('edge component behavior', () => {
  it('renders wrapped title without overflow clipping', () => {
    const { container } = render(<MarqueeTitle title="A title" className="extra" />)
    expect(container).toHaveTextContent('A title')
    const heading = container.querySelector('h3') as HTMLElement
    expect(heading).toHaveClass('whitespace-normal', 'break-words', 'extra')
  })

  it('renders a compact title wrapped properly', () => {
    const { container } = render(<MarqueeTitle title="Fits" />)
    const heading = container.querySelector('h3') as HTMLElement
    expect(heading).toHaveTextContent('Fits')
    expect(heading).toHaveClass('whitespace-normal', 'break-words')
    expect(heading.querySelector('[aria-hidden="true"]')).not.toBeInTheDocument()
  })

  it('corrects existing and newly inserted issue numbers', async () => {
    issuesApi.list.mockResolvedValue({ issues: [
      { id: 1, thread_id: 1, issue_number: '1', status: 'read', read_at: 'now', created_at: 'now' },
      { id: 2, thread_id: 1, issue_number: '2', status: 'unread', read_at: null, created_at: 'now' },
    ], next_page_token: null })
    issuesApi.create.mockResolvedValue({ issues: [{ id: 3, issue_number: 'Special', status: 'unread' }] })
    const onClose = vi.fn(); const onSuccess = vi.fn(); const user = userEvent.setup()
    render(<IssueCorrectionDialog isOpen threadId={1} currentIssueNumber="2" totalIssues={2} threadTitle="Saga" onClose={onClose} onSuccess={onSuccess} />)
    await waitFor(() => expect(screen.getByLabelText('Increase issue number')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Decrease issue number' }))
    await user.click(screen.getByRole('button', { name: 'Update' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('shows migration warnings for near-complete and completed series', async () => {
    const user = userEvent.setup(); migration.migrateThread.mockResolvedValue({ id: 1 })
    const onComplete = vi.fn()
    render(<MigrationDialog thread={{ id: 1, title: 'Saga' }} onComplete={onComplete} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '9')
    await user.type(screen.getByLabelText(/Total Issues/), '10')
    expect(screen.getByRole('status')).toHaveTextContent(/Almost done|One issue away/)
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
  })

  it('validates migration input, previews boundaries, and confirms skipping', async () => {
    const user = userEvent.setup()
    const onSkip = vi.fn()
    const onClose = vi.fn()
    migration.migrateThread.mockRejectedValueOnce(new Error('migration failed'))
    render(<MigrationDialog thread={{ id: 2, title: 'Other' }} onComplete={vi.fn()} onSkip={onSkip} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    expect(screen.getByRole('alert')).toHaveTextContent('fill in both')
    await user.type(screen.getByLabelText(/Last Issue Read/), '0')
    await user.type(screen.getByLabelText(/Total Issues/), '5')
    expect(screen.getByText(/all 5 issues will be marked as unread/i)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('migration failed'))
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Yes, Skip' }))
    expect(onSkip).toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('covers completion warnings and migration boundary validation', async () => {
    const user = userEvent.setup()
    migration.migrateThread.mockResolvedValue({ id: 3 })
    const onComplete = vi.fn()
    const { unmount } = render(<MigrationDialog thread={{ id: 3, title: 'Complete' }} onComplete={onComplete} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '10')
    await user.type(screen.getByLabelText(/Total Issues/), '10')
    expect(screen.getByRole('status')).toHaveTextContent(/Completing the series/)
    expect(screen.getByText(/All 10 issues will be marked as read/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    unmount()

    const onClose = vi.fn()
    render(<MigrationDialog thread={{ id: 4, title: 'Invalid' }} onComplete={vi.fn()} onSkip={vi.fn()} onClose={onClose} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '-1')
    await user.type(screen.getByLabelText(/Total Issues/), '0')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/negative|greater than 0/))
    fireEvent.click(screen.getByRole('dialog'))
    expect(onClose).toHaveBeenCalled()
  })
})
