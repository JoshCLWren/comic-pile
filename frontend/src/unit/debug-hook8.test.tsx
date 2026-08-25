import { renderHookWithClient } from './queryTestWrapper'
import { useQuery } from '@tanstack/react-query'
import { ToastProvider } from '../contexts/ToastProvider'
import { it, expect, vi } from 'vitest'

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

it('debug', async () => {
  const r = renderHookWithClient(() => useTestHook(), {
    innerWrapper: ({ children }) => <ToastProvider>{children}</ToastProvider>
  })
  console.error('DEBUG r.result.current:', r.result.current)
  expect(r.result.current).not.toBeNull()
})
