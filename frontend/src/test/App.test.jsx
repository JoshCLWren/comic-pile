import { expect, test, vi, beforeEach, afterEach, describe } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'

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

import App from '../App'

let currentInitialEntry = '/'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  const { MemoryRouter: ActualMemoryRouter } = actual

  return {
    ...actual,
    BrowserRouter: ({ children }) => {
      return (
        <ActualMemoryRouter initialEntries={[currentInitialEntry]}>
          {children}
        </ActualMemoryRouter>
      )
    },
  }
})

const renderApp = (initialEntry = '/') => {
  currentInitialEntry = initialEntry
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
}

test('renders navigation labels', () => {
  renderApp()

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
    renderApp('/')

    expect(screen.getByTestId('login-page')).toBeInTheDocument()
  })

  test('allows authenticated users to access protected routes', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/')

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  test('allows unauthenticated users to access /login', () => {
    renderApp('/login')

    expect(screen.getByTestId('login-page')).toBeInTheDocument()
  })

  test('allows unauthenticated users to access /register', async () => {
    renderApp('/register')

    await waitFor(() => {
      expect(screen.getByTestId('register-page')).toBeInTheDocument()
    })
  })

  test('redirects authenticated users from /login to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/login')

    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  test('redirects authenticated users from /register to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/register')

    expect(screen.queryByTestId('register-page')).not.toBeInTheDocument()
  })
})
