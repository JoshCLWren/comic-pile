import { beforeEach, describe, expect, test } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { setAccessToken } from '../../services/api'
import { OTHER_USER, TEST_USER, renderAppAtRoute, type HarnessUser } from './appNetworkHarness'

beforeEach(() => {
  setAccessToken(null)
  localStorage.clear()
})

function login(): void {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'reader' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse battery' } })
  fireEvent.submit(screen.getByRole('button', { name: 'Sign In' }).closest('form')!)
}

describe('authentication transitions', () => {
  test('login submits once and hydrates the new session once', async () => {
    let currentUser: HarnessUser = TEST_USER
    const app = renderAppAtRoute('/login', {
      auth: 'guest',
      handlers: {
        'POST /api/v1/auth/login': () => ({
          data: { access_token: 'token-a', refresh_token: 'refresh-a' },
        }),
        'GET /api/v1/auth/me': () => ({ data: currentUser }),
      },
    })
    await app.settle()
    expect(app.rows()).toEqual([])

    const base = app.ledger.mark()
    login()
    await app.settle()
    await waitFor(() => expect(app.currentPath()).toBe('/'))

    const rows = app.rows(app.ledger.since(base))
    expect(rows.filter(row => row.startsWith('POST /api/v1/auth/login'))).toEqual([
      'POST /api/v1/auth/login x1',
    ])
    expect(rows.filter(row => row.startsWith('GET /api/v1/auth/me'))).toEqual([
      'GET /api/v1/auth/me x1',
    ])
    expect(rows.some(row => row.startsWith('POST /api/v1/auth/refresh'))).toBe(false)
    expect(rows.filter(row => row.startsWith('GET /api/v1/identity-inbox'))).toHaveLength(1)

    currentUser = OTHER_USER
  })

  test('logout clears the session cache and returns to the login fast path', async () => {
    const app = renderAppAtRoute('/glossary', { auth: 'authenticated' })
    await app.settle()
    expect(app.queryClient.getQueryCache().getAll().length).toBeGreaterThan(0)

    const base = app.ledger.mark()
    await app.perform('logout', async () => {
      const buttons = screen.getAllByLabelText('Log out')
      buttons[0].click()
    })

    expect(app.currentPath()).toBe('/login')
    expect(app.rows(app.ledger.since(base))).toEqual([
      'GET /api/v1/auth/csrf x1',
      'POST /api/v1/auth/logout x1',
    ])
    expect(app.queryClient.getQueryCache().getAll().filter(query => query.state.data !== undefined)).toEqual([])
  })

  test('a second account never reuses the first account release cache', async () => {
    let currentUser: HarnessUser = TEST_USER
    const app = renderAppAtRoute('/whats-new', {
      auth: 'authenticated',
      handlers: {
        'POST /api/v1/auth/login': () => ({
          data: { access_token: 'token-b', refresh_token: 'refresh-b' },
        }),
        'GET /api/v1/auth/me': () => ({ data: currentUser }),
      },
    })
    await app.settle()
    const firstAccountReleases = app.rows().filter(row => row.includes('/api/v1/releases/'))
    expect(firstAccountReleases).toEqual(['GET /api/v1/releases/?limit=20&offset=0 x1'])

    await app.perform('logout', async () => {
      screen.getAllByLabelText('Log out')[0].click()
    })
    expect(app.queryClient.getQueryCache().getAll().filter(query => query.state.data !== undefined)).toEqual([])

    currentUser = OTHER_USER
    const base = app.ledger.mark()
    login()
    await app.settle()
    // ProtectedRoute sent the expired session to /login with `from` state, so
    // a successful login returns to the requested page rather than the Roll home.
    await waitFor(() => expect(app.currentPath()).toBe('/whats-new'))

    const secondAccountReleases = app.rows(app.ledger.since(base)).filter(row =>
      row.includes('/api/v1/releases/'),
    )
    expect(secondAccountReleases).toEqual(['GET /api/v1/releases/?limit=20&offset=0 x1'])
  })
})
