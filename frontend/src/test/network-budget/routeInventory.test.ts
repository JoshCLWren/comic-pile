import { describe, expect, test } from 'vitest'
import { AUDITED_ROUTES, readAppRoutePaths, specStatus } from './routeInventory'
import { publicBudget, auxBudget } from './routeBudgets'

describe('route inventory parity with App.tsx', () => {
  const appPaths = readAppRoutePaths()
  const inventoryPaths = AUDITED_ROUTES.map(route => route.path)

  test('inventory has no duplicate entries', () => {
    expect(new Set(inventoryPaths).size).toBe(inventoryPaths.length)
  })

  test('inventory exactly matches every App.tsx route', () => {
    expect([...inventoryPaths].sort()).toEqual([...appPaths].sort())
  })

  test('every inventoried route names an existing request-budget spec', () => {
    // Parent #4499 requirement 6: a new routed view must not escape
    // request-efficiency coverage. Every route — public, protected,
    // redirect, or unknown — carries the spec that measures its requests,
    // so adding a route to App.tsx fails here until its spec exists.
    expect(AUDITED_ROUTES.length).toBeGreaterThan(0)
    for (const route of AUDITED_ROUTES) {
      expect(route.spec, `${route.path} missing spec`).toBeTruthy()
      const status = specStatus(route.spec ?? '')
      expect(status.exists, `${route.path} -> ${route.spec} (${status.path})`).toBe(true)
    }
  })

  test('redirect routes declare their target', () => {
    for (const route of AUDITED_ROUTES.filter(entry => entry.auth === 'redirect')) {
      expect(route.redirectTo, `${route.path} missing redirectTo`).toBeTruthy()
    }
  })

  test('every public route has a budget entry', () => {
    // Redirects to feature routes (/help, /threads/:id) are measured by their
    // target's spec, not by a public budget row.
    const publicRoutes = AUDITED_ROUTES.filter(
      r => r.auth === 'public' || r.auth === 'conditional' || r.auth === 'unknown' || (r.auth === 'redirect' && r.redirectTo === '/'),
    )
    for (const route of publicRoutes) {
      // public routes use publicBudget; unknown routes map to '/unknown'
      const key = route.path === '*' ? '/unknown' : route.path
      expect(() => publicBudget(key)).not.toThrow(`Missing public budget for ${route.path}`)
    }
  })

  test('every auxiliary route has a budget entry', () => {
    for (const route of AUDITED_ROUTES.filter(r => r.auth === 'protected' && ['/whats-new', '/glossary', '/help'].includes(r.path))) {
      expect(() => auxBudget(route.path)).not.toThrow(`Missing aux budget for ${route.path}`)
    }
  })
})
