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
    preferencesApi: {
      get: (options?: { timeout?: number; skipAuthRedirect?: boolean }) =>
        apiMock.get('/v1/users/me/preferences', options),
      patch: (data: { theme?: string | null }) =>
        apiMock.patch('/v1/users/me/preferences', data),
    },
    clearAccessToken: mocks.clearAccessToken,
    setAccessToken: mocks.setAccessToken,
    getAccessToken: mocks.getAccessToken,
    readStoredAccessToken: mocks.readStoredAccessToken,
    refreshSession: mocks.refreshSession,
    isSessionRefreshRejected: mocks.isSessionRefreshRejected,
  }
})

import { PreferencesSync } from '../hooks/usePreferences'
import { AuthProvider, useAuth } from '../contexts/AuthContext'

let auth: AuthContextValue | null = null

function Consumer() {
  auth = useAuth()
  return null
}

function PreferencesSyncConsumer() {
  const { authState } = useAuth()
  return <PreferencesSync isAuthenticated={authState.status === 'authenticated'} />
}

function renderProvider() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
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
  })

  it('keeps bootstrap in recovery after a transient network failure and authenticates on retry', async () => {
    vi.useFakeTimers()
    // First call fails with network error, second succeeds
    mocks.get
      .mockRejectedValueOnce(Object.assign(new Error('network timeout'), { isAxiosError: true }))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    renderProvider()
    await act(async () => {
      await Promise.resolve()
    })

    // During bootstrap failure, status should be network_error (degraded), isLoading false
    expect(auth?.authState.status).toBe('network_error')
    expect(auth?.authState.isLoading).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(auth?.authState.isLoading).toBe(false)
    expect(auth?.authState.status).toBe('authenticated')
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.get).toHaveBeenCalledTimes(3)
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/v1/auth/me', {
      timeout: 15000,
      skipAuthRedirect: true,
    })
    await act(async () => {
      await Promise.resolve()
    })
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/v1/users/me/preferences', PREFERENCES_CONFIG)
  })

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