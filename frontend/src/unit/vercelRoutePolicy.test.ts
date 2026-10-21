/**
 * Cross-artifact regression guard for the Vercel routing layer (issue #3905).
 *
 * The deployment serves the prerendered `<route>.html` documents that
 * `scripts/generate-route-html.mjs` writes from the canonical route table, so
 * `vercel.json` must name exactly the routes the build produces. A mapping to
 * a file the build never writes is a dead route: the request 404s instead of
 * falling back to the SPA shell, and a route without a mapping silently serves
 * the landing page head, which tells crawlers that a private page is
 * indexable.
 *
 * The backend suites cannot catch this class of defect because those paths
 * never reach FastAPI in production; this guard compares the deployment
 * configuration with the canonical table instead.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, test } from 'vitest'

import { ROUTE_SEO_TABLE } from '../seo/routeSeo'

interface VercelRoute {
  src?: string
  dest?: string
  headers?: Record<string, string>
}

// SAFETY: the committed vercel.json is a static configuration file whose
// `routes` entries always carry a source and a destination.
const vercelConfig = JSON.parse(
  readFileSync(join(import.meta.dirname, '..', '..', '..', 'vercel.json'), 'utf-8'),
) as { routes: VercelRoute[] }

const API_ROUTE_SOURCES = new Set([
  '/api(?:/.*)?',
  '/(?:openapi\\.json|docs|redoc|health)',
])
const CATCH_ALL_SOURCE = '/(.*)'

/** The prerendered file `generate-route-html.mjs` writes for a route pattern. */
function generatedRouteFile(pattern: string): string {
  return pattern === '/' ? 'index.html' : `${pattern.slice(1)}.html`
}

/** Route patterns the build prerenders a static HTML document for. */
function prerenderedPatterns(): string[] {
  return ROUTE_SEO_TABLE.filter(entry => !entry.pattern.includes(':')).map(
    entry => entry.pattern,
  )
}

/** Explicit SPA page mappings in `vercel.json`, excluding API and fallback routes. */
function spaPageMappings(): Map<string, string> {
  const mappings = new Map<string, string>()
  for (const route of vercelConfig.routes) {
    const source = route.src
    const destination = route.dest
    if (source === undefined || destination === undefined) {
      continue
    }
    if (source === CATCH_ALL_SOURCE || API_ROUTE_SOURCES.has(source)) {
      continue
    }
    mappings.set(source, destination)
  }
  return mappings
}

describe('Vercel routing layer stays aligned with the canonical route table', () => {
  test('every prerendered route has an explicit deployment mapping', () => {
    const mappings = spaPageMappings()
    const missing = prerenderedPatterns().filter(pattern => !mappings.has(pattern))

    expect(
      missing,
      `routes without a vercel.json mapping: ${missing.join(', ')}`,
    ).toEqual([])
  })

  test('no deployment mapping targets a document the build never writes', () => {
    const generated = new Set(prerenderedPatterns().map(generatedRouteFile))
    const dead = [...spaPageMappings()].flatMap(([source, destination]) =>
      generated.has(destination.replace(/^\//, '')) ? [] : [`${source} -> ${destination}`],
    )

    expect(
      dead,
      `vercel.json routes with no generated HTML document: ${dead.join(', ')}`,
    ).toEqual([])
  })

  test('each mapping serves exactly the document the build generates', () => {
    const mappings = spaPageMappings()
    const mismatched = prerenderedPatterns()
      .filter(pattern => mappings.has(pattern))
      .filter(pattern => mappings.get(pattern) !== `/${generatedRouteFile(pattern)}`)
      .map(pattern => `${pattern} -> ${mappings.get(pattern)}`)

    expect(
      mismatched,
      `vercel.json routes serving the wrong HTML document: ${mismatched.join(', ')}`,
    ).toEqual([])
  })

  test('the deployment maps no route that the app does not declare', () => {
    const declared = new Set(ROUTE_SEO_TABLE.map(entry => entry.pattern))
    const unknown = [...spaPageMappings().keys()].filter(pattern => !declared.has(pattern))

    expect(
      unknown,
      `vercel.json routes absent from the canonical route table: ${unknown.join(', ')}`,
    ).toEqual([])
  })
})
