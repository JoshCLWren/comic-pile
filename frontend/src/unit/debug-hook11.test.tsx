import { renderHook as rtlRenderHook } from '@testing-library/react'
import { useQuery } from '@tanstack/react-query'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { it, expect, vi } from 'vitest'
import { ReactElement } from 'react'

function useTestHook() {
  const query = useQuery({
    queryKey: ['test'],
    queryFn: async () => ({ value: 42 }),
    staleTime: 30_000,
    retry: false,
  })
  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
  }
}

function createQueryWrapper(innerWrapper?: (children: React.ReactNode) => React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        {innerWrapper ? innerWrapper(children) : children}
      </QueryClientProvider>
    )
  }
}

function renderHookWithClient(render: () => any, options?: { innerWrapper?: (children: React.ReactNode) => React.ReactNode }) {
  const { innerWrapper, ...restOptions } = options ?? {}
  return rtlRenderHook(render, { wrapper: createQueryWrapper(innerWrapper), ...restOptions })
}

it('debug', async () => {
  const r = renderHookWithClient(() => useTestHook(), {
    innerWrapper: ({ children }) => <div>{children}</div>
  })
  console.error('DEBUG r.result.current:', JSON.stringify(r.result.current, null, 2))
  expect(r.result.current).not.toBeNull()
})
