import { useContext } from 'react'
import { CacheContext } from './CacheContextValue'

export function useCache() {
  const context = useContext(CacheContext)
  if (!context) {
    throw new Error('useCache must be used within a CacheProvider')
  }
  return context
}