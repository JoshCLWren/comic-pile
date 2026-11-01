import { describe, expect, test } from 'vitest'
import { AUDITED_ROUTES, readAppRoutePaths, specStatus } from './routeInventory'

describe('route inventory parity with App.tsx', () => {
  const appPaths = readAppRoutePaths()
  const inventoryPaths = AUDITED_ROUTES.map(route => route.path)

  test('inventory has no duplicate entries', () => {
    expect(new Set(inventoryPaths).size).toBe(inventoryPaths.length)
  })

  test('inventory exactly matches every App.tsx route', () => {
    expect([...inventoryPaths].sort()).toEqual([...appPaths].sort())
  })

  test('every 4504-owned route names an existing spec', () => {
    const owned = AUDITED_ROUTES.filter(route => route.auditedBy === '4504')
    expect(owned.length).toBeGreaterThan(0)
    for (const route of owned) {
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
})
