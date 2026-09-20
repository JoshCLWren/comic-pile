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
import RegisterPage from '../pages/RegisterPage'
import {
  RETURNING_VISITOR_STORAGE_KEY,
  isReturningVisitor,
  markReturningVisitor,
} from '../utils/returningVisitor'
import { AUTH_TOKEN_STORAGE_KEY } from '../services/api'

function renderRoute(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('returning-visitor signal (issue #2754)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('treats a fresh browser as a first-time visitor', () => {
    expect(isReturningVisitor()).toBe(false)
  })

  it('treats the explicit flag as a returning signal', () => {
    markReturningVisitor()
    expect(localStorage.getItem(RETURNING_VISITOR_STORAGE_KEY)).toBe('1')
    expect(isReturningVisitor()).toBe(true)
  })

  it('treats a stored auth token from a prior session as a returning signal', () => {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, 'prior-session-token')
    expect(isReturningVisitor()).toBe(true)
  })
})

describe('LoginPage auth chrome (issue #2754)', () => {
  beforeEach(() => {
    localStorage.clear()
    auth.login.mockReset()
    api.post.mockReset()
  })

  it('welcomes first-time visitors without saying "Welcome Back"', () => {
    renderRoute(<LoginPage />)
    expect(
      screen.getByRole('heading', { name: 'Welcome to Comic Pile' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Welcome Back')).not.toBeInTheDocument()
    expect(screen.getByText(/start your journey/i)).toBeInTheDocument()
  })

  it('keeps "Welcome Back" for returning visitors', () => {
    markReturningVisitor()
    renderRoute(<LoginPage />)
    expect(screen.getByRole('heading', { name: 'Welcome Back' })).toBeInTheDocument()
    expect(screen.getByText(/continue your journey/i)).toBeInTheDocument()
  })

  it('treats a prior-session token as a returning signal', () => {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, 'prior-session-token')
    renderRoute(<LoginPage />)
    expect(screen.getByRole('heading', { name: 'Welcome Back' })).toBeInTheDocument()
  })

  it('frames the signup entry as first-time, not a return', () => {
    renderRoute(<LoginPage />)
    expect(screen.getByText(/new to comic pile/i)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Create an account' }),
    ).toHaveAttribute('href', '/register')
  })

  it('marks the browser as returning after a successful sign-in', async () => {
    api.post.mockResolvedValueOnce({ access_token: 'token' })
    auth.login.mockResolvedValueOnce(undefined)
    renderRoute(<LoginPage />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('token'))
    expect(localStorage.getItem(RETURNING_VISITOR_STORAGE_KEY)).toBe('1')
  })
})

describe('RegisterPage auth chrome (issue #2754)', () => {
  beforeEach(() => {
    localStorage.clear()
    auth.login.mockReset()
    api.post.mockReset()
  })

  it('reads as a first-time welcome, never a return', () => {
    renderRoute(<RegisterPage />)
    expect(
      screen.getByRole('heading', { name: 'Create Account' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/welcome to comic pile/i)).toBeInTheDocument()
    expect(screen.queryByText('Welcome Back')).not.toBeInTheDocument()
    expect(screen.queryByText(/continue your journey/i)).not.toBeInTheDocument()
  })

  it('marks the browser as returning after a successful sign-up', async () => {
    api.post.mockResolvedValueOnce({ access_token: 'token' })
    auth.login.mockResolvedValueOnce(undefined)
    renderRoute(<RegisterPage />)
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'reader@example.com' },
    })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password' } })
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'password' },
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Create Account' }).closest('form')!)
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('token'))
    expect(localStorage.getItem(RETURNING_VISITOR_STORAGE_KEY)).toBe('1')
  })
})
