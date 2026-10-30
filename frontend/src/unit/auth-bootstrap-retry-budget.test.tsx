import { StrictMode } from 'react'
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { AuthContextValue } from '../contexts/AuthContext'

/**
 * Transport-level request accounting for one page load (#4269).
 *
 * These assertions count the real `/v1/auth/me` calls issued by the mounted
 * AuthProvider; they never mock the retry counter itself.
 *
 * - healthy session: exactly 1 request
 * - persistent 503/network outage: 1 initial + 5 automatic retries, then zero
 * - manual "Try again" while a retry is pending: 1 request beyond the initial
 *   probe, with no late duplicate from the cancelled timer
 * - logout/account switch: 0 requests after the session generation changes
 * - StrictMode: 1 initial request, not one per simulated effect mount
 */
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
  readStoredAccessToken: vi.fn<() => string | null>(),
  refreshSession: vi.fn(),
  isSessionRefreshRejected: vi.fn(() => false),
}))

vi.mock('../services/api', () => {
  const apiMock = {
    get: mocks.get,
    post: mocks.post,
    patch: mocks.patch,
  }
  return {
    default: apiMock,
    api: apiMock,
    clearAccessToken: mocks.clearAccessToken,
    setAccessToken: mocks.setAccessToken,
    getAccessToken: mocks.getAccessToken,
    readStoredAccessToken: mocks.readStoredAccessToken,
    refreshSession: mocks.refreshSession,
    isSessionRefreshRejected: mocks.isSessionRefreshRejected,
  }
})

import { AuthProvider, useAuth } from '../App'

let auth: AuthContextValue | null = null

function Consumer() {
  auth = useAuth()
  return null
}

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

function renderProvider() {
  return render(
    <QueryClientProvider
      client={new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })}
    >
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

function renderStrictProvider() {
  return render(
    <StrictMode>
      <QueryClientProvider
        client={new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })}
      >
        <AuthProvider>
          <Consumer />
        </AuthProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

function authMeCalls() {
  return mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')
}

async function flushTimers(milliseconds = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds)
  })
}

describe('auth bootstrap retry budget (#4269)', () => {
  beforeEach(() => {
    auth = null
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.clearAccessToken.mockReset()
    mocks.setAccessToken.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.refreshSession.mockReset()
    mocks.isSessionRefreshRejected.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.isSessionRefreshRejected.mockReturnValue(false)
    delete window.__COMIC_PILE_ACCESS_TOKEN
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('caps a persistent 503 at one initial attempt plus five retries on the intended backoff ordinals', async () => {
    vi.useFakeTimers()
    // Remove jitter so each base delay is exact and an attempt zero / 500ms
    // retry cannot hide behind the 1s jitter window.
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValue(axiosError(503))

    renderProvider()
    await flushTimers(0)

    expect(auth?.authState.status).toBe('service_unavailable')
    expect(authMeCalls()).toHaveLength(1)
    expect(auth?.authState.retryCount).toBe(1)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    // No attempt-zero / 500ms retry: the first retry is the full 1s base delay.
    await flushTimers(500)
    expect(authMeCalls()).toHaveLength(1)
    await flushTimers(499)
    expect(authMeCalls()).toHaveLength(1)
    await flushTimers(1)
    expect(authMeCalls()).toHaveLength(2)

    const retryDelays = [2000, 4000, 8000, 16000]
    for (const [index, delay] of retryDelays.entries()) {
      // The next attempt must not arrive early.
      await flushTimers(delay - 1)
      expect(authMeCalls()).toHaveLength(index + 2)
      await flushTimers(1)
      expect(authMeCalls()).toHaveLength(index + 3)
    }

    expect(authMeCalls()).toHaveLength(6)
    expect(auth?.authState.retryCount).toBe(5)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    // Once the budget is exhausted there is no timer left to poll forever.
    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(6)
    expect(auth?.authState.status).toBe('service_unavailable')
  }, 15000)

  it('applies the same bounded automatic budget to a persistent network failure', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValue(
      Object.assign(new Error('transport down'), { isAxiosError: true as const, code: 'ERR_NETWORK' }),
    )

    renderProvider()
    await flushTimers(0)
    expect(auth?.authState.status).toBe('network_error')
    expect(authMeCalls()).toHaveLength(1)

    await flushTimers(31000)
    expect(authMeCalls()).toHaveLength(6)
    expect(auth?.authState.retryCount).toBe(5)
    expect(auth?.authState.status).toBe('network_error')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(6)
  }, 15000)

  it('lets one manual retry cancel a pending retry and never issues a late duplicate', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get
      .mockRejectedValueOnce(axiosError(503))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })

    renderProvider()
    await flushTimers(0)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(authMeCalls()).toHaveLength(1)

    await act(async () => {
      await auth!.retryAuth()
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(authMeCalls()).toHaveLength(2)

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(2)
    expect(auth?.authState.status).toBe('authenticated')
  }, 15000)

  it('joins an in-flight bootstrap probe when "Try again" is clicked instead of probing twice', async () => {
    vi.useFakeTimers()
    let resolveBootstrap!: (user: { username: string; email: string }) => void
    mocks.get.mockImplementationOnce(
      () => new Promise(resolve => { resolveBootstrap = resolve }),
    )

    renderProvider()
    await flushTimers(0)
    expect(authMeCalls()).toHaveLength(1)

    let manualRetry!: Promise<void>
    act(() => {
      manualRetry = auth!.retryAuth()
    })
    await flushTimers(0)
    expect(authMeCalls()).toHaveLength(1)

    await act(async () => {
      resolveBootstrap({ username: 'reader', email: 'reader@example.com' })
      await manualRetry
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(authMeCalls()).toHaveLength(1)

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(1)
  }, 15000)

  it('keeps manual recovery ownership after a failed manual attempt', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValue(axiosError(503))

    renderProvider()
    await flushTimers(0)
    expect(authMeCalls()).toHaveLength(1)

    await act(async () => {
      await expect(auth!.retryAuth()).rejects.toMatchObject({ response: { status: 503 } })
    })
    expect(authMeCalls()).toHaveLength(2)
    expect(auth?.authState.status).toBe('service_unavailable')

    await flushTimers(60000)
    // The cancelled automatic timer must not resurrect itself after the manual
    // attempt, and it must not run concurrently with it.
    expect(authMeCalls()).toHaveLength(2)
  }, 15000)

  it('cancels a scheduled retry on logout and ignores late work', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValue(axiosError(503))

    renderProvider()
    await flushTimers(0)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(authMeCalls()).toHaveLength(1)

    act(() => auth!.logout())
    expect(auth?.authState.status).toBe('unauthenticated')
    expect(auth?.user).toBeNull()

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(1)
    expect(auth?.authState.status).toBe('unauthenticated')
  }, 15000)

  it('cancels an old session generation retry when the account changes', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValueOnce(axiosError(503))

    renderProvider()
    await flushTimers(0)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(authMeCalls()).toHaveLength(1)

    mocks.get.mockResolvedValueOnce({ username: 'second', email: 'second@example.com' })
    await act(async () => {
      await auth!.login('second-token')
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.user?.username).toBe('second')
    expect(authMeCalls()).toHaveLength(2)

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(2)
    expect(auth?.user?.username).toBe('second')
  }, 15000)

  it('cancels the pending bootstrap retry when a later revalidation succeeds', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get
      .mockRejectedValueOnce(axiosError(503))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })

    renderProvider()
    await flushTimers(0)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(auth?.authState.retryCount).toBe(1)

    await act(async () => {
      await auth!.revalidateSession(15000)
    })
    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.retryCount).toBe(0)

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(2)
  }, 15000)

  it('still logs out on a definitive 401 whose refresh also fails', async () => {
    vi.useFakeTimers()
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await flushTimers(0)

    expect(auth?.authState.status).toBe('unauthenticated')
    expect(mocks.clearAccessToken).toHaveBeenCalledOnce()
    expect(authMeCalls()).toHaveLength(1)
  }, 15000)

  it('performs a single initial bootstrap probe under StrictMode', async () => {
    vi.useFakeTimers()
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })

    renderStrictProvider()
    await flushTimers(0)
    await flushTimers(0)

    expect(auth?.authState.status).toBe('authenticated')
    expect(authMeCalls()).toHaveLength(1)
    expect(auth?.authState.retryCount).toBe(0)
  }, 15000)

  it('keeps the StrictMode persistent-outage budget bounded to one initial attempt plus five retries', async () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mocks.get.mockRejectedValue(axiosError(503))

    renderStrictProvider()
    await flushTimers(0)
    expect(authMeCalls()).toHaveLength(1)

    // 1s + 2s + 4s + 8s + 16s of automatic retries.
    await flushTimers(31000)
    expect(authMeCalls()).toHaveLength(6)
    expect(auth?.authState.retryCount).toBe(5)
    expect(auth?.authState.status).toBe('service_unavailable')

    await flushTimers(60000)
    expect(authMeCalls()).toHaveLength(6)
  }, 15000)
})
