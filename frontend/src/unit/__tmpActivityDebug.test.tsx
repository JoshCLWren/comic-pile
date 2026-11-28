import { writeFileSync } from 'node:fs'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, it, vi } from 'vitest'
import { useInfiniteQuery } from '@tanstack/react-query'

describe('debug', () => {
  it('finds the option that swallows errors', async () => {
    const results: Record<string, boolean> = {}
    const options = ['enabled', 'retry', 'placeholderData', 'refetchOnWindowFocus', 'staleTime', 'gcTime'] as const
    for (const option of options) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      const wrapper = ({ children }: PropsWithChildren) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      )
      const queryFn = vi.fn().mockRejectedValue(new Error('network down'))
      const extra = { [option]: undefined }
      const { result } = renderHook(() => useInfiniteQuery({
        queryKey: [`debug-${option}`],
        queryFn,
        initialPageParam: null as string | null,
        getNextPageParam: (p: { next_page_token?: string | null }) => p?.next_page_token ?? undefined,
        ...extra,
      }), { wrapper })
      await new Promise((resolve) => setTimeout(resolve, 100))
      results[option] = result.current.isError
    }
    writeFileSync('/tmp/opencode/debug-activity.json', JSON.stringify(results, null, 2))
  })
})
