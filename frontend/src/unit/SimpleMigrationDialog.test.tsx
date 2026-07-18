import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import SimpleMigrationDialog from '../components/SimpleMigrationDialog'

function renderDialog(onComplete = vi.fn(), onClose = vi.fn()) {
  render(<SimpleMigrationDialog threadTitle="Saga" onComplete={onComplete} onClose={onClose} />)
  return { onComplete, onClose }
}

it('focuses its input, validates blank submissions, and submits a supplied issue number', async () => {
  const user = userEvent.setup()
  const { onComplete } = renderDialog()
  const input = screen.getByLabelText(/what issue number/i)

  expect(input).toHaveFocus()
  await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Please enter an issue number')
  expect(onComplete).not.toHaveBeenCalled()

  await user.type(input, '42')
  await user.click(screen.getByRole('button', { name: 'Start Tracking' }))
  expect(onComplete).toHaveBeenCalledWith('42')
})

it('closes from Escape, its close button, and an overlay click', async () => {
  const user = userEvent.setup()
  const { onClose } = renderDialog()

  await user.keyboard('{Escape}')
  await user.click(screen.getByRole('button', { name: 'Close dialog' }))
  await user.click(screen.getByRole('dialog'))

  expect(onClose).toHaveBeenCalledTimes(3)
})
