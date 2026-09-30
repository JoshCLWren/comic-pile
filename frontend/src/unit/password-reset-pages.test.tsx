import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApi = vi.hoisted(() => ({
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
}))
const apiClient = vi.hoisted(() => ({ post: vi.fn() }))
const auth = vi.hoisted(() => ({ login: vi.fn(), logout: vi.fn() }))

vi.mock('../services/api', () => ({
  authApi,
  default: apiClient,
}))
vi.mock('../App', () => ({ useAuth: () => auth }))

import ForgotPasswordPage from '../pages/ForgotPasswordPage'
import LoginPage from '../pages/LoginPage'
import ResetPasswordPage from '../pages/ResetPasswordPage'

function renderForgot(initialEntry = '/forgot-password') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )
}

function renderReset(initialEntry = '/reset-password') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ResetPasswordPage />
    </MemoryRouter>,
  )
}

function axiosError(status: number): Error & { isAxiosError: true; response: { status: number } } {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status },
  })
}

function axiosErrorWithDetail(status: number, detail: unknown) {
  return Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true as const,
    response: { status, data: { detail } },
  })
}

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    authApi.forgotPassword.mockReset()
  })

  it('renders the request form and submits the email', async () => {
    authApi.forgotPassword.mockResolvedValueOnce({ message: 'ok' })
    renderForgot()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    expect(authApi.forgotPassword).toHaveBeenCalledWith({ email: 'reader@example.com' })
    expect(await screen.findByText('Check your email')).toBeInTheDocument()
  })

  it('renders the same acknowledgement for unknown emails', async () => {
    authApi.forgotPassword.mockResolvedValueOnce({ message: 'ok' })
    renderForgot()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ghost@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    await waitFor(() => {
      expect(screen.getByText('Check your email')).toBeInTheDocument()
    })
    expect(screen.getByText(/If an account exists for/)).toBeInTheDocument()
  })

  it('validates the email before submitting', () => {
    renderForgot()
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))
    expect(screen.getByText('Email is required')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))
    expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
    expect(authApi.forgotPassword).not.toHaveBeenCalled()
  })

  it('reports rate-limit errors without leaking account existence', async () => {
    authApi.forgotPassword.mockRejectedValueOnce(axiosError(429))

    renderForgot()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    await waitFor(() => {
      expect(screen.getByText('Too many requests. Please wait a moment and try again.')).toBeInTheDocument()
    })
  })

  it('renders a safe message when the API rejects the request shape', async () => {
    authApi.forgotPassword.mockRejectedValueOnce(
      axiosErrorWithDetail(422, [{ loc: ['body', 'email'], msg: 'value is not a valid email address' }]),
    )

    renderForgot()
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: `${'a'.repeat(400)}@example.com` },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Request failed. Please try again.')
    })
  })

  it('announces the error to assistive technology', async () => {
    authApi.forgotPassword.mockRejectedValueOnce(axiosError(429))

    renderForgot()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send Reset Link' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})

describe('LoginPage password recovery entry point', () => {
  beforeEach(() => {
    auth.login.mockReset()
    apiClient.post.mockReset()
  })

  it('exposes a discoverable forgot-password link', () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
  })
})

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    authApi.resetPassword.mockReset()
    auth.logout.mockReset()
  })

  it('renders a safe invalid-link state when the token is missing', () => {
    renderReset('/reset-password')
    expect(screen.getByText('Invalid Reset Link')).toBeInTheDocument()
    expect(screen.getByText(/This password reset link is invalid/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Request New Reset Link' })).toBeInTheDocument()
  })

  it('submits the new password and shows a success state', async () => {
    authApi.resetPassword.mockResolvedValueOnce({ message: 'ok' })
    renderReset('/reset-password?token=abc123')

    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpassword' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    expect(await screen.findByText('Password Reset Successfully')).toBeInTheDocument()
    expect(authApi.resetPassword).toHaveBeenCalledWith({ token: 'abc123', new_password: 'newpassword' })
    expect(auth.logout).toHaveBeenCalledOnce()
    expect(screen.getByText(/All existing sessions have been revoked/)).toBeInTheDocument()
  })

  it('validates password length and confirmation before submitting', () => {
    renderReset('/reset-password?token=abc123')
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))
    expect(screen.getByText('Password is required')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))
    expect(screen.getByText('Password must be at least 6 characters')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'longerpass' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'different' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
    expect(authApi.resetPassword).not.toHaveBeenCalled()
  })

  it('renders a safe expired-or-used state for a 400 response', async () => {
    authApi.resetPassword.mockRejectedValueOnce(axiosError(400))

    renderReset('/reset-password?token=abc123')
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpassword' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    await waitFor(() => {
      expect(
        screen.getByText('This reset link has expired or was already used. Please request a new one.'),
      ).toBeInTheDocument()
    })
  })

  it('does not persist the token in any client-side storage', () => {
    renderReset('/reset-password?token=secret-token')
    expect(window.localStorage.getItem('auth_token')).toBeNull()
    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
  })

  it('renders a safe message when the API rejects the request shape', async () => {
    authApi.resetPassword.mockRejectedValueOnce(
      axiosErrorWithDetail(422, [{ loc: ['body', 'token'], msg: 'field required' }]),
    )

    renderReset('/reset-password?token=abc123')
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpassword' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Reset failed. Please try again.')
    })
  })

  it('maps a server-supplied invalid-token detail to the safe invalid-link state', async () => {
    authApi.resetPassword.mockRejectedValueOnce(
      axiosErrorWithDetail(422, 'Reset token has already been used.'),
    )

    renderReset('/reset-password?token=abc123')
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpassword' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    await waitFor(() => {
      expect(
        screen.getByText('This reset link has expired or was already used. Please request a new one.'),
      ).toBeInTheDocument()
    })
  })
})

describe('post-reset re-login', () => {
  beforeEach(() => {
    authApi.resetPassword.mockReset()
    auth.logout.mockReset()
    auth.login.mockReset()
    apiClient.post.mockReset()
  })

  it('returns the reader to username login and signs in with the new password', async () => {
    authApi.resetPassword.mockResolvedValueOnce({ message: 'ok' })
    const reset = renderReset('/reset-password?token=abc123')
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'newpassword' } })
    fireEvent.change(screen.getByLabelText('Confirm New Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Password' }))

    const signInLink = await screen.findByRole('link', { name: 'Sign In with New Password' })
    expect(signInLink).toHaveAttribute('href', '/login')
    expect(screen.getByText(/sign in with your username and new password/i)).toBeInTheDocument()
    reset.unmount()

    apiClient.post.mockResolvedValueOnce({ access_token: 'fresh-token' })
    auth.login.mockResolvedValueOnce(undefined)
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'newpassword' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/v1/auth/login', {
        username: 'reader',
        password: 'newpassword',
      })
    })
    expect(auth.login).toHaveBeenCalledWith('fresh-token')
  })
})
