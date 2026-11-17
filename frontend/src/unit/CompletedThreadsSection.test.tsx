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

    expect(screen.getByRole('heading', { name: 'Finished Series' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Finished (2)' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByText('Descender')).not.toBeVisible()
    expect(screen.getByText('Paper Girls')).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Show Finished (2)' }))

    expect(screen.getByRole('button', { name: 'Hide Finished' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByText('Descender')).toBeVisible()
    expect(screen.getByText('Paper Girls')).toBeVisible()
  })

  it('preserves distinct reactivation paths and collapses after each selection', async () => {
    const user = userEvent.setup()
    const onReactivate = vi.fn()

    render(
      <CompletedThreadsSection
        threads={completedThreads}
        onReactivate={onReactivate}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Add back to queue' }))

    expect(onReactivate).toHaveBeenNthCalledWith(1, null)
    expect(screen.getByRole('button', { name: 'Show Finished (2)' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByText('Descender')).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Show Finished (2)' }))
    await user.click(screen.getByRole('button', { name: 'Add Descender back to queue' }))

    expect(onReactivate).toHaveBeenNthCalledWith(2, completedThreads[0])
    expect(screen.getByRole('button', { name: 'Show Finished (2)' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(
      screen.queryByRole('button', { name: 'Add Paper Girls back to queue' }),
    ).not.toBeInTheDocument()
  })

  it('shows only the loaded count and an explicit next-page action', async () => {
    const user = userEvent.setup()
    const onLoadMore = vi.fn()
    render(
      <CompletedThreadsSection
        threads={completedThreads}
        hasNextPage
        onLoadMore={onLoadMore}
        onReactivate={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Show Finished (2+)' })).toBeInTheDocument()
    expect(screen.getByText('2 finished series loaded, more available')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show Finished (2+)' }))
    await user.click(screen.getByRole('button', { name: 'Load more finished series' }))
    expect(onLoadMore).toHaveBeenCalledOnce()
  })

  it('preserves retry access when a completed collection fails', async () => {
    const user = userEvent.setup()
    const retry = vi.fn()
    render(
      <CompletedThreadsSection
        threads={[]}
        isError
        onRetry={retry}
        onReactivate={vi.fn()}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't load finished series.")
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(retry).toHaveBeenCalledOnce()
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

  it('renders a loading state instead of an empty shelf while the first page loads', () => {
    const { container } = render(
      <CompletedThreadsSection
        threads={[]}
        isLoading
        onReactivate={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Finished Series' })).toBeInTheDocument()
    expect(screen.getByText('Loading finished series...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add back to queue/i })).not.toBeInTheDocument()
    expect(container).not.toBeEmptyDOMElement()
  })
})
