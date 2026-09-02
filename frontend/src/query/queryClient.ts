import { QueryClient } from '@tanstack/react-query'

export const queryRetryPolicy = (failureCount: number, error: unknown): boolean => {
    const e = error as {
        response?: { status?: number; data?: { detail?: unknown } }
        data?: { detail?: unknown }
    }
    const status = e?.response?.status
    if (status === 401) return false
    if (
        status === 403
        && e?.response?.data?.detail === 'Not authenticated'
    ) {
        return false
    }
    if (status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429) {
        return false
    }
    return failureCount < 3
}

export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: queryRetryPolicy,
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
 * (with _retry flag) and login redirect. TanStack retry must NOT additionally retry
 * auth failures, and deterministic client errors must not be retried automatically.
 *
 * - 401 / auth 403 → never retried by TanStack
 * - deterministic 4xx → never retried, except transient 408 / 429
 * - network errors, 408 / 429, and 5xx → up to 3 retries
 */
