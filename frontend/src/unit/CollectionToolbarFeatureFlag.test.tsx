import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

vi.mock('../config/featureFlags', () => ({
  collectionsEnabled: false,
}))

vi.mock('../contexts/CollectionContext', () => ({
  useCollections: () => ({
    collections: [],
    activeCollectionId: null,
    setActiveCollectionId: vi.fn(),
    isLoading: false,
    error: null,
  }),
}))

import CollectionToolbar from '../components/CollectionToolbar'

it('renders nothing when collections are disabled', () => {
  const { container } = render(<CollectionToolbar />)

  expect(container).toBeEmptyDOMElement()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})
