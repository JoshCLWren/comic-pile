import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
                const e = error as {
                    response?: { status?: number; data?: { detail?: string } }
                    data?: { detail?: string }
                }
                if (e?.response?.status === 401) return false
                if (
                    e?.response?.status === 403
                    && e?.response?.data?.detail === 'Not authenticated'
                ) {
                    return false
                }
                return failureCount < 3
            },
        },
        mutations: {
            retry: false,
        },
    },
})

/**
 * Auth retry interplay:
 *
 * The axios interceptor in services/api.ts handles 401 → token refresh → single retry
 * (with _retry flag) and login redirect.  TanStack retry must NOT additionally retry
 * auth failures (401 or 403 "Not authenticated"), or it would double-refresh and
 * create confusing redirect loops.
 *
 * - 401           → never retried by TanStack
 * - 403 "Not authenticated" → never retried by TanStack
 * - All other errors → up to 3 retries (exponential backoff, TanStack default delay)
 */
