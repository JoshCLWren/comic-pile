import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { act, render, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import type { AuthContextValue } from '../App'

const mockApiGet = vi.fn()
const mockGetAccessToken = vi.fn<() => string | null>(() => null)
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()

vi.mock('../services/api', () => ({
  default: {
    get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
  },
  getAccessToken: () => mockGetAccessToken(),
  setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
  clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
}))

import { AuthProvider, useAuth } from '../App'

let authState: AuthContextValue | null = null

function AuthStateProbe() {
  const auth = useAuth()

  useEffect(() => {
    authState = auth
  }, [auth])

  return null
}

describe('hard refresh session bootstrap', () => {
  beforeEach(() => {
    authState = null
    mockApiGet.mockReset()
    mockGetAccessToken.mockReset()
    mockGetAccessToken.mockReturnValue(null)
    mockSetAccessToken.mockReset()
    mockClearAccessToken.mockReset()
    delete window.__COMIC_PILE_ACCESS_TOKEN
    vi.stubGlobal('BroadcastChannel', undefined)
  })

  afterEach(() => {
    window.history.replaceState({}, '', '/')
    vi.unstubAllGlobals()
  })

  test('validates a refresh-cookie session on a protected-route hard reload', async () => {
    window.history.replaceState({}, '', '/queue')
    mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@example.com' })

    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(authState?.isAuthenticated).toBe(true)
    })
    expect(mockApiGet).toHaveBeenCalledWith('/v1/auth/me', {
      timeout: 15000,
      skipAuthRedirect: true,
    })
    expect(mockClearAccessToken).not.toHaveBeenCalled()
  })

  test('preserves the authenticated screen when resume validation is temporarily unavailable', async () => {
    window.history.replaceState({}, '', '/queue')
    mockGetAccessToken.mockReturnValue('preserved-access-token')
    mockApiGet.mockResolvedValueOnce({ username: 'testuser', email: 'test@example.com' })

    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(authState?.isAuthenticated).toBe(true)
    })
    const accessTokenBeforeRevalidation = mockGetAccessToken()

    mockApiGet.mockRejectedValueOnce(new Error('cold server timeout'))

    await expect(
      act(async () => {
        await authState?.revalidateSession(8000)
      }),
    ).rejects.toThrow('cold server timeout')

    expect(authState?.isAuthenticated).toBe(true)
    expect(authState?.user?.username).toBe('testuser')
    expect(mockGetAccessToken()).toBe(accessTokenBeforeRevalidation)
    expect(window.location.pathname).toBe('/queue')
    expect(mockClearAccessToken).not.toHaveBeenCalled()
  })

  test('still skips the anonymous probe on the login page', async () => {
    window.history.replaceState({}, '', '/login')

    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(authState?.isLoading).toBe(false)
    })
    expect(authState?.isAuthenticated).toBe(false)
    expect(mockApiGet).not.toHaveBeenCalled()
  })

  test('still skips the anonymous probe on the register page', async () => {
    window.history.replaceState({}, '', '/register')

    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    )

    await waitFor(() => {
      expect(authState?.isLoading).toBe(false)
    })
    expect(authState?.isAuthenticated).toBe(false)
    expect(mockApiGet).not.toHaveBeenCalled()
  })
})
