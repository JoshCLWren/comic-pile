import { createContext } from 'react'

export interface CacheContextType {
  invalidateQueries: (queries: string[]) => void
  cache: Map<string, unknown>
  updateCache: (key: string, value: unknown) => void
}

export const CacheContext = createContext<CacheContextType | undefined>(undefined)