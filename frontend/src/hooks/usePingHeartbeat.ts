import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query/queryKeys';

export function usePingHeartbeat() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.ping.heartbeat(),
    queryFn: async () => {
      if (document.visibilityState === 'visible') {
        await fetch('/api/ping', { method: 'GET', cache: 'no-store' });
      }
      return null;
    },
    refetchInterval: 4 * 60 * 1000, // 4 minutes
    staleTime: Infinity, // Never consider data stale
  });

  return { isPending, isError };
}
