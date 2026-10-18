/**
 * Cross-artifact regression guard for the public indexability policy (issue #3064).
 *
 * The indexability contract is expressed in four places that must not drift:
 *
 * 1. `frontend/src/App.tsx` — the routes the application actually declares;
 * 2. `frontend/src/seo/routeSeo.ts` — the canonical indexability table;
 * 3. `frontend/public/robots.txt` — the crawler policy served at `/robots.txt`;
 * 4. `frontend/scripts/generate-sitemap.mjs` — the sitemap derived from (2).
 *
 * The unit suites for each artifact prove their internal behavior. This guard
 * proves they still agree with one another, so a newly added route cannot be
 * left unclassified or accidentally become a crawl target.
 */

import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, expect, test } from 'vitest'

import { ROUTE_SEO_TABLE, indexableRoutes, matchRouteSeo } from '../seo/routeSeo'

const APP_SOURCE = join(import.meta.dirname, '..', 'App.tsx')
const ROBOTS_SOURCE = join(import.meta.dirname, '..', '..', 'public', 'robots.txt')

/** Route patterns declared in `App.tsx`, in source order, excluding the `*` splat. */
function appRoutePatterns(): string[] {
  const source = readFileSync(APP_SOURCE, 'utf-8')
  const patterns: string[] = []
  for (const match of source.matchAll(/\bpath="([^"]*)"/g)) {
    const pattern = match[1] ?? ''
    if (pattern !== '') {
      patterns.push(pattern)
    }
  }
  return patterns
}

interface RobotsRule {
  type: 'allow' | 'disallow'
  pattern: string
}

function parseRobotsRules(): RobotsRule[] {
  const rules: RobotsRule[] = []
  for (const line of readFileSync(ROBOTS_SOURCE, 'utf-8').split('\n')) {
    const match = /^(Allow|Disallow):\s*(\S+)\s*$/.exec(line.trim())
    if (match) {
      rules.push({
        type: match[1] === 'Allow' ? 'allow' : 'disallow',
        pattern: match[2] ?? '',
      })
    }
  }
  return rules
}

/**
 * Apply robots.txt longest-prefix matching (an equally long `Allow` wins) and
 * report whether the path is excluded from crawling.
 */
function isDisallowed(path: string, rules: RobotsRule[]): boolean {
  let winner: RobotsRule | null = null
  for (const rule of rules) {
    if (!path.startsWith(rule.pattern)) {
      continue
    }
    if (
      winner === null ||
      rule.pattern.length > winner.pattern.length ||
      (rule.pattern.length === winner.pattern.length && rule.type === 'allow')
    ) {
      winner = rule
    }
  }
  return winner?.type === 'disallow'
}

/** Turn a route pattern into a concrete path by filling `:param` segments. */
function concreteSamplePath(pattern: string): string {
  return pattern
    .split('/')
    .map(segment => (segment.startsWith(':') ? 'sample' : segment))
    .join('/')
}

describe('public indexability policy stays consistent across artifacts', () => {
  test('every route declared in App.tsx is classified in the SEO table', () => {
    const appPatterns = appRoutePatterns().filter(pattern => pattern !== '*')
    const tablePatterns = new Set(ROUTE_SEO_TABLE.map(entry => entry.pattern))

    const unclassified = appPatterns.filter(pattern => !tablePatterns.has(pattern))
    expect(unclassified, `unclassified App.tsx routes: ${unclassified.join(', ')}`).toEqual([])
  })

  test('every SEO table route corresponds to a route declared in App.tsx', () => {
    const appPatterns = new Set(appRoutePatterns())
    const tableOnly = ROUTE_SEO_TABLE.map(entry => entry.pattern).filter(
      pattern => !appPatterns.has(pattern),
    )
    expect(tableOnly, `SEO table routes absent from App.tsx: ${tableOnly.join(', ')}`).toEqual([])
  })

  test('robots.txt disallows every non-indexable route and allows the landing page', () => {
    const rules = parseRobotsRules()
    const notDisallowed: string[] = []

    for (const entry of ROUTE_SEO_TABLE) {
      if (entry.visibility === 'public-indexable') {
        continue
      }
      const samplePath = concreteSamplePath(entry.pattern)
      if (!isDisallowed(samplePath, rules)) {
        notDisallowed.push(entry.pattern)
      }
    }

    expect(
      notDisallowed,
      `non-indexable routes missing a robots.txt Disallow: ${notDisallowed.join(', ')}`,
    ).toEqual([])

    for (const entry of indexableRoutes()) {
      expect(isDisallowed(concreteSamplePath(entry.pattern), rules)).toBe(false)
    }
  })

  test('the sitemap surface is exactly the indexable route set', () => {
    const indexable = indexableRoutes()
    expect(indexable.map(entry => entry.pattern)).toEqual(['/'])
    for (const entry of indexable) {
      expect(entry.canonicalPath).toBe('/')
    }
  })

  test('unknown paths still default to private and non-indexable', () => {
    const entry = matchRouteSeo('/not-a-declared-route')
    expect(entry.visibility).toBe('private')
    expect(entry.canonicalPath).toBeNull()
  })
})
