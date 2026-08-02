import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const collectionsApi = vi.hoisted(() => ({
    list: vi.fn(),
    create: vi.fn(),
}))
vi.mock('../services/api', () => ({ collectionsApi }))

import { useCollectionsQuery } from '../hooks/useCollectionsQuery'
import { queryKeys } from '../query/queryKeys'

function createClientNoRetry() {
    return new QueryClient({
        defaultOptions: {
            queries: { retry: false, staleTime: 0, gcTime: 0 },
            mutations: { retry: false },
        },
    })
}

function createClientWithRetry() {
    return new QueryClient({
        defaultOptions: {
            queries: {
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
                staleTime: 0,
                gcTime: 0,
            },
            mutations: { retry: false },
        },
    })
}

function makeWrapper(client: QueryClient) {
    return function Wrapper({ children }: { children: React.ReactNode }) {
        return <QueryClientProvider client={client}>{children}</QueryClientProvider>
    }
}

describe('useCollectionsQuery', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })
    afterEach(() => {
        vi.useRealTimers()
    })

    it('fetches collections successfully', async () => {
        const data = { collections: [{ id: 1, name: 'Test', position: 0 }] }
        collectionsApi.list.mockResolvedValueOnce(data)

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientNoRetry()),
        })

        await waitFor(() => expect(result.current.isPending).toBe(false))
        expect(result.current.data).toEqual(data.collections)
        expect(result.current.isError).toBe(false)
    })

    it('surfaces network failures as errors', async () => {
        collectionsApi.list.mockRejectedValue(new Error('Network error'))

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientNoRetry()),
        })

        await waitFor(() => expect(result.current.isError).toBe(true))
        expect(result.current.error).toBeDefined()
    })

    it('does not retry on 401 auth failures', async () => {
        collectionsApi.list.mockRejectedValue({
            response: { status: 401 },
        })

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientWithRetry()),
        })

        await waitFor(() => expect(result.current.isError).toBe(true))
        expect(collectionsApi.list).toHaveBeenCalledTimes(1)
    })

    it('does not retry on 403 Not authenticated', async () => {
        collectionsApi.list.mockRejectedValue({
            response: { status: 403, data: { detail: 'Not authenticated' } },
        })

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientWithRetry()),
        })

        await waitFor(() => expect(result.current.isError).toBe(true))
        expect(collectionsApi.list).toHaveBeenCalledTimes(1)
    })

    it('retries transient failures up to 3 times then errors', async () => {
        vi.useFakeTimers()
        collectionsApi.list.mockRejectedValue(new Error('temporary'))

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientWithRetry()),
        })

        await vi.advanceTimersByTimeAsync(1000)
        await vi.advanceTimersByTimeAsync(2000)
        await vi.advanceTimersByTimeAsync(4000)

        await vi.runAllTimersAsync()

        expect(result.current.isError).toBe(true)
        expect(collectionsApi.list).toHaveBeenCalledTimes(4)
    }, 10000)

    it('deduplicates requests when multiple consumers use the same key', async () => {
        const spy = vi.fn()
        collectionsApi.list.mockImplementation(() => {
            spy()
            return Promise.resolve({
                collections: [{ id: 1, name: 'Dedup', position: 0 }],
            })
        })

        const sharedClient = createClientNoRetry()
        const sharedWrapper = makeWrapper(sharedClient)

        const { result: r1 } = renderHook(() => useCollectionsQuery(), {
            wrapper: sharedWrapper,
        })
        const { result: r2 } = renderHook(() => useCollectionsQuery(), {
            wrapper: sharedWrapper,
        })

        await waitFor(() => {
            expect(r1.current.isPending).toBe(false)
            expect(r2.current.isPending).toBe(false)
        })

        expect(spy).toHaveBeenCalledTimes(1)
        expect(r1.current.data).toEqual([{ id: 1, name: 'Dedup', position: 0 }])
        expect(r2.current.data).toEqual([{ id: 1, name: 'Dedup', position: 0 }])
    })

    it('uses isPending for initial loading state', async () => {
        let resolveList!: (value: unknown) => void
        collectionsApi.list.mockReturnValue(
            new Promise((resolve) => {
                resolveList = resolve
            }),
        )

        const { result } = renderHook(() => useCollectionsQuery(), {
            wrapper: makeWrapper(createClientNoRetry()),
        })

        await waitFor(() => expect(result.current.isPending).toBe(true))
        expect(result.current.isLoading).toBe(true)

        resolveList({ collections: [{ id: 1, name: 'L', position: 0 }] })

        await waitFor(() => {
            expect(result.current.isPending).toBe(false)
            expect(result.current.isLoading).toBe(false)
        })
    })
})

describe('mutation invalidation integration', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('create mutation invalidates collections query key', async () => {
        const { useMutation, useQueryClient } = await import(
            '@tanstack/react-query'
        )

        const client = createClientNoRetry()
        collectionsApi.list.mockResolvedValue({
            collections: [{ id: 1, name: 'C1', position: 0 }],
        })
        collectionsApi.create.mockResolvedValue({ id: 2, name: 'C2' })

        const wrapperWithClient = makeWrapper(client)

        const { result: queryResult } = renderHook(
            () => useCollectionsQuery(),
            {
                wrapper: wrapperWithClient,
            },
        )

        await waitFor(() => expect(queryResult.current.isPending).toBe(false))
        expect(collectionsApi.list).toHaveBeenCalledTimes(1)

        const { result: mutationResult } = renderHook(
            () => {
                const queryClient = useQueryClient()
                return useMutation({
                    mutationFn: (data: { name: string }) =>
                        collectionsApi.create(data),
                    onSuccess: () => {
                        queryClient.invalidateQueries({
                            queryKey: queryKeys.collections,
                        })
                    },
                })
            },
            { wrapper: wrapperWithClient },
        )

        await mutationResult.current.mutateAsync({ name: 'C2' })

        await waitFor(() =>
            expect(collectionsApi.list).toHaveBeenCalledTimes(2),
        )
    })
})
