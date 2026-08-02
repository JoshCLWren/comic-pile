import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
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

const removedCollectionsContext: CollectionContextType = {
  collections: [],
  activeCollectionId: null,
  setActiveCollectionId: () => undefined,
  createCollection: async (_data: CollectionCreate) => undefined,
  updateCollection: async (_id: number, _data: CollectionUpdate) => undefined,
  deleteCollection: async (_id: number) => undefined,
  moveCollection: async (_id: number, _newPosition: number) => undefined,
  isLoading: false,
  error: null,
  retry: () => undefined,
}

const CollectionContext = createContext<CollectionContextType>(removedCollectionsContext)

/**
 * Transitional compatibility provider for #636.
 *
 * Collections are no longer loaded, persisted, selected, or mutated. This
 * provider remains only while the remaining Roll and Queue callers are removed
 * in follow-up slices, after which this file can be deleted entirely.
 */
export function CollectionProvider({ children }: { children: ReactNode }) {
  return (
    <CollectionContext.Provider value={removedCollectionsContext}>
      {children}
    </CollectionContext.Provider>
  )
}

export function useCollections() {
  return useContext(CollectionContext)
}
