import { render, screen, fireEvent } from '@testing-library/react'
import { DegradedServiceState, ServiceUnavailableShell } from '../components/DegradedServiceState'
import { AuthStatus } from '../services/authState'

describe('DegradedServiceState', () => {
  const mockOnRetry = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders service unavailable state with default message', () => {
    render(
      <DegradedServiceState 
        type="service_unavailable" 
        onRetry={mockOnRetry} 
      />
    )

    expect(screen.getByText('Service Unavailable')).toBeInTheDocument()
    expect(screen.getByText('ComicPile is temporarily unavailable')).toBeInTheDocument()
    expect(screen.getByText("Your session is still active. You don't need to login again.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('renders network error state with default message', () => {
    render(
      <DegradedServiceState 
        type="network_error" 
        onRetry={mockOnRetry} 
      />
    )

    expect(screen.getByText('Connection Issue')).toBeInTheDocument()
    expect(screen.getByText("Can't reach ComicPile")).toBeInTheDocument()
    expect(screen.getByText("Your session is still active. You don't need to login again.")).toBeInTheDocument()
  })

  it('renders custom message when provided', () => {
    const customMessage = 'Custom error message'
    render(
      <DegradedServiceState 
        type="service_unavailable" 
        message={customMessage}
        onRetry={mockOnRetry} 
      />
    )

    expect(screen.getByText(customMessage)).toBeInTheDocument()
  })

  it('calls onRetry when button is clicked', () => {
    render(
      <DegradedServiceState 
        type="service_unavailable" 
        onRetry={mockOnRetry} 
      />
    )

    const button = screen.getByRole('button', { name: 'Try again' })
    fireEvent.click(button)

    expect(mockOnRetry).toHaveBeenCalledTimes(1)
  })

  it('disables button and shows loading state when isRetrying is true', () => {
    render(
      <DegradedServiceState 
        type="service_unavailable" 
        onRetry={mockOnRetry}
        isRetrying={true}
      />
    )

    const button = screen.getByRole('button', { name: 'Retrying...' })
    expect(button).toBeDisabled()
    expect(button).toHaveTextContent('Retrying...')
  })
})

describe('ServiceUnavailableShell', () => {
  const mockOnRetry = vi.fn()

  const TestChild = () => <div>Child content</div>

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when no service state is active', () => {
    const { container } = render(
      <ServiceUnavailableShell 
        serviceUnavailable={false}
        networkError={false}
        onRetry={mockOnRetry}
      >
        <TestChild />
      </ServiceUnavailableShell>
    )

    expect(screen.getByText('Child content')).toBeInTheDocument()
    expect(container.querySelector('.fixed')).toBeNull()
  })

  it('renders children and degraded state for service unavailable', () => {
    const { container } = render(
      <ServiceUnavailableShell 
        serviceUnavailable={true}
        networkError={false}
        onRetry={mockOnRetry}
      >
        <TestChild />
      </ServiceUnavailableShell>
    )

    expect(screen.getByText('Child content')).toBeInTheDocument()
    expect(screen.getByText('Service Unavailable')).toBeInTheDocument()
    expect(container.querySelector('.fixed')).toBeInTheDocument()
  })

  it('renders children and degraded state for network error', () => {
    const { container } = render(
      <ServiceUnavailableShell 
        serviceUnavailable={false}
        networkError={true}
        onRetry={mockOnRetry}
      >
        <TestChild />
      </ServiceUnavailableShell>
    )

    expect(screen.getByText('Child content')).toBeInTheDocument()
    expect(screen.getByText('Connection Issue')).toBeInTheDocument()
    expect(container.querySelector('.fixed')).toBeInTheDocument()
  })

  it('calls onRetry when retry button is clicked in shell', () => {
    render(
      <ServiceUnavailableShell 
        serviceUnavailable={true}
        networkError={false}
        onRetry={mockOnRetry}
      >
        <TestChild />
      </ServiceUnavailableShell>
    )

    const button = screen.getByRole('button', { name: 'Try again' })
    fireEvent.click(button)

    expect(mockOnRetry).toHaveBeenCalledTimes(1)
  })
})