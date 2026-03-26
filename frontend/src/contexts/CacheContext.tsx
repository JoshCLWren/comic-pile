import { createContext, useContext } from 'react'

interface CacheEntry<T> {
  data: T
  timestamp: number
}

interface CacheContextValue {
  getCache: (key: string) => CacheEntry<unknown> | null
  setCache: (key: string, data: unknown, timestamp: number) => void
}

const CacheContext = createContext<CacheContextValue | null>(null)

export const CacheProvider = ({ children }: { children: React.ReactNode }) => {
  const cache = new Map<string, CacheEntry<unknown>>()

  const getCache = (key: string): CacheEntry<unknown> | null => {
    return cache.get(key)
  }

  const setCache = (key: string, data: unknown, timestamp: number): void => {
    cache.set(key, { data, timestamp })
  }

  return (
    <CacheContext.Provider value={{ getCache, setCache }}>
      {children}
    </CacheContext.Provider>
  )
}

export const useCache = () => {
  const context = useContext(CacheContext)
  if (!context) {
    throw new Error('useCache must be used within a CacheProvider')
  }
  return context
}