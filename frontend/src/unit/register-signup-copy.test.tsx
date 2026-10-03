import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ login: vi.fn() }))

vi.mock('../App', () => ({ useAuth: () => auth }))
vi.mock('../services/api', () => ({ default: { post: vi.fn() } }))

import RegisterPage from '../pages/RegisterPage'

function renderRoute(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
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
})