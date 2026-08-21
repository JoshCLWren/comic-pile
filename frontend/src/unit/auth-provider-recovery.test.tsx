import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthContextValue } from '../App'

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  clearAccessToken: vi.fn(),
  setAccessToken: vi.fn(),
  getAccessToken: vi.fn<() => string | null>(),
}))

vi.mock('../services/api', () => ({
  default: {
    get: mocks.get,
    post: mocks.post,
  },
  clearAccessToken: mocks.clearAccessToken,
  setAccessToken: mocks.setAccessToken,
  getAccessToken: mocks.getAccessToken,
}))

import { AuthProvider, useAuth } from '../App'

let auth: AuthContextValue | null = null

function Consumer() {
  auth = useAuth()
  return null
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Consumer />
    </AuthProvider>,
  )
}

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

describe('AuthProvider transient recovery', () => {
  beforeEach(() => {
    auth = null
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.clearAccessToken.mockReset()
    mocks.setAccessToken.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
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
    expect(mocks.get).toHaveBeenNthCalledWith(3, '/v1/users/me/preferences', {
      timeout: 15000,
      skipAuthRedirect: true,
    })
  })

  it('logs out when explicit recovery proves the persistent session is invalid', async () => {
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    mocks.post.mockRejectedValueOnce(axiosError(401))
    await act(async () => {
      await expect(auth!.recoverSession(15000)).rejects.toMatchObject({ response: { status: 401 } })
    })

    expect(auth?.isAuthenticated).toBe(false)
    expect(mocks.clearAccessToken).toHaveBeenCalledOnce()
  })

  it('preserves authenticated state when explicit recovery hits a transient server failure', async () => {
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    mocks.post.mockRejectedValueOnce(axiosError(503))
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
    mocks.post.mockResolvedValueOnce({ access_token: 'new-token', refresh_token: 'new-refresh' })

    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    expect(auth?.isLoading).toBe(false)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
    expect(mocks.post).toHaveBeenCalledWith('/v1/auth/refresh', undefined, { skipAuthRedirect: true })
  })

  it('only shows the login screen when silent recovery also fails', async () => {
    mocks.getAccessToken.mockReturnValue('stale-token')
    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.post.mockRejectedValueOnce(axiosError(401))

    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(false))

    expect(auth?.isLoading).toBe(false)
    expect(mocks.clearAccessToken).toHaveBeenCalled()
  })

  it('revalidates silently before logging the user out on resume', async () => {
    mocks.get.mockResolvedValue({ username: 'reader', email: 'reader@example.com' })
    renderProvider()
    await waitFor(() => expect(auth?.isAuthenticated).toBe(true))

    mocks.get.mockRejectedValueOnce(axiosError(401))
    mocks.post.mockResolvedValueOnce({ access_token: 'new-token', refresh_token: 'new-refresh' })
    mocks.get.mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })

    await act(async () => {
      await auth!.revalidateSession(15000)
    })

    expect(auth?.isAuthenticated).toBe(true)
    expect(mocks.clearAccessToken).not.toHaveBeenCalled()
  })
})
