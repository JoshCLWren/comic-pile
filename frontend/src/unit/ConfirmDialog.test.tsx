import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ConfirmDialog from '../components/ConfirmDialog'

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const props = {
    isOpen: true,
    title: 'Delete custom CBL',
    children: <p>This cannot be undone.</p>,
    confirmLabel: 'Delete custom CBL',
    isPending: false,
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    testId: 'delete-custom-cbl-dialog',
    ...overrides,
  }
  return { ...render(<ConfirmDialog {...props} />), props }
}

describe('ConfirmDialog', () => {
  it('announces a failure inside the still-open dialog', () => {
    renderDialog({ error: 'Unable to delete this Reading List.' })

    expect(screen.getByTestId('delete-custom-cbl-dialog-error')).toHaveTextContent(
      'Unable to delete this Reading List.',
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to delete this Reading List.')
  })

  it('runs cancel and confirm handlers', async () => {
    const user = userEvent.setup()
    const { props } = renderDialog()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(props.onCancel).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('confirm-delete-custom-cbl-dialog'))
    expect(props.onConfirm).toHaveBeenCalledTimes(1)
  })

  it('uses button typography rather than the small uppercase eyebrow treatment', () => {
    renderDialog()

    // docs/FRONTEND_VISUAL_GRAMMAR.md excludes buttons and action text from the
    // uppercase eyebrow treatment reserved for compact status/category labels.
    for (const button of screen.getAllByRole('button')) {
      expect(button.className).not.toMatch(/uppercase|tracking-widest/)
    }
  })

  it('shows the pending label while the action runs and disables both controls', () => {
    renderDialog({ isPending: true, pendingLabel: 'Deleting…' })

    expect(screen.getByTestId('confirm-delete-custom-cbl-dialog')).toHaveTextContent('Deleting…')
    expect(screen.getByTestId('confirm-delete-custom-cbl-dialog')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
})
