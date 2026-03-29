import { createContext, useContext, useState, useCallback } from 'react';

interface CacheContextType {
  invalidateQueries: (queries: string[]) => void;
  cache: Map<string, unknown>;
  updateCache: (key: string, value: unknown) => void;
}

export const CacheContext = createContext<CacheContextType | undefined>(undefined);

export function CacheProvider({ children }: { children: React.ReactNode }) {
  const [cache, setCache] = useState<Map<string, unknown>>(new Map());

  const updateCache = useCallback((key: string, value: unknown) => {
    setCache((prev) => new Map([...prev, [key, value]]));
  }, []);

  const invalidateQueries = useCallback((queries: string[]) => {
    queries.forEach((q) => {
      setCache((prev) => {
        const newCache = new Map(prev);
        for (const key of prev.keys()) {
          if (key.startsWith(q)) newCache.delete(key);
        }
        return newCache;
      });
    });
  }, []);

  return (
    <CacheContext.Provider value={{ cache, updateCache, invalidateQueries }}>{children}</CacheContext.Provider>
  );
}

export function useCache() {
  const context = useContext(CacheContext);
  if (!context) {
    throw new Error('useCache must be used within a CacheProvider');
  }
  return context;
}