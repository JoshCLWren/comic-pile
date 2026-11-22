import { render, screen } from './testingLibrary'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import RegisterPage from '../pages/RegisterPage'
import { AuthContext, type AuthContextValue } from '../contexts/AuthContext'

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
  login: vi.fn<AuthContextValue['login']>(),
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

describe('RegisterPage signup copy (issue #2756)', () => {
  it('explains that username is the sign-in identifier, not email', () => {
    renderRoute(<RegisterPage />)
    expect(
      screen.getByText((content) => content.includes('What you use to sign in.')),
    ).toBeInTheDocument()
  })

  it('explains that email is recovery/contact identity, never the sign-in method', () => {
    renderRoute(<RegisterPage />)
    expect(
      screen.getByText((content) =>
        content.includes('Recovery and contact identity') &&
          content.includes('never to sign in'),
      ),
    ).toBeInTheDocument()
  })

  it('states the password policy next to the password field', () => {
    renderRoute(<RegisterPage />)
    expect(screen.getByText('Minimum 6 characters.')).toBeInTheDocument()
  })

  it('does not render a redundant confirm-password field', () => {
    renderRoute(<RegisterPage />)
    expect(screen.queryByLabelText('Confirm Password')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Confirm New Password')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Re-enter password')).not.toBeInTheDocument()
  })

  it('keeps username, email, and password as the only identity fields', () => {
    renderRoute(<RegisterPage />)
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('associates each visible helper copy with its field for assistive tech', () => {
    renderRoute(<RegisterPage />)
    for (const field of ['Username', 'Email', 'Password']) {
      expect(screen.getByLabelText(field)).toHaveAccessibleDescription()
    }
    expect(screen.getByLabelText('Username')).toHaveAccessibleDescription('What you use to sign in.')
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription('Minimum 6 characters.')
  })
})
