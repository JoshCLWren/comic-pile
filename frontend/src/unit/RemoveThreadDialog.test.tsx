import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import RemoveThreadDialog from '../pages/QueuePage/RemoveThreadDialog'
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
    last_activity_at: null,
    last_rating: null,
    notes: null,
    is_test: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('RemoveThreadDialog', () => {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()

  it('renders nothing when no series is pending removal', () => {
    render(
      <RemoveThreadDialog
        thread={null}
        isPending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.queryByText('Remove from Queue')).not.toBeInTheDocument()
  })

  it('separates queue-only removal from permanent deletion', () => {
    render(
      <RemoveThreadDialog
        thread={makeThread()}
        isPending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Remove from Queue' })).toBeInTheDocument()
    expect(screen.getByText(/no longer appear in the active queue or rolls/i)).toBeInTheDocument()
    expect(screen.getByText(/kept everything|keeps everything/i)).toBeInTheDocument()
    expect(screen.getByText(/restore it later/i)).toBeInTheDocument()
    // The destructive alternative is named explicitly so the two actions are
    // never mistaken for each other.
    expect(screen.getByText(/Delete Series/)).toBeInTheDocument()
  })

  it('wires the confirm and cancel actions', async () => {
    const user = userEvent.setup()
    render(
      <RemoveThreadDialog
        thread={makeThread()}
        isPending={false}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Remove from Queue' }))
    expect(onConfirm).toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('labels the confirm action with the pending state and blocks both buttons', () => {
    render(
      <RemoveThreadDialog
        thread={makeThread()}
        isPending={true}
        error={null}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('button', { name: 'Removing...' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()
  })

  it('surfaces a removal error as an actionable inline alert', () => {
    render(
      <RemoveThreadDialog
        thread={makeThread()}
        isPending={false}
        error="Thread 1 is not active and cannot be excluded"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Thread 1 is not active and cannot be excluded',
    )
  })
})