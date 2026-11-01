import { beforeEach, describe, expect, test } from 'vitest'
import { setAccessToken } from '../../services/api'
import { renderAppAtRoute } from './appNetworkHarness'
import {
  AUTHENTICATED_SHELL,
  GUEST_AUTH_PROBE,
  auxBudget,
  isPeerRollRow,
} from './routeBudgets'

beforeEach(() => {
  setAccessToken(null)
  localStorage.clear()
})

describe('auxiliary route network budgets', () => {
  test('/whats-new reads one bounded release page and the shared shell', async () => {
    const app = renderAppAtRoute('/whats-new', { auth: 'authenticated' })
    await app.settle()

    expect(app.rows()).toEqual([...auxBudget('/whats-new')])
    expect(app.ledger.unhandled()).toEqual([])
    expect(app.currentPath()).toBe('/whats-new')
  })

  test('/glossary is a static page with only shared shell reads', async () => {
    const app = renderAppAtRoute('/glossary', { auth: 'authenticated' })
    await app.settle()

    expect(app.rows()).toEqual([...auxBudget('/glossary')])
    expect(app.ledger.unhandled()).toEqual([])
    expect(app.currentPath()).toBe('/glossary')
  })

  test('/help redirects to /glossary without duplicating shell reads', async () => {
    const app = renderAppAtRoute('/help', { auth: 'authenticated' })
    await app.settle()

    expect(app.currentPath()).toBe('/glossary')
    expect(app.rows()).toEqual([...auxBudget('/help')])
    expect(app.rows().some(row => row.includes('/api/v1/releases/'))).toBe(false)
  })

  test.each(['/whats-new', '/glossary'])('%s redirects a guest to /login without page reads', async path => {
    const app = renderAppAtRoute(path, { auth: 'guest' })
    await app.settle()

    expect(app.currentPath()).toBe('/login')
    expect(app.rows()).toEqual([...GUEST_AUTH_PROBE])
    expect(app.rows().some(row => row.includes('/api/v1/releases/'))).toBe(false)
  })

  test('StrictMode does not duplicate auxiliary requests', async () => {
    const app = renderAppAtRoute('/whats-new', { auth: 'authenticated', strictMode: true })
    await app.settle()

    expect(app.rows()).toEqual([...auxBudget('/whats-new')])
  })

  test('warm navigation between auxiliary routes reuses the cache', async () => {
    const app = renderAppAtRoute('/glossary', { auth: 'authenticated' })
    await app.settle()
    const first = app.ledger.mark()

    await app.navigate('/whats-new')
    const toWhatsNew = app.rows(app.ledger.since(first))
    expect(toWhatsNew).toEqual(['GET /api/v1/releases/?limit=20&offset=0 x1'])

    const second = app.ledger.mark()
    await app.navigate('/glossary')
    expect(app.rows(app.ledger.since(second))).toEqual([])

    const third = app.ledger.mark()
    await app.navigate('/whats-new')
    expect(app.rows(app.ledger.since(third))).toEqual([])
  })

  test('window focus and visibility changes do not refetch', async () => {
    const app = renderAppAtRoute('/whats-new', { auth: 'authenticated' })
    await app.settle()
    const base = app.ledger.mark()

    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await app.settle()

    expect(app.rows(app.ledger.since(base))).toEqual([])
  })

  test('an authenticated redirect to / does not repeat the shell reads', async () => {
    const app = renderAppAtRoute('/rate', { auth: 'authenticated' })
    await app.settle()

    expect(app.currentPath()).toBe('/')
    const ownRows = app.rows().filter(row => !isPeerRollRow(row))
    expect(ownRows).toEqual([...AUTHENTICATED_SHELL])
  })
})
