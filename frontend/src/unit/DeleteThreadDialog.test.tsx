import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DeleteThreadDialog from '../pages/QueuePage/DeleteThreadDialog'
import type { Thread } from '../types'

vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
    onClose,
  }: {
    isOpen: boolean
    title: string
    children: React.ReactNode
    onClose: () => void
  }) =>
    isOpen ? (
      <section>
        <h2>{title}</h2>
        <button onClick={onClose}>close modal</button>
        {children}
      </section>
    ) : null,
}))

function makeThread(overrides: Partial<Thread> = {}): Thread {
  return {
    id: 1,
    title: 'Saga',
    format: 'Comic',
    status: 'active',
    queue_position: 1,
    issues_remaining: 1,
    total_issues: null,
    is_blocked: false,
    blocking_reasons: [],
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('DeleteThreadDialog', () => {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when no thread is pending deletion', () => {
    render(
      <DeleteThreadDialog
        thread={null}
        isPending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.queryByText('Delete Series')).not.toBeInTheDocument()
  })

  it('asks for confirmation before the destructive delete and wires the actions', async () => {
    const user = userEvent.setup()
    render(
      <DeleteThreadDialog
        thread={makeThread()}
        isPending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Delete Series' })).toBeInTheDocument()
    const confirmText = screen.getByText((content) =>
      content.includes('Are you sure you want to delete'),
    )
    expect(confirmText).toHaveTextContent('Are you sure you want to delete Saga')

    await user.click(screen.getByRole('button', { name: /delete series/i }))
    expect(onConfirm).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('labels the destructive confirm action with the pending state', () => {
    render(
      <DeleteThreadDialog
        thread={makeThread()}
        isPending={true}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    const confirmButton = screen.getByRole('button', { name: 'Deleting...' })
    expect(confirmButton).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()
  })

  it('surfaces a delete error as an actionable inline alert', () => {
    render(
      <DeleteThreadDialog
        thread={makeThread()}
        isPending={false}
        error="Cannot delete thread: has connected dependencies"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Cannot delete thread: has connected dependencies',
    )
  })
})