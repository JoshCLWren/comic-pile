import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import MigrationDialog from '../components/MigrationDialog'
import { migrationApi } from '../services/api'

vi.mock('../services/api', () => ({ migrationApi: { migrateThread: vi.fn() } }))

const thread = { id: 7, title: 'Saga' }

describe('MigrationDialog', () => {
  beforeEach(() => vi.clearAllMocks())

  it('validates migration values and previews boundary states', async () => {
    const user = userEvent.setup()
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={vi.fn()} onClose={vi.fn()} />)
    const last = screen.getByLabelText(/Last Issue Read/)
    const total = screen.getByLabelText(/Total Issues/)
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    expect(screen.getByRole('alert')).toHaveTextContent('Please fill in both fields')
    await user.type(last, '0'); await user.type(total, '5')
    expect(screen.getByRole('status')).toHaveTextContent('Starting fresh')
    expect(screen.getByText(/All 5 issues will be marked as unread/)).toBeInTheDocument()
    await user.clear(last); await user.type(last, '4')
    expect(screen.getByRole('status')).toHaveTextContent('One issue away')
    await user.clear(last); await user.type(last, '5')
    expect(screen.getByRole('status')).toHaveTextContent('Completing the series')
    expect(screen.getByText(/All 5 issues will be marked as read/)).toBeInTheDocument()
    fireEvent.change(last, { target: { value: '1' } })
    fireEvent.change(total, { target: { value: '0' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    expect(screen.getByRole('alert')).toHaveTextContent('Total issues must be greater than 0')
    await user.clear(total); await user.type(total, '5'); await user.clear(last); await user.type(last, '6')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    expect(screen.getByRole('alert')).toHaveTextContent('cannot exceed')
  })

  it('submits successfully and exposes API failures and skip confirmation', async () => {
    const user = userEvent.setup(); const onComplete = vi.fn(); const onSkip = vi.fn(); const onClose = vi.fn()
    vi.mocked(migrationApi.migrateThread).mockResolvedValue({ id: 7, title: 'Saga' } as never)
    render(<MigrationDialog thread={thread} onComplete={onComplete} onSkip={onSkip} onClose={onClose} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '2')
    await user.type(screen.getByLabelText(/Total Issues/), '5')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({ id: 7, title: 'Saga' }))

    cleanup()
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={onSkip} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Skip' }))
    await user.click(screen.getByRole('button', { name: 'Yes, Skip' }))
    expect(onSkip).toHaveBeenCalled()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the form usable after a migration request fails', async () => {
    const user = userEvent.setup()
    vi.mocked(migrationApi.migrateThread).mockRejectedValueOnce(new Error('migration unavailable'))
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={vi.fn()} onClose={vi.fn()} />)
    await user.type(screen.getByLabelText(/Last Issue Read/), '1')
    await user.type(screen.getByLabelText(/Total Issues/), '3')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('migration unavailable'))
    expect(screen.getByRole('button', { name: 'Start Tracking' })).toBeEnabled()
  })

  it('reports numeric validation errors and Axios response messages', async () => {
    const user = userEvent.setup()
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={vi.fn()} onClose={vi.fn()} />)
    const last = screen.getByLabelText(/Last Issue Read/)
    const total = screen.getByLabelText(/Total Issues/)
    await user.type(last, '-1')
    await user.type(total, '2')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    expect(screen.getByRole('alert')).toHaveTextContent('cannot be negative')
    await user.clear(last); await user.type(last, 'abc')
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    expect(screen.getByRole('alert')).toHaveTextContent('Please fill in both fields')
    await user.clear(last); await user.type(last, '1')
    vi.mocked(migrationApi.migrateThread).mockRejectedValueOnce(
      new axios.AxiosError('fallback message', 'ERR_BAD_REQUEST', undefined, undefined, { data: { message: 'message detail' }, status: 400, statusText: 'Bad Request', headers: {}, config: {} } as never),
    )
    fireEvent.submit(screen.getByRole('button', { name: 'Start Tracking' }).closest('form')!)
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('message detail'))
  })

  it('closes on a backdrop click and cancels an Escape skip confirmation', async () => {
    const onClose = vi.fn()
    render(<MigrationDialog thread={thread} onComplete={vi.fn()} onSkip={vi.fn()} onClose={onClose} />)
    const dialog = screen.getByRole('dialog')
    fireEvent.click(dialog, { target: dialog, currentTarget: dialog })
    expect(onClose).toHaveBeenCalled()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Skip' }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText(/Skip migration/)).not.toBeInTheDocument()
  })

})
