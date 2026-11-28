import { writeFileSync } from 'node:fs'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, it, vi } from 'vitest'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useInfiniteCollection } from '../pagination/useInfiniteCollection'

describe('debug', () => {
  it('logs both', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const list = vi.fn().mockRejectedValue(new Error('network down'))
    const queryFn = async ({ pageParam }: { pageParam: string | null }) => {
      try {
        return await list(pageParam)
      } catch (error: unknown) {
        if (error instanceof Error) throw error
        throw new Error('fallback')
      }
    }
    const raw = renderHook(() => useInfiniteQuery({
      queryKey: ['debug-raw'], queryFn, initialPageParam: null as string | null,
      getNextPageParam: (p: { next_page_token: string | null }) => p.next_page_token ?? undefined,
    }), { wrapper })
    const canonical = renderHook(() => useInfiniteCollection({
      queryKey: ['debug-canonical'], queryFn, initialPageParam: null as string | null,
      getNextPageParam: (p: { next_page_token: string | null }) => p.next_page_token ?? undefined,
      selectPage: (p: { items: number[] }) => p.items,
    }), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 200))
    writeFileSync('/tmp/opencode/debug-activity.json', JSON.stringify({
      raw: { isError: raw.result.current.isError, isPending: raw.result.current.isPending },
      canonical: { isError: canonical.result.current.isError, isPending: canonical.result.current.isInitialLoading },
      cache: client.getQueryCache().getAll().map((q) => ({
        key: q.queryKey, status: q.state.status, error: String(q.state.error),
      })),
    }, null, 2))
  })
})
