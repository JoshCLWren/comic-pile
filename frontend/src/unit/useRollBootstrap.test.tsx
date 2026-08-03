import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollBootstrapApi.get)

const bootstrapResponse = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  pending_thread_id: null,
  last_rolled_result: null,
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
} as RollBootstrapResponse

function renderBootstrap() {
  return renderHook(() => useRollBootstrap(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <ToastProvider>{children}</ToastProvider>
    ),
  })
}

beforeEach(() => {
  mockedBootstrap.mockReset()
  localStorage.clear()
})

describe('useRollBootstrap', () => {
  it('loads bootstrap data and exposes a successful refetch', async () => {
    mockedBootstrap.mockResolvedValue(bootstrapResponse)

    const { result } = renderBootstrap()

    expect(result.current.isPending).toBe(true)
    expect(result.current.data).toBeNull()

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data).toBe(bootstrapResponse)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()

    await act(async () => {
      await expect(result.current.refetch()).resolves.toBe(bootstrapResponse)
    })

    expect(mockedBootstrap).toHaveBeenCalledTimes(2)
  })

  it('records Error failures and clears them before a successful retry', async () => {
    mockedBootstrap
      .mockRejectedValueOnce(new Error('bootstrap unavailable'))
      .mockResolvedValueOnce(bootstrapResponse)

    const { result } = renderBootstrap()

    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(result.current.error).toEqual(new Error('bootstrap unavailable'))
    expect(result.current.isPending).toBe(false)

    await act(async () => {
      await result.current.refetch()
    })

    expect(result.current.data).toBe(bootstrapResponse)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.isPending).toBe(false)
  })

  it('normalizes non-Error failures', async () => {
    mockedBootstrap.mockRejectedValue('offline')

    const { result } = renderBootstrap()

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data).toBeNull()
    expect(result.current.isError).toBe(true)
    expect(result.current.error).toEqual(
      new Error('Failed to fetch roll bootstrap'),
    )
  })

  it('still loads when persisting the session id fails', async () => {
    const originalStorage = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        clear: vi.fn(),
      },
    })
    mockedBootstrap.mockResolvedValue(bootstrapResponse)

    try {
      const { result } = renderBootstrap()

      await waitFor(() => expect(result.current.isPending).toBe(false))

      expect(result.current.data).toBe(bootstrapResponse)
      expect(result.current.isError).toBe(false)
      expect(result.current.error).toBeNull()
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
  })
})
