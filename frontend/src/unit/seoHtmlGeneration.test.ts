import { describe, expect, test } from 'vitest'
import {
  generateRouteHtml,
  generateSpaFallbackHtml,
  generateStructuredData,
  type RouteSeoEntryInput,
} from '../../scripts/generate-route-html.mjs'

/**
 * Stand-in for what `vite build` emits as `static/react/index.html`: the shared
 * bootstrap shell, hashed asset tags, and the default landing-page metadata.
 * Tests inject it directly so they never depend on prior build output and
 * cannot go stale against artifacts on disk.
 */
const BUILT_INDEX_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ComicPile — A dice-driven reading queue for your comic collection</title>
    <meta
      name="description"
      content="Built default description that must be replaced per route."
    />
    <link rel="canonical" href="/" />
    <meta property="og:type" content="website" />
    <meta property="og:title" content="Built default title" />
    <meta
      property="og:description"
      content="Built default description that must be replaced per route."
    />
    <meta property="og:url" content="/" />
    <script id="comic-pile-structured-data" type="application/ld+json">
      {"@context":"https://schema.org","@graph":[{"@type":"WebSite","name":"Built default","url":"/"}]}
    </script>
    <style>
      #bootstrap-shell { position: fixed; }
    </style>
  </head>
  <body>
    <div id="bootstrap-shell" role="status" aria-live="polite">Booting…</div>
    <div id="root"></div>
    <script type="module" crossorigin src="/assets/index-abc123.js"></script>
  </body>
</html>`

function countOccurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1
}

describe('SEO HTML generation', () => {
  test('CBL Sources page has correct title and metadata', () => {
    const route: RouteSeoEntryInput = {
      pattern: '/cbl-sources',
      title: 'CBL Sources — Comic Pile',
      description: 'Browse trusted reading-order sources and add them as Reading Plans in ComicPile.',
      canonicalPath: null,
      visibility: 'private',
    }

    const html = generateRouteHtml(route, BUILT_INDEX_HTML)

    expect(html).toContain('<title>CBL Sources — Comic Pile</title>')
    expect(html).toContain('Browse trusted reading-order sources and add them as Reading Plans in ComicPile.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="CBL Sources — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="Browse trusted reading-order sources and add them as Reading Plans in ComicPile." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/cbl-sources" />')
    // Private routes carry neither a canonical link nor JSON-LD, including the
    // default landing metadata inherited from the built page.
    expect(html).not.toContain('<link rel="canonical"')
    expect(html).not.toContain('comic-pile-structured-data')
    // Exactly one title and description: the built defaults were replaced.
    expect(countOccurrences(html, '<title>')).toBe(1)
    expect(html).not.toContain('Built default title')
    expect(html).not.toContain('Built default description that must be replaced per route.')
    // The shared bootstrap shell and hashed build assets stay intact.
    expect(html).toContain('id="bootstrap-shell"')
    expect(html).toContain('src="/assets/index-abc123.js"')
  })

  test('Login page has correct title and metadata', () => {
    const route: RouteSeoEntryInput = {
      pattern: '/login',
      title: 'Sign in — Comic Pile',
      description: 'ComicPile account utility page. This page is not indexed by search engines.',
      canonicalPath: null,
      visibility: 'public-noindex',
    }

    const html = generateRouteHtml(route, BUILT_INDEX_HTML)

    expect(html).toContain('<title>Sign in — Comic Pile</title>')
    expect(html).toContain('ComicPile account utility page. This page is not indexed by search engines.')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    expect(html).toContain('<meta property="og:title" content="Sign in — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile account utility page. This page is not indexed by search engines." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/login" />')
    expect(html).not.toContain('<link rel="canonical"')
    expect(html).not.toContain('comic-pile-structured-data')
  })

  test('Queue page has correct title and metadata', () => {
    const route: RouteSeoEntryInput = {
      pattern: '/queue',
      title: 'Queue — Comic Pile',
      description: 'ComicPile personal comic reading queue. Sign in to roll for your next read.',
      canonicalPath: '/queue',
      visibility: 'public-indexable',
    }

    const html = generateRouteHtml(route, BUILT_INDEX_HTML)

    expect(html).toContain('<title>Queue — Comic Pile</title>')
    expect(html).toContain('ComicPile personal comic reading queue. Sign in to roll for your next read.')
    expect(html).toContain('<meta name="robots" content="index, follow" />')
    expect(html).toContain('<link rel="canonical" href="https://comic-pile.vercel.app/queue" />')
    expect(html).toContain('<meta property="og:title" content="Queue — Comic Pile" />')
    expect(html).toContain('<meta property="og:description" content="ComicPile personal comic reading queue. Sign in to roll for your next read." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/queue" />')
    expect(html).toContain('<script id="comic-pile-structured-data" type="application/ld+json">')
    // The built landing JSON-LD is replaced, not duplicated.
    expect(countOccurrences(html, 'comic-pile-structured-data')).toBe(1)
    expect(html).not.toContain('"name":"Built default"')
    expect(countOccurrences(html, '<title>')).toBe(1)
  })

  test('Landing page has correct title and metadata', () => {
    const route: RouteSeoEntryInput = {
      pattern: '/',
      title: 'ComicPile',
      description: 'A dice-driven reading queue for your comic collection.',
      canonicalPath: '/',
      visibility: 'public-indexable',
    }

    const html = generateRouteHtml(route, BUILT_INDEX_HTML)

    expect(html).toContain('<title>ComicPile</title>')
    expect(html).toContain('A dice-driven reading queue for your comic collection.')
    expect(html).toContain('<link rel="canonical" href="https://comic-pile.vercel.app/" />')
    expect(html).toContain('<meta name="robots" content="index, follow" />')
    expect(html).toContain('<meta property="og:title" content="ComicPile" />')
    expect(html).toContain('<meta property="og:description" content="A dice-driven reading queue for your comic collection." />')
    expect(html).toContain('<meta property="og:url" content="https://comic-pile.vercel.app/" />')
    expect(html).toContain('<script id="comic-pile-structured-data" type="application/ld+json">')
    expect(countOccurrences(html, 'comic-pile-structured-data')).toBe(1)
    expect(html).toContain('src="/assets/index-abc123.js"')
  })

  test('generator refuses to run without built HTML', () => {
    const route: RouteSeoEntryInput = {
      pattern: '/login',
      title: 'Sign in — Comic Pile',
      description: 'ComicPile account utility page. This page is not indexed by search engines.',
      canonicalPath: null,
      visibility: 'public-noindex',
    }

    expect(() => generateRouteHtml(route, '')).toThrow(/built index\.html/)
  })

  test('SPA fallback shell is non-indexable and drops landing-only metadata', () => {
    const html = generateSpaFallbackHtml(BUILT_INDEX_HTML)

    expect(html).toContain('<title>Comic Pile</title>')
    expect(html).toContain('<meta name="robots" content="noindex, nofollow" />')
    // The fallback must never present itself as the crawlable landing page.
    expect(html).not.toContain('<link rel="canonical"')
    expect(html).not.toContain('comic-pile-structured-data')
    expect(html).not.toContain('Built default title')
    expect(html).not.toContain('Built default description that must be replaced per route.')
    // Exactly one metadata set, and the bootstrap shell plus hashed assets survive.
    expect(countOccurrences(html, '<title>')).toBe(1)
    expect(html).toContain('id="bootstrap-shell"')
    expect(html).toContain('src="/assets/index-abc123.js"')
  })

  test('fallback shell generator refuses to run without built HTML', () => {
    expect(() => generateSpaFallbackHtml('')).toThrow(/built index\.html/)
  })

  test('Structured data is generated correctly for public-indexable routes', () => {
    const structuredData = generateStructuredData()
    // SAFETY: generateStructuredData returns JSON.stringify output, so parsing it
    // always yields the documented graph shape.
    const parsed = JSON.parse(structuredData) as {
      '@context': string
      '@graph': Array<{ '@type': string; name?: string; featureList?: string[] }>
    }

    expect(parsed['@context']).toBe('https://schema.org')
    expect(parsed['@graph'].map(node => node['@type'])).toEqual(['WebSite', 'SoftwareApplication'])
    expect(parsed['@graph'][1].name).toBe('ComicPile')
    expect(parsed['@graph'][1].featureList).toContain('Weighted by your history')
    expect(structuredData).toContain('"@context":"https://schema.org"')
    expect(structuredData).toContain('continuity-aware and self-hosted')
  })
})
