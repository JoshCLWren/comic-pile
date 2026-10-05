/**
 * Canonical route indexability table for ComicPile (issue #3065).
 *
 * Every client route is classified exactly once:
 * - `public-indexable`: crawlable public surface. Emits one stable canonical URL
 *   and stays crawlable without JavaScript via the prerendered `index.html`.
 * - `public-noindex`: public utility routes (auth, demo, redirects) that must
 *   not appear in search results.
 * - `private`: authenticated routes. Never crawl targets; the backend
 *   `robots.txt` disallows them and both the backend (`X-Robots-Tag`) and the
 *   {@link Seo} head manager emit `noindex, nofollow` for them.
 *
 * Unknown paths default to `private` so a newly added route can never
 * accidentally become indexable. When adding a route to `App.tsx`, add it here
 * first and extend `frontend/src/unit/seoRouteTable.test.ts`.
 */

export type RouteIndexability = 'public-indexable' | 'public-noindex' | 'private'

export interface RouteSeoEntry {
  /** Route pattern; `:param` segments match a single path segment. */
  pattern: string
  visibility: RouteIndexability
  /**
   * Stable canonical path for indexable routes, `null` otherwise. Only the
   * landing page is indexable, so this is `/` wherever it is non-null.
   */
  canonicalPath: string | null
  /** Document title applied while this route is active. */
  title: string
  /** Meta description applied while this route is active. */
  description: string
}

const LANDING_TITLE = 'ComicPile — A dice-driven reading queue for your comic collection'
const LANDING_DESCRIPTION =
  'ComicPile is a dice-driven reading queue for your comic collection. ' +
  'Build your stack, roll the die, and read what comes up — continuity-aware and self-hosted.'

const APP_TITLE = 'Comic Pile'
const APP_DESCRIPTION =
  'ComicPile personal comic reading queue. Sign in to roll for your next read.'
const UTILITY_DESCRIPTION =
  'ComicPile account utility page. This page is not indexed by search engines.'

export const ROUTE_SEO_TABLE: readonly RouteSeoEntry[] = [
  { pattern: '/', visibility: 'public-indexable', canonicalPath: '/', title: LANDING_TITLE, description: LANDING_DESCRIPTION },
  { pattern: '/login', visibility: 'public-noindex', canonicalPath: null, title: `Sign in — ${APP_TITLE}`, description: UTILITY_DESCRIPTION },
  { pattern: '/register', visibility: 'public-noindex', canonicalPath: null, title: `Create your queue — ${APP_TITLE}`, description: UTILITY_DESCRIPTION },
  { pattern: '/forgot-password', visibility: 'public-noindex', canonicalPath: null, title: `Forgot password — ${APP_TITLE}`, description: UTILITY_DESCRIPTION },
  { pattern: '/reset-password', visibility: 'public-noindex', canonicalPath: null, title: `Reset password — ${APP_TITLE}`, description: UTILITY_DESCRIPTION },
  { pattern: '/demo', visibility: 'public-noindex', canonicalPath: null, title: `Try the demo — ${APP_TITLE}`, description: UTILITY_DESCRIPTION },
  // Retired redirect routes: crawlers follow the redirect, so the redirect
  // source itself stays non-indexable with no canonical of its own.
  { pattern: '/rate', visibility: 'public-noindex', canonicalPath: null, title: APP_TITLE, description: APP_DESCRIPTION },
  { pattern: '/analytics', visibility: 'public-noindex', canonicalPath: null, title: APP_TITLE, description: APP_DESCRIPTION },
  { pattern: '/help', visibility: 'public-noindex', canonicalPath: null, title: APP_TITLE, description: APP_DESCRIPTION },
  { pattern: '/queue', visibility: 'private', canonicalPath: null, title: `Queue — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/thread/:id', visibility: 'private', canonicalPath: null, title: `Thread — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/creators', visibility: 'private', canonicalPath: null, title: `Creators — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/creators/compare', visibility: 'private', canonicalPath: null, title: `Compare creators — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/creators/:creatorKey', visibility: 'private', canonicalPath: null, title: `Creator — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/history', visibility: 'private', canonicalPath: null, title: `History — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/sessions/:id', visibility: 'private', canonicalPath: null, title: `Session — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/crossovers', visibility: 'private', canonicalPath: null, title: `Crossovers — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/crossovers/:group', visibility: 'private', canonicalPath: null, title: `Crossover — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/continuity-plans', visibility: 'private', canonicalPath: null, title: `Continuity plans — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/continuity-plans/new', visibility: 'private', canonicalPath: null, title: `New continuity plan — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/continuity-plans/:id', visibility: 'private', canonicalPath: null, title: `Continuity plan — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/whats-new', visibility: 'private', canonicalPath: null, title: `What's new — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/glossary', visibility: 'private', canonicalPath: null, title: `Glossary — ${APP_TITLE}`, description: APP_DESCRIPTION },
  { pattern: '/identity-inbox', visibility: 'private', canonicalPath: null, title: `Identity inbox — ${APP_TITLE}`, description: APP_DESCRIPTION },
]

const FALLBACK_ENTRY: RouteSeoEntry = {
  pattern: '*',
  visibility: 'private',
  canonicalPath: null,
  title: APP_TITLE,
  description: APP_DESCRIPTION,
}

/** Normalize a pathname for table lookup: lowercase, no trailing slash. */
export function normalizeSeoPathname(pathname: string): string {
  const withoutQuery = pathname.split(/[?#]/, 1)[0] ?? ''
  const lower = withoutQuery.toLowerCase()
  if (lower.length > 1 && lower.endsWith('/')) {
    return lower.slice(0, -1)
  }
  return lower || '/'
}

function patternMatches(pattern: string, pathname: string): boolean {
  const patternSegments = pattern.split('/').filter(Boolean)
  const pathSegments = pathname.split('/').filter(Boolean)
  if (patternSegments.length !== pathSegments.length) {
    return false
  }
  return patternSegments.every(
    (segment, index) => segment.startsWith(':') || segment === pathSegments[index],
  )
}

/**
 * Look up the SEO entry for a pathname. Unknown paths resolve to the
 * private fallback so new routes are never accidentally indexable.
 */
export function matchRouteSeo(pathname: string): RouteSeoEntry {
  const normalized = normalizeSeoPathname(pathname)
  if (normalized === '/') {
    const root = ROUTE_SEO_TABLE.find(entry => entry.pattern === '/')
    return root ?? FALLBACK_ENTRY
  }
  for (const entry of ROUTE_SEO_TABLE) {
    if (entry.pattern !== '/' && patternMatches(entry.pattern, normalized)) {
      return entry
    }
  }
  return FALLBACK_ENTRY
}

/** True only for the crawlable public surface (currently just `/`). */
export function isIndexablePath(pathname: string): boolean {
  return matchRouteSeo(pathname).visibility === 'public-indexable'
}

/** All indexable entries; each must expose exactly one stable canonical URL. */
export function indexableRoutes(): RouteSeoEntry[] {
  return ROUTE_SEO_TABLE.filter(entry => entry.visibility === 'public-indexable')
}
