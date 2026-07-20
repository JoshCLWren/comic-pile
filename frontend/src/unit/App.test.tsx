import { expect, test, vi, beforeEach, describe } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useEffect } from 'react'
import type { AuthContextValue } from '../App'

// Create mock function for API get
const mockApiGet = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()

// Mock the API module with a factory that doesn't reference outer scope
vi.mock('../services/api', () => {
  return {
    default: {
      get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
      post: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    },
    setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
    clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
  }
})

vi.mock('../pages/LoginPage', () => ({
  default: () => <div data-testid="login-page">Welcome Back</div>,
}))
vi.mock('../pages/RegisterPage', () => ({
  default: () => <div data-testid="register-page">Create Account</div>,
}))
vi.mock('../pages/RollPage', () => ({ default: () => <div data-testid="roll-page">Roll</div> }))
vi.mock('../pages/RatePage', () => ({ default: () => <div data-testid="rate-page">Rate</div> }))
vi.mock('../pages/QueuePage', () => ({ default: () => <div data-testid="queue-page">Queue</div> }))
vi.mock('../pages/HistoryPage', () => ({ default: () => <div data-testid="history-page">History</div> }))
vi.mock('../pages/SessionPage', () => ({ default: () => <div data-testid="session-page">Session</div> }))
vi.mock('../pages/AnalyticsPage', () => ({ default: () => <div data-testid="analytics-page">Analytics</div> }))
vi.mock('../pages/ThreadDetailView', () => ({ default: () => <div data-testid="thread-detail-page">Thread detail</div> }))
vi.mock('../pages/HelpPage', () => ({ default: () => <div data-testid="help-page">Help</div> }))

import App, { AuthProvider, AppRoutes, useAuth } from '../App'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'

let authContextValue: AuthContextValue | null = null

const TestAuthConsumer = ({ onAuth }: { onAuth?: (auth: AuthContextValue) => void }) => {
  const auth = useAuth()
  useEffect(() => {
    authContextValue = auth
    if (onAuth) onAuth(auth)
  }, [auth, onAuth])
  return null
}

const renderWithAuth = (initialEntry = '/') => {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <TestAuthConsumer />
          <AppRoutes />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}

test('renders navigation labels', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth('/')

  await waitFor(() => {
    expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /analytics page/i })).toBeInTheDocument()
})

test('throws when the auth hook is used outside its provider', () => {
  expect(() => render(<TestAuthConsumer />)).toThrow('useAuth must be used within an AuthProvider')
})

test('clears a token when login validation fails', async () => {
  mockApiGet.mockRejectedValue(new Error('invalid token'))
  renderWithAuth('/login')
  await waitFor(() => expect(authContextValue).not.toBeNull())

  await expect(authContextValue!.login('bad-token')).rejects.toThrow('invalid token')
  expect(mockClearAccessToken).toHaveBeenCalled()
})

test('logs in successfully and logs out without BroadcastChannel support', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  const originalBroadcastChannel = globalThis.BroadcastChannel
  vi.stubGlobal('BroadcastChannel', undefined)
  renderWithAuth('/login')
  await waitFor(() => expect(authContextValue).not.toBeNull())
  await act(async () => authContextValue?.login('valid-token'))
  expect(mockSetAccessToken).toHaveBeenCalledWith('valid-token')
  act(() => authContextValue?.logout())
  expect(mockClearAccessToken).toHaveBeenCalled()
  if (originalBroadcastChannel) vi.stubGlobal('BroadcastChannel', originalBroadcastChannel)
  else vi.unstubAllGlobals()
})

test('mounts the application shell', async () => {
  mockApiGet.mockRejectedValue(new Error('unauthenticated'))
  render(<App />)
  await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
})

test('loads each authenticated lazy route', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  for (const path of ['/queue', '/history', '/sessions/1', '/analytics', '/help', '/thread/1']) {
    const { unmount } = renderWithAuth(path)
    await waitFor(() => expect(screen.queryByTestId(/-page$/)).not.toBeNull())
    unmount()
  }
})

test('broadcasts logout events and closes the auth channel', async () => {
  const postMessage = vi.fn()
  const close = vi.fn()
  let channel: TestBroadcastChannel | undefined
  class TestBroadcastChannel {
    onmessage: ((event: MessageEvent) => void) | null = null
    postMessage = postMessage
    close = close
    constructor(public readonly name: string) { channel = this }
  }
  vi.stubGlobal('BroadcastChannel', TestBroadcastChannel)
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth('/')
  await waitFor(() => expect(authContextValue?.isAuthenticated).toBe(true))
  act(() => channel?.onmessage?.({ data: { type: 'other' } } as MessageEvent))
  expect(authContextValue?.isAuthenticated).toBe(true)
  act(() => channel?.onmessage?.({ data: { type: 'logout' } } as MessageEvent))
  expect(authContextValue?.isAuthenticated).toBe(false)
  act(() => authContextValue?.logout())
  expect(postMessage).toHaveBeenCalledWith({ type: 'logout' })
  expect(close).toHaveBeenCalled()
  vi.unstubAllGlobals()
})

describe('route guards', () => {
  beforeEach(() => {
    mockApiGet.mockReset()
    mockSetAccessToken.mockReset()
    mockClearAccessToken.mockReset()
    mockApiGet.mockRejectedValue(new Error('unauthenticated'))
    delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
  })

  test('redirects unauthenticated users to /login when accessing protected routes', async () => {
    renderWithAuth('/')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })
  })

  test('allows authenticated users to access protected routes', async () => {
    mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
      'fake-token'
    renderWithAuth('/')

    await waitFor(() => {
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    })
  })

  test('allows unauthenticated users to access /login', async () => {
    mockApiGet.mockRejectedValue(new Error('unauthenticated'))
    renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })
  })

  test('allows unauthenticated users to access /register', async () => {
    mockApiGet.mockRejectedValue(new Error('unauthenticated'))
    renderWithAuth('/register')

    await waitFor(() => {
      expect(screen.getByTestId('register-page')).toBeInTheDocument()
    })
  })

  test('redirects authenticated users from /login to home', async () => {
    mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
      'fake-token'
    renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    })
  })

  test('redirects authenticated users from /register to home', async () => {
    mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
      'fake-token'
    renderWithAuth('/register')

    await waitFor(() => {
      expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
    })
  })
})

describe('auth state race condition regression', () => {
  beforeEach(() => {
    authContextValue = null
    mockApiGet.mockReset()
    mockSetAccessToken.mockReset()
    mockClearAccessToken.mockReset()
    mockApiGet.mockRejectedValue(new Error('unauthenticated'))
    delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
  })

  test('auth state updates immediately after login - no redirect loop', async () => {
    mockApiGet
      .mockRejectedValueOnce(new Error('unauthenticated'))
      .mockResolvedValue({ username: 'testuser', email: 'test@test.com' })

    renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(authContextValue).not.toBeNull()
    })

    await act(async () => {
      if (!authContextValue) {
        throw new Error('auth context not available')
      }
      await authContextValue.login('test-token')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    })
  })

  test('auth state updates immediately after register - no redirect loop', async () => {
    mockApiGet
      .mockRejectedValueOnce(new Error('unauthenticated'))
      .mockResolvedValue({ username: 'testuser', email: 'test@test.com' })

    renderWithAuth('/register')

    await waitFor(() => {
      expect(screen.getByTestId('register-page')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(authContextValue).not.toBeNull()
    })

    await act(async () => {
      if (!authContextValue) {
        throw new Error('auth context not available')
      }
      await authContextValue.login('test-token')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
    })
  })
})
