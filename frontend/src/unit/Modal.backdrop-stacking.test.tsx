import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import Modal from '../components/Modal'

it('ignores a lower modal backdrop while a higher modal is open', async () => {
  const user = userEvent.setup()
  const lowerOnClose = vi.fn()
  const upperOnClose = vi.fn()

  const lower = render(
    <Modal isOpen title="Lower" onClose={lowerOnClose}>
      <button type="button">Lower action</button>
    </Modal>,
  )
  const upper = render(
    <Modal isOpen title="Upper" onClose={upperOnClose}>
      <button type="button">Upper action</button>
    </Modal>,
  )

  const lowerBackdrop = lower.container.querySelector('[aria-hidden="true"]')
  const upperBackdrop = upper.container.querySelector('[aria-hidden="true"]')
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
