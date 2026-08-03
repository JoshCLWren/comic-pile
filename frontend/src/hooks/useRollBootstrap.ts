import { useCallback, useEffect, useState } from 'react';
import type { RollBootstrapResponse } from '../types';
import { rollApi } from '../services/api';

export function useRollBootstrap() {
  const [data, setData] = useState<RollBootstrapResponse | null>(null);
  const [isPending, setIsPending] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchBootstrap = useCallback(async () => {
    setIsPending(true);
    setIsError(false);
    setError(null);
    try {
      const result = await rollApi.bootstrap();
      setData(result);
      return result;
    } catch (err: unknown) {
      setIsError(true);
      setError(err instanceof Error ? err : new Error('Failed to fetch roll bootstrap'));
    } finally {
      setIsPending(false);
    }
  }, []);

  useEffect(() => {
    fetchBootstrap();
  }, [fetchBootstrap]);

  return { data, isPending, isError, error, refetch: fetchBootstrap };
}
