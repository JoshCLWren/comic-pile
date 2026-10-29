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
  resumeQueriesAfterOutage: vi.fn(async () => undefined),
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

vi.mock('../query/cacheEffects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../query/cacheEffects')>()
  return {
    ...actual,
    resumeQueriesAfterOutage: mocks.resumeQueriesAfterOutage,
  }
})

import { resetQueryRetryBudget, getQueryRetryBudgetSnapshot } from '../query/outageRetryBudget'
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

function renderProvider(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Consumer />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

async function flushTimers(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('AuthProvider query outage coordination (#4271)', () => {
  beforeEach(() => {
    auth = null
    resetQueryRetryBudget()
    mocks.get.mockReset()
    mocks.post.mockReset()
    mocks.patch.mockReset()
    mocks.clearAccessToken.mockReset()
    mocks.setAccessToken.mockReset()
    mocks.getAccessToken.mockReset()
    mocks.readStoredAccessToken.mockReset()
    mocks.refreshSession.mockReset()
    mocks.isSessionRefreshRejected.mockReset()
    mocks.resumeQueriesAfterOutage.mockReset()
    mocks.getAccessToken.mockReturnValue('test-token')
    mocks.isSessionRefreshRejected.mockReturnValue(false)
    delete window.__COMIC_PILE_ACCESS_TOKEN
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('suppresses query retries while degraded and resumes them once after auth recovery', async () => {
    vi.useFakeTimers()
    mocks.get
      .mockRejectedValueOnce(axiosError(503))
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: null, user_id: 1 })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderProvider(client)

    await flushTimers(0)
    expect(auth?.authState.status).toBe('service_unavailable')
    expect(getQueryRetryBudgetSnapshot().authDegraded).toBe(true)
    expect(mocks.resumeQueriesAfterOutage).not.toHaveBeenCalled()

    // The bounded auth bootstrap retry succeeds and marks the app healthy.
    await flushTimers(5_000)
    await flushTimers(0)

    expect(auth?.authState.status).toBe('authenticated')
    expect(getQueryRetryBudgetSnapshot().authDegraded).toBe(false)
    expect(mocks.resumeQueriesAfterOutage).toHaveBeenCalledTimes(1)
    expect(mocks.resumeQueriesAfterOutage).toHaveBeenCalledWith(client)
  })

  it('does not resume queries on an ordinary authenticated bootstrap', async () => {
    mocks.get
      .mockResolvedValueOnce({ username: 'reader', email: 'reader@example.com' })
      .mockResolvedValueOnce({ theme: null, user_id: 1 })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    renderProvider(client)

    await waitFor(() => expect(auth?.authState.status).toBe('authenticated'))
    expect(mocks.resumeQueriesAfterOutage).not.toHaveBeenCalled()
    expect(getQueryRetryBudgetSnapshot().authDegraded).toBe(false)
  })
})
