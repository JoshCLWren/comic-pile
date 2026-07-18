import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const collectionsApi = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(),
}))
vi.mock('../config/featureFlags', () => ({ collectionsEnabled: true }))
vi.mock('../services/api', () => ({ collectionsApi }))

import { CollectionProvider, useCollections } from '../contexts/CollectionContext'
import { CollectionBadge } from '../pages/QueuePage/CollectionBadge'

function Consumer() {
  const value = useCollections()
  return <>
    <span data-testid="collections">{value.collections.map((c) => c.name).join(',')}</span>
    <span data-testid="active">{String(value.activeCollectionId)}</span>
    <span data-testid="loading">{String(value.isLoading)}</span>
    <span data-testid="error">{value.error?.message ?? ''}</span>
    <button onClick={() => value.setActiveCollectionId(2)}>select</button>
    <button onClick={() => value.setActiveCollectionId(null)}>clear</button>
    <button onClick={() => void value.createCollection({ name: 'New', position: 3 })}>create</button>
    <button onClick={() => void value.updateCollection(1, { name: 'Renamed' })}>update</button>
    <button onClick={() => void value.deleteCollection(2)}>delete</button>
    <button onClick={() => void value.moveCollection(1, 9)}>move</button>
    <button onClick={value.retry}>retry</button>
    <CollectionBadge collectionId={1} />
    <CollectionBadge collectionId={99} />
  </>
}

describe('enabled collection provider', () => {
  const storage = new Map<string, string>()
  beforeEach(() => {
    vi.clearAllMocks()
    storage.clear()
    Object.defineProperty(window, 'localStorage', { configurable: true, value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    } })
    collectionsApi.list.mockResolvedValue({ collections: [
      { id: 2, name: 'Second', position: 2 }, { id: 1, name: 'First', position: 1 },
    ] })
    collectionsApi.create.mockResolvedValue({})
    collectionsApi.update.mockResolvedValue({})
    collectionsApi.delete.mockResolvedValue({})
  })

  it('loads, sorts, selects, persists, mutates, and renders badges', async () => {
    render(<CollectionProvider><Consumer /></CollectionProvider>)
    await waitFor(() => expect(screen.getByTestId('collections')).toHaveTextContent('First,Second'))
    expect(screen.getByTestId('collection-badge')).toHaveTextContent('First')
    fireEvent.click(screen.getByRole('button', { name: 'select' }))
    expect(localStorage.getItem('comic_pile_active_collection_id')).toBe('2')
    fireEvent.click(screen.getByRole('button', { name: 'clear' }))
    expect(localStorage.getItem('comic_pile_active_collection_id')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'create' }))
    fireEvent.click(screen.getByRole('button', { name: 'update' }))
    fireEvent.click(screen.getByRole('button', { name: 'delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'move' }))
    await waitFor(() => expect(collectionsApi.update).toHaveBeenCalledWith(1, { position: 9 }))
    expect(collectionsApi.create).toHaveBeenCalledWith({ name: 'New', position: 3 })
    expect(collectionsApi.delete).toHaveBeenCalledWith(2)
  })

  it('loads a stored active collection and reports errors', async () => {
    window.localStorage.setItem('comic_pile_active_collection_id', '2')
    collectionsApi.list.mockRejectedValueOnce({ response: { status: 401, data: { detail: 'Nope' } } })
    render(<CollectionProvider><Consumer /></CollectionProvider>)
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('Nope'))
    expect(screen.getByTestId('active')).toHaveTextContent('2')
    fireEvent.click(screen.getByRole('button', { name: 'retry' }))
    await waitFor(() => expect(collectionsApi.list).toHaveBeenCalledTimes(2))
  })
})
