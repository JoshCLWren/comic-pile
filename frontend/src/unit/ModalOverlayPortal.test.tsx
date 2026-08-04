import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import Modal from '../components/Modal'

afterEach(() => {
  cleanup()
})

it('mounts an open modal beneath the shared document overlay root', async () => {
  render(
    <Modal isOpen title="Edit thread" onClose={vi.fn()}>
      <button type="button">Save</button>
    </Modal>,
  )

  const dialog = await screen.findByRole('dialog', { name: 'Edit thread' })
  const overlayRoot = document.querySelector('[data-overlay-root="true"]')

  expect(overlayRoot).not.toBeNull()
  expect(overlayRoot?.parentElement).toBe(document.body)
  expect(overlayRoot?.contains(dialog)).toBe(true)
})

it('keeps the shared root until the last overlapping modal unmounts', async () => {
  const { rerender } = render(
    <>
      <Modal isOpen title="First modal" onClose={vi.fn()}>
        First
      </Modal>
      <Modal isOpen title="Second modal" onClose={vi.fn()}>
        Second
      </Modal>
    </>,
  )

  await screen.findByRole('dialog', { name: 'Second modal' })
  expect(document.querySelector('[data-overlay-root="true"]')).not.toBeNull()

  rerender(
    <>
      <Modal isOpen={false} title="First modal" onClose={vi.fn()}>
        First
      </Modal>
      <Modal isOpen title="Second modal" onClose={vi.fn()}>
        Second
      </Modal>
    </>,
  )

  expect(document.querySelector('[data-overlay-root="true"]')).not.toBeNull()

  rerender(
    <>
      <Modal isOpen={false} title="First modal" onClose={vi.fn()}>
        First
      </Modal>
      <Modal isOpen={false} title="Second modal" onClose={vi.fn()}>
        Second
      </Modal>
    </>,
  )

  await waitFor(() => {
    expect(document.querySelector('[data-overlay-root="true"]')).toBeNull()
  })
})

it('preserves topmost backdrop dismissal after portaling', async () => {
  const user = userEvent.setup()
  const closeFirst = vi.fn()
  const closeSecond = vi.fn()

  render(
    <>
      <Modal isOpen title="First modal" onClose={closeFirst}>
        First
      </Modal>
      <Modal isOpen title="Second modal" onClose={closeSecond}>
        Second
      </Modal>
    </>,
  )

  const dialogs = await screen.findAllByRole('dialog')
  const firstBackdrop = dialogs[0].previousElementSibling as HTMLElement
  const secondBackdrop = dialogs[1].previousElementSibling as HTMLElement

  await user.click(firstBackdrop)
  expect(closeFirst).not.toHaveBeenCalled()

  await user.click(secondBackdrop)
  expect(closeSecond).toHaveBeenCalledTimes(1)
})
