import { expect, test, vi, beforeEach, afterEach, describe } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as reactRouter from 'react-router-dom'

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

import App, { useAuth } from '../App'

const renderWithAuth = (initialEntry = '/') => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <reactRouter.MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </reactRouter.MemoryRouter>
  )
}

test('renders navigation labels', () => {
  renderWithAuth()

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

  test('redirects unauthenticated users to /login when accessing protected routes', () => {
    renderWithAuth('/')

    expect(screen.getByTestId('login-page')).toBeInTheDocument()
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
  })

  afterEach(() => {
    localStorage.clear()
  })

  test('auth state updates immediately after login - no redirect loop', async () => {
    const { container } = renderWithAuth('/login')

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument()
    })

    act(() => {
      localStorage.setItem('auth_token', 'test-token')
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

    act(() => {
      localStorage.setItem('auth_token', 'test-token')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
    })
  })

  test('isAuthenticated reflects localStorage token immediately', async () => {
    let authValue = null

    const TestComponent = () => {
      const auth = useAuth()
      authValue = auth
      return <div data-testid="auth-status">{auth.isAuthenticated ? 'auth' : 'no-auth'}</div>
    }

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <reactRouter.MemoryRouter initialEntries={['/login']}>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </reactRouter.MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('no-auth')
    })

    act(() => {
      localStorage.setItem('auth_token', 'new-token')
    })

    await waitFor(() => {
      expect(screen.getByTestId('auth-status')).toHaveTextContent('auth')
    })
  })
