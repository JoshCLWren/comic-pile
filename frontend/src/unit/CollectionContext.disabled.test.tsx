import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

vi.mock('../config/featureFlags', () => ({ collectionsEnabled: false }))
vi.mock('../services/api', () => ({ collectionsApi: { list: vi.fn() } }))

import { CollectionProvider, useCollections } from '../contexts/CollectionContext'

function Consumer() {
  const value = useCollections()
  return (
    <>
      <span data-testid="state">{`${value.collections.length}:${value.activeCollectionId}:${value.isLoading}`}</span>
      <button onClick={() => value.setActiveCollectionId(1)}>select</button>
      <button onClick={() => void value.createCollection({ name: 'x', position: 1 })}>create</button>
      <button onClick={() => void value.updateCollection(1, { name: 'x' })}>update</button>
      <button onClick={() => void value.deleteCollection(1)}>delete</button>
      <button onClick={() => void value.moveCollection(1, 2)}>move</button>
      <button onClick={value.retry}>retry</button>
    </>
  )
}

it('provides safe no-op collection operations when the feature is disabled', () => {
  render(<CollectionProvider><Consumer /></CollectionProvider>)
  expect(screen.getByTestId('state')).toHaveTextContent('0:null:false')
  for (const name of ['select', 'create', 'update', 'delete', 'move', 'retry']) {
    fireEvent.click(screen.getByRole('button', { name }))
  }
  expect(screen.getByTestId('state')).toHaveTextContent('0:null:false')
})

it('rejects using the collection hook outside its provider', () => {
  expect(() => render(<Consumer />)).toThrow('useCollections must be used within a CollectionProvider')
})
