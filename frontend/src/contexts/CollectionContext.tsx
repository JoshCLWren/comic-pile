import { createContext, useContext, useState, useCallback, useEffect, useMemo, ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { collectionsApi } from '../services/api'
import { queryKeys } from '../query/queryKeys'
import { useCollectionsQuery } from '../hooks/useCollectionsQuery'
import type { Collection, CollectionCreate, CollectionUpdate } from '../types'

interface CollectionError {
  message: string
  status?: number
}

interface CollectionContextType {
  collections: Collection[]
  activeCollectionId: number | null
  setActiveCollectionId: (id: number | null) => void
  createCollection: (data: CollectionCreate) => Promise<void>
  updateCollection: (id: number, data: CollectionUpdate) => Promise<void>
  deleteCollection: (id: number) => Promise<void>
  moveCollection: (id: number, newPosition: number) => Promise<void>
  isLoading: boolean
  error: CollectionError | null
  retry: () => void
}

const CollectionContext = createContext<CollectionContextType | null>(null)

const STORAGE_KEY = 'comic_pile_active_collection_id'

interface CollectionProviderProps {
  children: ReactNode
}

export const CollectionProvider = ({ children }: CollectionProviderProps) => {
  const [activeCollectionId, setActiveCollectionIdState] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const {
    data: collections = [],
    isPending,
    error: queryError,
    refetch,
  } = useCollectionsQuery()

  const sortedCollections = useMemo(() =>
    [...collections].sort((a, b) => a.position - b.position),
    [collections]
  )

  const createMutation = useMutation({
    mutationFn: (data: CollectionCreate) => collectionsApi.create(data),
    onSuccess: () => {
      return queryClient.invalidateQueries({ queryKey: queryKeys.collections })
    },
  })

  const contextError: CollectionError | null = useMemo(() => {
    if (!queryError) return null
    const e = queryError as { response?: { status?: number; data?: { detail?: string } }; message?: string }
    const status = e.response?.status
    const message = e.response?.data?.detail || e.message || 'Failed to load collections'
    return { message, status }
  }, [queryError])

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const id = parseInt(stored, 10)
      if (!isNaN(id)) {
        setActiveCollectionIdState(id)
      }
    }
  }, [])

  const setActiveCollectionId = useCallback((id: number | null) => {
    console.log('[CollectionContext] setActiveCollectionId called:', id)
    setActiveCollectionIdState(id)
    if (id !== null) {
      localStorage.setItem(STORAGE_KEY, id.toString())
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [])

  const createCollection = useCallback(async (data: CollectionCreate) => {
    await createMutation.mutateAsync(data)
  }, [createMutation])

  const updateCollection = useCallback(async (id: number, data: CollectionUpdate) => {
    await collectionsApi.update(id, data)
    await queryClient.invalidateQueries({ queryKey: queryKeys.collections })
  }, [queryClient])

  const deleteCollection = useCallback(async (id: number) => {
    await collectionsApi.delete(id)
    if (activeCollectionId === id) {
      setActiveCollectionId(null)
    }
    await queryClient.invalidateQueries({ queryKey: queryKeys.collections })
  }, [queryClient, activeCollectionId, setActiveCollectionId])

  const moveCollection = useCallback(async (id: number, newPosition: number) => {
    await collectionsApi.update(id, { position: newPosition })
    await queryClient.invalidateQueries({ queryKey: queryKeys.collections })
  }, [queryClient])

  const retry = useCallback(() => {
    refetch()
  }, [refetch])

  return (
    <CollectionContext.Provider
      value={{
        collections: sortedCollections,
        activeCollectionId,
        setActiveCollectionId,
        createCollection,
        updateCollection,
        deleteCollection,
        moveCollection,
        isLoading: isPending,
        error: contextError,
        retry,
      }}
    >
      {children}
    </CollectionContext.Provider>
  )
}

export const useCollections = () => {
  const context = useContext(CollectionContext)
  if (!context) {
    throw new Error('useCollections must be used within a CollectionProvider')
  }
  return context
}
