import { renderHook as rtlRenderHook } from '@testing-library/react'
import { useQuery } from '@tanstack/react-query'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { it, expect, vi } from 'vitest'
import { ReactElement } from 'react'

function useTestHook() {
  console.error('useTestHook: rendering')
  const query = useQuery({
    queryKey: ['test'],
    queryFn: async () => {
      console.error('queryFn: executing')
      return { value: 42 }
    },
    staleTime: 30_000,
    retry: false,
  })
  console.error('useTestHook: query', { data: query.data, isLoading: query.isLoading, isError: query.isError })
  return {
    data: query.data ?? null,
    isPending: query.isLoading,
    isError: query.isError,
    error: query.error ?? null,
  }
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

it('debug', async () => {
  const r = rtlRenderHook(() => useTestHook(), { wrapper: createWrapper() })
  console.error('DEBUG r:', r)
  console.error('DEBUG r.result:', r.result)
  console.error('DEBUG r.result.current:', r.result.current)
  console.error('DEBUG r.error:', r.error)
  expect(r.result.current).not.toBeNull()
})
