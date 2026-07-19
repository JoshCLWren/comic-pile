import { expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import CollectionDialog from '../components/CollectionDialog'

vi.mock('../config/featureFlags', () => ({ collectionsEnabled: false }))

it('does not render collection controls when collections are disabled', () => {
  const { container } = render(<CollectionDialog collection={null} onClose={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
})
