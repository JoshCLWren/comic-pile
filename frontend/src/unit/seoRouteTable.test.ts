import { describe, expect, test } from 'vitest'
import {
  ROUTE_SEO_TABLE,
  indexableRoutes,
  isIndexablePath,
  matchRouteSeo,
  normalizeSeoPathname,
} from '../seo/routeSeo'

describe('canonical route indexability table', () => {
  test('every table pattern is unique', () => {
    const patterns = ROUTE_SEO_TABLE.map(entry => entry.pattern)
    expect(new Set(patterns).size).toBe(patterns.length)
  })

  test('exactly one indexable route exists and it owns a stable canonical URL', () => {
    const indexable = indexableRoutes()
    expect(indexable.map(entry => entry.pattern)).toEqual(['/'])
    for (const entry of indexable) {
      expect(entry.canonicalPath).toBe('/')
    }
  })

  test('non-indexable routes never expose a canonical URL', () => {
    for (const entry of ROUTE_SEO_TABLE) {
      if (entry.visibility !== 'public-indexable') {
        expect(entry.canonicalPath).toBeNull()
      }
    }
  })

  test('landing page is the only indexable path', () => {
    expect(isIndexablePath('/')).toBe(true)
    expect(isIndexablePath('/login')).toBe(false)
    expect(isIndexablePath('/queue')).toBe(false)
  })

  test('auth and utility pages are public but not indexable', () => {
    for (const path of ['/login', '/register', '/forgot-password', '/reset-password', '/demo']) {
      const entry = matchRouteSeo(path)
      expect(entry.visibility).toBe('public-noindex')
      expect(entry.canonicalPath).toBeNull()
    }
  })

  test('retired redirect sources stay non-indexable', () => {
    for (const path of ['/rate', '/analytics', '/help']) {
      expect(matchRouteSeo(path).visibility).toBe('public-noindex')
    }
  })

  test('authenticated routes are private crawl exclusions', () => {
    const privatePaths = [
      '/queue',
      '/thread/42',
      '/creators',
      '/creators/x-men',
      '/creators/compare',
      '/history',
      '/sessions/abc',
      '/crossovers',
      '/crossovers/age-of-apocalypse',
      '/continuity-plans',
      '/continuity-plans/new',
      '/continuity-plans/7',
      '/whats-new',
      '/glossary',
      '/identity-inbox',
    ]
    for (const path of privatePaths) {
      const entry = matchRouteSeo(path)
      expect(entry.visibility).toBe('private')
      expect(entry.canonicalPath).toBeNull()
    }
  })

  test('exact patterns win over param patterns', () => {
    expect(matchRouteSeo('/continuity-plans/new').title).toContain('New')
    expect(matchRouteSeo('/continuity-plans/7').title).toContain('Continuity plan')
    expect(matchRouteSeo('/creators/compare').pattern).toBe('/creators/compare')
    expect(matchRouteSeo('/creators/creator%3A7').pattern).toBe('/creators/:creatorKey')
  })

  test('unknown paths safely default to private', () => {
    for (const path of ['/definitely-not-a-route', '/admin', '/.env', '/api/docs']) {
      const entry = matchRouteSeo(path)
      expect(entry.visibility).toBe('private')
      expect(entry.canonicalPath).toBeNull()
    }
  })

  test('lookup tolerates trailing slashes, case, and query strings', () => {
    expect(matchRouteSeo('/Login/').pattern).toBe('/login')
    expect(matchRouteSeo('/QUEUE?x=1').pattern).toBe('/queue')
    expect(normalizeSeoPathname('/Thread/42/')).toBe('/thread/42')
  })
})
