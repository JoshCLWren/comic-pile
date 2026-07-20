import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ login: vi.fn() }))
const api = vi.hoisted(() => ({ post: vi.fn() }))

vi.mock('../App', () => ({ useAuth: () => auth }))
vi.mock('../services/api', () => ({ default: api }))

import HelpPage from '../pages/HelpPage'
import LoginPage from '../pages/LoginPage'
import RegisterPage from '../pages/RegisterPage'

function renderRoute(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('HelpPage', () => {
  it('renders the complete glossary', () => {
    render(<HelpPage />)
    expect(screen.getByRole('heading', { name: 'Help / Glossary' })).toBeInTheDocument()
    expect(screen.getAllByTestId('glossary-term')).toHaveLength(7)
    expect(screen.getByText('Reading order rules: "read X before Y".')).toBeInTheDocument()
  })
})

describe('LoginPage', () => {
  beforeEach(() => {
    auth.login.mockReset()
    api.post.mockReset()
  })

  it('validates required and short credentials', () => {
    renderRoute(<LoginPage />)
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    expect(screen.getByText('Username is required')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'short' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    expect(screen.getByText('Password must be at least 6 characters')).toBeInTheDocument()
  })

  it('logs in successfully and reports API errors', async () => {
    api.post.mockResolvedValueOnce({ access_token: 'token' })
    auth.login.mockResolvedValueOnce(undefined)
    renderRoute(<LoginPage />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: ' reader ' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('token'))
    expect(api.post).toHaveBeenCalledWith('/auth/login', { username: 'reader', password: 'password' })

    api.post.mockRejectedValueOnce(new Error('network'))
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    await waitFor(() => expect(screen.getByText('Login failed. Please try again.')).toBeInTheDocument())
  })
})

describe('RegisterPage', () => {
  beforeEach(() => {
    auth.login.mockReset()
    api.post.mockReset()
  })

  it('validates registration fields and mismatched passwords', () => {
    renderRoute(<RegisterPage />)
    const form = screen.getByRole('button', { name: 'Create Account' }).closest('form')!
    fireEvent.submit(form)
    expect(screen.getByText('Username is required')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.submit(form)
    expect(screen.getByText('Email is required')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'invalid' } })
    fireEvent.submit(form)
    expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: 'different' } })
    fireEvent.submit(form)
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument()
  })

  it('registers successfully and reports a generic API failure', async () => {
    api.post.mockResolvedValueOnce({ access_token: 'token' })
    auth.login.mockResolvedValueOnce(undefined)
    renderRoute(<RegisterPage />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.change(screen.getByLabelText('Confirm Password'), { target: { value: 'password' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Create Account' }).closest('form')!)
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('token'))

    api.post.mockRejectedValueOnce(new Error('network'))
    fireEvent.submit(screen.getByRole('button', { name: 'Create Account' }).closest('form')!)
    await waitFor(() => expect(screen.getByText('Registration failed. Please try again.')).toBeInTheDocument())
  })
})
