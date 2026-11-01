import { beforeEach, describe, expect, test } from 'vitest'
import { screen } from '@testing-library/react'
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
    '%s renders its form without page-owned reads',
    async path => {
      const app = renderAppAtRoute(path, { auth: 'guest' })
      await app.settle()

      // The only traffic is the shared bootstrap probe, not a page request.
      expect(app.rows()).toEqual([...GUEST_AUTH_PROBE])
      expect(app.ledger.unhandled()).toEqual([])
      expect(app.currentPath()).toBe(path)
    },
  )

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

  test('StrictMode does not duplicate the guest auth probe', async () => {
    const app = renderAppAtRoute('/forgot-password', { auth: 'guest', strictMode: true })
    await app.settle()

    expect(app.rows()).toEqual([...GUEST_AUTH_PROBE])
  })
})
