import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import CollectionToolbar from '../components/CollectionToolbar'

const mockCollections = [
  { id: 1, name: 'Collection 1', is_default: true, position: 0 },
  { id: 2, name: 'Collection 2', is_default: false, position: 1 },
]

const mockUseCollections = vi.fn()

vi.mock('../contexts/CollectionContext', () => ({
  useCollections: () => mockUseCollections(),
}))

it('renders loading state', () => {
  mockUseCollections.mockReturnValue({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: true,
    error: null,
  })

  render(<CollectionToolbar />)

  expect(screen.getByText('Loading collections...')).toBeInTheDocument()
})

it('renders collections when loaded', () => {
  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar />)

  expect(screen.getByLabelText('Filter by collection')).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'All Collections' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Collection 1 ★' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Collection 2' })).toBeInTheDocument()
})

it('displays new collection button when showNewLabel and onNewCollection are provided', () => {
  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar showNewLabel={true} onNewCollection={vi.fn()} />)

  expect(screen.getByRole('button', { name: 'Create new collection' })).toBeInTheDocument()
})

it('does not display new collection button when showNewLabel is false', () => {
  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar showNewLabel={false} onNewCollection={vi.fn()} />)

  expect(screen.queryByRole('button', { name: 'Create new collection' })).not.toBeInTheDocument()
})

it('does not display new collection button when onNewCollection is not provided', () => {
  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar showNewLabel={true} />)

  expect(screen.queryByRole('button', { name: 'Create new collection' })).not.toBeInTheDocument()
})

it('calls onNewCollection when new collection button is clicked', async () => {
  const user = userEvent.setup()
  const onNewCollection = vi.fn()

    mockUseCollections.mockReturnValue({
      collections: mockCollections,
      activeCollectionId: null,
      setActiveCollectionId: vi.fn(),
      isLoading: false,
      error: null,
    })

    render(<CollectionToolbar showNewLabel={true} onNewCollection={onNewCollection} />)

    const button = screen.getByRole('button', { name: 'Create new collection' })
    await user.click(button)

  expect(onNewCollection).toHaveBeenCalledTimes(1)
})

it('handles collection selection change', async () => {
  const user = userEvent.setup()
  const setActiveCollectionId = vi.fn()

  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId,
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar />)

  const selector = screen.getByLabelText('Filter by collection')
  await user.selectOptions(selector, '1')

  expect(setActiveCollectionId).toHaveBeenCalledWith(1)
})

it('handles "All Collections" selection', async () => {
  const user = userEvent.setup()
  const setActiveCollectionId = vi.fn()

  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: 1,
    setActiveCollectionId,
    isLoading: false,
    error: null,
  })

  render(<CollectionToolbar />)

  const selector = screen.getByLabelText('Filter by collection')
  await user.selectOptions(selector, 'all')

  expect(setActiveCollectionId).toHaveBeenCalledWith(null)
})

it('displays error state when error is present', () => {
  mockUseCollections.mockReturnValue({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: { message: 'Failed to load collections', status: 500 },
  })

  render(<CollectionToolbar />)

  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByText('Error: Failed to load collections')).toBeInTheDocument()
})

it('applies custom className', () => {
  mockUseCollections.mockReturnValue({
    collections: mockCollections,
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  })

  const { container } = render(<CollectionToolbar className="custom-class" />)

  const toolbar = container.querySelector('.collection-toolbar')
  expect(toolbar).toHaveClass('custom-class')
})
