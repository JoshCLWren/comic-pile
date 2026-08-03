import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useCurrentSessionQuery } from '../hooks/useCurrentSessionQuery'
import { queryKeys } from '../query/queryKeys'
import { sessionApi } from '../services/api'

const showToast = vi.fn()

vi.mock('../contexts/useToast', () => ({
  useToast: () => ({ showToast }),
}))

vi.mock('../services/api', () => ({
  sessionApi: {
    getCurrent: vi.fn(),
  },
}))

describe('useCurrentSessionQuery', () => {
  beforeEach(() => {
    localStorage.clear()
    showToast.mockReset()
    vi.mocked(sessionApi.getCurrent).mockReset()
  })

  it('shares the canonical current-session key and refetches after exact invalidation', async () => {
    vi.mocked(sessionApi.getCurrent)
      .mockResolvedValueOnce({ id: 10, current_die: 6, user_id: 7 })
      .mockResolvedValueOnce({ id: 11, current_die: 8, user_id: 7 })

    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useCurrentSessionQuery(), { wrapper })

    await waitFor(() => expect(result.current.data?.id).toBe(10))
    expect(client.getQueryData(queryKeys.session.current())).toMatchObject({ id: 10 })

    await act(async () => {
      await client.invalidateQueries({
        queryKey: queryKeys.session.current(),
        exact: true,
      })
    })

    await waitFor(() => expect(result.current.data?.id).toBe(11))
    expect(sessionApi.getCurrent).toHaveBeenCalledTimes(2)
    expect(showToast).toHaveBeenCalledWith(
      'Session started. Happy reading!',
      'info',
    )
  })

  it('writes compatible local updates into the same canonical cache entry', async () => {
    vi.mocked(sessionApi.getCurrent).mockResolvedValue({
      id: 20,
      current_die: 12,
      user_id: 9,
    })

    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useCurrentSessionQuery(), { wrapper })
    await waitFor(() => expect(result.current.data?.id).toBe(20))

    act(() => {
      result.current.setData((current) =>
        current ? { ...current, id: 21 } : current,
      )
    })

    expect(result.current.data?.id).toBe(21)
    expect(client.getQueryData(queryKeys.session.current())).toMatchObject({ id: 21 })
  })
})
