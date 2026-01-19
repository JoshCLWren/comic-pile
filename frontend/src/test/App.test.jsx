import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, test, vi, beforeEach, afterEach, describe } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    BrowserRouter: ({ children }) => {
      return <>{children}</>
    },
  }
})

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

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  test('allows authenticated users to access protected routes', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/')

    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
  })

  test('allows unauthenticated users to access /login', () => {
    renderApp('/login')

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  test('allows unauthenticated users to access /register', () => {
    renderApp('/register')

    expect(screen.getByText('Register page')).toBeInTheDocument()
  })

  test('redirects authenticated users from /login to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/login')

    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
  })

  test('redirects authenticated users from /register to home', () => {
    localStorage.setItem('auth_token', 'fake-token')
    renderApp('/register')

    expect(screen.queryByText('Register page')).not.toBeInTheDocument()
  })
})
