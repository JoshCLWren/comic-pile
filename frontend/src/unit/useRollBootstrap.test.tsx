import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
import { rollBootstrapApi } from '../services/rollBootstrapApi'
import { queryClient } from '../query/queryClient'
import type { RollBootstrapResponse } from '../types/rollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'

vi.mock('../services/rollBootstrapApi', () => ({
  rollBootstrapApi: {
    get: vi.fn(),
  },
}))

const mockedBootstrap = vi.mocked(rollBootstrapApi.get)

const bootstrapResponse: RollBootstrapResponse = {
  session_id: 1,
  user_id: 1,
  current_die: 6,
  manual_die: null,
  pending_thread_id: null,
  last_rolled_result: null,
  session_mode: {
    active_bandwidth: null,
    predicted_bandwidth: null,
    bandwidth_confidence: null,
    bandwidth_source: null,
    bandwidth_version: null,
    active_intent: null,
    predicted_intent: null,
    intent_confidence: null,
    intent_source: null,
    intent_version: null,
    session_mode_correction_guidance: null,
  },
  active_thread: null,
  roll_pool: [],
  snoozed_threads: [],
  snoozed_count: 0,
  blocked_count: 0,
  blocked_threads: [],
  stale_thread_count: 0,
  stale_thread: null,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

function renderBootstrap() {
  return renderHook(() => useRollBootstrap(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <ToastProvider>{children}</ToastProvider>
      </QueryClientProvider>
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

    // React Query transitions an errored observer back to success asynchronously
    // after a successful refetch; await that transition before asserting.
    await waitFor(() => expect(result.current.data).toBe(bootstrapResponse))
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

  it('still loads when reading the persisted session id fails', async () => {
    const originalStorage = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        setItem: vi.fn(),
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
      expect(window.localStorage.setItem).toHaveBeenCalledWith(
        'comic_pile_last_session_id_1',
        '1',
      )
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
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

  it('records a changed session id and suppresses duplicate notifications', async () => {
    localStorage.setItem('comic_pile_last_session_id_1', '99')
    mockedBootstrap.mockResolvedValue(bootstrapResponse)

    const { result } = renderBootstrap()

    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data).toBe(bootstrapResponse)
    expect(localStorage.getItem('comic_pile_last_session_id_1')).toBe('1')

    localStorage.setItem('comic_pile_last_session_id_1', '98')
    await act(async () => {
      await result.current.refetch()
    })

    expect(result.current.data).toBe(bootstrapResponse)
    expect(result.current.isError).toBe(false)
  })

  it('uses the anonymous storage key when the bootstrap has no user id', async () => {
    const anonymousResponse = {
      ...bootstrapResponse,
      session_id: 7,
      user_id: undefined,
    } as unknown as RollBootstrapResponse
    mockedBootstrap.mockResolvedValue(anonymousResponse)

    const { result } = renderBootstrap()

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data).toBe(anonymousResponse)
    expect(localStorage.getItem('comic_pile_last_session_id_anonymous')).toBe('7')
  })

  it('ignores a malformed stored session id and replaces it with the current id', async () => {
    localStorage.setItem('comic_pile_last_session_id_1', 'not-a-number')
    mockedBootstrap.mockResolvedValue(bootstrapResponse)

    const { result } = renderBootstrap()

    await waitFor(() => expect(result.current.isPending).toBe(false))

    expect(result.current.data).toBe(bootstrapResponse)
    expect(result.current.isError).toBe(false)
    expect(localStorage.getItem('comic_pile_last_session_id_1')).toBe('1')
  })

  it('keeps reconciled state when an older bootstrap request resolves later', async () => {
    const initialRequest = deferred<RollBootstrapResponse>()
    mockedBootstrap.mockReturnValueOnce(initialRequest.promise)
    const reconciled = { ...bootstrapResponse, current_die: 8 }
    const { result } = renderBootstrap()

    await waitFor(() => expect(mockedBootstrap).toHaveBeenCalledTimes(1))

    act(() => {
      window.dispatchEvent(
        new CustomEvent(ROLL_BOOTSTRAP_RECONCILED_EVENT, { detail: reconciled }),
      )
    })

    // The reconciled value is authoritative in the cache, but React Query keeps a
    // query with an in-flight fetch at pending, so the observer only reflects it
    // once the older request settles. Resolve it; the generation guard must keep
    // the reconciled value instead of letting the stale request overwrite it.
    await act(async () => {
      initialRequest.resolve(bootstrapResponse)
      await initialRequest.promise
    })

    await waitFor(() => expect(result.current.data).toEqual(reconciled))
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('ignores an older bootstrap failure after successful reconciliation', async () => {
    const initialRequest = deferred<RollBootstrapResponse>()
    mockedBootstrap.mockReturnValueOnce(initialRequest.promise)
    const reconciled = { ...bootstrapResponse, current_die: 8 }
    const { result } = renderBootstrap()

    await waitFor(() => expect(mockedBootstrap).toHaveBeenCalledTimes(1))

    act(() => {
      window.dispatchEvent(
        new CustomEvent(ROLL_BOOTSTRAP_RECONCILED_EVENT, { detail: reconciled }),
      )
    })

    // An older bootstrap failure must not erase the reconciled state. React Query
    // keeps the fetching observer at pending, so assert the final cache-driven state
    // once the stale request settles.
    await act(async () => {
      initialRequest.reject(new Error('stale bootstrap failure'))
      await expect(initialRequest.promise).rejects.toThrow('stale bootstrap failure')
    })

    await waitFor(() => expect(result.current.data).toEqual(reconciled))
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()
  })
})
