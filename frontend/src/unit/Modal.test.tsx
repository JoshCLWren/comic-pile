import { fireEvent, render, screen } from '@testing-library/react'
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

it('uses a translucent modal surface with a softened overlay', () => {
  const { container } = render(
    <Modal isOpen title="Translucent Modal" onClose={() => {}}>
      <p>Modal content</p>
    </Modal>
  )

  const dialog = screen.getByRole('dialog', { name: 'Translucent Modal' })
  const overlay = container.querySelector('[aria-hidden="true"]')

  expect(dialog).toHaveClass('modal-card')
  expect(dialog.className).toContain('modal-card')
  expect(overlay).not.toBeNull()
  expect(overlay).toHaveClass('backdrop-blur-sm')
})

it('returns null while closed and supports fallback focus without autofocus', async () => {
  const onClose = vi.fn()
  const { rerender } = render(
    <Modal isOpen={false} title="Closed" onClose={onClose}>
      <button type="button">Action</button>
    </Modal>,
  )
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  rerender(
    <Modal isOpen title="Open" onClose={onClose} autoFocus={false} data-testid="modal">
      <button type="button">Action</button>
    </Modal>,
  )
  expect(screen.getByRole('button', { name: /close modal/i })).toHaveFocus()

  const user = userEvent.setup()
  await user.keyboard('{Escape}')
  expect(onClose).toHaveBeenCalledTimes(1)
})

it('wraps focus in both tab directions and restores the trigger focus', async () => {
  const trigger = document.createElement('button')
  trigger.textContent = 'Trigger'
  document.body.append(trigger)
  trigger.focus()
  const { unmount } = render(
    <Modal isOpen title="Focus" onClose={() => {}}>
      <input aria-label="First" />
      <button type="button">Last</button>
    </Modal>,
  )
  const close = screen.getByRole('button', { name: /close modal/i })
  const last = screen.getByRole('button', { name: 'Last' })
  close.focus()
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(last).toHaveFocus()
  last.focus()
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: false })
  expect(close).toHaveFocus()
  unmount()
  expect(trigger).toHaveFocus()
  trigger.remove()
})

it('keeps the root lock until overlapping modals have both closed', () => {
  const root = document.createElement('div')
  root.id = 'root'
  document.body.append(root)
  root.style.overflow = 'auto'
  const first = render(<Modal isOpen title="One" onClose={() => {}}>One</Modal>)
  const second = render(<Modal isOpen title="Two" onClose={() => {}}>Two</Modal>)
  expect(root.style.overflow).toBe('hidden')
  first.rerender(<Modal isOpen={false} title="One" onClose={() => {}}>One</Modal>)
  expect(root.style.overflow).toBe('hidden')
  second.unmount()
  expect(root.style.overflow).toBe('auto')
  root.remove()
})

it('uses the close button as the autofocus fallback', () => {
  render(
    <Modal isOpen title="Empty" onClose={() => {}} autoFocus={false}>
      <p>No controls</p>
    </Modal>,
  )

  expect(screen.getByRole('button', { name: /close modal/i })).toHaveFocus()
})

it('does not wrap focus when tabbing from a middle focusable element', () => {
  // Covers the false arms of the shift/non-shift focus-wrap guards in the keydown handler
  const { container } = render(
    <Modal isOpen title="Focus Wrap" onClose={() => {}}>
      <input aria-label="First field" />
      <input aria-label="Middle field" />
      <button type="button">Last</button>
    </Modal>,
  )
  const middle = container.querySelectorAll('input')[1] as HTMLElement
  middle.focus()
  // shift+tab from a non-first element: activeElement !== firstElement -> no wrap
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  // tab from a non-last element: activeElement !== lastElement -> no wrap
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: false })
  expect(middle).toHaveFocus()
})
