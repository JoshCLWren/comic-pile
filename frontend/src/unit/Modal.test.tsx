import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
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

it('keeps focus on a controlled input while typing across parent rerenders', async () => {
  const user = userEvent.setup()

  function TestModal() {
    const [isOpen, setIsOpen] = useState(true)
    const [title, setTitle] = useState('')

    return (
      <Modal isOpen={isOpen} title="Add Thread" onClose={() => setIsOpen(false)}>
        <label htmlFor="thread-title">Title</label>
        <input
          id="thread-title"
          value={title}
          onChange={event => setTitle(event.target.value)}
        />
      </Modal>
    )
  }

  render(<TestModal />)

  const titleInput = screen.getByLabelText('Title')
  const closeButton = screen.getByRole('button', { name: /close modal/i })

  expect(titleInput).toHaveFocus()
  await user.type(titleInput, 'Saga')

  expect(titleInput).toHaveFocus()
  expect(closeButton).not.toHaveFocus()
  expect(titleInput).toHaveValue('Saga')
})

