import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import Tooltip from '../components/Tooltip'

it('shows tooltip content on hover', async () => {
  const user = userEvent.setup()

  render(
    <Tooltip content="Helpful text">
      <button type="button">Hover me</button>
    </Tooltip>
  )

  expect(screen.queryByText('Helpful text')).not.toBeInTheDocument()
  await user.hover(screen.getByRole('button', { name: /hover me/i }))
  expect(screen.getByText('Helpful text')).toBeInTheDocument()
})
