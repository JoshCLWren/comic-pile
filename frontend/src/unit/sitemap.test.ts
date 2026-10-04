import { describe, expect, test } from 'vitest'
import {
  ROUTE_SEO_TABLE,
  indexableRoutes,
  isIndexablePath,
} from '../seo/routeSeo'

describe('sitemap generation regression', () => {
  test('indexable routes match the canonical public surface', () => {
    const indexable = indexableRoutes()
    
    // Only the landing page should be indexable
    expect(indexable.map(entry => entry.pattern)).toEqual(['/'])
    
    // Each indexable route must have a canonical path
    for (const entry of indexable) {
      expect(entry.canonicalPath).toBe('/')
    }
  })

  test('no private or public-noindex routes are accidentally indexable', () => {
    const privatePaths = [
      '/queue',
      '/thread/42',
      '/creators',
      '/creators/x-men',
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
      expect(isIndexablePath(path)).toBe(false)
    }

    const publicNoindexPaths = [
      '/login',
      '/register',
      '/forgot-password',
      '/reset-password',
      '/demo',
      '/rate',
      '/analytics',
      '/help',
    ]

    for (const path of publicNoindexPaths) {
      expect(isIndexablePath(path)).toBe(false)
    }
  })

  test('indexable routes have stable canonical URLs', () => {
    const indexable = indexableRoutes()

    for (const entry of indexable) {
      // `indexableRoutes()` only returns public-indexable entries, and the
      // route table contract gives every one of them a canonical path.
      const canonicalPath = entry.canonicalPath
      if (canonicalPath === null) {
        throw new Error(`indexable route ${entry.pattern} has no canonicalPath`)
      }

      // Canonical path must be a non-empty string starting with /
      expect(canonicalPath).toMatch(/^\//)

      // No trailing slash except root
      if (canonicalPath !== '/') {
        expect(canonicalPath).not.toMatch(/\/$/)
      }
    }
  })

  test('route table and sitemap generation logic stay in sync', () => {
    // This test ensures that if someone adds a new route to routeSeo.ts
    // and marks it as public-indexable, they must also give it a canonical
    // path. `scripts/generate-sitemap.mjs` refuses to build a sitemap for an
    // indexable entry without one, and `scripts/generate-sitemap.test.mjs`
    // asserts the generated artifact lists exactly these canonical URLs.
    const indexable = indexableRoutes()

    for (const entry of indexable) {
      const canonicalPath = entry.canonicalPath
      if (canonicalPath === null) {
        throw new Error(`indexable route ${entry.pattern} has no canonicalPath`)
      }

      expect(canonicalPath.length).toBeGreaterThan(0)
      expect(canonicalPath.startsWith('/')).toBe(true)
    }
  })

  test('exactly one indexable route exists (the landing page)', () => {
    const indexable = indexableRoutes()
    expect(indexable.length).toBe(1)
    expect(indexable[0].pattern).toBe('/')
  })

  test('route table completeness - all known routes are classified', () => {
    // This test documents all known routes in the application.
    // If a new route is added to App.tsx, it must be added here too.
    const knownPatterns = new Set(ROUTE_SEO_TABLE.map(e => e.pattern))
    
    // These are all the route patterns from App.tsx
    const appRoutes = [
      '/',
      '/login',
      '/register',
      '/forgot-password',
      '/reset-password',
      '/demo',
      '/rate',        // redirect
      '/analytics',   // redirect
      '/help',        // redirect
      '/queue',
      '/thread/:id',
      '/creators/:creatorKey',
      '/history',
      '/sessions/:id',
      '/creators',
      '/crossovers',
      '/crossovers/:group',
      '/continuity-plans',
      '/continuity-plans/new',
      '/continuity-plans/:id',
      '/whats-new',
      '/glossary',
      '/identity-inbox',
    ]

    for (const route of appRoutes) {
      expect(knownPatterns.has(route)).toBe(true)
    }
  })
})