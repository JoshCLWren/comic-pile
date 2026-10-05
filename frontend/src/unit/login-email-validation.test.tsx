import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, fireEvent, screen, waitFor } from '@testing-library/react'
import LoginPage from '../pages/LoginPage'
import { useAuth } from '../App'
import api from '../services/api'

vi.mock('../App', () => ({ useAuth: vi.fn() }))
vi.mock('../services/api', () => ({ default: { post: vi.fn() } }))

const mockedUseAuth = vi.mocked(useAuth)
const mockedApi = vi.mocked(api)

describe('LoginPage Email Validation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    
    // Mock the auth context
    mockedUseAuth.mockReturnValue({
      login: vi.fn().mockResolvedValue(undefined)
    })
    
    // Mock successful API response
    mockedApi.post.mockResolvedValue({
      access_token: 'mock-token'
    })
  })

  it('should show error when email-shaped username is submitted', () => {
    render(<LoginPage />)
    
    // Enter email in username field
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'reader@example.com' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show error message
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should show error for email with multiple @ symbols', () => {
    render(<LoginPage />)
    
    // Enter email with multiple @ symbols
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'user@name@domain.com' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show error message
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should allow username with @ in the middle', () => {
    render(<LoginPage />)
    
    // Enter username with @ symbol but not email-shaped
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'user@home' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should not show email error
    expect(screen.queryByText('Sign in with your username, not your email.')).not.toBeInTheDocument()
    
    // Should call API (no validation error)
    expect(mockedApi.post).toHaveBeenCalledWith(
      '/v1/auth/login',
      expect.objectContaining({
        username: 'user@home',
        password: 'password123'
      })
    )
  })

  it('should allow username without @ symbol', () => {
    render(<LoginPage />)
    
    // Enter valid username
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'validusername' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should not show email error
    expect(screen.queryByText('Sign in with your username, not your email.')).not.toBeInTheDocument()
    
    // Should call API
    expect(mockedApi.post).toHaveBeenCalledWith(
      '/v1/auth/login',
      expect.objectContaining({
        username: 'validusername',
        password: 'password123'
      })
    )
  })

  it('should show error for email with spaces', () => {
    render(<LoginPage />)
    
    // Enter email with spaces
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'user name@example.com' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show error message
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should show error for email with special characters', () => {
    render(<LoginPage />)
    
    // Enter email with special characters
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'user+tag@example.com' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show error message
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should handle empty username field', () => {
    render(<LoginPage />)
    
    // Leave username empty
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: '' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show username required error
    expect(screen.getByText('Username is required')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should handle empty password field', () => {
    render(<LoginPage />)
    
    // Enter username
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'testuser' }
    })
    
    // Leave password empty
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: '' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show password required error
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    
    // Should not call API
    expect(mockedApi.post).not.toHaveBeenCalled()
  })

  it('should handle API error for invalid credentials', async () => {
    render(<LoginPage />)
    
    // Mock API error
    mockedApi.post.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 401,
        data: {}
      }
    })
    
    // Enter valid username
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'testuser' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'wrongpassword' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show API error
    await waitFor(() => {
      expect(screen.getByText('Invalid username or password')).toBeInTheDocument()
    })
  })

  it('should handle network error', async () => {
    render(<LoginPage />)
    
    // Mock network error
    mockedApi.post.mockRejectedValue(new Error('Network Error'))
    
    // Enter valid username
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'testuser' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show generic error
    await waitFor(() => {
      expect(screen.getByText('Login failed. Please try again.')).toBeInTheDocument()
    })
  })

  it('should clear error when user starts typing again', () => {
    render(<LoginPage />)
    
    // Enter email
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'reader@example.com' }
    })
    
    // Enter password
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'password123' }
    })
    
    // Submit form - should show error
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Should show error message
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Clear username field
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: '' }
    })
    
    // Error should still be there (until form is resubmitted)
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Enter valid username
    fireEvent.change(screen.getByLabelText('Username'), {
      target: { value: 'validuser' }
    })
    
    // Error should still be there (until form is resubmitted)
    expect(screen.getByText('Sign in with your username, not your email.')).toBeInTheDocument()
    
    // Submit form again with valid username
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }))
    
    // Error should be cleared and API should be called
    expect(screen.queryByText('Sign in with your username, not your email.')).not.toBeInTheDocument()
    expect(mockedApi.post).toHaveBeenCalled()
  })
})
