import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingModeSheet } from '../pages/RollPage/components/ReadingModeSheet'

const mocks = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('../services/api', () => ({
  api: { post: mocks.post },
}))

function renderSheet(props: Partial<Parameters<typeof ReadingModeSheet>[0]> = {}) {
  const onClose = vi.fn()
  const onUpdated = vi.fn()
  render(
    <ReadingModeSheet
      isOpen
      activeMode={{ bandwidth: 'balanced', intent: 'balanced', source: null }}
      onClose={onClose}
      onUpdated={onUpdated}
      {...props}
    />,
  )
  return { onClose, onUpdated }
}

describe('ReadingModeSheet', () => {
  beforeEach(() => {
    mocks.post.mockReset()
    mocks.post.mockResolvedValue({})
  })

  it('renders both option groups with active values', () => {
    renderSheet({ activeMode: { bandwidth: 'deep', intent: 'explore', source: null } })

    expect(screen.getByRole('dialog', { name: 'Reading mode selector' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Deep' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Explore' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('submits independent selections without resetting the other dimension', async () => {
    const user = userEvent.setup()
    const { onUpdated, onClose } = renderSheet()

    await user.click(screen.getByRole('button', { name: 'Light' }))
    await user.click(screen.getByRole('button', { name: 'Momentum' }))
    // 'Balanced' exists in both groups: bandwidth selection was cleared, intent preserved.
    const balancedStates = screen
      .getAllByRole('button', { name: 'Balanced' })
      .map((button) => button.getAttribute('aria-pressed'))
    expect(balancedStates).toEqual(['false', 'true'])

    await user.click(screen.getByRole('button', { name: 'Apply Mode' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(mocks.post).toHaveBeenCalledWith('/v1/sessions/current/mode/', {
      bandwidth: 'light',
      intent: 'momentum',
    })
    expect(onUpdated).toHaveBeenCalled()
  })

  it('explains Random as unweighted selection within the current die pool', async () => {
    const user = userEvent.setup()
    renderSheet()

    expect(
      screen.queryByText(/unweighted issue from the current die pool/i),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Random' }))

    expect(screen.getByText(/unweighted issue from the current die pool/i)).toBeInTheDocument()
  })

  it('shows an error and stays open when the API call fails', async () => {
    const user = userEvent.setup()
    const { onClose, onUpdated } = renderSheet()
    mocks.post.mockRejectedValue(new Error('network down'))

    await user.click(screen.getByRole('button', { name: 'Apply Mode' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to update reading mode. Please try again.',
    )
    expect(onClose).not.toHaveBeenCalled()
    expect(onUpdated).not.toHaveBeenCalled()
  })

  it('closes on Escape and focuses the first control when opened', async () => {
    const user = userEvent.setup()
    const { onClose } = renderSheet()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Light' })).toHaveFocus())

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders as a mobile bottom sheet and centers on desktop breakpoints', () => {
    const { container } = renderSheet()
    const backdrop = container.querySelector('[role="dialog"]')

    expect(backdrop).not.toBeNull()
    expect(backdrop?.className).toContain('items-end')
    expect(backdrop?.className).toContain('md:items-center')
    expect(backdrop?.firstElementChild?.className).toContain('rounded-t-2xl')
    expect(backdrop?.firstElementChild?.className).toContain('md:rounded-2xl')
  })
})
