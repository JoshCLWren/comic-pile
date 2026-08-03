/** Test-only declaration retained while RollPage tests finish migrating off Collections. */
export interface RetiredCollectionContextValue {
  collections: never[]
  activeCollectionId: null
  setActiveCollectionId: (value: null) => void
  isLoading: boolean
}

export declare function useCollections(): RetiredCollectionContextValue
