import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CompletedThreadsSection from '../pages/QueuePage/CompletedThreadsSection'

const completedThreads = [
  {
    id: 2,
    title: 'Descender',
    format: 'Comic',
    notes: 'Finished the main series',
  },
  {
    id: 3,
    title: 'Paper Girls',
    format: 'Trade',
    notes: null,
  },
]

describe('CompletedThreadsSection', () => {
  it('keeps completed thread cards hidden until the user opts in', async () => {
    const user = userEvent.setup()

    render(
      <CompletedThreadsSection
        threads={completedThreads}
        onReactivate={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Completed Threads' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Completed (2)' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.queryByText('Descender')).not.toBeInTheDocument()
    expect(screen.queryByText('Paper Girls')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show Completed (2)' }))

    expect(screen.getByRole('button', { name: 'Hide Completed' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByText('Descender')).toBeInTheDocument()
    expect(screen.getByText('Paper Girls')).toBeInTheDocument()
  })

  it('preserves accessible targeted and picker-based reactivation paths', async () => {
    const user = userEvent.setup()
    const onReactivate = vi.fn()

    render(
      <CompletedThreadsSection
        threads={completedThreads}
        onReactivate={onReactivate}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Show Completed (2)' }))
    await user.click(
      screen.getByRole('button', { name: 'Choose completed thread to reactivate' }),
    )
    await user.click(screen.getByRole('button', { name: 'Reactivate Descender' }))

    expect(onReactivate).toHaveBeenNthCalledWith(1, null)
    expect(onReactivate).toHaveBeenNthCalledWith(2, completedThreads[0])
    expect(screen.getByRole('button', { name: 'Reactivate Paper Girls' })).toBeInTheDocument()
  })

  it('renders nothing when there are no completed threads', () => {
    const { container } = render(
      <CompletedThreadsSection
        threads={[]}
        onReactivate={vi.fn()}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})
