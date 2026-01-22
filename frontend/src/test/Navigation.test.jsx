import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { expect, test, afterEach } from 'vitest'
import App, { AuthProvider } from '../App'
import Navigation from '../components/Navigation'

afterEach(() => {
  localStorage.clear()
})

const renderWithAuth = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  localStorage.setItem('auth_token', 'test-token')

  return render(
    <MemoryRouter initialEntries={['/']}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Navigation />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

const renderWithoutAuth = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <MemoryRouter initialEntries={['/']}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Navigation />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

test('renders navigation links when authenticated', () => {
  renderWithAuth()

  expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /rate page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /analytics page/i })).toBeInTheDocument()
})

test('does not render when not authenticated', () => {
  const { container } = renderWithoutAuth()

  expect(container).toBeEmptyDOMElement()
})

test('shows logout button when authenticated', () => {
  renderWithAuth()

  expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
})
