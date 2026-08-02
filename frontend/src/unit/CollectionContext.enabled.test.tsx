import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CollectionProvider, useCollections } from '../contexts/CollectionContext'
import { CollectionBadge } from '../pages/QueuePage/CollectionBadge'

const collectionsApi = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), delete: vi.fn(),
}))
vi.mock('../services/api', () => ({ collectionsApi }))

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          const e = error as {
            response?: { status?: number; data?: { detail?: string } }
            data?: { detail?: string }
          }
          if (e?.response?.status === 401) return false
          if (
            e?.response?.status === 403
            && e?.response?.data?.detail === 'Not authenticated'
          ) {
            return false
          }
          return failureCount < 3
        },
        staleTime: 0,
        gcTime: 0,
      },
      mutations: { retry: false },
    },
  })
}

function TestWrapper({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => createTestQueryClient())
  return (
    <QueryClientProvider client={client}>
      <CollectionProvider>{children}</CollectionProvider>
    </QueryClientProvider>
  )
}

function Consumer() {
  const value = useCollections()
  return <>
    <span data-testid="collections">{value.collections.map((c) => c.name).join(',')}</span>
    <span data-testid="active">{String(value.activeCollectionId)}</span>
    <span data-testid="loading">{String(value.isLoading)}</span>
    <span data-testid="error">{value.error?.message ?? ''}</span>
    <button onClick={() => value.setActiveCollectionId(2)}>select</button>
    <button onClick={() => value.setActiveCollectionId(1)}>select-first</button>
    <button onClick={() => value.setActiveCollectionId(null)}>clear</button>
    <button onClick={() => { void value.createCollection({ name: 'New', position: 3 }).catch(() => {}) }}>create</button>
    <button onClick={() => { void value.updateCollection(1, { name: 'Renamed' }).catch(() => {}) }}>update</button>
    <button onClick={() => { void value.deleteCollection(2).catch(() => {}) }}>delete</button>
    <button onClick={() => { value.setActiveCollectionId(1); void value.deleteCollection(1).catch(() => {}) }}>delete-active</button>
    <button onClick={() => { void value.moveCollection(1, 9).catch(() => {}) }}>move</button>
    <button onClick={value.retry}>retry</button>
    <CollectionBadge collectionId={1} />
    <CollectionBadge collectionId={99} />
  </>
}

describe('enabled collection provider', () => {
  afterEach(() => vi.useRealTimers())
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
    render(<TestWrapper><Consumer /></TestWrapper>)
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
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      window.localStorage.setItem('comic_pile_active_collection_id', '2')
      collectionsApi.list.mockRejectedValue({ response: { status: 401, data: { detail: 'Nope' } } })
      render(<TestWrapper><Consumer /></TestWrapper>)
      await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('Nope'))
      expect(screen.getByTestId('active')).toHaveTextContent('2')
      fireEvent.click(screen.getByRole('button', { name: 'retry' }))
      await waitFor(() => expect(collectionsApi.list).toHaveBeenCalledTimes(2))
      expect(consoleError).not.toHaveBeenCalledWith(expect.stringContaining('Failed to fetch collections:'), expect.anything())
    } finally {
      consoleError.mockRestore()
    }
  })

  it('clears the active selection when the selected collection is deleted', async () => {
    render(<TestWrapper><Consumer /></TestWrapper>)
    await waitFor(() => expect(screen.getByTestId('collections')).toHaveTextContent('First,Second'))
    fireEvent.click(screen.getByRole('button', { name: 'select-first' }))
    fireEvent.click(screen.getByRole('button', { name: 'delete-active' }))
    await waitFor(() => expect(collectionsApi.delete).toHaveBeenCalledWith(1))
    expect(screen.getByTestId('active')).toHaveTextContent('null')
    expect(localStorage.getItem('comic_pile_active_collection_id')).toBeNull()
  })

  it('retries transient load errors and always clears loading after mutation failures', async () => {
    vi.useFakeTimers()
    collectionsApi.list.mockRejectedValue(new Error('temporary'))
    collectionsApi.create.mockResolvedValue({})
    render(<TestWrapper><Consumer /></TestWrapper>)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    expect(collectionsApi.list).toHaveBeenCalled()
    vi.useRealTimers()

    collectionsApi.list.mockResolvedValue({ collections: [] })
    fireEvent.click(screen.getByRole('button', { name: 'create' }))
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    fireEvent.click(screen.getByRole('button', { name: 'delete-active' }))
    await waitFor(() => expect(collectionsApi.delete).toHaveBeenCalledWith(1))
  })

  it('keeps provider usable when collection mutations fail and stored state is invalid', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    window.localStorage.setItem('comic_pile_active_collection_id', 'not-a-number')
    collectionsApi.list.mockResolvedValueOnce({})
    render(<TestWrapper><Consumer /></TestWrapper>)
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
    expect(screen.getByTestId('collections')).toHaveTextContent('')

    collectionsApi.create.mockRejectedValueOnce(new Error('create failed'))
    collectionsApi.update.mockRejectedValueOnce(new Error('update failed'))
    collectionsApi.delete.mockRejectedValueOnce(new Error('delete failed'))
    await user.click(screen.getByRole('button', { name: 'create' }))
    await user.click(screen.getByRole('button', { name: 'update' }))
    await user.click(screen.getByRole('button', { name: 'delete' }))
    await user.click(screen.getByRole('button', { name: 'move' }))
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))
  })

  it('uses the generic load error when an API error has no message', async () => {
    vi.useFakeTimers()
    collectionsApi.list.mockRejectedValue({ response: { status: 500 } })
    render(<TestWrapper><Consumer /></TestWrapper>)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(4000)
    await vi.runAllTimersAsync()
    expect(screen.getByTestId('error')).toHaveTextContent('Failed to load collections')
  })

  it('createCollection resolves only after collections refetch completes', async () => {
    let resolveListCall: (value: unknown) => void = () => {
      throw new Error('Expected the collections refetch to start')
    }
    let listCallCount = 0

    collectionsApi.list.mockImplementation(() => {
      listCallCount++
      if (listCallCount === 1) {
        return Promise.resolve({ collections: [{ id: 1, name: 'Initial', position: 1 }] })
      }
      return new Promise((resolve) => {
        resolveListCall = resolve
      })
    })

    collectionsApi.create.mockResolvedValue({ id: 2, name: 'New', position: 2 })

    let createResolved = false

    function CreateTester() {
      const { createCollection, collections } = useCollections()
      return (
        <>
          <span data-testid="collections">{collections.map((c) => c.name).join(',')}</span>
          <button
            onClick={() => {
              void createCollection({ name: 'New', position: 2 }).then(() => {
                createResolved = true
              })
            }}
          >
            create-and-track
          </button>
        </>
      )
    }

    render(<TestWrapper><CreateTester /></TestWrapper>)

    await waitFor(() => expect(screen.getByTestId('collections')).toHaveTextContent('Initial'))

    fireEvent.click(screen.getByRole('button', { name: 'create-and-track' }))

    await waitFor(() => expect(collectionsApi.create).toHaveBeenCalled())

    expect(createResolved).toBe(false)
    expect(listCallCount).toBe(2)

    resolveListCall({ collections: [
      { id: 1, name: 'Initial', position: 1 },
      { id: 2, name: 'New', position: 2 },
    ] })

    await waitFor(() => expect(createResolved).toBe(true))
    await waitFor(() => expect(screen.getByTestId('collections')).toHaveTextContent('Initial,New'))
  })

})

it('rejects consumers outside the provider', () => {
  expect(() => render(<Consumer />)).toThrow('useCollections must be used within a CollectionProvider')
})
