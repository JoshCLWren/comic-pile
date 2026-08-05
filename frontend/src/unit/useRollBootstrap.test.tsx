import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { ROLL_BOOTSTRAP_RECONCILED_EVENT } from '../hooks/rollMutationReconciliation'
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

    expect(result.current.data).toEqual(reconciled)
    expect(result.current.isPending).toBe(false)

    await act(async () => {
      initialRequest.resolve(bootstrapResponse)
      await initialRequest.promise
    })

    expect(result.current.data).toEqual(reconciled)
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

    await act(async () => {
      initialRequest.reject(new Error('stale bootstrap failure'))
      await expect(initialRequest.promise).rejects.toThrow('stale bootstrap failure')
    })

    expect(result.current.data).toEqual(reconciled)
    expect(result.current.isPending).toBe(false)
    expect(result.current.isError).toBe(false)
    expect(result.current.error).toBeNull()
  })
})
