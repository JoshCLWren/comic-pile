import { createContext, useContext, useState, useCallback, useEffect, ReactNode, useRef } from 'react'
import { collectionsApi } from '../services/api'
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
const MAX_RETRIES = 3
const RETRY_DELAY = 1000

interface CollectionProviderProps {
  children: ReactNode
}

export const CollectionProvider = ({ children }: CollectionProviderProps) => {
  const [collections, setCollections] = useState<Collection[]>([])
  const [activeCollectionId, setActiveCollectionIdState] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<CollectionError | null>(null)
  const retryCountRef = useRef(0)

  const sortedCollections = collections.sort((a, b) => a.position - b.position)

  const fetchCollections = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await collectionsApi.list()
      const fetchedCollections: Collection[] = response.collections || []
      setCollections(fetchedCollections)
      retryCountRef.current = 0
    } catch (err) {
      const axiosError = err as { response?: { status: number; data?: { detail?: string } }; message?: string }
      const status = axiosError.response?.status
      const message = axiosError.response?.data?.detail || axiosError.message || 'Failed to load collections'
      setError({ message, status })
      console.error('Failed to fetch collections:', err)
      if (status !== 401 && retryCountRef.current < MAX_RETRIES) {
        retryCountRef.current += 1
        setTimeout(() => {
          fetchCollections()
        }, RETRY_DELAY * retryCountRef.current)
      }
    } finally {
      setIsLoading(false)
    }
  }, [])

  const retry = useCallback(() => {
    retryCountRef.current = 0
    fetchCollections()
  }, [fetchCollections])

  useEffect(() => {
    fetchCollections()
  }, [fetchCollections])

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
    setActiveCollectionIdState(id)
    if (id !== null) {
      localStorage.setItem(STORAGE_KEY, id.toString())
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [])

  const createCollection = useCallback(async (data: CollectionCreate) => {
    setIsLoading(true)
    try {
      await collectionsApi.create(data)
      await fetchCollections()
    } finally {
      setIsLoading(false)
    }
  }, [fetchCollections])

  const updateCollection = useCallback(async (id: number, data: CollectionUpdate) => {
    setIsLoading(true)
    try {
      await collectionsApi.update(id, data)
      await fetchCollections()
    } finally {
      setIsLoading(false)
    }
  }, [fetchCollections])

  const deleteCollection = useCallback(async (id: number) => {
    setIsLoading(true)
    try {
      await collectionsApi.delete(id)
      if (activeCollectionId === id) {
        setActiveCollectionId(null)
      }
      await fetchCollections()
    } finally {
      setIsLoading(false)
    }
  }, [fetchCollections, activeCollectionId, setActiveCollectionId])

  const moveCollection = useCallback(async (id: number, newPosition: number) => {
    setIsLoading(true)
    try {
      await collectionsApi.update(id, { position: newPosition })
      await fetchCollections()
    } finally {
      setIsLoading(false)
    }
  }, [fetchCollections])

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
        isLoading,
        error,
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
