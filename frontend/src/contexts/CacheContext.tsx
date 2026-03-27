import { createContext, useContext, useState, useCallback } from 'react';

interface CacheContextType {
  invalidateQueries: (queries: string[]) => void;
  cache: Map<string, any>;
  cacheKeys: string[];
}

export const CacheContext = createContext<CacheContextType | undefined>(undefined);

export function CacheProvider({ children }: { children: React.ReactNode }) {
  const [cacheKeys, setCacheKeys] = useState<string[]>([]);
  const [cache, setCache] = useState<Map<string, any>>(new Map());

  const updateCache = useCallback((key: string, value: any) => {
    setCacheKeys((prev) => [...new Set([...prev, key])]);
    setCache((prev) => new Map([...prev, [key, value]]));
  }, [cacheKeys]);

  const invalidateQueries = useCallback((queries: string[]) => {
    queries.forEach((q) => {
      setCacheKeys((prev) => prev.filter((k) => !k.startsWith(q)));
      setCache((prev) => {
        const newCache = new Map(prev);
        for (const key of prev.keys()) {
          if (key.startsWith(q)) newCache.delete(key);
        }
        return newCache;
      });
    });
  }, [cacheKeys, cache]);

  return (
    <CacheContext.Provider value={{ cache, updateCache, invalidateQueries, cacheKeys }}>{children}</CacheContext.Provider>
  );
}

export function useCache() {
  const context = useContext(CacheContext);
  if (!context) {
    throw new Error('useCache must be used within a CacheProvider');
  }
  return context;
}

export * from './CacheContext';