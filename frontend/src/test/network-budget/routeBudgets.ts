/**
 * Deterministic request budgets for public and auxiliary routes.
 *
 * A row is the canonical request identity from `requestLedger.ts`:
 * `METHOD /api/path?sorted-query xCOUNT`. Rows are sorted by identity.
 *
 * These are exact counts, measured at the axios transport boundary on a cold
 * mount. They cover the shared auth bootstrap, the authenticated app shell
 * (preferences + Navigation identity-inbox badge), and each page's own reads.
 */

/**
 * Sort budget rows the same way the ledger reports them.
 *
 * @param rows - Canonical request rows.
 * @returns Rows ordered by canonical identity.
 */
export function budget(...rows: string[]): readonly string[] {
  return [...rows].sort((left, right) => left.localeCompare(right))
}

/** Two-probe bootstrap a cookieless guest currently pays on non-login public routes. */
export const GUEST_AUTH_PROBE = budget(
  'GET /api/v1/auth/me x1',
  'POST /api/v1/auth/refresh x1',
)

/** App-shell reads every authenticated layout mounts. */
export const AUTHENTICATED_SHELL = budget(
  'GET /api/v1/auth/me x1',
  'GET /api/v1/identity-inbox?limit=1&offset=0 x1',
  'GET /api/v1/users/me/preferences x1',
)

/**
 * Confirmed redundant call, blocked on shared-file allocation.
 *
 * `/login` and `/register` short-circuit the bootstrap when no token is stored
 * (`App.tsx` `isPublicAuthPage`), producing zero requests. `/forgot-password`
 * and `/reset-password` are the same class of public credential form but still
 * pay {@link GUEST_AUTH_PROBE}. Target budget is `[]`; see task-4504.md for the
 * exact App.tsx allocation request.
 */
export const PUBLIC_CREDENTIAL_FORM_TARGET: readonly string[] = []

const PUBLIC_ENTRIES = {
  '/login': [],
  '/register': [],
  '/forgot-password': GUEST_AUTH_PROBE,
  '/reset-password': GUEST_AUTH_PROBE,
  '/demo': budget(...GUEST_AUTH_PROBE, 'GET /api/v1/demo/roll x1'),
  '/': GUEST_AUTH_PROBE,
  '/unknown': GUEST_AUTH_PROBE,
} satisfies Record<string, readonly string[]>

const AUX_ENTRIES = {
  '/whats-new': budget(
    ...AUTHENTICATED_SHELL,
    'GET /api/v1/releases/?limit=20&offset=0 x1',
  ),
  '/glossary': AUTHENTICATED_SHELL,
  '/help': AUTHENTICATED_SHELL,
} satisfies Record<string, readonly string[]>

/** Exact cold-mount budgets keyed by route path. */
export const PUBLIC_ROUTE_BUDGETS = new Map<string, readonly string[]>(Object.entries(PUBLIC_ENTRIES))

/** Exact cold-mount budgets for authenticated auxiliary routes. */
export const AUX_ROUTE_BUDGETS = new Map<string, readonly string[]>(Object.entries(AUX_ENTRIES))

/**
 * Read one public route budget, failing closed when a route was not declared.
 *
 * @param path - Audited public route path.
 * @returns The exact request rows for a cold mount.
 */
export function publicBudget(path: string): readonly string[] {
  const rows = PUBLIC_ROUTE_BUDGETS.get(path)
  if (!rows) throw new Error(`No public network budget declared for ${path}`)
  return rows
}

/**
 * Read one auxiliary route budget, failing closed when a route was not declared.
 *
 * @param path - Audited auxiliary route path.
 * @returns The exact request rows for a cold mount.
 */
export function auxBudget(path: string): readonly string[] {
  const rows = AUX_ROUTE_BUDGETS.get(path)
  if (!rows) throw new Error(`No auxiliary network budget declared for ${path}`)
  return rows
}

/**
 * Peer-owned Roll traffic fired by redirect targets. Public/auxiliary tests
 * filter it so they never assert counts owned by worker #4503.
 *
 * @param row - Canonical request row.
 * @returns True when the row belongs to the authenticated Roll surface.
 */
export function isPeerRollRow(row: string): boolean {
  return row.startsWith('GET /api/v2/roll/')
}
