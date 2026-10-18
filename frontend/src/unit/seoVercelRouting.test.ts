/**
 * Regression guard for the production Vercel SEO routing contract (issue #3905).
 *
 * Issue #3905 found that the build-generated `<route>.html` metadata files were
 * deployed but never served: the Vercel catch-all sent every non-file path to
 * `index.html`, so authenticated routes returned the indexable landing page head
 * and no `noindex` header while FastAPI handled them correctly in isolation.
 *
 * This suite runs against the *actual* `vercel.json` routing config and the
 * canonical route table. It fails when the routing layer stops serving
 * route-specific HTML or stops sending `noindex, nofollow` for non-landing
 * paths, which a FastAPI-only test cannot catch.
 */

import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, expect, test } from 'vitest'

import { ROUTE_SEO_TABLE } from '../seo/routeSeo'
import { SPA_FALLBACK_FILENAME } from '../../scripts/generate-route-html.mjs'

const VERCEL_CONFIG_PATH = join(import.meta.dirname, '..', '..', '..', 'vercel.json')

interface VercelRoute {
  src?: string
  dest?: string
  handle?: string
  headers?: Record<string, string>
}

interface VercelConfig {
  routes: VercelRoute[]
}

// SAFETY: vercel.json is a build-controlled config file whose routes array is validated by the test suite below.
const config = JSON.parse(readFileSync(VERCEL_CONFIG_PATH, 'utf-8')) as VercelConfig
const routes = config.routes

/** Every literal (non-parameterized) route the build emits a `.html` file for. */
function staticRoutePatterns(): string[] {
  return ROUTE_SEO_TABLE.map(entry => entry.pattern).filter(
    pattern => pattern !== '*' && !pattern.includes(':'),
  )
}

interface RouteHtmlRewrite {
  src: string
  dest: string
  headers?: Record<string, string>
}

function routeHtmlRewrite(): RouteHtmlRewrite {
  const matches = routes.filter(route => route.dest === '/$1.html')
  expect(matches).toHaveLength(1)
  const route = matches[0]
  if (!route?.src || !route.dest) {
    throw new Error('vercel.json is missing the <route>.html rewrite route')
  }
  return { src: route.src, dest: route.dest, headers: route.headers }
}

describe('Vercel routing serves the SEO metadata files (issue #3905)', () => {
  test('every non-parameterized route is rewritten to its generated .html file', () => {
    const { src } = routeHtmlRewrite()
    const matcher = new RegExp(`^${src.replace(/\$$/, '')}$`)

    for (const pattern of staticRoutePatterns()) {
      if (pattern === '/') {
        continue
      }
      const match = matcher.exec(pattern)
      expect(match, `${pattern} is not served a route-specific HTML file`).not.toBeNull()
      expect(`/${match?.[1]}.html`).toBe(`${pattern}.html`)
    }
  })

  test('parameterized and unknown paths fall through to the catch-all', () => {
    const { src } = routeHtmlRewrite()
    const matcher = new RegExp(`^${src.replace(/\$$/, '')}$`)

    for (const path of [
      '/thread/17938',
      '/threads/17938',
      '/sessions/abc',
      '/creators/some-creator',
      '/crossovers/age-of-apocalypse',
      '/continuity-plans/7',
      '/continuity-plans/7/edit',
      '/not-a-declared-route',
    ]) {
      expect(matcher.test(path), `${path} must not match the route-file rewrite`).toBe(false)
    }
  })

  test('route-specific HTML and the SPA fallback send noindex, nofollow', () => {
    expect(routeHtmlRewrite().headers?.['X-Robots-Tag']).toBe('noindex, nofollow')
    const catchAll = routes[routes.length - 1]
    expect(catchAll?.src).toBe('/(.*)')
    expect(catchAll?.dest).toBe(`/${SPA_FALLBACK_FILENAME}`)
    expect(catchAll?.headers?.['X-Robots-Tag']).toBe('noindex, nofollow')
  })

  test('only the landing page is served the indexable index.html without noindex', () => {
    const landing = routes[2]
    expect(landing?.src).toBe('/')
    expect(landing?.dest).toBe('/index.html')
    expect(landing?.headers?.['X-Robots-Tag']).toBeUndefined()
  })

  test('route rewrites run before the filesystem boundary and catch-all', () => {
    const routeFileIndex = routes.findIndex(route => route.dest === '/$1.html')
    const filesystemIndex = routes.findIndex(route => route.handle === 'filesystem')
    expect(routeFileIndex).toBeGreaterThan(-1)
    expect(filesystemIndex).toBeGreaterThan(routeFileIndex)
    expect(filesystemIndex).toBeLessThan(routes.length - 1)
  })
})
