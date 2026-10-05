import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ login: vi.fn() }))
const api = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('../App', () => ({ useAuth: () => auth }))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, default: api }
})

import LoginPage from '../pages/LoginPage'

function renderRoute(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
}

describe('LoginPage Email Validation', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    auth.login.mockResolvedValue(undefined)
    api.post.mockResolvedValue({ access_token: 'mock-token' })
  })

  it('should show error when email-shaped username is submitted', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('reader@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should show error for email with multiple @ symbols', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user@name@domain.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should reject username with @ in the middle', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user@home', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should allow username without @ symbol', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('validusername', 'password123')
    expect(
      screen.queryByText('Sign in with your username, not your email.'),
    ).not.toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith(
      '/v1/auth/login',
      expect.objectContaining({ username: 'validusername', password: 'password123' }),
    )
  })

  it('should show error for email with spaces', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user name@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should show error for email with special characters', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('user+tag@example.com', 'password123')
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should handle empty username field', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('', 'password123')
    expect(screen.getByText('Username is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should handle empty password field', () => {
    renderRoute(<LoginPage />)
    fillAndSubmit('testuser', '')
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('should handle API error for invalid credentials', async () => {
    api.post.mockRejectedValue({ isAxiosError: true, response: { status: 401, data: {} } })
    renderRoute(<LoginPage />)
    fillAndSubmit('testuser', 'wrongpassword')
    await waitFor(() => {
      expect(screen.getByText('Invalid username or password')).toBeInTheDocument()
    })
  })

  it('should handle network error', async () => {
    api.post.mockRejectedValue(new Error('Network Error'))
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
    expect(api.post).toHaveBeenCalled()
  })
})
