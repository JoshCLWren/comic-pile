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
  /** Spec that measures this route's requests, or the owning worker when not ours. */
  auditedBy: string
  /** Path of the owning spec when `auditedBy` names this harness. */
  spec?: string
}

/**
 * Canonical audited route inventory.
 *
 * Every `<Route path="...">` in `App.tsx` must appear exactly once. Public and
 * auxiliary routes are owned by task #4504; feature routes are owned by peer
 * worker #4503 and are listed so a newly added route cannot escape review.
 */
export const AUDITED_ROUTES: AuditedRoute[] = [
  { path: '/login', auth: 'public', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/register', auth: 'public', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/forgot-password', auth: 'public', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/reset-password', auth: 'public', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/demo', auth: 'public', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/rate', auth: 'redirect', redirectTo: '/', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/analytics', auth: 'redirect', redirectTo: '/', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/roll', auth: 'redirect', redirectTo: '/', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/', auth: 'conditional', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
  { path: '/queue', auth: 'protected', auditedBy: '4503' },
  { path: '/thread/:id', auth: 'protected', auditedBy: '4503' },
  { path: '/threads/:id', auth: 'redirect', redirectTo: '/thread/:id', auditedBy: '4503' },
  { path: '/creators/compare', auth: 'protected', auditedBy: '4503' },
  { path: '/creators/:creatorKey', auth: 'protected', auditedBy: '4503' },
  { path: '/history', auth: 'protected', auditedBy: '4503' },
  { path: '/sessions/:id', auth: 'protected', auditedBy: '4503' },
  { path: '/creators', auth: 'protected', auditedBy: '4503' },
  { path: '/crossovers', auth: 'protected', auditedBy: '4503' },
  { path: '/crossovers/:group', auth: 'protected', auditedBy: '4503' },
  { path: '/continuity-plans', auth: 'protected', auditedBy: '4503' },
  { path: '/continuity-plans/new', auth: 'protected', auditedBy: '4503' },
  { path: '/continuity-plans/events', auth: 'protected', auditedBy: '4503' },
  { path: '/continuity-plans/:id/edit', auth: 'protected', auditedBy: '4503' },
  { path: '/continuity-plans/:id', auth: 'protected', auditedBy: '4503' },
  { path: '/reading-lists/:id', auth: 'protected', auditedBy: '4503' },
  { path: '/cbl-sources', auth: 'protected', auditedBy: '4503' },
  { path: '/whats-new', auth: 'protected', auditedBy: '4504', spec: 'auxiliaryRoutes.network.test.tsx' },
  { path: '/glossary', auth: 'protected', auditedBy: '4504', spec: 'auxiliaryRoutes.network.test.tsx' },
  { path: '/help', auth: 'redirect', redirectTo: '/glossary', auditedBy: '4504', spec: 'auxiliaryRoutes.network.test.tsx' },
  { path: '/identity-inbox', auth: 'protected', auditedBy: '4503' },
  { path: '*', auth: 'unknown', auditedBy: '4504', spec: 'publicRoutes.network.test.tsx' },
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
 * Resolve an audited spec path next to this module.
 *
 * @param spec - Spec filename from {@link AUDITED_ROUTES}.
 * @returns Absolute path and whether it exists.
 */
export function specStatus(spec: string): SpecStatus {
  const path = resolve(process.cwd(), 'src/test/network-budget', spec)
  return { path, exists: existsSync(path) }
}
