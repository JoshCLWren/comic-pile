import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ login: vi.fn() }))

vi.mock('../App', () => ({ useAuth: () => auth }))

import LandingPage from '../pages/LandingPage'
import LoginPage from '../pages/LoginPage'
import RegisterPage from '../pages/RegisterPage'
import ForgotPasswordPage from '../pages/ForgotPasswordPage'
import ResetPasswordPage from '../pages/ResetPasswordPage'
import DemoRollPage from '../pages/DemoRollPage'
import type { RollResponse } from '../types'

const seededDemoRoll: RollResponse = {
  thread_id: 999,
  title: 'Sample: The Dark Knight Returns (Demo)',
  format: 'comic',
  issues_remaining: 3,
  queue_position: 1,
  die_size: 6,
  result: 4,
  offset: 0,
  snoozed_count: 0,
  issue_id: 1001,
  issue_number: '#4',
  next_issue_id: 1002,
  next_issue_number: '#5',
  total_issues: 12,
  reading_progress: 'Late in arc — the final act is building.',
  explanation: 'Demo roll: seeded sample data, no account state.',
}

/**
 * Assert the rendered page owns exactly one primary H1. Public routes must
 * never ship a missing or duplicate page-level H1.
 */
function expectSinglePrimaryH1(): void {
  const h1s = screen.getAllByRole('heading', { level: 1 })
  if (h1s.length !== 1) {
    throw new Error(`Expected exactly one primary H1 on the page, found ${h1s.length}`)
  }
}

function renderPublicPage(page: 'landing' | 'login' | 'register' | 'forgot' | 'reset' | 'demo') {
  switch (page) {
    case 'landing':
      return render(
        <MemoryRouter>
          <LandingPage />
        </MemoryRouter>,
      )
    case 'login':
      return render(
        <MemoryRouter initialEntries={['/login']}>
          <LoginPage />
        </MemoryRouter>,
      )
    case 'register':
      return render(
        <MemoryRouter initialEntries={['/register']}>
          <RegisterPage />
        </MemoryRouter>,
      )
    case 'forgot':
      return render(
        <MemoryRouter initialEntries={['/forgot-password']}>
          <ForgotPasswordPage />
        </MemoryRouter>,
      )
    case 'reset':
      return render(
        <MemoryRouter initialEntries={['/reset-password']}>
          <ResetPasswordPage />
        </MemoryRouter>,
      )
    case 'demo':
      return render(
        <MemoryRouter initialEntries={['/demo']}>
          <DemoRollPage api={{ roll: () => Promise.resolve(seededDemoRoll) }} />
        </MemoryRouter>,
      )
  }
}

describe('public route primary H1 enforcement (issue #3067)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('the landing page exposes exactly one primary H1', () => {
    renderPublicPage('landing')
    expectSinglePrimaryH1()
  })

  it('the login page exposes exactly one primary H1', () => {
    renderPublicPage('login')
    expectSinglePrimaryH1()
  })

  it('the register page exposes exactly one primary H1', () => {
    renderPublicPage('register')
    expectSinglePrimaryH1()
  })

  it('the forgot password page exposes exactly one primary H1', () => {
    renderPublicPage('forgot')
    expectSinglePrimaryH1()
  })

  it('the reset password page exposes exactly one primary H1', () => {
    renderPublicPage('reset')
    expectSinglePrimaryH1()
  })

  it('the demo page exposes exactly one primary H1 once the seeded roll loads', async () => {
    renderPublicPage('demo')
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument()
    expectSinglePrimaryH1()
  })

  it('rejects a page with a duplicate primary H1', () => {
    render(
      <MemoryRouter>
        <div>
          <h1>First title</h1>
          <h1>Second title</h1>
        </div>
      </MemoryRouter>,
    )
    expect(() => expectSinglePrimaryH1()).toThrow(/exactly one primary H1/)
  })

  it('rejects a page with a missing primary H1', () => {
    render(
      <MemoryRouter>
        <div>
          <h2>Only a section heading</h2>
        </div>
      </MemoryRouter>,
    )
    expect(() => expectSinglePrimaryH1()).toThrow(/found 0/)
  })
})
