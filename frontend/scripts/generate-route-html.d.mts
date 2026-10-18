/**
 * Type declarations for `generate-route-html.mjs` so TypeScript tests can
 * import the build script without enabling `allowJs` for the whole project.
 */

/** Shape of one entry from `frontend/src/seo/routeSeo.ts` consumed by the generator. */
export interface RouteSeoEntryInput {
  /** Route pattern; `:param` segments match a single path segment. */
  pattern: string
  /** Whether the route is indexable, a public utility route, or private. */
  visibility: 'public-indexable' | 'public-noindex' | 'private'
  /** Stable canonical path for indexable routes, `null` otherwise. */
  canonicalPath: string | null
  /** Document title for the route. */
  title: string
  /** Meta description for the route. */
  description: string
}

/**
 * Generate a route-specific HTML document by rewriting the SEO metadata of the
 * built `index.html` content.
 *
 * @param route - Route SEO entry.
 * @param builtIndexHtml - Vite's built `index.html` content.
 * @returns Full HTML document for the route.
 */
export function generateRouteHtml(route: RouteSeoEntryInput, builtIndexHtml: string): string

/**
 * Built file name of the shared noindex SPA fallback shell.
 */
export const SPA_FALLBACK_FILENAME: string

/**
 * Generate the shared noindex SPA fallback shell by rewriting the SEO metadata
 * of the built `index.html` content. Served for parameterized and unknown routes
 * instead of `index.html` so they never inherit the landing page's indexable
 * metadata.
 *
 * @param builtIndexHtml - Vite's built `index.html` content.
 * @returns Full HTML document for the fallback shell.
 */
export function generateSpaFallbackHtml(builtIndexHtml: string): string

/**
 * Generate the JSON-LD graph for indexable routes.
 *
 * @returns Compact JSON-LD document.
 */
export function generateStructuredData(): string
