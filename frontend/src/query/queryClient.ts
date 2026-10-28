import { QueryClient } from '@tanstack/react-query'
import { resumeQueriesAfterOutage } from './cacheEffects'
import {
  noteSuccessfulQuery,
  queryRetryDelay,
  shouldRetryQuery,
} from './outageRetryBudget'

/**
 * Query retry policy.
 *
 * Auth failures and deterministic client errors are never retried. Transient
 * failures follow the shared outage-aware budget in `outageRetryBudget.ts`, so
 * independent observers cannot each launch a retry storm while the API is
 * unavailable.
 *
 * @param failureCount - Zero-based count of failures for this query.
 * @param error - Rejected query value.
 * @returns True when this query may retry now.
 */
export const queryRetryPolicy = (failureCount: number, error: unknown): boolean =>
  shouldRetryQuery(failureCount, error)

/**
 * Build an app-configured QueryClient.
 *
 * Applies the canonical defaults and wires outage recovery: the first request
 * that succeeds after an outage refetches the queries that failed during it,
 * once per distinct query key. Tests build isolated clients through this
 * factory so they exercise the same retry and recovery wiring as production.
 *
 * @returns A new QueryClient with app defaults and outage recovery attached.
 */
export function createAppQueryClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: queryRetryPolicy,
        retryDelay: queryRetryDelay,
      },
      mutations: {
        retry: false,
      },
    },
  })

  client.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated' || event.action.type !== 'success') {
      return
    }
    // Ignore manual cache writes (setQueryData, optimistic updates) which
    // also emit 'success' updates but are not network fetches. Network
    // successes include a fetchId on the action.
    if (!('fetchId' in event.action)) {
      return
    }
    if (!noteSuccessfulQuery()) {
      return
    }
    void resumeQueriesAfterOutage(client)
  })

  return client
}

export const queryClient = createAppQueryClient()

/**
 * Auth retry interplay:
 *
 * The axios interceptor in services/api.ts handles 401 → token refresh → single retry
 * (with _retry flag) and login redirect. TanStack retry must NOT additionally retry
 * auth failures, and deterministic client errors must not be retried automatically.
 *
 * - 401 / auth 403 → never retried by TanStack
 * - deterministic 4xx → never retried, except transient 408 / 429
 * - network errors, 408 / 429, and 5xx → up to 3 retries per query until an
 *   outage is recognized, then one shared probe (see outageRetryBudget.ts)
 */
