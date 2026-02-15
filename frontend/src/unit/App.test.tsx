import { expect, test, vi, beforeEach, afterEach, describe } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useEffect } from 'react'

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

import App, { AuthProvider, AppRoutes, useAuth } from '../App'

interface AuthContextValue {
  token: string | null
  login: (token: string) => void
  logout: () => void
}

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
        <TestAuthConsumer />
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>
  )
}

test('renders navigation labels', () => {
  localStorage.setItem('auth_token', 'test-token')
  renderWithAuth('/')

  expect(screen.getByText('Roll')).toBeInTheDocument()
  expect(screen.getByText('Rate')).toBeInTheDocument()
  expect(screen.getByText('Queue')).toBeInTheDocument()
  expect(screen.getByText('History')).toBeInTheDocument()
  expect(screen.getByText('Analytics')).toBeInTheDocument()
})

describe('route guards', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  test('redirects unauthenticated users to /login when accessing protected routes', async () => {
    renderWithAuth('/')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })
  })

  test('allows authenticated users to access protected routes', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderWithAuth('/')

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  test('allows unauthenticated users to access /login', () => {
    renderWithAuth('/login')

    expect(screen.getByTestId('login-page')).toBeInTheDocument()
  })

  test('allows unauthenticated users to access /register', async () => {
    renderWithAuth('/register')

    await waitFor(() => {
      expect(screen.getByTestId('register-page')).toBeInTheDocument()
    })
  })

  test('redirects authenticated users from /login to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderWithAuth('/login')

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  test('redirects authenticated users from /register to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderWithAuth('/register')

    expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
  })
})

describe('auth state race condition regression', () => {
  beforeEach(() => {
    localStorage.clear()
    authContextValue = null
  })

  afterEach(() => {
    localStorage.clear()
  })

  test('auth state updates immediately after login - no redirect loop', async () => {
    renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(authContextValue).not.toBeNull()
    })

    act(() => {
      authContextValue!.login('test-token')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
    })
  })

  test('auth state updates immediately after register - no redirect loop', async () => {
    renderWithAuth('/register')

    await waitFor(() => {
      expect(screen.getByTestId('register-page')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(authContextValue).not.toBeNull()
    })

    act(() => {
      authContextValue!.login('test-token')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
    })
  })
})
