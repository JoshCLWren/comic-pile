import { beforeEach, describe, expect, test, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'

// The authenticated redirect target is the Roll home, which is peer-owned and
// has its own request suite. Stub only that page so this spec measures the
// credential-form redirect and shell, not Roll bootstrap internals.
vi.mock('../../pages/RollPage', () => ({
  default: () => <div data-testid="roll-page-stub" />,
}))
import { setAccessToken } from '../../services/api'
import { renderAppAtRoute } from './appNetworkHarness'
import { GUEST_AUTH_PROBE, publicBudget } from './routeBudgets'

beforeEach(() => {
  setAccessToken(null)
  localStorage.clear()
})

describe('public route network budgets', () => {
  test.each(['/login', '/register'])('%s makes no request for a cookieless guest', async path => {
    const app = renderAppAtRoute(path, { auth: 'guest' })
    await app.settle()

    expect(app.rows()).toEqual([...publicBudget(path)])
    expect(app.ledger.unhandled()).toEqual([])
    expect(app.currentPath()).toBe(path)
  })

  test.each(['/forgot-password', '/reset-password'])(
    '%s renders its form without an auth probe',
    async path => {
      const app = renderAppAtRoute(path, { auth: 'guest' })
      await app.settle()

      expect(app.rows()).toEqual([...publicBudget(path)])
      expect(app.rows()).toEqual([])
      expect(app.ledger.unhandled()).toEqual([])
      expect(app.currentPath()).toBe(path)
    },
  )

  test('forgot-password submit posts once without a CSRF probe', async () => {
    const app = renderAppAtRoute('/forgot-password', {
      auth: 'guest',
      handlers: {
        'POST /api/v1/auth/forgot-password': () => ({ data: { message: 'sent' } }),
      },
    })
    await app.settle()
    const base = app.ledger.mark()

    await app.perform('forgot-submit', async () => {
      fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'reader@example.test' } })
      fireEvent.submit(screen.getByRole('button', { name: 'Send Reset Link' }).closest('form')!)
    })

    expect(app.rows(app.ledger.since(base))).toEqual([
      'POST /api/v1/auth/forgot-password x1',
    ])
    expect(screen.getByText('Check your email')).toBeInTheDocument()
  })

  test('reset-password submit posts once with its token and no CSRF probe', async () => {
    const app = renderAppAtRoute('/reset-password?token=reset-token-1', {
      auth: 'guest',
      handlers: {
        'POST /api/v1/auth/reset-password': () => ({ data: { message: 'ok' } }),
      },
    })
    await app.settle()
    const base = app.ledger.mark()

    await app.perform('reset-submit', async () => {
      fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'new-password-1' } })
      fireEvent.change(screen.getByLabelText('Confirm New Password'), {
        target: { value: 'new-password-1' },
      })
      fireEvent.submit(screen.getByRole('button', { name: 'Reset Password' }).closest('form')!)
    })

    expect(app.rows(app.ledger.since(base))).toEqual([
      'POST /api/v1/auth/reset-password x1',
    ])
    expect(screen.getByRole('link', { name: 'Sign In with New Password' })).toBeInTheDocument()
  })

  test('a stored token still validates and redirects an authenticated visitor', async () => {
    setAccessToken('stored-access-token')
    const app = renderAppAtRoute('/forgot-password', { auth: 'authenticated' })
    await app.settle()
    expect(app.currentPath()).toBe('/')
    expect(app.rows()).toContain('GET /api/v1/auth/me x1')
    expect(app.rows()).toContain('GET /api/v1/users/me/preferences x1')
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
  })

  test('a rejected stored token clears and renders the credential form', async () => {
    setAccessToken('stale-access-token')
    const app = renderAppAtRoute('/forgot-password', { auth: 'guest' })
    await app.settle()

    expect(app.currentPath()).toBe('/forgot-password')
    expect(app.rows()).toEqual([...GUEST_AUTH_PROBE])
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  test('guest landing fetches nothing beyond the shared auth probe', async () => {
    const app = renderAppAtRoute('/', { auth: 'guest' })
    await app.settle()

    expect(app.rows()).toEqual([...publicBudget('/')])
    expect(app.ledger.unhandled()).toEqual([])
    expect(app.currentPath()).toBe('/')
  })

  test('/demo makes one seeded-roll read and no write', async () => {
    const app = renderAppAtRoute('/demo', { auth: 'guest' })
    await app.settle()

    expect(app.rows()).toEqual([...publicBudget('/demo')])
    expect(app.ledger.unhandled()).toEqual([])
    expect(app.currentPath()).toBe('/demo')
  })

  test('/demo retry requests exactly the failed demo roll again', async () => {
    const app = renderAppAtRoute('/demo', {
      auth: 'guest',
      handlers: {
        'GET /api/v1/demo/roll': () => ({ status: 503, data: { detail: 'unavailable' } }),
      },
    })
    await app.settle()
    const base = app.ledger.mark()

    await app.perform('demo-retry', async () => {
      screen.getByTestId('demo-retry').click()
    })

    expect(app.rows(app.ledger.since(base))).toEqual(['GET /api/v1/demo/roll x1'])
  })

  test.each(['/rate', '/analytics', '/roll'])(
    '%s redirects a guest to / with no extra request',
    async path => {
      const app = renderAppAtRoute(path, { auth: 'guest' })
      await app.settle()

      expect(app.currentPath()).toBe('/')
      expect(app.rows()).toEqual([...GUEST_AUTH_PROBE])
    },
  )

  test('an unknown guest route stays on the not-found page with one probe', async () => {
    const app = renderAppAtRoute('/definitely-missing', { auth: 'guest' })
    await app.settle()

    expect(app.currentPath()).toBe('/definitely-missing')
    expect(app.rows()).toEqual([...publicBudget('/unknown')])
  })

  test('an unknown authenticated route keeps the shell badge but not preferences', async () => {
    const app = renderAppAtRoute('/definitely-missing', { auth: 'authenticated' })
    await app.settle()

    // 404 uses PublicLayout, so the authenticated page shell (and its
    // PreferencesSync read) is intentionally absent.
    expect(app.rows()).toEqual([
      'GET /api/v1/auth/me x1',
      'GET /api/v1/identity-inbox?limit=1&offset=0 x1',
    ])
    expect(app.currentPath()).toBe('/definitely-missing')
  })

  test('StrictMode does not add credential-form requests', async () => {
    const app = renderAppAtRoute('/forgot-password', { auth: 'guest', strictMode: true })
    await app.settle()

    expect(app.rows()).toEqual([])
  })
})
