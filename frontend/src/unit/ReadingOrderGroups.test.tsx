import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingOrderGroups } from '../pages/RollPage/components/ReadingOrderGroups'
import { useDependencyGroups } from '../hooks/useDependencyGroups'

vi.mock('../hooks/useDependencyGroups', () => ({
  useDependencyGroups: vi.fn(),
}))

const mockedUseDependencyGroups = vi.mocked(useDependencyGroups)

describe('ReadingOrderGroups', () => {
  beforeEach(() => {
    mockedUseDependencyGroups.mockReset()
  })

  it('renders nothing when there is no active thread', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })

    const { container } = render(<ReadingOrderGroups threadId={null} />)

    expect(container).toBeEmptyDOMElement()
    expect(mockedUseDependencyGroups).toHaveBeenCalledWith(null)
  })

  it('announces crossover loading without showing stale names', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: true, error: null })

    render(<ReadingOrderGroups threadId={17} />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading crossovers')
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('renders an accessible crossover error state', () => {
    mockedUseDependencyGroups.mockReturnValue({
      groups: [],
      isLoading: false,
      error: new Error('network failed'),
    })

    render(<ReadingOrderGroups threadId={17} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load crossovers.')
  })

  it('does not add an empty section for threads without crossovers', () => {
    mockedUseDependencyGroups.mockReturnValue({ groups: [], isLoading: false, error: null })

    const { container } = render(<ReadingOrderGroups threadId={17} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('renders every owned crossover name and preserves long-name wrapping', () => {
    mockedUseDependencyGroups.mockReturnValue({
      groups: [
        { id: 1, name: 'Bwa Haha-era Justice League' },
        { id: 2, name: 'A deliberately long crossover name for narrow mobile screens' },
      ],
      isLoading: false,
      error: null,
    })

    render(<ReadingOrderGroups threadId={17} />)

    expect(screen.getByRole('heading', { name: 'Crossovers' })).toBeInTheDocument()
    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getByText('Bwa Haha-era Justice League')).toBeInTheDocument()
    expect(
      screen.getByText('A deliberately long crossover name for narrow mobile screens'),
    ).toHaveClass('break-words')
  })
})
