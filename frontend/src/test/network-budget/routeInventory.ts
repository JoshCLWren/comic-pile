import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** How a route gates access. */
export type RouteAuth = 'public' | 'protected' | 'conditional' | 'redirect' | 'unknown'

/** Existence check result for an audited route spec. */
export interface SpecStatus {
  path: string
  exists: boolean
}

/** One audited route in `frontend/src/App.tsx`. */
export interface AuditedRoute {
  /** Exact `path` prop from App.tsx. */
  path: string
  auth: RouteAuth
  /** Target for redirect-only routes. */
  redirectTo?: string
  /** Spec that measures this route's requests, relative to `frontend/src/`. */
  spec?: string
}

/**
 * Canonical audited route inventory.
 *
 * Every `<Route path="...">` in `App.tsx` must appear exactly once, and every
 * entry must name the spec that measures its requests. A newly added route
 * therefore cannot enter the app without request-efficiency coverage: the
 * parity test fails until both the inventory row and its spec exist
 * (parent #4499 requirement 6).
 */
export const AUDITED_ROUTES: AuditedRoute[] = [
  { path: '/login', auth: 'public', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/register', auth: 'public', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/forgot-password', auth: 'public', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/reset-password', auth: 'public', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/demo', auth: 'public', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/rate', auth: 'redirect', redirectTo: '/', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/analytics', auth: 'redirect', redirectTo: '/', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/roll', auth: 'redirect', redirectTo: '/', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/', auth: 'conditional', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
  { path: '/queue', auth: 'protected', spec: 'unit/coreRouteRequestBudget.test.tsx' },
  { path: '/thread/:id', auth: 'protected', spec: 'unit/ThreadDetailView.request-budget.test.tsx' },
  { path: '/threads/:id', auth: 'redirect', redirectTo: '/thread/:id', spec: 'unit/App.test.tsx' },
  { path: '/creators/compare', auth: 'protected', spec: 'unit/creatorDiscoveryRequestBudget.test.tsx' },
  { path: '/creators/:creatorKey', auth: 'protected', spec: 'unit/creatorDiscoveryRequestBudget.test.tsx' },
  { path: '/history', auth: 'protected', spec: 'unit/coreRouteRequestBudget.test.tsx' },
  { path: '/sessions/:id', auth: 'protected', spec: 'unit/coreRouteRequestBudget.test.tsx' },
  { path: '/creators', auth: 'protected', spec: 'unit/creatorDiscoveryRequestBudget.test.tsx' },
  { path: '/crossovers', auth: 'protected', spec: 'unit/App.test.tsx' },
  { path: '/crossovers/:group', auth: 'protected', spec: 'unit/creatorDiscoveryRequestBudget.test.tsx' },
  { path: '/continuity-plans', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/continuity-plans/new', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/continuity-plans/events', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/continuity-plans/:id/edit', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/continuity-plans/:id', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/reading-lists/:id', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '/cbl-sources', auth: 'protected', spec: 'unit/creatorDiscoveryRequestBudget.test.tsx' },
  { path: '/whats-new', auth: 'protected', spec: 'test/network-budget/auxiliaryRoutes.network.test.tsx' },
  { path: '/glossary', auth: 'protected', spec: 'test/network-budget/auxiliaryRoutes.network.test.tsx' },
  { path: '/help', auth: 'redirect', redirectTo: '/glossary', spec: 'test/network-budget/auxiliaryRoutes.network.test.tsx' },
  { path: '/identity-inbox', auth: 'protected', spec: 'unit/continuityIdentityRequestBudget.test.tsx' },
  { path: '*', auth: 'unknown', spec: 'test/network-budget/publicRoutes.network.test.tsx' },
]

/**
 * Extract every literal `<Route path="...">` from the production App source.
 *
 * @param source - Contents of `frontend/src/App.tsx`.
 * @returns Literal route paths in source order.
 */
export function extractRoutePaths(source: string): string[] {
  const paths: string[] = []
  const pattern = /<Route\s+path="([^"]+)"/g
  let match: RegExpExecArray | null
  while ((match = pattern.exec(source)) !== null) {
    paths.push(match[1])
  }
  return paths
}

function appSourcePath(): string {
  return resolve(process.cwd(), 'src/App.tsx')
}

/**
 * Read and parse the production route table.
 *
 * @returns Every literal App.tsx route path in source order.
 */
export function readAppRoutePaths(): string[] {
  return extractRoutePaths(readFileSync(appSourcePath(), 'utf8'))
}

/**
 * Resolve an audited spec path relative to `frontend/src/`.
 *
 * @param spec - Spec path from {@link AUDITED_ROUTES}.
 * @returns Absolute path and whether it exists.
 */
export function specStatus(spec: string): SpecStatus {
  const path = resolve(process.cwd(), 'src', spec)
  return { path, exists: existsSync(path) }
}
