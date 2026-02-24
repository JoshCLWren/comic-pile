import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react'
import { collectionsApi } from '../services/api'

export interface Collection {
  id: number
  name: string
  user_id: number
  is_default: boolean
  position: number
  created_at: string
}

export interface CollectionCreate {
  name: string
  is_default?: boolean
  position?: number
}

export interface CollectionUpdate {
  name?: string
  is_default?: boolean
  position?: number
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
}

const CollectionContext = createContext<CollectionContextType | null>(null)

const STORAGE_KEY = 'comic_pile_active_collection_id'

interface CollectionProviderProps {
  children: ReactNode
}

export const CollectionProvider = ({ children }: CollectionProviderProps) => {
  const [collections, setCollections] = useState<Collection[]>([])
  const [activeCollectionId, setActiveCollectionIdState] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const sortedCollections = collections.sort((a, b) => a.position - b.position)

  const fetchCollections = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await collectionsApi.list()
      const fetchedCollections: Collection[] = response.collections || []
      setCollections(fetchedCollections)
    } finally {
      setIsLoading(false)
    }
  }, [])

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
