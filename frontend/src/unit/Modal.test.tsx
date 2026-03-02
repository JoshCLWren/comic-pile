import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import Modal from '../components/Modal'

it('renders content and handles close actions', async () => {
  const user = userEvent.setup()
  const handleClose = vi.fn()

  const { container } = render(
    <Modal isOpen title="Test Modal" onClose={handleClose}>
      <p>Modal content</p>
    </Modal>
  )

  expect(screen.getByText('Modal content')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /close modal/i }))
  const backdrop = container.querySelector('[aria-hidden="true"]')
  if (!backdrop) {
    throw new Error('Backdrop not found')
  }
  await user.click(backdrop)
  expect(handleClose).toHaveBeenCalled()
})
