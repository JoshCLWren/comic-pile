import { writeFileSync } from 'node:fs'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, it, vi } from 'vitest'
import { useActivity } from '../hooks/useActivity'

describe('debug', () => {
  it('logs failing state', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const api = { list: vi.fn().mockRejectedValueOnce(new Error('network down')) }
    const { result } = renderHook(() => useActivity(api as never), { wrapper })
    await new Promise((resolve) => setTimeout(resolve, 200))
    console.log('DEBUG', JSON.stringify({
      isPending: result.current.isPending,
      isError: result.current.isError,
      isRetrying: result.current.isRetrying,
      error: String(result.current.error),
      data: result.current.data,
      calls: api.list.mock.calls.length,
    }))
  })
})
