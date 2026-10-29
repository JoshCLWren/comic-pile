import { StrictMode } from 'react'
import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { AuthContextValue } from '../contexts/AuthContext'

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

vi.mock('../services/api-preferences', () => ({
  preferencesApi: {
    get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
      mocks.get('/v1/users/me/preferences', options),
    patch: (data: { theme?: string | null }) => mocks.patch('/v1/users/me/preferences', data),
  },
}))

import { PreferencesSync } from '../hooks/usePreferences'
import { AuthProvider, useAuth } from '../App'

let auth: AuthContextValue | null = null

function Consumer() {
  auth = useAuth()
  return null
}

function PreferencesSyncConsumer() {
  const { authState } = useAuth()
  return <PreferencesSync isAuthenticated={authState.status === 'authenticated'} />
}

function renderProvider(queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })) {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Consumer />
        <PreferencesSyncConsumer />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

const PREFERENCES_CONFIG = { timeout: 15000, skipAuthRedirect: true }

async function waitForPreferencesFetch() {
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('/v1/users/me/preferences', PREFERENCES_CONFIG))
}

describe('AuthProvider transient recovery', () => {
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
  })

  it('clears cached user data and mutations on logout and a new login', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider(client)
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    const key = ['queue', 'first-user']
    client.setQueryData(key, { title: 'First user private queue' })
    client.getMutationCache().build(client, { mutationKey: ['private-write'] })

    act(() => auth!.logout())
    expect(client.getQueryData(key)).toBeUndefined()
    expect(client.getMutationCache().getAll()).toHaveLength(0)
    expect(auth?.isAuthenticated).toBe(false)

    client.setQueryData(key, { title: 'Stale data' })
    mocks.get.mockResolvedValue({ username: 'second', email: 'second@example.com' })
    await act(async () => auth!.login('second-token'))
    expect(auth?.user?.username).toBe('second')
    expect(client.getQueryData(key)).toBeUndefined()
  })

  it('does not let a pending session validation sign a logged-out user back in', async () => {
    let resolveUser!: (user: { username: string; email: string }) => void
    mocks.get.mockImplementationOnce(() => new Promise(resolve => { resolveUser = resolve }))
    renderProvider()
    act(() => auth!.logout())
    await act(async () => resolveUser({ username: 'first', email: 'first@example.com' }))
    expect(auth?.isAuthenticated).toBe(false)
    expect(auth?.user).toBeNull()
  })

  it('clears private cache on a logout received from another tab', async () => {
    let channel!: { onmessage: ((event: MessageEvent) => void) | null }
    class TestChannel {
      onmessage: ((event: MessageEvent) => void) | null = null
      constructor() { channel = this }
      close() {}
      postMessage() {}
    }
    vi.stubGlobal('BroadcastChannel', TestChannel)
    const client = new QueryClient()
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider(client)
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    client.setQueryData(['private'], 'first-user-data')
    act(() => channel.onmessage?.(new MessageEvent('message', { data: { type: 'logout' } })))
    expect(auth?.isAuthenticated).toBe(false)
    expect(client.getQueryData(['private'])).toBeUndefined()
    expect(client.getQueryCache().getAll().every(query => query.state.data === undefined)).toBe(true)
  })

  it('clears private cache when refresh definitively rejects the session', async () => {
    const client = new QueryClient()
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider(client)
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    client.setQueryData(['private'], 'first-user-data')
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))
    await act(async () => { await auth!.revalidateSession().catch(() => undefined) })
    expect(auth?.isAuthenticated).toBe(false)
    expect(client.getQueryData(['private'])).toBeUndefined()
    expect(client.getQueryCache().getAll().every(query => query.state.data === undefined)).toBe(true)
  })

  it('retains private cache during a transient revalidation outage', async () => {
    const client = new QueryClient()
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider(client)
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    client.setQueryData(['private'], 'first-user-data')
    mocks.get.mockRejectedValueOnce(axiosError(503))
    await act(async () => { await auth!.revalidateSession().catch(() => undefined) })
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(client.getQueryData(['private'])).toBe('first-user-data')
  })

  it('rejects a previously rejected refresh without another cookie probe', async () => {
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    mocks.isSessionRefreshRejected.mockReturnValue(true)
    await act(async () => {
      await expect(auth!.recoverSession()).rejects.toMatchObject({ response: { status: 401 } })
    })
    expect(auth?.isAuthenticated).toBe(false)
    expect(mocks.refreshSession).not.toHaveBeenCalled()
  })

  it.each(['success', 'failure'])('ignores a late %s from revalidation after account switching', async outcome => {
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    let finish!: (user: { username: string; email: string }) => void
    let fail!: (error: Error) => void
    mocks.get.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    let pending!: Promise<void>
    act(() => { pending = auth!.revalidateSession() })
    mocks.get.mockResolvedValue({ username: 'second', email: 'second@example.com' })
    await act(async () => auth!.login('second-token'))
    await act(async () => {
      if (outcome === 'success') finish({ username: 'first', email: 'first@example.com' })
      else fail(axiosError(401))
      await pending
    })
    expect(auth?.user?.username).toBe('second')
    expect(auth?.isAuthenticated).toBe(true)
    expect(mocks.refreshSession).not.toHaveBeenCalled()
  })

  it.each(['success', 'failure'])('ignores a late %s from login after logout', async outcome => {
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    let finish!: (user: { username: string; email: string }) => void
    let fail!: (error: Error) => void
    mocks.get.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    let pending!: Promise<void>
    act(() => { pending = auth!.login('second-token') })
    act(() => auth!.logout())
    await act(async () => {
      if (outcome === 'success') finish({ username: 'second', email: 'second@example.com' })
      else fail(axiosError(503))
      await pending
    })
    expect(auth?.user).toBeNull()
    expect(auth?.authState.status).toBe('unauthenticated')
  })

  it.each(['success', 'failure'])('ignores a late refresh %s after logout', async outcome => {
    mocks.get.mockResolvedValue({ username: 'first', email: 'first@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    let finish!: (token: string) => void
    let fail!: (error: Error) => void
    mocks.refreshSession.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject }))
    let pending!: Promise<void>
    act(() => { pending = auth!.recoverSession() })
    act(() => auth!.logout())
    const requestsAtLogout = mocks.get.mock.calls.length
    await act(async () => {
      if (outcome === 'success') finish('old-account-token')
      else fail(axiosError(401))
      await pending
    })
    expect(auth?.isAuthenticated).toBe(false)
    expect(auth?.user).toBeNull()
    expect(mocks.get).toHaveBeenCalledTimes(requestsAtLogout)
  })

  it('keeps bootstrap in recovery after a transient network failure and authenticates on retry', async () => {
    vi.useFakeTimers()
    // First call fails with network error, second succeeds
    mocks.get
      .mockRejectedValueOnce(Object.assign(new Error('network timeout'), { isAxiosError: true, code: 'ERR_NETWORK' }))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    renderProvider()

    // Flush the initial bootstrap attempt: network failure -> degraded state
    // with a bounded exponential-backoff retry scheduled.
    // NOTE: waitFor cannot be used with fake timers (its polling timers never
    // fire), so the retry is driven deterministically with timer advancement.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.status).toBe('network_error')

    // Fire the scheduled backoff retry (attempt-1 delay is ~1000-1100ms) and
    // flush the recovery chain through to the authenticated state.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.isLoading).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.get).toHaveBeenCalledTimes(3)
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/v1/auth/me', {
      timeout: 15000,
      skipAuthRedirect: true,
    })
    
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/v1/users/me/preferences', PREFERENCES_CONFIG)
  }, 15000)

  it('logs out when explicit recovery proves the persistent session is invalid', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('authenticated'))
    await waitForPreferencesFetch()

    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))
    await act(async () => {
      await expect(auth!.recoverSession(15000)).rejects.toMatchObject({ response: { status: 401 } })
    })

    expect(auth?.authState.status).toBe('unauthenticated')
    expect(mocks.clearAccessToken).toHaveBeenCalledOnce()
  })

  it('transitions to degraded state when explicit recovery hits a transient server failure', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('authenticated'))
    await waitForPreferencesFetch()

    mocks.refreshSession.mockRejectedValueOnce(axiosError(503))
    await act(async () => {
      await expect(auth!.recoverSession(15000)).rejects.toMatchObject({ response: { status: 503 } })
    })

    // New behavior: transition to service_unavailable degraded state instead of staying authenticated
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    // User should still have access to content (ProtectedRoute allows degraded states)
    expect(auth?.authState.user).toEqual({ username: 'reader', email: 'reader@example.com' })
  })

  it('silently recovers the bootstrap session when the access token is rejected', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get
      .mockRejectedValueOnce(axiosError(401))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    mocks.refreshSession.mockResolvedValueOnce('new-token')

    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('authenticated'))
    await waitForPreferencesFetch()

    expect(auth?.authState.isLoading).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.refreshSession).toHaveBeenCalledWith({ skipAuthRedirect: true })
  })

  it('only shows the login screen when silent recovery also fails', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('unauthenticated'))

    expect(auth?.authState.isLoading).toBe(false)
    expect(mocks.clearAccessToken).toHaveBeenCalled()
  })

  it('clears a stale access token without probing refresh when the cookie session is already rejected', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.isSessionRefreshRejected.mockReturnValue(true)
    mocks.get.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('unauthenticated'))

    expect(mocks.refreshSession).not.toHaveBeenCalled()
    expect(mocks.clearAccessToken).toHaveBeenCalled()
  })

  it('revalidates silently before logging the user out on resume', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.authState.status).toBe('authenticated'))
    await waitForPreferencesFetch()

    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockResolvedValueOnce('new-token')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    await act(async () => {
      await auth!.revalidateSession(15000)
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
  })
})

describe('bootstrap retry budget and manual recovery race', () => {
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
  })

  it('exhausts retry budget at 5 retries for persistent 503 and stops scheduling', async () => {
    vi.useFakeTimers()
    // Simulate 6 calls: 1 initial + 5 retries, all failing with 503
    // The 7th call should never happen
    const error503 = axiosError(503)
    for (let i = 0; i < 6; i++) {
      mocks.get.mockRejectedValueOnce(error503)
    }

    renderProvider()

    // Initial bootstrap attempt fails
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(auth?.authState.retryCount).toBe(1)

    // Retry 1 (~1s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(2)

    // Retry 2 (~2s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2200)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(3)

    // Retry 3 (~4s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4400)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(4)

    // Retry 4 (~8s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8800)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(5)

    // Retry 5 (~16s) - this is the final retry
    await act(async () => {
      await vi.advanceTimersByTimeAsync(17600)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(5) // Should stay at 5, not go to 6
    expect(auth?.authState.status).toBe('service_unavailable')

    // Advance well beyond the final retry - no more calls should be made
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    // Should only have 6 calls: 1 initial + 5 retries
    expect(mocks.get).toHaveBeenCalledTimes(6)
  }, 15000)

  it('manual retryAuth clears stale in-flight recovery and succeeds', async () => {
    vi.useFakeTimers()
    // Bootstrap starts with a 503 failure that will schedule a retry
    // Manual retryAuth should succeed on its own attempt
    mocks.get
      .mockRejectedValueOnce(axiosError(503)) // initial bootstrap
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' }) // manual retry succeeds
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 }) // preferences

    renderProvider()

    // Initial bootstrap fails
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(auth?.authState.isLoading).toBe(false)

    // User clicks "Try again" while a retry is scheduled
    // This should clear the stale recovery and run a fresh one
    await act(async () => {
      await auth!.retryAuth()
    })

    // Should succeed and transition to authenticated
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.isLoading).toBe(false)
    expect(auth?.authState.user).toEqual({ username: 'reader', email: 'reader@example.com' })

    // Should have made 3 calls: initial bootstrap, manual retry, preferences
    expect(mocks.get).toHaveBeenCalledTimes(3)
  }, 15000)

  it('manual recovery during an in-flight bootstrap joins it instead of probing twice', async () => {
    vi.useFakeTimers()
    let resolveSlowBootstrap!: (user: { username: string; email: string }) => void

    mocks.get
      .mockImplementationOnce(() => new Promise(resolve => { resolveSlowBootstrap = resolve })) // slow bootstrap
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 }) // preferences

    renderProvider()

    // Do not advance timers: the initial bootstrap probe is in flight.

    // User clicks "Try again" before the bootstrap resolves.
    const manualRetryPromise = act(async () => {
      await auth!.retryAuth()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    // The manual retry joined the in-flight probe: exactly one concurrent
    // /v1/auth/me request was issued for this session.
    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')).toHaveLength(1)

    await act(async () => {
      resolveSlowBootstrap({ username: 'reader', email: 'reader@example.com' })
      await vi.advanceTimersByTimeAsync(0)
    })
    await manualRetryPromise

    // The single shared probe authenticates; no duplicate request was added.
    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.user?.username).toBe('reader')
    expect(auth?.authState.isLoading).toBe(false)
    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')).toHaveLength(1)
  }, 15000)

  it('manual retryAuth while recoverSession is in-flight does not hang isLoading', async () => {
    vi.useFakeTimers()
    let resolveRecovery!: (user: { username: string; email: string }) => void

    // First call: initial bootstrap fails with 503
    // Second call: recoverSession (triggered by retryAuth) - we'll make it slow
    mocks.refreshSession.mockResolvedValue('new-token')
    mocks.get
      .mockRejectedValueOnce(axiosError(503))
      .mockImplementationOnce(() => new Promise(resolve => { resolveRecovery = resolve }))
      .mockResolvedValueOnce({ username: 'recovered', email: 'recovered@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    renderProvider()

    // Initial bootstrap fails - flush the useEffect
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    // Wait for state to update
    await act(async () => {
      await Promise.resolve()
    })
    // Verify auth is set
    expect(auth).not.toBeNull()
    expect(auth?.authState.status).toBe('service_unavailable')

    // User clicks "Try again" - this calls recoverSession
    const retryPromise = act(async () => {
      await auth!.retryAuth()
    })

    // At this point, recoverSession is in-flight (waiting on resolveRecovery)
    // The retryAuth should not hang even though recoverSession hasn't resolved yet
    // Because retryAuth cleared recoveryPromise and started a fresh one

    // Yield until the mocked recovery request has started so the resolver is assigned
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    resolveRecovery({ username: 'recovered', email: 'recovered@example.com' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    await retryPromise

    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.isLoading).toBe(false)
    expect(auth?.user?.username).toBe('recovered')
  }, 15000)

  it('logout during bootstrap cancels the scheduled retry and ignores stale responses', async () => {
    vi.useFakeTimers()
    const error503 = axiosError(503)
    // Initial bootstrap fails with 503, which schedules a retry.
    mocks.get.mockRejectedValueOnce(error503)

    renderProvider()

    // Flush the initial bootstrap attempt: 503 -> degraded state with a retry scheduled.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(auth?.authState.retryCount).toBe(1)
    expect(mocks.get).toHaveBeenCalledTimes(1)

    // User logs out while a retry timer is scheduled.
    act(() => auth!.logout())
    expect(auth?.authState.status).toBe('unauthenticated')
    expect(auth?.authState.user).toBeNull()
    expect(auth?.authState.retryCount).toBe(0)

    // Advance well beyond the scheduled retry delay. No more /auth/me calls should happen
    // because the timer was cancelled and the generation was incremented.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(mocks.get).toHaveBeenCalledTimes(1)
    expect(auth?.authState.status).toBe('unauthenticated')
  }, 15000)

  it('remount (StrictMode simulation) resets bootstrap without duplicate state corruption', async () => {
    vi.useFakeTimers()
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })

    // First mount: bootstrap succeeds.
    const { unmount } = renderProvider()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.user?.username).toBe('reader')
    const callsAfterFirstMount = mocks.get.mock.calls.length

    // Simulate StrictMode unmount: cleanup runs, clearing timers and in-flight state.
    unmount()

  // Second mount: fresh bootstrap starts, counter reset, new /auth/me call.
  renderProvider()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(auth?.authState.status).toBe('authenticated')
  expect(auth?.user?.username).toBe('reader')

  const authMeCalls = mocks.get.mock.calls.filter(
    ([url]) => url === '/v1/auth/me',
  )
  const authMeCallsAfterFirstMount = mocks.get.mock.calls
    .slice(0, callsAfterFirstMount)
    .filter(([url]) => url === '/v1/auth/me')

  // Exactly one additional /auth/me call from the second mount's bootstrap.
  expect(authMeCalls.length).toBe(authMeCallsAfterFirstMount.length + 1)
  expect(authMeCalls[authMeCalls.length - 1]).toEqual([
    '/v1/auth/me',
    {
      timeout: 15000,
      skipAuthRedirect: true,
    },
  ])
  expect(auth?.authState.retryCount).toBe(0)
  }, 15000)

  it('manual Try again does not resume the automatic retry budget after it fails', async () => {
    vi.useFakeTimers()
    mocks.get.mockRejectedValue(axiosError(503))

    renderProvider()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(1)
    expect(mocks.get).toHaveBeenCalledTimes(1)

    await act(async () => {
      await auth!.retryAuth().catch(() => undefined)
    })
    expect(auth?.authState.isLoading).toBe(false)

    const callsAfterManualRetry = mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me').length
    // Manual recovery owns the budget now: no further automatic probe may fire.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')).toHaveLength(callsAfterManualRetry)
    expect(auth?.authState.status).toBe('service_unavailable')
  }, 15000)

  it('a successful resume revalidation cancels the pending bootstrap retry', async () => {
    vi.useFakeTimers()
    mocks.get
      .mockRejectedValueOnce(axiosError(503)) // initial bootstrap probe
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' }) // resume revalidation
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 }) // preferences

    renderProvider()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(auth?.authState.retryCount).toBe(1)

    await act(async () => {
      await auth!.revalidateSession(15000)
    })
    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.retryCount).toBe(0)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    // Only the failed bootstrap probe and the successful revalidation probe.
    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')).toHaveLength(2)
  }, 15000)

  it('a 401 followed by a transient recovery probe retries instead of logging out', async () => {
    vi.useFakeTimers()
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get
      .mockRejectedValueOnce(axiosError(401)) // bootstrap probe sees a stale token
      .mockRejectedValueOnce(axiosError(503)) // recovery /auth/me stays unavailable
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' }) // automatic retry succeeds
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 }) // preferences

    renderProvider()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    // The 401 must not log the user out while the recovery probe is transient.
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(auth?.authState.retryCount).toBe(1)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(auth?.authState.status).toBe('authenticated')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
  }, 15000)

  it('StrictMode double-mount performs a single initial bootstrap probe', async () => {
    vi.useFakeTimers()
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })

    // Enable root-level strict mode and verify that the effect runs twice while sharing one request
    // We need to bypass the default test wrapper to put StrictMode at the actual root level
    const { render } = await vi.importActual<typeof import('@testing-library/react')>('@testing-library/react')
    
    render(
      <StrictMode>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <AuthProvider>
            <Consumer />
          </AuthProvider>
        </QueryClientProvider>
      </StrictMode>,
      { wrapper: undefined } // Bypass the default test wrapper
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(mocks.get.mock.calls.filter(([url]) => url === '/v1/auth/me')).toHaveLength(1)
    expect(auth?.authState.status).toBe('authenticated')
    expect(auth?.authState.retryCount).toBe(0)
  }, 15000)
})
