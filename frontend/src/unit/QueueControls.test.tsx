import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueueControls } from '../pages/QueuePage/QueueControls'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'

const baseProps = {
  activeCount: 3,
  shuffleDisabled: false,
  shufflePending: false,
  onShuffle: vi.fn(),
  onCreateThread: vi.fn(),
  sortBy: 'position' as QueueSortBy,
  onSortChange: vi.fn(),
  searchQuery: '',
  onSearchChange: vi.fn(),
}

const flushDebounce = async () => {
  await waitFor(
    () => {
      expect(baseProps.onSearchChange).toHaveBeenCalled()
    },
    { timeout: 1000 },
  )
}

describe('QueueControls', () => {
  beforeEach(() => {
    baseProps.onShuffle.mockClear()
    baseProps.onCreateThread.mockClear()
    baseProps.onSortChange.mockClear()
    baseProps.onSearchChange.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces search input and only commits after the delay', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)
    const input = screen.getByPlaceholderText('Search...')

    await user.type(input, 'batman')
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()

    await flushDebounce()
    expect(baseProps.onSearchChange).toHaveBeenCalledTimes(1)
    expect(baseProps.onSearchChange).toHaveBeenLastCalledWith('batman')
  })

  it('cancels a pending debounce when the user types again', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)
    const input = screen.getByPlaceholderText('Search...')

    await user.type(input, 'b')
    await user.type(input, 'a')
    await user.type(input, 't')
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()

    await flushDebounce()
    expect(baseProps.onSearchChange).toHaveBeenCalledTimes(1)
    expect(baseProps.onSearchChange).toHaveBeenLastCalledWith('bat')
  })

  it('commits immediately when the user presses Enter with a pending debounce', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)
    const input = screen.getByPlaceholderText('Search...')

    await user.type(input, 'spider')
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() =>
      expect(baseProps.onSearchChange).toHaveBeenCalledWith('spider'),
    )
    expect(baseProps.onSearchChange).toHaveBeenCalledTimes(1)

    await new Promise((r) => setTimeout(r, 400))
    expect(baseProps.onSearchChange).toHaveBeenCalledTimes(1)
  })

  it('does nothing on Enter when the field is empty (non-Enter branch coverage)', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)
    const input = screen.getByPlaceholderText('Search...')

    fireEvent.keyDown(input, { key: 'a' })
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()
  })

  it('handles Enter when no debounce is pending', async () => {
    render(<QueueControls {...baseProps} searchQuery="iron" />)
    const input = screen.getByPlaceholderText('Search...')

    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() =>
      expect(baseProps.onSearchChange).toHaveBeenCalledWith('iron'),
    )
  })

  it('commits a pending value on blur when local differs from committed', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} searchQuery="" />)
    const input = screen.getByPlaceholderText('Search...')

    await user.type(input, 'hulk')
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()

    fireEvent.blur(input)
    await waitFor(() =>
      expect(baseProps.onSearchChange).toHaveBeenCalledWith('hulk'),
    )
  })

  it('commits on blur when local differs and no debounce is pending', async () => {
    render(<QueueControls {...baseProps} searchQuery="old" />)
    const input = screen.getByPlaceholderText('Search...') as HTMLInputElement

    fireEvent.change(input, { target: { value: 'new' } })
    fireEvent.blur(input)

    await waitFor(() =>
      expect(baseProps.onSearchChange).toHaveBeenCalledWith('new'),
    )
  })

  it('does not commit on blur when local matches committed', async () => {
    render(<QueueControls {...baseProps} searchQuery="vision" />)
    const input = screen.getByPlaceholderText('Search...')

    expect(input).toHaveValue('vision')
    fireEvent.blur(input)
    await new Promise((r) => setTimeout(r, 400))
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()
  })

  it('syncs local value when searchQuery prop changes externally', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<QueueControls {...baseProps} searchQuery="" />)
    const input = screen.getByPlaceholderText('Search...') as HTMLInputElement

    await user.type(input, 'typed-')
    rerender(<QueueControls {...baseProps} searchQuery="from-parent" />)
    expect(input).toHaveValue('from-parent')
  })

  it('clears pending debounce timer on unmount', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<QueueControls {...baseProps} />)
    const input = screen.getByPlaceholderText('Search...')

    await user.type(input, 'gone')
    unmount()
    await new Promise((r) => setTimeout(r, 400))
    expect(baseProps.onSearchChange).not.toHaveBeenCalled()
  })

  it('invokes shuffle, create, and sort callbacks', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)

    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    expect(baseProps.onShuffle).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('queue-add-thread-desktop'))
    expect(baseProps.onCreateThread).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'A-Z' }))
    expect(baseProps.onSortChange).toHaveBeenCalledWith('alphabetical')
    await user.click(screen.getByRole('button', { name: 'New' }))
    expect(baseProps.onSortChange).toHaveBeenCalledWith('created')
  })
})