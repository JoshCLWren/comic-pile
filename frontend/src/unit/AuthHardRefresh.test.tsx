import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { act, render, waitFor } from './testingLibrary'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { AuthContextValue } from '../App'
import { AuthProvider, useAuth } from '../App'
import api, * as authTransport from '../services/api'

const originalApiMethods = { get: api.get, post: api.post }
const mockApiGet = vi.fn<typeof api.get>()
const mockApiPost = vi.fn<typeof api.post>()
const mockGetAccessToken = vi.fn<typeof authTransport.getAccessToken>()
const mockSetAccessToken = vi.fn<typeof authTransport.setAccessToken>()
const mockClearAccessToken = vi.fn<typeof authTransport.clearAccessToken>()
const mockReadStoredAccessToken = vi.fn<typeof authTransport.readStoredAccessToken>()
const mockRefreshSession = vi.fn<typeof authTransport.refreshSession>()
const mockIsSessionRefreshRejected = vi.fn<typeof authTransport.isSessionRefreshRejected>()

let authState: AuthContextValue | null = null

function AuthStateProbe() {
  const auth = useAuth()

  useEffect(() => {
    authState = auth
  }, [auth])

  return null
}

function renderAuthProvider() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('hard refresh session bootstrap', () => {
  beforeEach(() => {
    Object.assign(api, { get: mockApiGet, post: mockApiPost })
    vi.spyOn(authTransport, 'getAccessToken').mockImplementation(mockGetAccessToken)
    vi.spyOn(authTransport, 'readStoredAccessToken').mockImplementation(mockReadStoredAccessToken)
    vi.spyOn(authTransport, 'setAccessToken').mockImplementation(mockSetAccessToken)
    vi.spyOn(authTransport, 'clearAccessToken').mockImplementation(mockClearAccessToken)
    vi.spyOn(authTransport, 'refreshSession').mockImplementation(mockRefreshSession)
    vi.spyOn(authTransport, 'isSessionRefreshRejected').mockImplementation(mockIsSessionRefreshRejected)
    authState = null
    mockApiGet.mockReset()
    mockApiPost.mockReset()
    mockGetAccessToken.mockReset()
    mockGetAccessToken.mockReturnValue(null)
    mockReadStoredAccessToken.mockReset()
    mockReadStoredAccessToken.mockReturnValue(null)
    mockSetAccessToken.mockReset()
    mockClearAccessToken.mockReset()
    mockRefreshSession.mockReset()
    mockRefreshSession.mockRejectedValue(Object.assign(new Error('unauthenticated'), {
      isAxiosError: true,
      response: { status: 401 },
    }))
    mockIsSessionRefreshRejected.mockReset()
    mockIsSessionRefreshRejected.mockReturnValue(false)
    delete window.__COMIC_PILE_ACCESS_TOKEN
    vi.stubGlobal('BroadcastChannel', undefined)
  })

  afterEach(() => {
    Object.assign(api, originalApiMethods)
    Object.assign(authTransport, originalAuthTransport)
    window.history.replaceState({}, '', '/')
    vi.unstubAllGlobals()
  })

  test('validates a refresh-cookie session on a protected-route hard reload', async () => {
    window.history.replaceState({}, '', '/queue')
    mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@example.com' })

    renderAuthProvider()

    await waitFor(() => {
      expect(authState?.isAuthenticated).toBe(true)
    })
    expect(mockApiGet).toHaveBeenCalledWith('/v2/auth/me', {
      timeout: 15000,
      skipAuthRedirect: true,
      skipAuthRefresh: true,
    })
    expect(mockClearAccessToken).not.toHaveBeenCalled()
  })

  test('preserves the authenticated screen when resume validation is temporarily unavailable', async () => {
    window.history.replaceState({}, '', '/queue')
    mockGetAccessToken.mockReturnValue('preserved-access-token')
    mockApiGet.mockResolvedValueOnce({ username: 'testuser', email: 'test@example.com' })

    renderAuthProvider()

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

    renderAuthProvider()

    await waitFor(() => {
      expect(authState?.isLoading).toBe(false)
    })
    expect(authState?.isAuthenticated).toBe(false)
    expect(mockApiGet).not.toHaveBeenCalled()
  })

  test('still skips the anonymous probe on the register page', async () => {
    window.history.replaceState({}, '', '/register')

    renderAuthProvider()

    await waitFor(() => {
      expect(authState?.isLoading).toBe(false)
    })
    expect(authState?.isAuthenticated).toBe(false)
    expect(mockApiGet).not.toHaveBeenCalled()
  })
})
