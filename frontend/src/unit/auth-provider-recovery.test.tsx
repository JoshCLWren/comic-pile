import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthContextValue } from '../App'

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
import { AuthProvider, useAuth } from '../App'

let auth: AuthContextValue | null = null

function Consumer() {
  auth = useAuth()
  return null
}

function PreferencesSyncConsumer() {
  const { isAuthenticated } = useAuth()
  return <PreferencesSync isAuthenticated={isAuthenticated} />
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Consumer />
      <PreferencesSyncConsumer />
    </AuthProvider>,
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

  it('keeps bootstrap in recovery after a transient failure and authenticates on retry', async () => {
    vi.useFakeTimers()
    mocks.get
      .mockRejectedValueOnce(new Error('network timeout'))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    renderProvider()
    await act(async () => {
      await Promise.resolve()
    })

    expect(auth?.isLoading).toBe(true)
    expect(auth?.isAuthenticated).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })

    expect(auth?.isLoading).toBe(false)
    expect(auth?.isAuthenticated).toBe(true)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.get).toHaveBeenCalledTimes(3)
    expect(mocks.get).toHaveBeenNthCalledWith(2, '/v1/auth/me', {
      timeout: 15000,
      skipAuthRedirect: true,
    })
    await waitForPreferencesFetch()
  })

  it('logs out when explicit recovery proves the persistent session is invalid', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    await waitForPreferencesFetch()

    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))
    await act(async () => {
      await expect(auth!.recoverSession(15000)).rejects.toMatchObject({ response: { status: 401 } })
    })

    expect(auth?.isAuthenticated).toBe(false)
    expect(mocks.clearAccessToken).toHaveBeenCalledOnce()
  })

  it('preserves authenticated state when explicit recovery hits a transient server failure', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    await waitForPreferencesFetch()

    mocks.refreshSession.mockRejectedValueOnce(axiosError(503))
    await act(async () => {
      await expect(auth!.recoverSession(15000)).rejects.toMatchObject({ response: { status: 503 } })
    })

    expect(auth?.isAuthenticated).toBe(true)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
  })

  it('silently recovers the bootstrap session when the access token is rejected', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get
      .mockRejectedValueOnce(axiosError(401))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    mocks.refreshSession.mockResolvedValueOnce('new-token')

    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    await waitForPreferencesFetch()

    expect(auth?.isLoading).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.refreshSession).toHaveBeenCalledWith({ skipAuthRedirect: true })
  })

  it('only shows the login screen when silent recovery also fails', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(false))

    expect(auth?.isLoading).toBe(false)
    expect(mocks.clearAccessToken).toHaveBeenCalled()
  })

  it('clears a stale access token without probing refresh when the cookie session is already rejected', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.isSessionRefreshRejected.mockReturnValue(true)
    mocks.get.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(false))

    expect(mocks.refreshSession).not.toHaveBeenCalled()
    expect(mocks.clearAccessToken).toHaveBeenCalled()
  })

  it('revalidates silently before logging the user out on resume', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))
    await waitForPreferencesFetch()

    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.refreshSession.mockResolvedValueOnce('new-token')
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: 'classic', user_id: 1 })

    await act(async () => {
      await auth!.revalidateSession(15000)
    })

    expect(auth?.isAuthenticated).toBe(true)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
  })
})