import { expect, test, vi, beforeEach, describe, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useEffect } from 'react'
import type { AuthContextValue } from '../App'

const mockApiGet = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()
const mockGetAccessToken = vi.fn<() => string | null>(() => 'test-token')

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
    getAccessToken: () => mockGetAccessToken(),
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

test('renders retained navigation labels', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth('/')

  await waitFor(() => {
    expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /analytics page/i })).not.toBeInTheDocument()
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

test('ignores an auth response that arrives after the provider unmounts', async () => {
  let resolveAuth!: (value: { username: string }) => void
  mockApiGet.mockReturnValueOnce(new Promise((resolve) => { resolveAuth = resolve }))
  const view = renderWithAuth('/')
  view.unmount()
  await act(async () => resolveAuth({ username: 'late-user' }))
})

test('ignores an auth failure that arrives after the provider unmounts', async () => {
  let rejectAuth!: (reason?: unknown) => void
  mockApiGet.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectAuth = reject }))
  const view = renderWithAuth('/')
  view.unmount()
  await act(async () => {
    rejectAuth(new Error('late auth failure'))
    await Promise.resolve()
  })
})

test('loads each retained authenticated lazy route', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  const routes = {
    '/queue': 'queue-page',
    '/history': 'history-page',
    '/sessions/1': 'session-page',
    '/help': 'help-page',
    '/thread/1': 'thread-detail-page',
  }
  for (const [path, testId] of Object.entries(routes)) {
    const { unmount } = renderWithAuth(path)
    await waitFor(() => expect(screen.getByTestId(testId)).toBeInTheDocument())
    unmount()
  }
})

test('redirects the retired analytics route to Roll', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth('/analytics')

  await waitFor(() => expect(screen.getByTestId('roll-page')).toBeInTheDocument())
  expect(screen.queryByText('Analytics')).not.toBeInTheDocument()
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

describe('anonymous no-token probe suppression', () => {
  beforeEach(() => {
    mockApiGet.mockReset()
    mockGetAccessToken.mockReset()
    mockGetAccessToken.mockReturnValue(null)
    mockSetAccessToken.mockReset()
    mockClearAccessToken.mockReset()
    delete (window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN
  })

  afterEach(() => {
    mockGetAccessToken.mockReset()
  })

  test('anonymous user does not call /auth/me when no token exists', async () => {
    renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })
    expect(mockApiGet).not.toHaveBeenCalledWith('/auth/me')
  })

  test('anonymous user falls through correctly to login page from protected route', async () => {
    renderWithAuth('/')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })
  })

  test('SSR token injection still triggers /auth/me when in-memory token is null', async () => {
    mockApiGet.mockResolvedValue({ username: 'ssruser', email: 'ssr@test.com' })
    ;(window as Window & { __COMIC_PILE_ACCESS_TOKEN?: string }).__COMIC_PILE_ACCESS_TOKEN =
      'ssr-token'
    renderWithAuth('/')

    await waitFor(() => {
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    })
    expect(mockApiGet).toHaveBeenCalledWith('/auth/me')
    expect(mockSetAccessToken).toHaveBeenCalledWith('ssr-token')
  })
})
