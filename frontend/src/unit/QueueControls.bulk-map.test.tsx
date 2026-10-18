import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import QueueControls from '../pages/QueuePage/QueueControls'

describe('QueueControls', () => {
  const defaultProps = {
    activeCount: 5,
    shuffleDisabled: false,
    shufflePending: false,
    onShuffle: jest.fn(),
    onCreateThread: jest.fn(),
    onAddFromComicVine: jest.fn(),
    onBulkMapSeries: jest.fn(),
    sortBy: 'position' as const,
    onSortChange: jest.fn(),
    searchQuery: '',
    onSearchChange: jest.fn(),
  }

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('renders bulk map series button', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueControls {...defaultProps} />
      </QueryClientProvider>
    )

    expect(screen.getByText('Map Series')).toBeInTheDocument()
    expect(screen.getByTestId('queue-bulk-map-desktop')).toBeInTheDocument()
  })

  it('calls onBulkMapSeries when button is clicked', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <QueueControls {...defaultProps} />
      </QueryClientProvider>
    )

    const bulkMapButton = screen.getByText('Map Series')
    bulkMapButton.click()

    expect(defaultProps.onBulkMapSeries).toHaveBeenCalled()
  })

  it('shows disabled state when no threads need mapping', () => {
    const propsWithNoThreads = {
      ...defaultProps,
      activeCount: 0,
    }

    render(
      <QueryClientProvider client={queryClient}>
        <QueueControls {...propsWithNoThreads} />
      </QueryClientProvider>
    )

    const bulkMapButton = screen.getByText('Map Series')
    expect(bulkMapButton).toBeDisabled()
  })
})