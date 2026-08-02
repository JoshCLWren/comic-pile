import type { Collection, CollectionCreate, CollectionUpdate } from '../types'

interface CollectionError {
  message: string
  status?: number
}

interface RemovedCollectionsState {
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

const removedCollectionsState: RemovedCollectionsState = {
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

/**
 * Temporary caller shim while the last Roll and Queue collection branches are
 * deleted under #636. It owns no React state, context, persistence, requests,
 * or mutation behavior and therefore requires no provider in the app shell.
 */
export function useCollections(): RemovedCollectionsState {
  return removedCollectionsState
}
