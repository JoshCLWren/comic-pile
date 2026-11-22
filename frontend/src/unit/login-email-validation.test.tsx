import { fireEvent, render, screen, waitFor } from './testingLibrary'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from '../pages/LoginPage'
import { AuthContext, type AuthContextValue } from '../contexts/AuthContext'
import api from '../services/api'

const originalApiPost = api.post
const mockApiPost = vi.fn<typeof api.post>()
const login = vi.fn<AuthContextValue['login']>()
const auth: AuthContextValue = {
  authState: {
    status: 'unauthenticated',
    isLoading: false,
    user: null,
    error: null,
    retryCount: 0,
    lastRetryAt: null,
  },
  isAuthenticated: false,
  isLoading: false,
  user: null,
  login,
  logout: vi.fn(),
  revalidateSession: vi.fn<AuthContextValue['revalidateSession']>(),
  recoverSession: vi.fn<AuthContextValue['recoverSession']>(),
  retryAuth: vi.fn<AuthContextValue['retryAuth']>(),
  clearAuthError: vi.fn(),
}

function renderRoute(ui: React.ReactElement) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={auth}>{ui}</AuthContext.Provider>
    </MemoryRouter>,
  )
}

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
}

describe('LoginPage Email Validation', () => {
  beforeEach(() => {
    Object.assign(api, { post: mockApiPost })
    localStorage.clear()
    vi.clearAllMocks()
    login.mockResolvedValue(undefined)
    mockApiPost.mockResolvedValue({ access_token: 'mock-token' })
  })

  afterEach(() => {
    Object.assign(api, { post: originalApiPost })
  })

  it('should show error when email-shaped username is submitted', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('reader@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should show error for email with multiple @ symbols', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user@name@domain.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should reject username with @ in the middle', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user@home', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should allow username without @ symbol', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('validusername', 'password123')
    expect(
      screen.queryByText('Sign in with your username, not your email.'),
    ).not.toBeInTheDocument()
    expect(mockApiPost).toHaveBeenCalledWith(
      '/v2/auth/login',
      expect.objectContaining({ username: 'validusername', password: 'password123' }),
    )
  })

  it('should show error for email with spaces', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user name@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should show error for email with special characters', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user+tag@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should handle empty username field', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('', 'password123')
    expect(screen.getByText('Username is required')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should handle empty password field', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('testuser', '')
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    expect(mockApiPost).not.toHaveBeenCalled()
  })

  it('should handle API error for invalid credentials', async () => {
    mockApiPost.mockRejectedValue({ isAxiosError: true, response: { status: 401, data: {} } })
    renderRoute(<LoginPage />)
    fillAndSubmit('testuser', 'wrongpassword')
    await waitFor(() => {
      expect(screen.getByText('Invalid username or password')).toBeInTheDocument()
    })
  })

  it('should handle network error', async () => {
    mockApiPost.mockRejectedValue(new Error('Network Error'))
    renderRoute(<LoginPage />)
    fillAndSubmit('testuser', 'password123')
    await waitFor(() => {
      expect(screen.getByText('Login failed. Please try again.')).toBeInTheDocument()
    })
  })

  it('should clear error when valid input is resubmitted', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('reader@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    fillAndSubmit('validuser', 'password123')
    expect(
      screen.queryByText('Sign in with your username, not your email.'),
    ).not.toBeInTheDocument()
    expect(mockApiPost).toHaveBeenCalled()
  })
})
