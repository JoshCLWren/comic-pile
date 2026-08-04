import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import Modal from '../components/Modal'

it('ignores a lower modal backdrop while a higher modal is open', async () => {
  const user = userEvent.setup()
  const lowerOnClose = vi.fn()
  const upperOnClose = vi.fn()

  render(
    <Modal isOpen title="Lower" onClose={lowerOnClose}>
      <button type="button">Lower action</button>
    </Modal>,
  )
  render(
    <Modal isOpen title="Upper" onClose={upperOnClose}>
      <button type="button">Upper action</button>
    </Modal>,
  )

  const overlayRoot = document.querySelector('[data-overlay-root="true"]')
  const backdrops = overlayRoot?.querySelectorAll('[aria-hidden="true"]')
  const lowerBackdrop = backdrops?.[0]
  const upperBackdrop = backdrops?.[1]
  if (!lowerBackdrop || !upperBackdrop) {
    throw new Error('Expected both modal backdrops to be rendered')
  }

  await user.click(lowerBackdrop)
  expect(lowerOnClose).not.toHaveBeenCalled()
  expect(upperOnClose).not.toHaveBeenCalled()

  await user.click(upperBackdrop)
  expect(upperOnClose).toHaveBeenCalledTimes(1)
  expect(lowerOnClose).not.toHaveBeenCalled()
})
