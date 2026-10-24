import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { QueueBoundaryNotice } from '../pages/QueuePage/QueueBoundaryNotice'

it('shows one batch failure with a working retry and clears after recovery', async () => {
  const onRetry = vi.fn()
  const { rerender } = render(<QueueBoundaryNotice isError onRetry={onRetry} />)
  expect(screen.getAllByRole('alert')).toHaveLength(1)
  expect(screen.getByRole('alert')).toHaveTextContent('Rows fall back to their recorded prerequisites.')
  await userEvent.click(screen.getByRole('button', { name: 'Retry reading boundaries' }))
  expect(onRetry).toHaveBeenCalledTimes(1)
  rerender(<QueueBoundaryNotice isError={false} onRetry={onRetry} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
