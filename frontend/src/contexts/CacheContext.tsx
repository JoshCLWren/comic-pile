import { useState, useCallback } from 'react';
import { CacheContext } from './CacheContextValue';

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
