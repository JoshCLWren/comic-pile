import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test, beforeEach, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { AuthProvider } from '../App'
import Navigation from '../components/Navigation'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'

const mockApiGet = vi.fn()
const mockApiPost = vi.fn()
const mockSetAccessToken = vi.fn()
const mockClearAccessToken = vi.fn()

vi.mock('../services/api', () => {
  return {
    default: {
      get: (...args: Parameters<typeof mockApiGet>) => mockApiGet(...args),
      post: (...args: Parameters<typeof mockApiPost>) => mockApiPost(...args),
    },
    setAccessToken: (...args: Parameters<typeof mockSetAccessToken>) => mockSetAccessToken(...args),
    clearAccessToken: (...args: Parameters<typeof mockClearAccessToken>) => mockClearAccessToken(...args),
  }
})

beforeEach(() => {
  mockApiGet.mockReset()
  mockApiPost.mockReset()
  mockSetAccessToken.mockReset()
  mockClearAccessToken.mockReset()
})

const renderWithAuth = () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  mockSetAccessToken.mockImplementation(() => undefined)

  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}

const renderWithoutAuth = () => {
  mockApiGet.mockRejectedValue(new Error('unauthenticated'))
  return render(
    <MemoryRouter initialEntries={['/']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>
  )
}

test('renders navigation links when authenticated', async () => {
  renderWithAuth()

  await waitFor(() => {
    expect(screen.getByRole('link', { name: /roll page/i })).toBeInTheDocument()
  })
  expect(screen.getByRole('link', { name: /queue page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /history page/i })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /analytics page/i })).toBeInTheDocument()
})

test('does not render when not authenticated', async () => {
  const { container } = renderWithoutAuth()

  await waitFor(() => {
    expect(container).toBeEmptyDOMElement()
  })
})

test('shows logout button when authenticated', async () => {
  mockApiGet.mockResolvedValue({ username: 'testuser', email: 'test@test.com' })
  renderWithAuth()

  await waitFor(() => {
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })
})

test('shows loading and non-auth failure states and logs out gracefully', async () => {
  mockApiGet.mockResolvedValueOnce({ username: 'user', email: 'user@example.com' })
    .mockRejectedValueOnce(new Error('server unavailable'))
  render(
    <MemoryRouter initialEntries={['/queue']}>
      <AuthProvider>
        <BugReportRestoreProvider>
          <Navigation onBugReportSubmit={vi.fn()} />
        </BugReportRestoreProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument())
  mockApiPost.mockRejectedValueOnce(new Error('logout unavailable'))
  await userEvent.setup().click(screen.getByRole('button', { name: /log out/i }))
  await waitFor(() => expect(mockClearAccessToken).toHaveBeenCalled())

})
