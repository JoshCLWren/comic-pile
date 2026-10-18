import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QueueControls } from '../pages/QueuePage/QueueControls'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'

describe('QueueControls', () => {
  const baseProps = {
    activeCount: 5,
    shuffleDisabled: false,
    shufflePending: false,
    onShuffle: vi.fn(),
    onCreateThread: vi.fn(),
    onAddFromComicVine: vi.fn(),
    onBulkMapSeries: vi.fn(),
    sortBy: 'position' as QueueSortBy,
    onSortChange: vi.fn(),
    searchQuery: '',
    onSearchChange: vi.fn(),
  }

  it('renders bulk map series button', () => {
    render(<QueueControls {...baseProps} />)

    expect(screen.getByText('Map Series')).toBeInTheDocument()
    expect(screen.getByTestId('queue-bulk-map-desktop')).toBeInTheDocument()
  })

  it('calls onBulkMapSeries when button is clicked', async () => {
    const { user } = await import('@testing-library/user-event')
    const USER = await user.setup()
    render(<QueueControls {...baseProps} />)

    const bulkMapButton = screen.getByText('Map Series')
    await USER.click(bulkMapButton)

    expect(baseProps.onBulkMapSeries).toHaveBeenCalled()
  })

  it('shows disabled state when no threads need mapping', () => {
    const propsWithNoThreads = {
      ...baseProps,
      activeCount: 0,
    }

    render(<QueueControls {...propsWithNoThreads} />)

    const bulkMapButton = screen.getByText('Map Series')
    expect(bulkMapButton).toBeDisabled()
  })
})