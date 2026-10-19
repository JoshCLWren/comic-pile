import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueueControls } from '../pages/QueuePage/QueueControls'
import type { QueueSortBy } from '../pages/QueuePage/useQueueFilters'

const baseProps = {
  activeCount: 5,
  shuffleDisabled: false,
  shufflePending: false,
  onShuffle: vi.fn(),
  onCreateThread: vi.fn(),
  onAddFromComicVine: vi.fn(),
  onBulkMapSeries: vi.fn(),
  // SAFETY: test fixture uses the valid default sort option
  sortBy: 'position' as QueueSortBy,
  onSortChange: vi.fn(),
  searchQuery: '',
  onSearchChange: vi.fn(),
}

describe('QueueControls bulk mapping entry point', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders both the desktop and mobile bulk map actions', () => {
    render(<QueueControls {...baseProps} />)

    expect(screen.getByTestId('queue-bulk-map-desktop')).toBeInTheDocument()
    expect(screen.getByTestId('queue-bulk-map-mobile')).toBeInTheDocument()
  })

  it('calls onBulkMapSeries from the desktop action', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)

    await user.click(screen.getByTestId('queue-bulk-map-desktop'))

    expect(baseProps.onBulkMapSeries).toHaveBeenCalledTimes(1)
  })

  it('calls onBulkMapSeries from the mobile action', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} />)

    await user.click(screen.getByTestId('queue-bulk-map-mobile'))

    expect(baseProps.onBulkMapSeries).toHaveBeenCalledTimes(1)
  })

  it('disables both actions when no series need mapping', async () => {
    const user = userEvent.setup()
    render(<QueueControls {...baseProps} bulkMapDisabled />)

    const desktop = screen.getByTestId('queue-bulk-map-desktop')
    const mobile = screen.getByTestId('queue-bulk-map-mobile')
    expect(desktop).toBeDisabled()
    expect(mobile).toBeDisabled()

    await user.click(desktop)
    expect(baseProps.onBulkMapSeries).not.toHaveBeenCalled()
  })
})
