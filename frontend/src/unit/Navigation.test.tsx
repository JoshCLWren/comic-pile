import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, beforeEach, afterEach, vi } from 'vitest'
import App, { AuthProvider } from '../App'
import Navigation from '../components/Navigation'

const mockApiGet = vi.fn()

vi.mock('../services/api', () => {
  return {
    default: {
      get: (...args) => mockApiGet(...args),
      post: vi.fn(),
    },
  }
})

beforeEach(() => {
  mockApiGet.mockReset()
})

afterEach(() => {
  localStorage.clear()
})

const renderWithAuth = () => {
  localStorage.setItem('auth_token', 'test-token')

  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <Navigation />
      </AuthProvider>
    </MemoryRouter>
  )
}

const renderWithoutAuth = () => {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <Navigation />
      </AuthProvider>
    </MemoryRouter>
  )
}

test('renders navigation links when authenticated', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth()

  await waitFor(() => {
    expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /analytics page/i })).toBeInTheDocument()
})

test('does not render when not authenticated', () => {
  const { container } = renderWithoutAuth()

  expect(container).toBeEmptyDOMElement()
})

test('shows logout button when authenticated', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth()

  await waitFor(() => {
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })
})
